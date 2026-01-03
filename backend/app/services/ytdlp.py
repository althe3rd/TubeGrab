import yt_dlp
import asyncio
import os
import subprocess
from typing import Optional, Callable, Dict, Any, List, Tuple
from pathlib import Path
import re

from app.models.schemas import (
    AnalyzeResponse,
    VideoFormat,
    FormatType,
    PlaylistItem,
)


# Directory paths from environment variables
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "/downloads"))
PLEX_MOVIES_DIR = Path(os.environ.get("PLEX_MOVIES_DIR", "/plex/movies"))
PLEX_MUSIC_DIR = Path(os.environ.get("PLEX_MUSIC_DIR", "/plex/music"))


class YTDLPService:
    """Service wrapper for yt-dlp operations."""

    def __init__(
        self,
        download_dir: Path = DOWNLOAD_DIR,
        plex_movies_dir: Path = PLEX_MOVIES_DIR,
        plex_music_dir: Path = PLEX_MUSIC_DIR,
    ):
        self.download_dir = download_dir
        self.plex_movies_dir = plex_movies_dir
        self.plex_music_dir = plex_music_dir
        
        # Mount status cache: stores (status, timestamp) tuples
        # Key is mount path (as string), value is (is_available: bool, timestamp: float)
        self._mount_status_cache: Dict[str, Tuple[bool, float]] = {}
        self._mount_cache_ttl = 30.0  # Cache TTL in seconds (30 seconds)
        
        # Background health monitor task
        self._health_monitor_task: Optional[asyncio.Task] = None
        self._monitor_running = False
        
        # Create directories if they don't exist
        self._mkdir_with_retry(self.download_dir)
        # Set permissions for NFS shares
        self._set_file_permissions(self.download_dir)

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a filename/folder name to remove invalid characters."""
        # Remove or replace invalid characters for filesystems
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '')
        # Remove leading/trailing spaces and dots
        name = name.strip(' .')
        # Replace multiple spaces with single space
        name = re.sub(r'\s+', ' ', name)
        return name

    def _get_output_dir(self, is_audio_only: bool, send_to_plex: bool, artist: Optional[str] = None, album: Optional[str] = None) -> Tuple[Path, str]:
        """
        Get the appropriate output directory and filename template.
        Returns (output_dir, filename_template)
        """
        if send_to_plex and is_audio_only:
            # Plex music structure: /Artist/Album/TrackNumber - TrackName.ext
            if artist and album:
                artist_clean = self._sanitize_filename(artist)
                album_clean = self._sanitize_filename(album)
                
                # Create Artist/Album folder structure
                output_dir = self.plex_music_dir / artist_clean / album_clean
                self._mkdir_with_retry(output_dir)
                # Set permissions for NFS shares
                self._set_file_permissions(output_dir)
                # Also set permissions on parent directories (with retry for NFS)
                try:
                    if self._retry_nfs_operation(lambda: output_dir.parent.exists(), max_retries=2, operation_name=f"checking parent dir: {output_dir.parent}", path=output_dir.parent):
                        self._set_file_permissions(output_dir.parent)
                    if self._retry_nfs_operation(lambda: self.plex_music_dir.exists(), max_retries=2, operation_name=f"checking plex_music_dir: {self.plex_music_dir}", path=self.plex_music_dir):
                        self._set_file_permissions(self.plex_music_dir)
                except Exception as e:
                    print(f"Warning: Could not set permissions on parent directories: {e}")
                
                # Filename template: TrackNumber - TrackName.ext
                # We'll use 01, 02, etc. based on existing files in the album
                return output_dir, "%(title)s.%(ext)s"
            else:
                # Fallback if no artist/album info
                self._mkdir_with_retry(self.plex_music_dir)
                self._set_file_permissions(self.plex_music_dir)
                return self.plex_music_dir, "%(title)s.%(ext)s"
        elif send_to_plex and not is_audio_only:
            # Plex movies: just put in movies folder
            self._mkdir_with_retry(self.plex_movies_dir)
            self._set_file_permissions(self.plex_movies_dir)
            return self.plex_movies_dir, "%(title)s.%(ext)s"
        else:
            # Regular downloads
            return self.download_dir, "%(title)s.%(ext)s"

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

    def _get_track_number(self, album_dir: Path, codec: str) -> str:
        """Get the next track number for files in an album directory."""
        # Check if directory exists with retry for NFS
        try:
            dir_exists = self._retry_nfs_operation(
                lambda: album_dir.exists(),
                max_retries=3,
                operation_name=f"checking directory existence: {album_dir}"
            )
            if not dir_exists:
                return "01"
        except Exception as e:
            print(f"Error checking directory {album_dir}: {e}, defaulting to track 01")
            return "01"
        
        # Find all audio files in the album with retry for NFS
        audio_files = []
        try:
            for ext in [".mp3", ".m4a", ".flac", ".ogg", ".wav"]:
                files = self._retry_nfs_operation(
                    lambda: list(album_dir.glob(f"*{ext}")),
                    max_retries=3,
                    operation_name=f"listing files in {album_dir}",
                    path=album_dir
                )
                if files:
                    audio_files.extend(files)
        except Exception as e:
            print(f"Error listing files in {album_dir}: {e}, defaulting to track 01")
            return "01"
        
        # Extract track numbers from existing files
        track_numbers = []
        for file in audio_files:
            # Look for pattern: "NN - " or "NNN - " at start of filename
            match = re.match(r"^(\d{2,3})\s*-\s*", file.stem)
            if match:
                try:
                    track_numbers.append(int(match.group(1)))
                except ValueError:
                    pass
        
        # Get next track number
        if track_numbers:
            next_track = max(track_numbers) + 1
        else:
            next_track = 1
        
        return f"{next_track:02d}"

    async def download(
        self,
        url: str,
        format_id: str,
        is_audio_only: bool = False,
        audio_quality: Optional[str] = None,
        audio_codec: Optional[str] = None,
        send_to_plex: bool = False,
        convert_video: bool = False,
        progress_callback: Optional[Callable[[Dict], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        """Download a video/audio and return the file path."""

        # First, extract metadata for embedding and folder structure
        def _extract_metadata():
            opts = self._get_base_opts()
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info

        loop = asyncio.get_event_loop()
        video_info = await loop.run_in_executor(None, _extract_metadata)

        # Extract artist and album info for Plex folder structure
        artist = None
        album = None
        clean_title = video_info.get("title", "")
        
        if is_audio_only:
            uploader = video_info.get("uploader", "") or video_info.get("channel", "")
            uploader_id = video_info.get("uploader_id", "")
            channel = video_info.get("channel", "")
            
            # Default artist
            artist = uploader or channel or uploader_id or "Unknown Artist"
            
            # Clean up title
            for suffix in [" (Official Video)", " (Official Audio)", " [Official Video]", " [Official Audio]"]:
                if clean_title.endswith(suffix):
                    clean_title = clean_title[:-len(suffix)]
            
            # Parse "Artist - Title" format
            if " - " in clean_title:
                parts = clean_title.split(" - ", 1)
                if len(parts) == 2:
                    artist = parts[0].strip()
                    clean_title = parts[1].strip()
            elif ": " in clean_title and clean_title.count(": ") == 1:
                parts = clean_title.split(": ", 1)
                if len(parts) == 2:
                    artist = parts[0].strip()
                    clean_title = parts[1].strip()
            
            # Try to extract album from video metadata
            # Check if yt-dlp extracted album info (available for some music sources)
            album = video_info.get("album")
            
            # Check playlist name (often represents an album for music videos)
            if not album:
                playlist = video_info.get("playlist") or video_info.get("playlist_title")
                if playlist:
                    # Use playlist name as album if it looks like an album name
                    # (not generic names like "Uploads" or "Videos")
                    generic_names = ["uploads", "videos", "playlist", "music", "songs", "tracks"]
                    if playlist.lower() not in generic_names:
                        album = playlist
            
            # If no album in metadata, try to extract from description
            if not album:
                description = video_info.get("description", "")
                # Look for common album patterns in description
                # Pattern: "Album:", "from [Album]", "on [Album]", etc.
                album_patterns = [
                    r'Album[:\s]+([^\n]+)',
                    r'from\s+["\']?([^"\'\n]+)["\']?\s+album',
                    r'on\s+["\']?([^"\'\n]+)["\']?\s+album',
                    r'Album:\s*([^\n]+)',
                ]
                for pattern in album_patterns:
                    match = re.search(pattern, description, re.IGNORECASE)
                    if match:
                        album = match.group(1).strip()
                        # Clean up common suffixes
                        album = re.sub(r'\s*\[.*?\]\s*$', '', album)  # Remove [stuff]
                        album = re.sub(r'\s*\(.*?\)\s*$', '', album)  # Remove (stuff)
                        album = album.strip()
                        if album:
                            break
            
            # If still no album, check if title contains album info (e.g., "Song (from Album)")
            if not album:
                # Pattern: "Title (from Album)" or "Title [from Album]"
                album_match = re.search(r'\(from\s+([^)]+)\)|\[from\s+([^\]]+)\]', clean_title, re.IGNORECASE)
                if album_match:
                    album = (album_match.group(1) or album_match.group(2)).strip()
                    # Remove the album part from title
                    clean_title = re.sub(r'\s*\(from\s+[^)]+\)\s*|\s*\[from\s+[^\]]+\]\s*', '', clean_title, flags=re.IGNORECASE).strip()
            
            # Fallback: use uploader/channel as album name only if we have no other option
            # But prefer "Singles" or artist name + " Collection" as more accurate
            if not album:
                # Use a generic fallback instead of uploader to avoid confusion
                album = "Singles" if artist else (uploader or channel or "YouTube")

        # Get output directory and filename template
        output_dir, filename_template = self._get_output_dir(
            is_audio_only, 
            send_to_plex, 
            artist, 
            album
        )
        
        # For Plex music, determine track number and add to filename
        track_num = None
        if send_to_plex and is_audio_only and artist and album:
            codec = audio_codec or "mp3"
            track_num = self._get_track_number(output_dir, codec)
            # Update template to include track number
            filename_template = f"{track_num} - %(title)s.%(ext)s"
        
        # Validate output directory is accessible (important for NFS mounts)
        try:
            self._retry_nfs_operation(
                lambda: output_dir.exists() or output_dir.mkdir(parents=True, exist_ok=True),
                max_retries=3,
                operation_name=f"validating output directory: {output_dir}",
                path=output_dir
            )
            # Test write access by checking if we can list the directory
            self._retry_nfs_operation(
                lambda: list(output_dir.iterdir()) if output_dir.exists() else True,
                max_retries=2,
                operation_name=f"testing directory access: {output_dir}",
                path=output_dir
            )
        except Exception as e:
            raise Exception(f"Cannot access output directory {output_dir}: {e}. This may be an NFS stale file handle issue. Please check your NFS mount.")
        
        output_template = str(output_dir / filename_template)
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

            # Add metadata embedding for better Plex recognition
            if is_audio_only:
                # Download best audio and convert to specified format
                opts["format"] = "bestaudio/best"
                
                # Determine codec and quality
                codec = audio_codec or "mp3"
                quality = audio_quality or "192"
                
                # Use the artist/album/title we already extracted above
                # (These are available in the outer scope)
                
                # Build postprocessors list
                postprocessors = []
                
                # Handle "best" quality for m4a (no conversion needed)
                if codec == "m4a" and quality == "best":
                    postprocessors.append({
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "m4a",
                    })
                else:
                    postprocessors.append({
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": codec,
                        "preferredquality": quality,
                    })
                
                opts["postprocessors"] = postprocessors
                
            else:
                # Download specified format with best audio
                opts["format"] = f"{format_id}+bestaudio/best"
                opts["merge_output_format"] = "mp4"
                # Still add metadata for videos
                opts["addmetadata"] = True

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _download)

        # Find the actual downloaded file (extension might have changed)
        final_file = None
        if downloaded_file:
            # If audio only, the extension might have changed
            if is_audio_only:
                codec = audio_codec or "mp3"
                converted_file = Path(downloaded_file).with_suffix(f".{codec}")
                if converted_file.exists():
                    final_file = converted_file
            if not final_file and Path(downloaded_file).exists():
                final_file = Path(downloaded_file)

        # Fallback: find most recent file in output dir (exclude temp files)
        if not final_file:
            try:
                all_files = self._retry_nfs_operation(
                    lambda: list(output_dir.glob("*")),
                    max_retries=3,
                    operation_name=f"finding files in {output_dir}",
                    path=output_dir
                )
                files = [f for f in all_files 
                        if f.is_file() and not f.name.endswith(".tmp.mp4") and not f.name.endswith(".tmp.m4a")]
                if files:
                    # Get file mtime with retry
                    def get_mtime(f):
                        return self._retry_nfs_operation(
                            lambda: f.stat().st_mtime,
                            max_retries=2,
                            operation_name=f"getting mtime for {f.name}",
                            path=f
                        )
                    final_file = max(files, key=get_mtime)
            except Exception as e:
                print(f"Error finding files in output directory: {e}")
                raise Exception("Could not locate downloaded file")

        if not final_file:
            raise Exception("Could not locate downloaded file")

        # For Plex music, ensure filename has proper format with cleaned title
        if send_to_plex and is_audio_only and artist and album and track_num:
            # File should already have track number from template, just clean the title
            sanitized_title = self._sanitize_filename(clean_title)
            new_name = f"{track_num} - {sanitized_title}{final_file.suffix}"
            new_file = output_dir / new_name
            
            # Rename if filename is different (to use cleaned title)
            if final_file.name != new_name:
                # Check if new file exists with retry
                new_exists = self._retry_nfs_operation(
                    lambda: new_file.exists(),
                    max_retries=2,
                    operation_name=f"checking if {new_file.name} exists",
                    path=new_file
                )
                if not new_exists:
                    # Rename with retry for NFS
                    self._retry_nfs_operation(
                        lambda: final_file.rename(new_file),
                        max_retries=3,
                        operation_name=f"renaming {final_file.name} to {new_file.name}",
                        path=final_file
                    )
                    final_file = new_file
                    # Set permissions on the renamed file
                    self._set_file_permissions(final_file)

        # Set permissions on the final file for NFS shares
        if final_file.exists():
            self._set_file_permissions(final_file)

        # Add metadata for audio files to help Plex identify them
        if is_audio_only and final_file.exists():
            # Use the artist, album, and clean_title we already extracted above
            # Get uploader for album_artist if needed
            uploader = video_info.get("uploader", "") or video_info.get("channel", "")
            
            # Run in executor to avoid blocking
            def _add_metadata():
                return self._add_audio_metadata(
                    final_file,
                    clean_title,
                    artist,
                    album,
                    uploader if uploader else None
                )
            await loop.run_in_executor(None, _add_metadata)
            # Set permissions after metadata is added
            if final_file.exists():
                self._set_file_permissions(final_file)

        # Convert video if requested (only for video files, not audio-only)
        if convert_video and not is_audio_only and final_file.exists():
            # Clean up any leftover temp files from previous failed conversions
            temp_files = list(final_file.parent.glob("*.tmp.mp4"))
            for temp_file in temp_files:
                try:
                    if temp_file.exists():
                        temp_file.unlink()
                        print(f"Cleaned up leftover temp file: {temp_file.name}")
                except Exception as e:
                    print(f"Could not clean up temp file {temp_file.name}: {e}")
            
            # Validate that we're not trying to convert a temp file
            if final_file.name.endswith(".tmp.mp4"):
                # This shouldn't happen, but if it does, find the original file
                original_name = final_file.name.replace(".tmp.mp4", ".mp4")
                original_file = final_file.parent / original_name
                if original_file.exists() and original_file.stat().st_size > 0:
                    print(f"Found temp file, using original instead: {original_file.name}")
                    final_file = original_file
                else:
                    raise Exception(f"Cannot convert temp file. Original file not found: {original_name}")
            
            # Validate file is not empty or corrupted
            if final_file.stat().st_size == 0:
                raise Exception(f"File is empty: {final_file.name}")
            
            # Validate file is a valid video file using ffprobe
            try:
                validate_args = [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(final_file)
                ]
                validate_result = subprocess.run(
                    validate_args,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if validate_result.returncode != 0:
                    raise Exception(f"File appears to be corrupted or incomplete: {final_file.name}. Error: {validate_result.stderr[:200]}")
            except subprocess.TimeoutExpired:
                print(f"Warning: Could not validate file {final_file.name} (timeout), proceeding anyway")
            except Exception as e:
                raise Exception(f"Cannot convert file - validation failed: {e}")
            
            if progress_callback:
                progress_callback({
                    "status": "converting",
                    "progress": 0,
                    "speed": None,
                    "eta": "Starting conversion...",
                })
            
            # Create a progress callback wrapper for conversion
            def conversion_progress_callback(progress: float, speed: Optional[str]):
                """Wrapper to convert conversion progress to download progress format."""
                if progress_callback:
                    # Map conversion progress (0-100) to overall progress (95-99)
                    # Start at 95% (after download), end at 99% (before finalizing)
                    mapped_progress = 95 + (progress * 0.04)  # 95% to 99%
                    progress_callback({
                        "status": "converting",
                        "progress": mapped_progress,
                        "speed": speed,
                        "eta": f"Converting... {int(progress)}%",
                    })
            
            # Run conversion in executor with progress callback
            def _convert():
                return self._convert_video(final_file, cancel_check, conversion_progress_callback)
            
            try:
                print(f"Starting video conversion for: {final_file.name}")
                converted_file = await loop.run_in_executor(None, _convert)
                final_file = converted_file
                print(f"Video conversion completed: {final_file.name}")
                # Set permissions on converted file
                if final_file.exists():
                    self._set_file_permissions(final_file)
                
                # Send final progress update (100%) but don't set status
                # Let the queue service set it to COMPLETED when download function returns
                if progress_callback:
                    progress_callback({
                        "progress": 100,
                        "speed": None,
                        "eta": None,
                    })
            except Exception as e:
                error_msg = str(e)
                print(f"Video conversion error: {error_msg}")
                # Log to stderr so it's more visible
                import sys
                print(f"ERROR: Video conversion failed for {final_file.name}: {error_msg}", file=sys.stderr)
                # Continue with original file if conversion fails
                # Send progress update but don't set status - let queue service handle completion
                if progress_callback:
                    progress_callback({
                        "progress": 100,
                        "speed": None,
                        "eta": None,
                    })
                pass

        return str(final_file)

    def _parse_progress(self, percent_str: str) -> float:
        """Parse progress percentage string."""
        try:
            return float(percent_str.strip().replace("%", ""))
        except (ValueError, AttributeError):
            return 0.0

    def _add_audio_metadata(self, file_path: Path, title: str, artist: str, album: str, album_artist: Optional[str] = None):
        """Add metadata to an audio file using ffmpeg."""
        try:
            args = [
                "ffmpeg",
                "-i", str(file_path),
                "-metadata", f"title={title}",
                "-metadata", f"artist={artist}",
                "-metadata", f"album={album}",
            ]
            
            if album_artist:
                args.extend(["-metadata", f"albumartist={album_artist}"])
            
            # For MP3, ensure ID3v2 tags are written
            if file_path.suffix.lower() == ".mp3":
                args.extend(["-id3v2_version", "3"])
            
            # Write to temp file then replace
            temp_file = file_path.with_suffix(f".tmp{file_path.suffix}")
            args.extend([
                "-codec", "copy",  # Copy audio without re-encoding
                "-y",  # Overwrite output file
                str(temp_file),
            ])
            
            # Run ffmpeg
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Replace original with tagged file
            temp_file.replace(file_path)
            # Set permissions on the file with metadata for NFS shares
            self._set_file_permissions(file_path)
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"Failed to add metadata: {e.stderr}")
            return False
        except Exception as e:
            print(f"Error adding metadata: {e}")
            return False

    def _check_nvidia_gpu(self) -> bool:
        """Check if NVIDIA GPU is available for hardware encoding."""
        try:
            # Check if nvidia-smi works
            result = subprocess.run(
                ["nvidia-smi"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return False
            
            # Check if ffmpeg has h264_nvenc encoder available
            test_result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=5
            )
            # Just check if encoder is listed - actual functionality will be tested during conversion
            return test_result.returncode == 0 and "h264_nvenc" in test_result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            print(f"GPU check failed: {e}, using CPU encoding")
            return False

    def _get_video_duration(self, file_path: Path) -> float:
        """Get video duration in seconds using ffprobe."""
        try:
            args = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path)
            ]
            result = subprocess.run(args, capture_output=True, text=True, check=True)
            return float(result.stdout.strip())
        except Exception as e:
            print(f"Could not get video duration: {e}")
            return 0.0

    def _parse_ffmpeg_progress(self, line: str, duration: float) -> Optional[float]:
        """Parse ffmpeg progress output and return percentage."""
        # FFmpeg with -progress outputs: key=value pairs
        # We need to extract the out_time_ms or time value
        if "=" not in line:
            return None
        
        key, value = line.strip().split("=", 1)
        
        if key == "out_time_ms":
            # Time in microseconds
            try:
                elapsed = float(value) / 1000000.0  # Convert to seconds
                if duration > 0:
                    progress = min(100.0, (elapsed / duration) * 100.0)
                    return progress
            except ValueError:
                pass
        elif key == "out_time":
            # Time in HH:MM:SS.microseconds format
            try:
                # Parse time string like "00:00:05.123456"
                parts = value.split(":")
                if len(parts) == 3:
                    hours = int(parts[0])
                    minutes = int(parts[1])
                    sec_parts = parts[2].split(".")
                    seconds = int(sec_parts[0])
                    microseconds = int(sec_parts[1]) if len(sec_parts) > 1 else 0
                    elapsed = hours * 3600 + minutes * 60 + seconds + microseconds / 1000000.0
                    if duration > 0:
                        progress = min(100.0, (elapsed / duration) * 100.0)
                        return progress
            except (ValueError, IndexError):
                pass
        
        return None

    def _convert_video(
        self, 
        file_path: Path, 
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Path:
        """
        Convert video to H.264/AAC MP4 format.
        Uses hardware acceleration (NVENC) if available, otherwise software encoding.
        """
        try:
            # Get video duration for progress calculation
            duration = self._get_video_duration(file_path)
            
            # Check for NVIDIA GPU
            use_hw_accel = self._check_nvidia_gpu()
            
            # Use temporary file to avoid overwriting input
            # FFmpeg can't write to the same file it's reading from
            temp_file = file_path.with_suffix(".tmp.mp4")
            output_file = file_path.with_suffix(".mp4")
            
            # Build ffmpeg command
            args = [
                "ffmpeg",
                "-i", str(file_path),
                "-progress", "pipe:1",  # Output progress to stdout
                "-loglevel", "error",  # Only show errors in stderr
            ]
            
            if cancel_check and cancel_check():
                raise Exception("Conversion cancelled")
            
            # Map all streams (video and audio)
            args.extend(["-map", "0"])
            
            # Try conversion - first with GPU if available, fallback to CPU on error
            conversion_success = False
            for attempt in range(2):  # Try GPU first, then CPU
                try_gpu = use_hw_accel and attempt == 0
                
                # Build ffmpeg command
                args = [
                    "ffmpeg",
                    "-i", str(file_path),
                    "-progress", "pipe:1",
                    "-loglevel", "error",
                    "-map", "0",
                ]
                
                # Video encoding options
                if try_gpu:
                    # Use NVIDIA hardware encoding
                    args.extend([
                        "-c:v", "h264_nvenc",
                        "-preset", "p4",
                        "-crf", "23",
                        "-b:v", "0",
                    ])
                    print(f"Attempting GPU encoding (attempt {attempt + 1})...")
                else:
                    # Software encoding (libx264)
                    args.extend([
                        "-c:v", "libx264",
                        "-preset", "medium",
                        "-crf", "23",
                    ])
                    if attempt == 1:
                        print("GPU encoding failed, falling back to CPU encoding...")
                
                # Audio encoding - FORCE re-encoding to AAC (don't copy)
                args.extend([
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-ar", "48000",
                    "-ac", "2",
                    "-map_metadata", "0",
                    "-movflags", "+faststart",
                    "-y", str(temp_file),
                ])
                
                if attempt == 0:
                    print(f"Converting video: {file_path.name} -> {output_file.name}")
                    print(f"Using temporary file: {temp_file.name}")
                    if duration > 0:
                        print(f"Video duration: {duration:.2f} seconds")
                
                # Run conversion with progress tracking
                import threading
                process = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                
                # Read progress from stdout and errors from stderr
                stderr_lines = []
                
                def read_stderr():
                    for line in process.stderr:
                        stderr_lines.append(line)
                
                stderr_thread = threading.Thread(target=read_stderr, daemon=True)
                stderr_thread.start()
                
                # Read progress from stdout
                last_progress = 0.0
                current_speed = None
                for line in process.stdout:
                    if cancel_check and cancel_check():
                        process.terminate()
                        process.wait()
                        raise Exception("Conversion cancelled")
                    
                    # Parse progress line (key=value format)
                    if "=" in line:
                        key, value = line.strip().split("=", 1)
                        
                        # Extract speed
                        if key == "speed":
                            try:
                                speed_val = float(value)
                                current_speed = f"{speed_val:.2f}x"
                            except ValueError:
                                pass
                        
                        # Extract progress
                        progress = self._parse_ffmpeg_progress(line, duration)
                        if progress is not None and progress > last_progress:
                            last_progress = progress
                            if progress_callback:
                                progress_callback(progress, current_speed)
                
                # Wait for stderr thread to finish
                stderr_thread.join(timeout=1)
                
                # Wait for process to complete
                process.wait()
                
                if process.returncode == 0:
                    conversion_success = True
                    break
                else:
                    stderr_output = "\n".join(stderr_lines) if stderr_lines else "Unknown error"
                    
                    # If GPU encoding failed due to driver/library issues, retry with CPU
                    if try_gpu and (
                        "libnvidia-encode" in stderr_output or 
                        "driver" in stderr_output.lower() or
                        ("nvenc" in stderr_output.lower() and ("cannot" in stderr_output.lower() or "error" in stderr_output.lower()))
                    ):
                        print(f"GPU encoding failed: {stderr_output[:200]}...")
                        print("NVIDIA libraries not accessible from container (NVIDIA Container Toolkit may not be configured)")
                        print("Falling back to CPU encoding...")
                        # Will retry with CPU on next iteration
                        continue
                    else:
                        # Other errors - fail immediately
                        raise subprocess.CalledProcessError(process.returncode, args, stderr=stderr_output)
            
            if not conversion_success:
                raise Exception("Video conversion failed with both GPU and CPU encoding")
            
            # Check if temp file was created and has content
            if not temp_file.exists():
                raise Exception("Conversion output file was not created")
            
            if temp_file.stat().st_size == 0:
                raise Exception("Conversion produced empty file")
            
            # Verify the conversion worked by checking codecs
            verify_args = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(temp_file)
            ]
            
            verify_result = subprocess.run(
                verify_args,
                capture_output=True,
                text=True
            )
            
            audio_codec = verify_result.stdout.strip()
            if audio_codec.lower() != "aac":
                print(f"Warning: Audio codec is {audio_codec}, expected AAC")
            
            # Replace original file with converted file
            if output_file.exists() and output_file != file_path:
                # If output file already exists and is different from input, remove it
                output_file.unlink()
            
            # Move temp file to final location
            temp_file.replace(output_file)
            
            # Set permissions on the converted file for NFS shares
            self._set_file_permissions(output_file)
            
            # Remove original file if it's different from output
            if file_path != output_file and file_path.exists():
                file_path.unlink()  # Delete original
            
            print(f"Conversion successful: {output_file.name} (audio codec: {audio_codec})")
            return output_file
                
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else e.stdout if e.stdout else "Unknown error"
            print(f"Video conversion failed: {error_msg}")
            raise Exception(f"Video conversion failed: {error_msg}")
        except Exception as e:
            print(f"Error converting video: {e}")
            raise

    def get_plex_status(self, use_cache: bool = True) -> Dict[str, Any]:
        """
        Check if Plex directories are configured and accessible.
        
        Args:
            use_cache: If True, use cached status if available and valid
            
        Returns:
            Dictionary with Plex status information
        """
        # Check cached status first
        if use_cache:
            cached_movies = self._get_cached_mount_status(self.plex_movies_dir)
            cached_music = self._get_cached_mount_status(self.plex_music_dir)
            
            # If both are cached and valid, use them
            if cached_movies is not None and cached_music is not None:
                movies_available = cached_movies
                music_available = cached_music
            else:
                # Need to check at least one, so check both
                movies_available, music_available = self._check_plex_mounts()
        else:
            movies_available, music_available = self._check_plex_mounts()
        
        return {
            "enabled": movies_available or music_available,
            "movies_path": str(self.plex_movies_dir),
            "movies_available": movies_available,
            "music_path": str(self.plex_music_dir),
            "music_available": music_available,
        }
    
    def _check_plex_mounts(self) -> Tuple[bool, bool]:
        """
        Check Plex mount availability and update cache.
        
        Returns:
            Tuple of (movies_available, music_available)
        """
        # Check movies directory
        try:
            movies_exists = self._retry_nfs_operation(
                lambda: self.plex_movies_dir.exists(),
                max_retries=3,
                operation_name=f"checking plex_movies_dir: {self.plex_movies_dir}",
                path=self.plex_movies_dir
            )
            movies_available = movies_exists or self._can_create_dir(self.plex_movies_dir)
            self._set_cached_mount_status(self.plex_movies_dir, movies_available)
        except Exception as e:
            print(f"Error checking plex_movies_dir: {e}")
            movies_available = False
            self._set_cached_mount_status(self.plex_movies_dir, False)
        
        # Check music directory
        try:
            music_exists = self._retry_nfs_operation(
                lambda: self.plex_music_dir.exists(),
                max_retries=3,
                operation_name=f"checking plex_music_dir: {self.plex_music_dir}",
                path=self.plex_music_dir
            )
            music_available = music_exists or self._can_create_dir(self.plex_music_dir)
            self._set_cached_mount_status(self.plex_music_dir, music_available)
        except Exception as e:
            print(f"Error checking plex_music_dir: {e}")
            music_available = False
            self._set_cached_mount_status(self.plex_music_dir, False)
        
        return movies_available, music_available

    async def _mount_health_monitor(self, interval: float = 45.0):
        """
        Background task to periodically monitor NFS mount health and proactively refresh mounts.
        
        Args:
            interval: How often to check mounts in seconds (default: 45 seconds)
        """
        import time
        while self._monitor_running:
            try:
                # Check both Plex mounts (they're always configured, even if using defaults)
                mounts_to_check = [self.plex_movies_dir, self.plex_music_dir]
                
                for mount_path in mounts_to_check:
                    try:
                        # Try to access the mount - if it fails, it might be stale
                        # Use a quick check that doesn't require the full get_plex_status logic
                        try:
                            mount_path.stat()
                            # Mount is accessible, refresh cache with positive status
                            self._set_cached_mount_status(mount_path, True)
                            # Proactively refresh the mount to prevent staleness
                            self._refresh_nfs_mount(mount_path)
                        except OSError as e:
                            if e.errno == 116:  # Stale file handle
                                print(f"Health monitor detected stale file handle on {mount_path}, attempting refresh...")
                                # Try to refresh the mount
                                refresh_success = self._refresh_nfs_mount(mount_path)
                                if refresh_success:
                                    # Try accessing again after refresh
                                    try:
                                        mount_path.stat()
                                        self._set_cached_mount_status(mount_path, True)
                                        print(f"Mount refresh successful for {mount_path}")
                                    except OSError:
                                        self._set_cached_mount_status(mount_path, False)
                                        print(f"Mount still unavailable after refresh: {mount_path}")
                                else:
                                    self._set_cached_mount_status(mount_path, False)
                            else:
                                # Other error, mark as unavailable
                                self._set_cached_mount_status(mount_path, False)
                    except Exception as e:
                        print(f"Error in health monitor checking {mount_path}: {e}")
                        self._set_cached_mount_status(mount_path, False)
                
                # Wait for next check
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                # Task was cancelled, exit cleanly
                break
            except Exception as e:
                print(f"Error in mount health monitor: {e}")
                # Wait a bit before retrying to avoid tight error loops
                await asyncio.sleep(interval)

    async def start_monitor(self):
        """Start the background mount health monitor."""
        if not self._monitor_running:
            self._monitor_running = True
            loop = asyncio.get_event_loop()
            self._health_monitor_task = loop.create_task(self._mount_health_monitor())
            print("NFS mount health monitor started")

    async def stop_monitor(self):
        """Stop the background mount health monitor."""
        if self._monitor_running:
            self._monitor_running = False
            if self._health_monitor_task:
                self._health_monitor_task.cancel()
                try:
                    await self._health_monitor_task
                except asyncio.CancelledError:
                    pass
                self._health_monitor_task = None
            print("NFS mount health monitor stopped")

    def _can_create_dir(self, path: Path) -> bool:
        """Check if we can create a directory at the given path."""
        try:
            self._mkdir_with_retry(path)
            return True
        except (PermissionError, OSError):
            return False

    def _set_file_permissions(self, file_path: Path):
        """Set appropriate file permissions for NFS shares and shared storage.
        Sets files to 664 (rw-rw-r--) and directories to 775 (rwxrwxr-x).
        """
        try:
            if file_path.exists():
                if file_path.is_dir():
                    # Directories: 775 (rwxrwxr-x) - readable/writable by owner and group
                    file_path.chmod(0o775)
                else:
                    # Files: 664 (rw-rw-r--) - readable/writable by owner and group
                    file_path.chmod(0o664)
        except (PermissionError, OSError) as e:
            # If we can't set permissions (e.g., on NFS with root_squash), log but don't fail
            print(f"Could not set permissions on {file_path}: {e}")

    def _get_cached_mount_status(self, mount_path: Path) -> Optional[bool]:
        """
        Get cached mount status if it's still valid (within TTL).
        
        Args:
            mount_path: The mount path to check
            
        Returns:
            True if mount is available, False if unavailable, None if cache is expired/missing
        """
        path_str = str(mount_path)
        if path_str in self._mount_status_cache:
            status, timestamp = self._mount_status_cache[path_str]
            import time
            age = time.time() - timestamp
            if age < self._mount_cache_ttl:
                return status
            else:
                # Cache expired, remove it
                del self._mount_status_cache[path_str]
        return None

    def _set_cached_mount_status(self, mount_path: Path, is_available: bool):
        """
        Cache mount status with current timestamp.
        
        Args:
            mount_path: The mount path
            is_available: Whether the mount is available
        """
        import time
        path_str = str(mount_path)
        self._mount_status_cache[path_str] = (is_available, time.time())

    def _invalidate_mount_cache(self, mount_path: Optional[Path] = None):
        """
        Invalidate mount status cache.
        
        Args:
            mount_path: Specific mount path to invalidate, or None to invalidate all
        """
        if mount_path:
            path_str = str(mount_path)
            if path_str in self._mount_status_cache:
                del self._mount_status_cache[path_str]
        else:
            # Invalidate all cache
            self._mount_status_cache.clear()

    def _refresh_nfs_mount(self, path: Path) -> bool:
        """
        Refresh an NFS mount by accessing parent directories.
        This forces the NFS client to revalidate the mount connection.
        
        Args:
            path: The path to refresh (can be a file or directory)
            
        Returns:
            True if refresh was successful, False otherwise
        """
        try:
            # Convert to absolute path
            abs_path = path.resolve()
            path_str = str(abs_path)
            
            # Determine which mount point this path belongs to (if any)
            mount_root = None
            if path_str.startswith(str(self.plex_movies_dir)):
                mount_root = self.plex_movies_dir
            elif path_str.startswith(str(self.plex_music_dir)):
                mount_root = self.plex_music_dir
            
            # First, try to refresh by accessing the mount root directly
            if mount_root:
                try:
                    mount_root.stat()
                except OSError:
                    # If mount root is stale, that's a problem but we'll continue
                    pass
            
            # Walk up the directory tree from the path, accessing each parent
            # This helps refresh the specific path hierarchy
            current = abs_path.parent if abs_path.is_file() else abs_path
            
            # Stop at root directory (/) to avoid going too far up
            accessed_count = 0
            max_walk = 10  # Limit how far up we walk
            while current != current.parent and accessed_count < max_walk:
                try:
                    # Access the directory by calling stat() - this refreshes the mount
                    current.stat()
                    accessed_count += 1
                    # If we've reached a mount root, we can stop
                    if mount_root and current == mount_root:
                        break
                    current = current.parent
                except OSError as e:
                    # If we hit an error, try to continue to next parent
                    # But stop if we've already accessed several directories
                    if accessed_count > 0:
                        break
                    current = current.parent
                except Exception:
                    # Any other error, continue to next parent
                    if accessed_count > 0:
                        break
                    current = current.parent
            
            return True
        except Exception as e:
            print(f"Error refreshing NFS mount for {path}: {e}")
            return False

    def _retry_nfs_operation(self, operation, *args, max_retries: int = 3, operation_name: str = "operation", path: Optional[Path] = None, **kwargs):
        """
        Retry an NFS operation that may fail with stale file handle errors.
        
        Args:
            operation: The operation function to retry
            *args: Positional arguments to pass to the operation
            max_retries: Maximum number of retry attempts
            operation_name: Human-readable name for logging
            path: Optional Path object for the file/directory being operated on.
                  If provided and a stale file handle is detected, the mount will be refreshed.
            **kwargs: Keyword arguments to pass to the operation
            
        Returns:
            The result of the operation
        """
        import time
        for attempt in range(max_retries):
            try:
                return operation(*args, **kwargs)
            except OSError as e:
                if e.errno == 116:  # Stale file handle
                    if attempt < max_retries - 1:
                        # Try to refresh the mount if we have a path
                        if path:
                            try:
                                print(f"NFS stale file handle error during {operation_name}, attempting mount refresh...")
                                self._refresh_nfs_mount(path)
                                # Small delay after refresh to let the mount stabilize
                                time.sleep(0.1)
                            except Exception as refresh_error:
                                print(f"Mount refresh failed: {refresh_error}, will retry normally")
                        
                        wait_time = (attempt + 1) * 0.5  # Exponential backoff
                        print(f"Retrying {operation_name} in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"Failed {operation_name} after {max_retries} attempts: {e}")
                        raise
                else:
                    raise
            except Exception as e:
                # Check if it's a stale file handle in the error message
                if "stale file handle" in str(e).lower() or "errno 116" in str(e).lower():
                    if attempt < max_retries - 1:
                        # Try to refresh the mount if we have a path
                        if path:
                            try:
                                print(f"NFS stale file handle error during {operation_name}, attempting mount refresh...")
                                self._refresh_nfs_mount(path)
                                # Small delay after refresh to let the mount stabilize
                                time.sleep(0.1)
                            except Exception as refresh_error:
                                print(f"Mount refresh failed: {refresh_error}, will retry normally")
                        
                        wait_time = (attempt + 1) * 0.5
                        print(f"Retrying {operation_name} in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"Failed {operation_name} after {max_retries} attempts: {e}")
                        raise
                else:
                    raise
        return None

    def _mkdir_with_retry(self, path: Path, max_retries: int = 3):
        """Create directory with retry logic for NFS stale file handle errors."""
        return self._retry_nfs_operation(
            lambda: path.mkdir(parents=True, exist_ok=True),
            max_retries=max_retries,
            operation_name=f"directory creation: {path}",
            path=path
        )


# Singleton instance
ytdlp_service = YTDLPService()
