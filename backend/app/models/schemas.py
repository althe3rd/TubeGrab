from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
from datetime import datetime
import uuid


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FormatType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"


class VideoFormat(BaseModel):
    format_id: str
    ext: str
    resolution: Optional[str] = None
    filesize: Optional[int] = None
    filesize_approx: Optional[int] = None
    format_note: Optional[str] = None
    fps: Optional[int] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    format_type: FormatType = FormatType.VIDEO


class PlaylistItem(BaseModel):
    id: str
    title: str
    url: str
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    index: int


class AnalyzeRequest(BaseModel):
    url: str


class AnalyzeResponse(BaseModel):
    id: str
    title: str
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    uploader: Optional[str] = None
    is_playlist: bool = False
    playlist_count: Optional[int] = None
    playlist_title: Optional[str] = None
    playlist_items: Optional[List[PlaylistItem]] = None
    formats: List[VideoFormat] = []


class DownloadRequest(BaseModel):
    url: str
    video_id: str
    title: str
    thumbnail: Optional[str] = None
    format_id: str
    format_label: str
    is_audio_only: bool = False
    audio_quality: Optional[str] = None  # e.g., "320", "192", "128"
    audio_codec: Optional[str] = None  # e.g., "mp3", "m4a"
    playlist_items: Optional[List[str]] = None  # List of video IDs if downloading multiple


class QueueItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    video_id: str
    url: str
    title: str
    thumbnail: Optional[str] = None
    format_id: str
    format_label: str
    is_audio_only: bool = False
    audio_quality: Optional[str] = None
    audio_codec: Optional[str] = None
    status: DownloadStatus = DownloadStatus.QUEUED
    progress: float = 0.0
    speed: Optional[str] = None
    eta: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    file_path: Optional[str] = None


class QueueItemUpdate(BaseModel):
    id: str
    status: DownloadStatus
    progress: float = 0.0
    speed: Optional[str] = None
    eta: Optional[str] = None
    error: Optional[str] = None
    file_path: Optional[str] = None


class QueueResponse(BaseModel):
    items: List[QueueItem]
    active_downloads: int
    completed_count: int
    failed_count: int
