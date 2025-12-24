# TubeGrab - YouTube Downloader

A self-hosted YouTube video and audio downloader with a beautiful web interface. Perfect for home labs and Unraid servers.

## Features

- **Easy URL Input** - Just paste a YouTube URL and analyze
- **Playlist Support** - Automatically detects playlists and lets you choose to download one or all videos
- **Quality Selection** - Choose from available resolutions (4K, 1080p, 720p, etc.)
- **Audio Extraction** - Download audio-only in MP3 (320/192/128 kbps) or M4A format
- **Plex Integration** - Send videos directly to your Plex Movies library, audio to Music library
- **Download Queue** - View, manage, cancel, and retry downloads
- **Real-time Progress** - See download progress with speed and ETA
- **Browser Downloads** - Download completed files directly from the web UI
- **Dark Theme** - Beautiful modern dark UI
- **Multi-Architecture** - Supports AMD64 (Intel/AMD) and ARM64 (Apple Silicon, Raspberry Pi)
- **Docker Ready** - Easy deployment with Docker

## Quick Start

### Using Docker Hub (Recommended)

```bash
docker run -d \
  --name tubegrab \
  -p 8080:8080 \
  -v /path/to/downloads:/downloads \
  -e TZ=America/Chicago \
  --restart unless-stopped \
  althe3rd/tubegrab:latest
```

Then open http://localhost:8080

### Using Docker Compose

```bash
git clone https://github.com/althe3rd/TubeGrab.git
cd TubeGrab
docker-compose up -d
```

## Unraid Installation

### Via Docker UI (Recommended)

1. Go to **Docker** tab in Unraid
2. Click **Add Container**
3. Configure:

   | Setting | Value |
   |---------|-------|
   | **Name** | `tubegrab` |
   | **Repository** | `althe3rd/tubegrab:latest` |
   | **Network Type** | `bridge` |
   | **WebUI** | `http://[IP]:[PORT:8080]` |

4. Add **Port Mapping**:
   - Container Port: `8080`
   - Host Port: `8080`

5. Add **Path** for downloads:
   - Container Path: `/downloads`
   - Host Path: `/mnt/user/downloads/youtube`

6. Add **Path** for cache (optional):
   - Container Path: `/root/.cache/yt-dlp`
   - Host Path: `/mnt/user/appdata/tubegrab/cache`

7. Add **Variable** for timezone:
   - Key: `TZ`
   - Value: `America/Chicago` (or your timezone)

8. Click **Apply**

### Via SSH

```bash
docker run -d \
  --name tubegrab \
  -p 8080:8080 \
  -v /mnt/user/downloads/youtube:/downloads \
  -v /mnt/user/appdata/tubegrab/cache:/root/.cache/yt-dlp \
  -e TZ=America/Chicago \
  --restart unless-stopped \
  althe3rd/tubegrab:latest
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TZ` | `UTC` | Timezone for timestamps |
| `PLEX_MOVIES_DIR` | `/plex/movies` | Container path for Plex movies |
| `PLEX_MUSIC_DIR` | `/plex/music` | Container path for Plex music |

### Volume Mounts

| Container Path | Purpose |
|----------------|---------|
| `/downloads` | Default download location |
| `/plex/movies` | Plex movies library (for video content) |
| `/plex/music` | Plex music library (for audio content) |
| `/root/.cache/yt-dlp` | (Optional) Cache for yt-dlp metadata |

### Ports

| Port | Purpose |
|------|---------|
| 8080 | Web interface |

## Plex Integration

TubeGrab can send downloads directly to your Plex library folders. When enabled, videos go to your Movies library and audio goes to your Music library.

### Setup

1. Map your Plex library folders as volumes:
   ```bash
   docker run -d \
     --name tubegrab \
     -p 8080:8080 \
     -v /path/to/downloads:/downloads \
     -v /path/to/plex/movies:/plex/movies \
     -v /path/to/plex/music:/plex/music \
     althe3rd/tubegrab:latest
   ```

