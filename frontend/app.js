/**
 * TubeGrab - YouTube Downloader Frontend
 */

// State
const state = {
    currentVideo: null,
    isPlaylist: false,
    playlistItems: [],
    selectedFormat: null,
    isAudioOnly: false,
    queue: [],
    eventSource: null,
};

// Audio quality presets
const AUDIO_PRESETS = [
    { id: 'mp3-320', label: 'MP3 320kbps', quality: '320', codec: 'mp3' },
    { id: 'mp3-192', label: 'MP3 192kbps', quality: '192', codec: 'mp3' },
    { id: 'mp3-128', label: 'MP3 128kbps', quality: '128', codec: 'mp3' },
    { id: 'best-audio', label: 'Best (M4A)', quality: 'best', codec: 'm4a' },
];

// DOM Elements
const elements = {
    urlInput: document.getElementById('url-input'),
    analyzeBtn: document.getElementById('analyze-btn'),
    videoSection: document.getElementById('video-section'),
    videoThumbnail: document.getElementById('video-thumbnail'),
    videoDuration: document.getElementById('video-duration'),
    videoTitle: document.getElementById('video-title'),
    videoUploader: document.getElementById('video-uploader'),
    formatOptions: document.getElementById('format-options'),
    downloadBtn: document.getElementById('download-btn'),
    queueList: document.getElementById('queue-list'),
    queueEmpty: document.getElementById('queue-empty'),
    clearCompletedBtn: document.getElementById('clear-completed-btn'),
    activeStat: document.getElementById('active-stat'),
    completedStat: document.getElementById('completed-stat'),
    playlistModal: document.getElementById('playlist-modal'),
    playlistCount: document.getElementById('playlist-count'),
    playlistPreview: document.getElementById('playlist-preview'),
    downloadFirst: document.getElementById('download-first'),
    downloadAll: document.getElementById('download-all'),
    modalClose: document.getElementById('modal-close'),
    toastContainer: document.getElementById('toast-container'),
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    connectSSE();
});

function setupEventListeners() {
    // URL Input & Analyze
    elements.analyzeBtn.addEventListener('click', handleAnalyze);
    elements.urlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleAnalyze();
    });

    // Format Tabs
    document.querySelectorAll('.format-tab').forEach(tab => {
        tab.addEventListener('click', () => handleFormatTabChange(tab));
    });

    // Download Button
    elements.downloadBtn.addEventListener('click', handleDownload);

    // Clear Completed
    elements.clearCompletedBtn.addEventListener('click', handleClearCompleted);

    // Playlist Modal
    elements.modalClose.addEventListener('click', closePlaylistModal);
    elements.downloadFirst.addEventListener('click', () => handlePlaylistChoice('first'));
    elements.downloadAll.addEventListener('click', () => handlePlaylistChoice('all'));
    elements.playlistModal.addEventListener('click', (e) => {
        if (e.target === elements.playlistModal) closePlaylistModal();
    });
}

// SSE Connection for real-time updates
function connectSSE() {
    if (elements.eventSource) {
        elements.eventSource.close();
    }

    state.eventSource = new EventSource('/api/queue/events');

    state.eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleSSEMessage(data);
    };

    state.eventSource.onerror = () => {
        console.error('SSE connection lost, reconnecting...');
        setTimeout(connectSSE, 3000);
    };
}

function handleSSEMessage(data) {
    if (data.type === 'full_update') {
        state.queue = data.queue.items;
        updateQueueDisplay();
        updateStats(data.queue);
    } else if (data.type === 'item_update') {
        if (data.removed) {
            state.queue = state.queue.filter(item => item.id !== data.item.id);
        } else {
            const index = state.queue.findIndex(item => item.id === data.item.id);
            if (index >= 0) {
                state.queue[index] = data.item;
            } else {
                state.queue.push(data.item);
            }
        }
        updateQueueDisplay();
    }
}

// Analyze URL
async function handleAnalyze() {
    const url = elements.urlInput.value.trim();
    if (!url) {
        showToast('Please enter a YouTube URL', 'error');
        return;
    }

    setLoading(true);

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to analyze URL');
        }

        const data = await response.json();
        state.currentVideo = data;

        if (data.is_playlist) {
            showPlaylistModal(data);
        } else {
            displayVideoInfo(data);
        }

    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        setLoading(false);
    }
}

function setLoading(loading) {
    elements.analyzeBtn.classList.toggle('loading', loading);
    elements.analyzeBtn.disabled = loading;
}

// Display Video Info
function displayVideoInfo(video) {
    elements.videoThumbnail.src = video.thumbnail || '';
    elements.videoDuration.textContent = formatDuration(video.duration);
    elements.videoTitle.textContent = video.title;
    elements.videoUploader.textContent = video.uploader || 'Unknown';

    // Populate format options
    renderFormatOptions(video.formats);

    elements.videoSection.classList.remove('hidden');
}

