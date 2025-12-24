from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from typing import List
from pathlib import Path
import urllib.parse

from app.models.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    DownloadRequest,
    QueueItem,
)
from app.services.ytdlp import ytdlp_service
from app.services.queue import queue_manager


router = APIRouter()

# Download directory
DOWNLOAD_DIR = Path("/downloads")


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_url(request: AnalyzeRequest):
    """
    Analyze a YouTube URL and return video/playlist information.
    
    Returns available formats, playlist info if applicable, and video metadata.
    """
    try:
        result = await ytdlp_service.analyze_url(request.url)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/download", response_model=QueueItem)
async def start_download(request: DownloadRequest):
    """
    Add a download to the queue.
    
    The download will be processed by the background worker.
    """
    try:
        item = await queue_manager.add_to_queue(request)
        return item
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/download/batch", response_model=List[QueueItem])
async def start_batch_download(requests: List[DownloadRequest]):
    """
    Add multiple downloads to the queue (for playlists).
    """
    items = []
    for request in requests:
        try:
            item = await queue_manager.add_to_queue(request)
            items.append(item)
        except Exception as e:
            # Continue with other items even if one fails
            pass
    return items


@router.get("/files/{item_id}")
async def download_file(item_id: str):
    """
    Download a completed file by queue item ID.
    """
    queue_response = await queue_manager.get_queue()
    
    # Find the item in the queue
    item = None
    for q_item in queue_response.items:
        if q_item.id == item_id:
            item = q_item
            break
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if not item.file_path:
        raise HTTPException(status_code=404, detail="File not available")
    
    file_path = Path(item.file_path)
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    
    # Get the filename for the download
    filename = file_path.name
    
    # URL encode the filename for Content-Disposition header
    encoded_filename = urllib.parse.quote(filename)
    
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )


@router.get("/files/list")
async def list_files():
    """
    List all downloaded files.
    """
    if not DOWNLOAD_DIR.exists():
        return {"files": []}
    
    files = []
    for f in DOWNLOAD_DIR.iterdir():
        if f.is_file():
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime,
            })
    
    # Sort by modification time, newest first
    files.sort(key=lambda x: x["modified"], reverse=True)
    
    return {"files": files}


@router.get("/plex/status")
async def get_plex_status():
    """
    Check if Plex integration is available.
    Returns status of Plex directory mappings.
    """
    return ytdlp_service.get_plex_status()