2. In the TubeGrab UI, toggle "Send to Plex Library" before downloading

3. Plex will automatically detect new content (or trigger a library scan)

### Unraid Example

```bash
docker run -d \
  --name tubegrab \
  -p 8080:8080 \
  -v /mnt/user/downloads/youtube:/downloads \
  -v /mnt/user/data/media/movies:/plex/movies \
  -v /mnt/user/data/media/music:/plex/music \
  -e TZ=America/Chicago \
  --restart unless-stopped \
  althe3rd/tubegrab:latest
```

### Notes

- The Plex toggle only appears if the Plex directories are mounted
- Videos → `/plex/movies` (your Plex Movies library)
- Audio → `/plex/music` (your Plex Music library)
- Regular downloads still go to `/downloads`

## Video Conversion

TubeGrab can convert downloaded videos to H.264/AAC MP4 format for better compatibility. This is especially useful for videos that use Opus or other codecs that may not be supported by all players.

### Features

- **Hardware Acceleration**: Automatically uses NVIDIA GPU (NVENC) if available
- **Software Fallback**: Uses CPU encoding if GPU is not available
- **Format**: Converts to H.264 video + AAC audio in MP4 container
- **Quality**: CRF 23 (good balance of quality and file size)

### Usage

1. When downloading a video (not audio-only), you'll see a toggle: **"Convert to H.264/AAC MP4"**
2. Enable it before clicking "Add to Queue"
3. The conversion happens automatically after download
4. The converted file replaces the original

### GPU Support (Optional)

**The container works perfectly without GPU** - it will use software encoding. GPU support is optional for faster conversion.

#### For Unraid with NVIDIA GPU:

**Prerequisites:**
1. Install the **"Nvidia Driver"** plugin from Community Applications
2. Install your preferred NVIDIA driver version (latest, production, etc.)
3. **Restart your Unraid server** - This is required for the driver to be active
4. After restart, verify the driver is loaded: Go to Settings → Nvidia Driver and confirm your GPU is listed

**Option 1: Using Unraid Docker UI (Recommended)**

If `--gpus all` doesn't work, use environment variables instead:

1. In the container settings, go to **"Show more settings"**
2. Under **"Add another Path, Port, Variable, Label or Device"**, add these **Variables**:
   - **Key**: `NVIDIA_VISIBLE_DEVICES` → **Value**: `all`
   - **Key**: `NVIDIA_DRIVER_CAPABILITIES` → **Value**: `compute,video,utility`
3. **Do NOT add** `--gpus all` in Extra Parameters if using the variables above

**Option 2: Using Extra Parameters (Alternative)**

If environment variables don't work, try:
1. Under **"Extra Parameters"**, add: `--gpus all`
2. If this causes the container to fail to start, use Option 1 instead

**Option 3: Using Command Line**
```bash
docker run -d \
  --name tubegrab \
  -p 8080:8080 \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,video,utility \
  -v /mnt/user/downloads/youtube:/downloads \
  -v /mnt/user/appdata/tubegrab/cache:/root/.cache/yt-dlp \
  -v /mnt/user/data/media/movies:/plex/movies \
  -v /mnt/user/data/media/music:/plex/music \
  -e TZ=America/Chicago \
  --restart unless-stopped \
  althe3rd/tubegrab:latest
```

**Troubleshooting:**
- If the container won't start with GPU settings, remove them - the app will use CPU encoding (slower but works fine)
- Check container logs: `docker logs tubegrab` to see if GPU is detected
- The app will automatically detect GPU and use it if available, or fall back to CPU
- After adding GPU support, you should see "Using NVIDIA NVENC" in the logs during conversion

## Usage

1. **Enter URL**: Paste a YouTube video or playlist URL
2. **Analyze**: Click "Analyze" to fetch video information
3. **Select Format**: 
   - Choose "Video" or "Audio Only" tab
   - Select your preferred quality/resolution
   - For audio: Choose MP3 quality (320/192/128 kbps) or Best M4A