function renderFormatOptions(formats) {
    const videoFormats = formats.filter(f => f.format_type === 'video');

    if (state.isAudioOnly) {
        // Show audio quality presets
        elements.formatOptions.innerHTML = AUDIO_PRESETS.map((preset, i) => `
            <div class="format-option ${i === 0 ? 'selected' : ''}" 
                 data-format="${preset.id}" 
                 data-label="${preset.label}"
                 data-quality="${preset.quality}"
                 data-codec="${preset.codec}">
                <span class="format-label">${preset.label.split(' ')[0]}</span>
                <span class="format-size">${preset.label.split(' ')[1] || ''}</span>
            </div>
        `).join('');

        state.selectedFormat = {
            id: AUDIO_PRESETS[0].id,
            label: AUDIO_PRESETS[0].label,
            quality: AUDIO_PRESETS[0].quality,
            codec: AUDIO_PRESETS[0].codec,
        };
    } else {
        // Show video formats
        if (videoFormats.length === 0) {
            elements.formatOptions.innerHTML = `
                <div class="format-option selected" data-format="best" data-label="Best">
                    <span class="format-label">Best</span>
                    <span class="format-size">Highest</span>
                </div>
            `;
            state.selectedFormat = { id: 'best', label: 'Best Quality' };
        } else {
            // Group by resolution for video
            const grouped = {};
            videoFormats.forEach(f => {
                const key = f.resolution || f.format_note || f.format_id;
                if (!grouped[key] || (f.filesize && (!grouped[key].filesize || f.filesize > grouped[key].filesize))) {
                    grouped[key] = f;
                }
            });

            const uniqueFormats = Object.values(grouped).slice(0, 6);

            elements.formatOptions.innerHTML = uniqueFormats.map((f, i) => `
                <div class="format-option ${i === 0 ? 'selected' : ''}" 
                     data-format="${f.format_id}" 
                     data-label="${f.resolution || f.format_note || 'Unknown'}">
                    <span class="format-label">${f.resolution || f.format_note || 'Unknown'}</span>
                    <span class="format-size">${formatFileSize(f.filesize || f.filesize_approx)}</span>
                </div>
            `).join('');

            if (uniqueFormats.length > 0) {
                state.selectedFormat = {
                    id: uniqueFormats[0].format_id,
                    label: uniqueFormats[0].resolution || uniqueFormats[0].format_note || 'Unknown'
                };
            }
        }
    }

    // Add click handlers
    elements.formatOptions.querySelectorAll('.format-option').forEach(option => {
        option.addEventListener('click', () => {
            elements.formatOptions.querySelectorAll('.format-option').forEach(o => o.classList.remove('selected'));
            option.classList.add('selected');
            state.selectedFormat = {
                id: option.dataset.format,
                label: option.dataset.label,
                quality: option.dataset.quality,
                codec: option.dataset.codec,
            };
        });
    });
}

function handleFormatTabChange(tab) {
    document.querySelectorAll('.format-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');

    state.isAudioOnly = tab.dataset.type === 'audio';

    if (state.currentVideo) {
        renderFormatOptions(state.currentVideo.formats);
    }
}

// Playlist Modal
function showPlaylistModal(data) {
    state.isPlaylist = true;
    state.playlistItems = data.playlist_items || [];

    elements.playlistCount.textContent = data.playlist_count || state.playlistItems.length;

    // Show preview of playlist items
    elements.playlistPreview.innerHTML = state.playlistItems.slice(0, 10).map(item => `
        <div class="playlist-preview-item">
            <span class="playlist-preview-index">${item.index}.</span>
            <span class="playlist-preview-title">${item.title}</span>
        </div>
    `).join('');

    if (state.playlistItems.length > 10) {
        elements.playlistPreview.innerHTML += `
            <div class="playlist-preview-item">
                <span class="playlist-preview-index">...</span>
                <span class="playlist-preview-title">and ${state.playlistItems.length - 10} more videos</span>
            </div>
        `;
    }

    elements.playlistModal.classList.remove('hidden');
}

function closePlaylistModal() {
    elements.playlistModal.classList.add('hidden');
}

function handlePlaylistChoice(choice) {
    closePlaylistModal();

    if (choice === 'first' && state.playlistItems.length > 0) {
        // Just show the first video
        const firstItem = state.playlistItems[0];
        analyzeFirstVideo(firstItem);
    } else if (choice === 'all') {
        // Display the first video for format selection, then download all
        if (state.playlistItems.length > 0) {
            state.currentVideo = {
                ...state.currentVideo,
                id: state.playlistItems[0].id,
                title: state.playlistItems[0].title,
                thumbnail: state.playlistItems[0].thumbnail,
                duration: state.playlistItems[0].duration,
            };
            displayVideoInfo(state.currentVideo);
            showToast(`${state.playlistItems.length} videos will be added to queue`, 'info');
        }
    }
}

