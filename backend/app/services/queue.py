import asyncio
import threading
from typing import Dict, List, Optional, Set
from datetime import datetime
import json
from queue import Queue, Empty

from app.models.schemas import (
    QueueItem,
    QueueItemUpdate,
    QueueResponse,
    DownloadStatus,
    DownloadRequest,
)
from app.services.ytdlp import ytdlp_service


class DownloadQueueManager:
    """Manages the download queue with background processing."""

    def __init__(self):
        self._queue: Dict[str, QueueItem] = {}
        self._order: List[str] = []  # Maintains insertion order
        self._cancelled: Set[str] = set()
        self._worker_task: Optional[asyncio.Task] = None
        self._progress_task: Optional[asyncio.Task] = None
        self._running = False
        self._subscribers: List[asyncio.Queue] = []
        self._lock = asyncio.Lock()
        self._thread_lock = threading.Lock()  # For thread-safe access
        self._progress_queue: Queue = Queue()  # Thread-safe queue for progress updates
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start_worker(self):
        """Start the background download worker."""
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._worker_task = asyncio.create_task(self._process_queue())
        self._progress_task = asyncio.create_task(self._process_progress_updates())

    async def stop_worker(self):
        """Stop the background download worker."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        if self._progress_task:
            self._progress_task.cancel()
            try:
                await self._progress_task
            except asyncio.CancelledError:
                pass

    async def add_to_queue(self, request: DownloadRequest) -> QueueItem:
        """Add a download request to the queue."""
        async with self._lock:
            item = QueueItem(
                video_id=request.video_id,
                url=request.url,
                title=request.title,
                thumbnail=request.thumbnail,
                format_id=request.format_id,
                format_label=request.format_label,
                is_audio_only=request.is_audio_only,
                audio_quality=request.audio_quality,
                audio_codec=request.audio_codec,
            )
            self._queue[item.id] = item
            self._order.append(item.id)

        await self._broadcast_update(item)
        return item

    async def get_queue(self) -> QueueResponse:
        """Get the current queue status."""
        async with self._lock:
            items = [self._queue[id] for id in self._order if id in self._queue]

        active = sum(1 for item in items if item.status == DownloadStatus.DOWNLOADING)
        completed = sum(1 for item in items if item.status == DownloadStatus.COMPLETED)
        failed = sum(1 for item in items if item.status == DownloadStatus.FAILED)

        return QueueResponse(
            items=items,
            active_downloads=active,
            completed_count=completed,
            failed_count=failed,
        )

    async def remove_from_queue(self, item_id: str) -> bool:
        """Remove an item from the queue."""
        async with self._lock:
            if item_id in self._queue:
                item = self._queue[item_id]

                # If downloading, mark for cancellation
                if item.status == DownloadStatus.DOWNLOADING:
                    with self._thread_lock:
                        self._cancelled.add(item_id)
                    item.status = DownloadStatus.CANCELLED

                # Remove from queue
                del self._queue[item_id]
                if item_id in self._order:
                    self._order.remove(item_id)

                await self._broadcast_update(item, removed=True)
                return True
        return False

    async def cancel_download(self, item_id: str) -> bool:
        """Cancel an active download."""
        async with self._lock:
            if item_id in self._queue:
                item = self._queue[item_id]
                if item.status in [DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING]:
                    with self._thread_lock:
                        self._cancelled.add(item_id)
                    item.status = DownloadStatus.CANCELLED
                    await self._broadcast_update(item)
                    return True
        return False

    async def retry_download(self, item_id: str) -> bool:
        """Retry a failed download."""
        async with self._lock:
            if item_id in self._queue:
                item = self._queue[item_id]
                if item.status in [DownloadStatus.FAILED, DownloadStatus.CANCELLED]:
                    item.status = DownloadStatus.QUEUED
                    item.progress = 0.0
                    item.error = None
                    with self._thread_lock:
                        self._cancelled.discard(item_id)
                    await self._broadcast_update(item)
                    return True
        return False

    async def clear_completed(self) -> int:
        """Clear all completed downloads from the queue."""
        count = 0
        async with self._lock:
            to_remove = []
            for item_id, item in self._queue.items():
                if item.status == DownloadStatus.COMPLETED:
                    to_remove.append(item_id)

            for item_id in to_remove:
                del self._queue[item_id]
                if item_id in self._order:
                    self._order.remove(item_id)
                count += 1

        if count > 0:
            await self._broadcast_full_update()
        return count

    async def subscribe(self) -> asyncio.Queue:
        """Subscribe to queue updates (for SSE)."""
        queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        """Unsubscribe from queue updates."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def _broadcast_update(self, item: QueueItem, removed: bool = False):
        """Broadcast an item update to all subscribers."""
        event_data = {
            "type": "item_update",
            "item": item.model_dump(mode="json"),
            "removed": removed,
        }
        await self._send_to_subscribers(event_data)

    async def _broadcast_full_update(self):
        """Broadcast full queue state to all subscribers."""
        queue_state = await self.get_queue()
        event_data = {
            "type": "full_update",
            "queue": queue_state.model_dump(mode="json"),
        }
        await self._send_to_subscribers(event_data)

    async def _send_to_subscribers(self, data: dict):
        """Send data to all SSE subscribers."""
        dead_subscribers = []
        for sub_queue in self._subscribers:
            try:
                sub_queue.put_nowait(json.dumps(data))
            except asyncio.QueueFull:
                dead_subscribers.append(sub_queue)

        for sub in dead_subscribers:
            self._subscribers.remove(sub)

    async def _process_progress_updates(self):
        """Background task that processes progress updates from the thread-safe queue."""
        while self._running:
            try:
                # Check for progress updates
                try:
                    while True:
                        item_id, data = self._progress_queue.get_nowait()
                        await self._apply_progress_update(item_id, data)
                except Empty:
                    pass
                
                await asyncio.sleep(0.1)  # Small delay to prevent busy loop
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Progress update error: {e}")

    async def _apply_progress_update(self, item_id: str, data: dict):
        """Apply a progress update to a queue item."""
        async with self._lock:
            if item_id in self._queue:
                item = self._queue[item_id]
                item.progress = data.get("progress", item.progress)
                item.speed = data.get("speed")
                item.eta = data.get("eta")

                if data.get("status") == "processing":
                    item.status = DownloadStatus.PROCESSING

                await self._broadcast_update(item)

    async def _process_queue(self):
        """Background worker that processes the download queue."""
        while self._running:
            try:
                # Find next queued item
                next_item = None
                async with self._lock:
                    for item_id in self._order:
                        if item_id in self._queue:
                            item = self._queue[item_id]
                            if item.status == DownloadStatus.QUEUED:
                                next_item = item
                                break

                if next_item:
                    await self._download_item(next_item)
                else:
                    # No items to process, wait a bit
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Queue worker error: {e}")
                await asyncio.sleep(1)

    async def _download_item(self, item: QueueItem):
        """Download a single queue item."""
        item_id = item.id

        # Check if already cancelled
        with self._thread_lock:
            if item_id in self._cancelled:
                return

        # Update status to downloading
        async with self._lock:
            if item_id in self._queue:
                item.status = DownloadStatus.DOWNLOADING
                await self._broadcast_update(item)

        def progress_callback(data: dict):
            """Handle progress updates from yt-dlp (called from thread pool)."""
            # Simply put the update in the thread-safe queue
            # The async task will pick it up and process it
            try:
                self._progress_queue.put_nowait((item_id, data))
            except Exception as e:
                print(f"Failed to queue progress update: {e}")

        def cancel_check() -> bool:
            """Check if download should be cancelled."""
            with self._thread_lock:
                return item_id in self._cancelled

        try:
            file_path = await ytdlp_service.download(
                url=item.url,
                format_id=item.format_id,
                is_audio_only=item.is_audio_only,
                audio_quality=item.audio_quality,
                audio_codec=item.audio_codec,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )

            # Mark as completed
            async with self._lock:
                with self._thread_lock:
                    is_cancelled = item_id in self._cancelled
                    
                if item_id in self._queue and not is_cancelled:
                    item.status = DownloadStatus.COMPLETED
                    item.progress = 100.0
                    item.completed_at = datetime.now()
                    item.file_path = file_path
                    await self._broadcast_update(item)

        except Exception as e:
            error_msg = str(e)
            print(f"Download error for {item_id}: {error_msg}")
            
            if "cancelled" in error_msg.lower():
                async with self._lock:
                    if item_id in self._queue:
                        item.status = DownloadStatus.CANCELLED
                        await self._broadcast_update(item)
            else:
                async with self._lock:
                    if item_id in self._queue:
                        item.status = DownloadStatus.FAILED
                        item.error = error_msg
                        await self._broadcast_update(item)


# Singleton instance
queue_manager = DownloadQueueManager()
