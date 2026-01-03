from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os

from app.routes import downloads, queue
from app.services.queue import queue_manager
from app.services.ytdlp import ytdlp_service
from fastapi import Query


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start the background download worker and mount health monitor
    await queue_manager.start_worker()
    await ytdlp_service.start_monitor()
    yield
    # Shutdown: Stop the worker and monitor
    await ytdlp_service.stop_monitor()
    await queue_manager.stop_worker()


app = FastAPI(
    title="YouTube Downloader",
    description="Download YouTube videos and audio with ease",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(downloads.router, prefix="/api", tags=["downloads"])
app.include_router(queue.router, prefix="/api", tags=["queue"])


# Health check endpoint
@app.get("/api/health")
async def health_check(include_mounts: bool = Query(default=False, description="Include NFS mount status")):
    """
    Health check endpoint.
    
    Args:
        include_mounts: If True, include NFS mount status in the response
    """
    response = {"status": "healthy", "version": "1.0.0"}
    
    if include_mounts:
        # Get mount status (will use cache if available)
        plex_status = ytdlp_service.get_plex_status(use_cache=True)
        response["mounts"] = {
            "plex_movies": {
                "available": plex_status["movies_available"],
                "path": plex_status["movies_path"]
            },
            "plex_music": {
                "available": plex_status["music_available"],
                "path": plex_status["music_path"]
            }
        }
    
    return response


# Serve frontend static files
frontend_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    async def serve_frontend():
        return FileResponse(os.path.join(frontend_path, "index.html"))
    
    @app.get("/manifest.json")
    async def serve_manifest():
        manifest_path = os.path.join(frontend_path, "manifest.json")
        if os.path.exists(manifest_path):
            return FileResponse(manifest_path, media_type="application/manifest+json")
        return {"error": "Manifest not found"}

