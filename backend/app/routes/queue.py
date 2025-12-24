from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import asyncio
import json

from app.models.schemas import QueueResponse
from app.services.queue import queue_manager


router = APIRouter()


@router.get("/queue", response_model=QueueResponse)
async def get_queue():
    """Get the current download queue status."""
    return await queue_manager.get_queue()


@router.delete("/queue/{item_id}")
async def remove_queue_item(item_id: str):
    """Remove an item from the queue or cancel if downloading."""
    success = await queue_manager.remove_from_queue(item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found in queue")
    return {"status": "removed", "id": item_id}


@router.post("/queue/{item_id}/cancel")
async def cancel_download(item_id: str):
    """Cancel an active or queued download."""
    success = await queue_manager.cancel_download(item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found or cannot be cancelled")
    return {"status": "cancelled", "id": item_id}


@router.post("/queue/{item_id}/retry")
async def retry_download(item_id: str):
    """Retry a failed or cancelled download."""
    success = await queue_manager.retry_download(item_id)
    if not success:
        raise HTTPException(status_code=404, detail="Item not found or cannot be retried")
    return {"status": "retrying", "id": item_id}


@router.post("/queue/clear-completed")
async def clear_completed():
    """Clear all completed downloads from the queue."""
    count = await queue_manager.clear_completed()
    return {"status": "cleared", "count": count}


@router.post("/queue/cancel-all")
async def cancel_all():
    """Cancel all active, queued, and converting downloads."""
    count = await queue_manager.cancel_all()
    return {"status": "cancelled", "count": count}


@router.get("/queue/events")
async def queue_events():
    """
    Server-Sent Events endpoint for real-time queue updates.
    
    Connect to this endpoint to receive live updates about download progress.
    """
    async def event_generator():
        subscriber_queue = await queue_manager.subscribe()

        try:
            # Send initial queue state
            initial_state = await queue_manager.get_queue()
            yield f"data: {json.dumps({'type': 'full_update', 'queue': initial_state.model_dump(mode='json')})}\n\n"

            while True:
                try:
                    # Wait for updates with timeout to keep connection alive
                    message = await asyncio.wait_for(
                        subscriber_queue.get(),
                        timeout=30.0
                    )
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield f": keepalive\n\n"

        except asyncio.CancelledError:
            pass
        finally:
            queue_manager.unsubscribe(subscriber_queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

