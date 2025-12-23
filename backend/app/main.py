from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os

from app.routes import downloads, queue
from app.services.queue import queue_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start the background download worker
    await queue_manager.start_worker()
    yield
    # Shutdown: Stop the worker
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
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}


# Serve frontend static files
frontend_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

    @app.get("/")
    async def serve_frontend():
        return FileResponse(os.path.join(frontend_path, "index.html"))

