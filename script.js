/* ============================================================
   YouTube Downloader — Frontend Logic
   ============================================================ */

const PRODUCTION_URL = ''; // Railway will use the current domain automatically
const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.protocol === 'file:')
    ? 'http://localhost:5000'
    : window.location.origin;

// DOM Elements
const urlInput = document.getElementById('urlInput');
const fetchBtn = document.getElementById('fetchBtn');
const pasteBtn = document.getElementById('pasteBtn');
const clearBtn = document.getElementById('clearBtn');
const loadingCard = document.getElementById('loadingCard');
const videoCard = document.getElementById('videoCard');
const errorToast = document.getElementById('errorToast');
const errorMessage = document.getElementById('errorMessage');
const successToast = document.getElementById('successToast');
const successMessage = document.getElementById('successMessage');
const formatSelect = document.getElementById('formatSelect');
const downloadBtn = document.getElementById('downloadBtn');
const downloadBtnText = document.getElementById('downloadBtnText');
const progressSection = document.getElementById('progressSection');
const progressBar = document.getElementById('progressBar');
const progressPercent = document.getElementById('progressPercent');
const progressStatus = document.getElementById('progressStatus');
const progressSpeed = document.getElementById('progressSpeed');
const progressEta = document.getElementById('progressEta');
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const rewardedAdModal = document.getElementById('rewardedAdModal');
const skipAdBtn = document.getElementById('skipAdBtn');

let currentVideoUrl = '';
let sessionId = '';
let progressInterval = null;
let isDownloading = false;

/* ============================================================
   Background Particles
   ============================================================ */
function createParticles() {
    const container = document.getElementById('bgParticles');
    const colors = ['#ff3d3d', '#ff9f9f', '#a855f7', '#3b82f6', '#22c55e'];
    for (let i = 0; i < 20; i++) {
        const p = document.createElement('div');
        p.className = 'particle';
        const size = Math.random() * 4 + 2;
        p.style.cssText = `
            width:${size}px; height:${size}px;
            background:${colors[Math.floor(Math.random() * colors.length)]};
            left:${Math.random() * 100}%;
            animation-duration:${Math.random() * 20 + 15}s;
            animation-delay:${Math.random() * 20}s;
        `;
        container.appendChild(p);
    }
}

/* ============================================================
   Server Health Check
   ============================================================ */
async function checkServerHealth() {
    // Longer timeout for the first check to allow Render to wake up
    const isFirstCheck = statusText.textContent === 'Checking server...';
    const timeout = isFirstCheck ? 15000 : 5000; 

    if (isFirstCheck) {
        statusText.textContent = 'Server is waking up (Render free tier)...';
    }

    try {
        const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(timeout) });
        if (res.ok) {
            statusDot.className = 'status-dot online';
            statusText.textContent = 'Server is running — Ready to download';
        } else { 
            setServerOffline(); 
        }
    } catch (err) {
        setServerOffline();
    }
}

function setServerOffline() {
    statusDot.className = 'status-dot offline';
    const isLocal = (window.location.hostname === 'localhost' || window.location.protocol === 'file:');
    
    if (isLocal) {
        statusText.textContent = 'Server offline — Run start.bat to launch the server';
    } else {
        statusText.textContent = 'Server sleeping — Please wait ~30s or refresh';
    }
}

/* ============================================================
   URL Input
   ============================================================ */
urlInput.addEventListener('input', () => {
    clearBtn.style.display = urlInput.value ? 'flex' : 'none';
});

urlInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') fetchVideoInfo();
});

pasteBtn.addEventListener('click', async () => {
    try {
        const text = await navigator.clipboard.readText();
        urlInput.value = text;
        clearBtn.style.display = text ? 'flex' : 'none';
        if (isYouTubeUrl(text)) fetchVideoInfo();
    } catch { urlInput.focus(); }
});

clearBtn.addEventListener('click', () => {
    urlInput.value = '';
    clearBtn.style.display = 'none';
    hideError();
    hideVideoCard();
    urlInput.focus();
});

function isYouTubeUrl(url) {
    return /^(https?:\/\/)?(www\.)?(youtube\.com\/watch|youtu\.be\/|youtube\.com\/shorts\/)/i.test(url.trim());
}

/* ============================================================
   Fetch Video Info
   ============================================================ */
fetchBtn.addEventListener('click', fetchVideoInfo);