async function analyzeFirstVideo(item) {
    const url = item.url || `https://www.youtube.com/watch?v=${item.id}`;
    elements.urlInput.value = url;
    state.isPlaylist = false;
    state.playlistItems = [];

    setLoading(true);
    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });

        if (!response.ok) throw new Error('Failed to analyze video');

        const data = await response.json();
        state.currentVideo = data;
        displayVideoInfo(data);
    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        setLoading(false);
    }
}

// Download
async function handleDownload() {
    if (!state.currentVideo || !state.selectedFormat) {
        showToast('Please select a format first', 'error');
        return;
    }

    elements.downloadBtn.disabled = true;

    try {
        if (state.isPlaylist && state.playlistItems.length > 0) {
            // Download all playlist items
            const requests = state.playlistItems.map(item => ({
                url: item.url || `https://www.youtube.com/watch?v=${item.id}`,
                video_id: item.id,
                title: item.title,
                thumbnail: item.thumbnail,
                format_id: state.selectedFormat.id,
                format_label: state.selectedFormat.label,
                is_audio_only: state.isAudioOnly,
                audio_quality: state.selectedFormat.quality,
                audio_codec: state.selectedFormat.codec,
            }));

            const response = await fetch('/api/download/batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requests),
            });

            if (!response.ok) throw new Error('Failed to add to queue');

            showToast(`Added ${state.playlistItems.length} videos to queue`, 'success');
        } else {
            // Single video download
            const request = {
                url: elements.urlInput.value.trim(),
                video_id: state.currentVideo.id,
                title: state.currentVideo.title,
                thumbnail: state.currentVideo.thumbnail,
                format_id: state.selectedFormat.id,
                format_label: state.selectedFormat.label,
                is_audio_only: state.isAudioOnly,
                audio_quality: state.selectedFormat.quality,
                audio_codec: state.selectedFormat.codec,
            };

            const response = await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(request),
            });

            if (!response.ok) throw new Error('Failed to add to queue');

            showToast('Added to download queue', 'success');
        }

        // Reset state
        elements.videoSection.classList.add('hidden');
        elements.urlInput.value = '';
        state.currentVideo = null;
        state.isPlaylist = false;
        state.playlistItems = [];

    } catch (error) {
        showToast(error.message, 'error');
    } finally {
        elements.downloadBtn.disabled = false;
    }
}

// Queue Management
function updateQueueDisplay() {
    if (state.queue.length === 0) {
        elements.queueEmpty.style.display = 'flex';
        // Clear any existing items
        Array.from(elements.queueList.children).forEach(child => {
            if (child !== elements.queueEmpty) child.remove();
        });
        return;
    }

    elements.queueEmpty.style.display = 'none';

    // Get existing items
    const existingItems = new Map();
    elements.queueList.querySelectorAll('.queue-item').forEach(el => {
        existingItems.set(el.dataset.id, el);
    });

    // Update or create items
    state.queue.forEach((item, index) => {
        let itemEl = existingItems.get(item.id);

        if (itemEl) {
            // Update existing item
            updateQueueItemElement(itemEl, item);
            existingItems.delete(item.id);
        } else {
            // Create new item
            itemEl = createQueueItemElement(item);
            elements.queueList.appendChild(itemEl);
        }
    });

    // Remove items no longer in queue
    existingItems.forEach(el => el.remove());

    // Update stats
    const active = state.queue.filter(i => i.status === 'downloading').length;
    const completed = state.queue.filter(i => i.status === 'completed').length;
    updateStats({ active_downloads: active, completed_count: completed });
}

function createQueueItemElement(item) {
    const div = document.createElement('div');
    div.className = 'queue-item';
    div.dataset.id = item.id;
    updateQueueItemElement(div, item);
    return div;
}