4. **Download**: Click "Add to Queue" to start the download
5. **Get File**: Click the green download button on completed items to save to your computer

### Playlist Handling

When you paste a playlist URL, a modal will appear with options:
- **First Video Only**: Downloads just the first video
- **All Videos**: Queues all videos from the playlist

## Updating

### Unraid Docker UI
1. Click the TubeGrab icon
2. Select **Force Update**

### Command Line
```bash
docker pull althe3rd/tubegrab:latest
docker stop tubegrab
docker rm tubegrab
# Run the docker run command again
```

## Development

### Prerequisites

- Python 3.11+
- Docker with buildx support
- FFmpeg (for audio conversion)

### Local Development

```bash
# Clone the repo
git clone https://github.com/althe3rd/TubeGrab.git
cd TubeGrab

# Install Python dependencies
cd backend
pip install -r requirements.txt
cd ..

# Create downloads directory
mkdir -p downloads

# Run the development server
cd backend
uvicorn app.main:app --reload --port 8080
```

### Building Docker Images

**Build for local testing:**
```bash
docker build -t tubegrab .
docker run -p 8080:8080 -v $(pwd)/downloads:/downloads tubegrab
```

**Build and push multi-architecture image (AMD64 + ARM64):**
```bash
# Set up buildx (one-time)
docker buildx create --name multiarch --use

# Build and push for both architectures
docker buildx build --platform linux/amd64,linux/arm64 -t althe3rd/tubegrab:latest --push .
```

### Project Structure

```
TubeGrab/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py           # FastAPI application
│   │   ├── models/
│   │   │   └── schemas.py    # Pydantic models
│   │   ├── routes/
│   │   │   ├── downloads.py  # Download endpoints
│   │   │   └── queue.py      # Queue management
│   │   └── services/
│   │       ├── ytdlp.py      # yt-dlp wrapper
│   │       └── queue.py      # Queue manager
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/analyze` | Analyze a YouTube URL |
| `POST` | `/api/download` | Add a download to the queue |
| `POST` | `/api/download/batch` | Add multiple downloads (playlists) |
| `GET` | `/api/queue` | Get current queue status |
| `DELETE` | `/api/queue/{id}` | Remove an item from queue |
| `POST` | `/api/queue/{id}/cancel` | Cancel an active download |
| `POST` | `/api/queue/{id}/retry` | Retry a failed download |
| `POST` | `/api/queue/clear-completed` | Clear completed downloads |
| `GET` | `/api/queue/events` | SSE stream for real-time updates |
| `GET` | `/api/files/{id}` | Download a completed file |
| `GET` | `/api/health` | Health check endpoint |

## Troubleshooting

### Container won't start / "exec format error"
This means the image architecture doesn't match your server. Pull the latest image which supports both AMD64 and ARM64:
```bash
docker pull althe3rd/tubegrab:latest
```

### Download fails immediately
- Check container logs: `docker logs tubegrab`
- Ensure the URL is a valid YouTube link
- yt-dlp auto-updates on container start, but you can force an update by restarting

### No audio in downloaded videos
- FFmpeg is included in the Docker image
- Try downloading audio-only to verify FFmpeg works

### Cannot access web interface
- Verify container is running: `docker ps`
- Check if port 8080 is available
- Try accessing via IP instead of hostname

## Tech Stack

- **Backend**: Python 3.11, FastAPI, yt-dlp
- **Frontend**: Vanilla JavaScript, CSS
- **Real-time Updates**: Server-Sent Events (SSE)
- **Containerization**: Docker (multi-arch)

## License

MIT License - feel free to use, modify, and distribute.

## Acknowledgments

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - The backbone of this application
- [FastAPI](https://fastapi.tiangolo.com/) - Excellent Python web framework
