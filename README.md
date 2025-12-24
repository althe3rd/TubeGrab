# TubeGrab - YouTube Downloader

A self-hosted YouTube video and audio downloader with a beautiful web interface. Perfect for home labs and Unraid servers.

## Features

- **Easy URL Input** - Just paste a YouTube URL and analyze
- **Playlist Support** - Automatically detects playlists and lets you choose to download one or all videos
- **Quality Selection** - Choose from available resolutions (4K, 1080p, 720p, etc.)
- **Audio Extraction** - Download audio-only in MP3 (320/192/128 kbps) or M4A format
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

### Volume Mounts

| Container Path | Purpose |
|----------------|---------|
| `/downloads` | Where downloaded videos/audio are saved |
| `/root/.cache/yt-dlp` | (Optional) Cache for yt-dlp metadata |

### Ports

| Port | Purpose |
|------|---------|
| 8080 | Web interface |

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