function updateQueueItemElement(el, item) {
    const statusLabels = {
        queued: 'Queued',
        downloading: 'Downloading',
        processing: 'Processing',
        completed: 'Completed',
        failed: 'Failed',
        cancelled: 'Cancelled',
    };

    const showProgress = ['downloading', 'processing'].includes(item.status);
    const showCancel = ['queued', 'downloading'].includes(item.status);
    const showRetry = ['failed', 'cancelled'].includes(item.status);
    const showDownload = item.status === 'completed';

    el.innerHTML = `
        <img class="queue-item-thumbnail" src="${item.thumbnail || ''}" alt="">
        <div class="queue-item-info">
            <div class="queue-item-title">${escapeHtml(item.title)}</div>
            <div class="queue-item-meta">
                <span class="queue-item-format">${item.format_label}</span>
                ${item.is_audio_only ? '<span>Audio</span>' : '<span>Video</span>'}
            </div>
        </div>
        ${showProgress ? `
            <div class="queue-item-progress">
                <div class="progress-bar-container">
                    <div class="progress-bar" style="width: ${item.progress}%"></div>
                </div>
                <div class="progress-text">
                    <span>${Math.round(item.progress)}%</span>
                    <span>${item.speed || ''} ${item.eta ? `• ${item.eta}` : ''}</span>
                </div>
            </div>
        ` : ''}
        <div class="queue-item-status ${item.status}">
            ${statusLabels[item.status] || item.status}
        </div>
        <div class="queue-item-actions">
            ${showDownload ? `
                <button class="queue-action-btn download-file" data-action="download-file" data-id="${item.id}" title="Download File">
                    <svg viewBox="0 0 24 24" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><polyline points="7,10 12,15 17,10" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><line x1="12" y1="15" x2="12" y2="3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                </button>
            ` : ''}
            ${showCancel ? `
                <button class="queue-action-btn cancel" data-action="cancel" data-id="${item.id}" title="Cancel">
                    <svg viewBox="0 0 24 24" fill="none"><line x1="18" y1="6" x2="6" y2="18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="6" y1="6" x2="18" y2="18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
                </button>
            ` : ''}
            ${showRetry ? `
                <button class="queue-action-btn retry" data-action="retry" data-id="${item.id}" title="Retry">
                    <svg viewBox="0 0 24 24" fill="none"><polyline points="23,4 23,10 17,10" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                </button>
            ` : ''}
            <button class="queue-action-btn remove" data-action="remove" data-id="${item.id}" title="Remove">
                <svg viewBox="0 0 24 24" fill="none"><polyline points="3,6 5,6 21,6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </button>
        </div>
    `;

    // Add action handlers
    el.querySelectorAll('.queue-action-btn').forEach(btn => {
        btn.onclick = () => handleQueueAction(btn.dataset.action, btn.dataset.id);
    });
}

async function handleQueueAction(action, itemId) {
    try {
        // Handle file download separately
        if (action === 'download-file') {
            // Trigger file download via browser
            window.location.href = `/api/files/${itemId}`;
            return;
        }

        let endpoint = '';
        let method = 'POST';

        switch (action) {
            case 'cancel':
                endpoint = `/api/queue/${itemId}/cancel`;
                break;
            case 'retry':
                endpoint = `/api/queue/${itemId}/retry`;
                break;
            case 'remove':
                endpoint = `/api/queue/${itemId}`;
                method = 'DELETE';
                break;
        }

        const response = await fetch(endpoint, { method });
        if (!response.ok) throw new Error('Action failed');

    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function handleClearCompleted() {
    try {
        const response = await fetch('/api/queue/clear-completed', { method: 'POST' });
        if (!response.ok) throw new Error('Failed to clear completed');

        const data = await response.json();
        showToast(`Cleared ${data.count} completed downloads`, 'success');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

function updateStats(data) {
    const activeValue = elements.activeStat.querySelector('.stat-value');
    const completedValue = elements.completedStat.querySelector('.stat-value');

    if (activeValue) activeValue.textContent = data.active_downloads || 0;
    if (completedValue) completedValue.textContent = data.completed_count || 0;
}

// Utilities
function formatDuration(seconds) {
    if (!seconds) return '';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;

    if (h > 0) {
        return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatFileSize(bytes) {
    if (!bytes) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) {
        bytes /= 1024;
        i++;
    }
    return `~${bytes.toFixed(1)} ${units[i]}`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Toast Notifications
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icons = {
        success: '<svg viewBox="0 0 24 24" fill="none"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><polyline points="22,4 12,14.01 9,11.01" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        error: '<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/><line x1="15" y1="9" x2="9" y2="15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="9" y1="9" x2="15" y2="15" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
        info: '<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/><line x1="12" y1="16" x2="12" y2="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="12" y1="8" x2="12.01" y2="8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    };

    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || icons.info}</span>
        <span class="toast-message">${escapeHtml(message)}</span>
        <button class="toast-close">
            <svg viewBox="0 0 24 24" fill="none" width="16" height="16"><line x1="18" y1="6" x2="6" y2="18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="6" y1="6" x2="18" y2="18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
        </button>
    `;

    toast.querySelector('.toast-close').onclick = () => toast.remove();

    elements.toastContainer.appendChild(toast);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (toast.parentNode) {
            toast.style.animation = 'slideIn 0.3s ease reverse';
            setTimeout(() => toast.remove(), 300);
        }
    }, 5000);
}
