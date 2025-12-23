import yt_dlp
import asyncio
from typing import Optional, Callable, Dict, Any, List
from pathlib import Path
import re

from app.models.schemas import (
    AnalyzeResponse,
    VideoFormat,
    FormatType,
    PlaylistItem,
)


# Default download directory
DOWNLOAD_DIR = Path("/downloads")


class YTDLPService:
    """Service wrapper for yt-dlp operations."""

    def __init__(self, download_dir: Path = DOWNLOAD_DIR):
        self.download_dir = download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def _get_base_opts(self) -> Dict[str, Any]:
        """Get base yt-dlp options."""
        return {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }

    def _parse_formats(self, formats: List[Dict]) -> List[VideoFormat]:
        """Parse yt-dlp formats into our schema."""
        parsed_formats = []
        seen_resolutions = set()

        # Common resolutions we want to offer
        target_resolutions = ["2160", "1440", "1080", "720", "480", "360", "240"]

        for fmt in formats:
            format_id = fmt.get("format_id", "")
            ext = fmt.get("ext", "")
            vcodec = fmt.get("vcodec", "none")
            acodec = fmt.get("acodec", "none")
            height = fmt.get("height")
            filesize = fmt.get("filesize") or fmt.get("filesize_approx")

            # Skip formats without proper codecs
            if vcodec == "none" and acodec == "none":
                continue

            # Determine format type
            if vcodec != "none" and vcodec:
                format_type = FormatType.VIDEO
                resolution = f"{height}p" if height else fmt.get("format_note", "Unknown")
            else:
                format_type = FormatType.AUDIO
                resolution = "Audio"

            # Skip duplicate resolutions for video
            if format_type == FormatType.VIDEO and height:
                res_key = f"{height}_{ext}"
                if res_key in seen_resolutions:
                    continue
                seen_resolutions.add(res_key)

            parsed_formats.append(VideoFormat(
                format_id=format_id,
                ext=ext,
                resolution=resolution,
                filesize=filesize,
                format_note=fmt.get("format_note"),
                fps=fmt.get("fps"),
                vcodec=vcodec if vcodec != "none" else None,
                acodec=acodec if acodec != "none" else None,
                format_type=format_type,
            ))

        # Sort by resolution (highest first for video)
        def sort_key(f: VideoFormat):
            if f.format_type == FormatType.AUDIO:
                return (1, 0)  # Audio at the end
            match = re.search(r"(\d+)", f.resolution or "0")
            height = int(match.group(1)) if match else 0
            return (0, -height)  # Video sorted by height descending

        parsed_formats.sort(key=sort_key)
        return parsed_formats

    async def analyze_url(self, url: str) -> AnalyzeResponse:
        """Analyze a YouTube URL and return metadata."""

        def _extract():
            opts = self._get_base_opts()
            opts["extract_flat"] = "in_playlist"

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info

        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, _extract)

        if not info:
            raise ValueError("Could not extract video information")

        # Check if it's a playlist
        is_playlist = info.get("_type") == "playlist" or "entries" in info

        if is_playlist:
            entries = list(info.get("entries", []))
            playlist_items = []

            for idx, entry in enumerate(entries[:50]):  # Limit to first 50 items
                if entry:
                    playlist_items.append(PlaylistItem(
                        id=entry.get("id", ""),
                        title=entry.get("title", "Unknown"),
                        url=entry.get("url") or entry.get("webpage_url", ""),
                        thumbnail=entry.get("thumbnail"),
                        duration=entry.get("duration"),
                        index=idx + 1,
                    ))

            # Get formats from first video if available
            formats = []
            if entries and entries[0]:
                first_video_url = entries[0].get("url") or entries[0].get("webpage_url")
                if first_video_url:
                    formats = await self._get_formats_for_video(first_video_url)

            return AnalyzeResponse(
                id=info.get("id", ""),
                title=info.get("title", "Unknown Playlist"),
                thumbnail=info.get("thumbnail") or (entries[0].get("thumbnail") if entries else None),
                is_playlist=True,
                playlist_count=len(entries),
                playlist_title=info.get("title"),
                playlist_items=playlist_items,
                formats=formats,
            )
        else:
            # Single video
            formats = self._parse_formats(info.get("formats", []))

            return AnalyzeResponse(
                id=info.get("id", ""),
                title=info.get("title", "Unknown"),
                thumbnail=info.get("thumbnail"),
                duration=info.get("duration"),
                uploader=info.get("uploader"),
                is_playlist=False,
                formats=formats,
            )

    async def _get_formats_for_video(self, url: str) -> List[VideoFormat]:
        """Get available formats for a single video."""

        def _extract():
            opts = self._get_base_opts()
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info.get("formats", []) if info else []

        loop = asyncio.get_event_loop()
        formats = await loop.run_in_executor(None, _extract)
        return self._parse_formats(formats)

    async def download(
        self,
        url: str,
        format_id: str,
        is_audio_only: bool = False,
        audio_quality: Optional[str] = None,
        audio_codec: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        """Download a video/audio and return the file path."""

        output_template = str(self.download_dir / "%(title)s.%(ext)s")
        downloaded_file = None

        def progress_hook(d):
            nonlocal downloaded_file

            if cancel_check and cancel_check():
                raise Exception("Download cancelled")

            if d["status"] == "downloading":
                if progress_callback:
                    progress_callback({
                        "status": "downloading",
                        "progress": self._parse_progress(d.get("_percent_str", "0%")),
                        "speed": d.get("_speed_str", ""),
                        "eta": d.get("_eta_str", ""),
                    })
            elif d["status"] == "finished":
                downloaded_file = d.get("filename")
                if progress_callback:
                    progress_callback({
                        "status": "processing",
                        "progress": 100,
                        "speed": None,
                        "eta": None,
                    })

        def _download():
            opts = {
                "outtmpl": output_template,
                "progress_hooks": [progress_hook],
                "quiet": True,
                "no_warnings": True,
            }

            if is_audio_only:
                # Download best audio and convert to specified format
                opts["format"] = "bestaudio/best"
                
                # Determine codec and quality
                codec = audio_codec or "mp3"
                quality = audio_quality or "192"
                
                # Handle "best" quality for m4a (no conversion needed)
                if codec == "m4a" and quality == "best":
                    opts["postprocessors"] = [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "m4a",
                    }]
                else:
                    opts["postprocessors"] = [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": codec,
                        "preferredquality": quality,
                    }]
            else:
                # Download specified format with best audio
                opts["format"] = f"{format_id}+bestaudio/best"
                opts["merge_output_format"] = "mp4"

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _download)

        # Find the actual downloaded file (extension might have changed)
        if downloaded_file:
            # If audio only, the extension will be .mp3
            if is_audio_only:
                mp3_file = Path(downloaded_file).with_suffix(".mp3")
                if mp3_file.exists():
                    return str(mp3_file)
            if Path(downloaded_file).exists():
                return downloaded_file

        # Fallback: find most recent file in download dir
        files = list(self.download_dir.glob("*"))
        if files:
            return str(max(files, key=lambda f: f.stat().st_mtime))

        raise Exception("Could not locate downloaded file")

    def _parse_progress(self, percent_str: str) -> float:
        """Parse progress percentage string."""
        try:
            return float(percent_str.strip().replace("%", ""))
        except (ValueError, AttributeError):
            return 0.0


# Singleton instance
ytdlp_service = YTDLPService()