async function fetchVideoInfo() {
    const url = urlInput.value.trim();
    if (!url) { showError('Please enter a YouTube URL.'); urlInput.focus(); return; }
    if (!isYouTubeUrl(url)) { showError('Please enter a valid YouTube URL (youtube.com or youtu.be).'); return; }

    currentVideoUrl = url;
    hideError(); hideVideoCard(); hideSuccess();
    setFetchLoading(true);

    try {
        const res = await fetch(`${API_BASE}/info`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed to fetch video info');
        displayVideoInfo(data);
    } catch (err) {
        if (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
            const isLocal = (window.location.hostname === 'localhost' || window.location.protocol === 'file:');
            if (isLocal) {
                showError('Cannot connect to server. Make sure start.bat is running.');
            } else {
                showError('Server is waking up (Render free tier). Please wait 30 seconds and try again.');
            }
        } else {
            showError(err.message || 'Failed to fetch video information.');
        }
    } finally {
        setFetchLoading(false);
    }
}

function setFetchLoading(loading) {
    fetchBtn.disabled = loading;
    fetchBtn.querySelector('.fetch-btn-text').textContent = loading ? 'Fetching...' : 'Fetch Video';
    loadingCard.style.display = loading ? 'flex' : 'none';
}

/* ============================================================
   Display Video Info
   ============================================================ */
function displayVideoInfo(data) {
    const thumb = document.getElementById('videoThumbnail');
    thumb.src = data.thumbnail || '';
    thumb.onerror = () => { thumb.src = ''; thumb.style.display = 'none'; };

    document.getElementById('videoTitle').textContent = data.title || 'Unknown Title';
    document.getElementById('videoChannel').textContent = data.channel || 'Unknown';
    document.getElementById('videoViews').textContent = data.views || '—';
    document.getElementById('durationBadge').textContent = data.duration || '';

    formatSelect.innerHTML = '';
    (data.formats || []).forEach(fmt => {
        const opt = document.createElement('option');
        opt.value = fmt.format_id;
        opt.textContent = fmt.label;
        formatSelect.appendChild(opt);
    });

    resetDownloadState();
    videoCard.style.display = 'block';
    videoCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideVideoCard() {
    videoCard.style.display = 'none';
    resetDownloadState();
}

/* ============================================================
   DOWNLOAD  — Direct browser download via anchor tag
   Flask streams the file with Content-Disposition: attachment
   so the browser saves natively to the Downloads folder.
   No blob, no memory limit — works for multi-GB files.
   ============================================================ */
downloadBtn.addEventListener('click', startDownload);

async function startDownload() {
    if (isDownloading || !currentVideoUrl) return;

    const formatId = formatSelect.value;
    if (!formatId) { showError('Please select a quality/format.'); return; }

    isDownloading = true;
    sessionId = 'sess_' + Date.now();

    downloadBtn.disabled = true;
    downloadBtnText.textContent = 'Preparing...';
    progressSection.style.display = 'block';
    progressStatus.textContent = 'Server pe video download ho raha hai...';
    progressSpeed.textContent = '';
    progressEta.textContent = '';
    setProgress(0);
    hideError();

    // Build URL pointing to Flask /download endpoint
    const params = new URLSearchParams({ url: currentVideoUrl, format_id: formatId, session_id: sessionId });
    const downloadUrl = `${API_BASE}/download?${params.toString()}`;

    // Trigger native browser download — browser handles the Save-As dialog itself
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    downloadBtnText.textContent = 'Downloading...';

    // Poll server for progress while it downloads & merges
    try {
        await pollUntilDone(sessionId);
    } catch (err) {
        showError(err.message || 'Download failed.');
        resetDownloadState();
        return;
    } finally {
        clearProgressPolling();
        isDownloading = false;
        setTimeout(() => {
            downloadBtn.disabled = false;
            downloadBtnText.textContent = 'Download Now';
        }, 4000);
    }
}

function pollUntilDone(sid) {
    return new Promise((resolve, reject) => {
        const POLL_MS = 1000;
        const TIMEOUT_H = 3;   // give up after 3 hours (handles longest videos)

        const deadlineTimer = setTimeout(() => {
            clearProgressPolling();
            resolve(); // Don't reject — file may still arrive
        }, TIMEOUT_H * 60 * 60 * 1000);

        progressInterval = setInterval(async () => {
            try {
                const res = await fetch(`${API_BASE}/progress?session_id=${sid}`);
                if (!res.ok) return;
                const data = await res.json();

                switch (data.status) {
                    case 'downloading':
                        const pct = Math.min(95, data.percent || 0);
                        setProgress(pct);
                        progressStatus.textContent = 'Server pe download ho raha hai...';
                        if (data.speed) progressSpeed.textContent = data.speed;
                        if (data.eta) progressEta.textContent = `ETA: ${data.eta}`;
                        break;

                    case 'processing':
                        setProgress(97);
                        progressStatus.textContent = 'Video + Audio merge ho raha hai (ffmpeg)...';
                        progressEta.textContent = 'Almost done...';
                        break;

                    case 'done':
                        clearTimeout(deadlineTimer);
                        clearProgressPolling();
                        setProgress(100);
                        progressStatus.textContent = 'Download complete! File saved in your Downloads folder.';
                        progressSpeed.textContent = '';
                        progressEta.textContent = '';
                        downloadBtnText.textContent = 'Downloaded!';
                        showSuccess('File aapke Downloads folder me save ho gayi!');
                        resolve();
                        break;

                    case 'error':
                        clearTimeout(deadlineTimer);
                        clearProgressPolling();
                        reject(new Error('Server error during download. Please try again.'));
                        break;
                }
            } catch { /* ignore transient poll errors */ }
        }, POLL_MS);
    });
}

function setProgress(percent) {
    const p = Math.min(100, Math.max(0, percent));
    progressBar.style.width = p + '%';
    progressPercent.textContent = p.toFixed(0) + '%';
}

function resetDownloadState() {
    isDownloading = false;
    downloadBtn.disabled = false;
    downloadBtnText.textContent = 'Download Now';
    progressSection.style.display = 'none';
    setProgress(0);
    progressStatus.textContent = '';
    progressSpeed.textContent = '';
    progressEta.textContent = '';
    clearProgressPolling();
}

function clearProgressPolling() {
    if (progressInterval) { clearInterval(progressInterval); progressInterval = null; }
}

/* ============================================================
   Toast Notifications
   ============================================================ */
function showError(msg) {
    errorMessage.textContent = msg;
    errorToast.style.display = 'flex';
    successToast.style.display = 'none';
}
function hideError() { errorToast.style.display = 'none'; }

function showSuccess(msg) {
    successMessage.textContent = msg;
    successToast.style.display = 'flex';
    setTimeout(() => { successToast.style.display = 'none'; }, 6000);
}
function hideSuccess() { successToast.style.display = 'none'; }

window.hideError = hideError;

/* ============================================================
   Init
   ============================================================ */
createParticles();
checkServerHealth();
setInterval(checkServerHealth, 15000);
urlInput.focus();
