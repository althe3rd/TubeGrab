# TubeGrab - YouTube Downloader

A self-hosted YouTube video and audio downloader with a beautiful web interface. Perfect for home labs and Unraid servers.

![TubeGrab Interface](https://via.placeholder.com/800x450/0a0a0f/ff3366?text=TubeGrab)

## Features

- **Easy URL Input** - Just paste a YouTube URL and analyze
- **Playlist Support** - Automatically detects playlists and lets you choose to download one or all videos
- **Quality Selection** - Choose from available resolutions (4K, 1080p, 720p, etc.)
- **Audio Extraction** - Download audio-only in MP3 format
- **Download Queue** - View, manage, cancel, and retry downloads
- **Real-time Progress** - See download progress with speed and ETA
- **Dark Theme** - Beautiful modern dark UI
- **Docker Ready** - Easy deployment with Docker Compose

## Quick Start

### Using Docker Compose (Recommended)

1. **Clone or download this repository:**
   ```bash
   git clone https://github.com/yourusername/tubegrab.git
   cd tubegrab
   ```

2. **Create the downloads directory:**
   ```bash
   mkdir -p downloads
   ```

3. **Start the container:**
   ```bash
   docker-compose up -d
   ```

4. **Access the web interface:**
   Open http://localhost:8080 in your browser

### Using Docker Run

```bash
docker build -t tubegrab .

docker run -d \
  --name tubegrab \
  -p 8080:8080 \
  -v $(pwd)/downloads:/downloads \
  --restart unless-stopped \
  tubegrab
```

## Unraid Installation

### Method 1: Docker Compose Manager

1. Install the "Docker Compose Manager" plugin from Community Applications
2. Create a new stack with the following compose file:

```yaml
version: "3.8"
services:
  tubegrab:
    build: https://github.com/yourusername/tubegrab.git
    container_name: tubegrab
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - /mnt/user/appdata/tubegrab/downloads:/downloads
      - /mnt/user/appdata/tubegrab/cache:/root/.cache/yt-dlp
    environment:
      - TZ=America/Chicago
```

3. Deploy the stack

### Method 2: Manual Docker

1. SSH into your Unraid server
2. Navigate to a suitable directory:
   ```bash
   cd /mnt/user/appdata
   git clone https://github.com/yourusername/tubegrab.git
   cd tubegrab
   ```
3. Build and run:
   ```bash
   docker build -t tubegrab .
   docker run -d \
     --name tubegrab \
     -p 8080:8080 \
     -v /mnt/user/downloads/youtube:/downloads \
     --restart unless-stopped \
     tubegrab
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

1. **Enter URL**: Paste a YouTube video or playlist URL in the input field
2. **Analyze**: Click the "Analyze" button to fetch video information
3. **Select Format**: 
   - Choose "Video" or "Audio Only" tab
   - Select your preferred quality/resolution
4. **Download**: Click "Add to Queue" to start the download
5. **Manage Queue**: View progress, cancel, retry, or remove downloads from the queue

### Playlist Handling

When you paste a playlist URL, a modal will appear with options:
- **First Video Only**: Downloads just the first video in the playlist
- **All Videos**: Queues all videos from the playlist for download

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/analyze` | Analyze a YouTube URL |
| `POST` | `/api/download` | Add a download to the queue |
| `POST` | `/api/download/batch` | Add multiple downloads (for playlists) |
| `GET` | `/api/queue` | Get current queue status |
| `DELETE` | `/api/queue/{id}` | Remove an item from the queue |
| `POST` | `/api/queue/{id}/cancel` | Cancel an active download |
| `POST` | `/api/queue/{id}/retry` | Retry a failed download |
| `POST` | `/api/queue/clear-completed` | Clear all completed downloads |
| `GET` | `/api/queue/events` | SSE stream for real-time updates |
| `GET` | `/api/health` | Health check endpoint |

## Development

### Prerequisites

- Python 3.11+
- Node.js (optional, for frontend development)
- FFmpeg (for audio conversion)

### Local Setup

1. **Install Python dependencies:**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. **Create downloads directory:**
   ```bash
   mkdir -p ../downloads
   ```

3. **Run the development server:**
   ```bash
   uvicorn app.main:app --reload --port 8080
   ```

4. **Access the application:**
   Open http://localhost:8080

### Project Structure

```
tubegrab/
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

## Troubleshooting

### Download Fails Immediately

- Check that yt-dlp is up to date (container auto-updates on startup)
- Verify the URL is a valid YouTube link
- Check container logs: `docker logs tubegrab`

### No Audio in Downloaded Videos

- Ensure FFmpeg is installed (included in Docker image)
- Try downloading audio-only and check if that works

### Cannot Access Web Interface

- Verify the container is running: `docker ps`
- Check if port 8080 is available
- Try accessing via IP instead of hostname

### Downloads Not Appearing

- Check volume mount permissions
- Verify the downloads directory exists and is writable
- Check container logs for errors

## Tech Stack

- **Backend**: Python 3.11, FastAPI, yt-dlp
- **Frontend**: Vanilla JavaScript, CSS
- **Real-time Updates**: Server-Sent Events (SSE)
- **Containerization**: Docker

## License

MIT License - feel free to use, modify, and distribute.

## Acknowledgments

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - The backbone of this application
- [FastAPI](https://fastapi.tiangolo.com/) - Excellent Python web framework

