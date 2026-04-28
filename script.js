/* ============================================================
   YouTube Downloader — Frontend Logic
   ============================================================ */

const PRODUCTION_URL = ''; 
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

// Cookie Setup Elements (FIXED: Added declarations)
const settingsBtn = document.getElementById('settingsBtn');
const setupModal = document.getElementById('setupModal');
const closeModal = document.getElementById('closeModal');
const saveCookiesBtn = document.getElementById('saveCookiesBtn');
const clearCookiesBtn = document.getElementById('clearCookiesBtn');
const cookieInput = document.getElementById('cookieInput');
const setupReminder = document.getElementById('setupReminder');
const setupTabs = document.querySelectorAll('.setup-tab');

let currentVideoUrl = '';
let sessionId = '';
let progressInterval = null;
let isDownloading = false;

// Initialize Cookie State
function initCookieState() {
    const cookies = localStorage.getItem('yt_cookies');
    if (setupReminder) {
        if (!cookies) {
            setupReminder.style.display = 'block';
        } else {
            setupReminder.style.display = 'none';
        }
    }
}

/* ============================================================
   Background Particles
   ============================================================ */
function createParticles() {
    const container = document.getElementById('bgParticles');
    if (!container) return;
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
    if (!statusText || !statusDot) return;
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
    if (!statusDot || !statusText) return;
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
if (urlInput) {
    urlInput.addEventListener('input', () => {
        if (clearBtn) clearBtn.style.display = urlInput.value ? 'flex' : 'none';
    });

    urlInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') fetchVideoInfo();
    });
}

if (pasteBtn) {
    pasteBtn.addEventListener('click', async () => {
        try {
            const text = await navigator.clipboard.readText();
            urlInput.value = text;
            if (clearBtn) clearBtn.style.display = text ? 'flex' : 'none';
            if (isYouTubeUrl(text)) fetchVideoInfo();
        } catch { urlInput.focus(); }
    });
}

if (clearBtn) {
    clearBtn.addEventListener('click', () => {
        urlInput.value = '';
        clearBtn.style.display = 'none';
        hideError();
        hideVideoCard();
        urlInput.focus();
    });
}

function isYouTubeUrl(url) {
    return /^(https?:\/\/)?(www\.)?(youtube\.com\/watch|youtu\.be\/|youtube\.com\/shorts\/)/i.test(url.trim());
}

/* ============================================================
   Fetch Video Info
   ============================================================ */
if (fetchBtn) fetchBtn.addEventListener('click', fetchVideoInfo);

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
            body: JSON.stringify({ 
                url: url,
                cookies: localStorage.getItem('yt_cookies') || ''
            })
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
            if (err.message.includes('Sign-in required') || err.message.includes('sign-in')) {
                showErrorWithAction('This video requires sign-in. Please complete the One-Time Setup to fix this.', 'Fix Now');
            } else {
                showError(err.message || 'Failed to fetch video information.');
            }
        }
    } finally {
        setFetchLoading(false);
    }
}

function setFetchLoading(loading) {
    if (!fetchBtn) return;
    fetchBtn.disabled = loading;
    const btnText = fetchBtn.querySelector('.fetch-btn-text');
    if (btnText) btnText.textContent = loading ? 'Fetching...' : 'Fetch Video';
    if (loadingCard) loadingCard.style.display = loading ? 'flex' : 'none';
}

/* ============================================================
   Display Video Info
   ============================================================ */
function displayVideoInfo(data) {
    const thumb = document.getElementById('videoThumbnail');
    if (thumb) {
        thumb.src = data.thumbnail || '';
        thumb.onerror = () => { thumb.src = ''; thumb.style.display = 'none'; };
    }

    const titleEl = document.getElementById('videoTitle');
    const channelEl = document.getElementById('videoChannel');
    const viewsEl = document.getElementById('videoViews');
    const durationEl = document.getElementById('durationBadge');

    if (titleEl) titleEl.textContent = data.title || 'Unknown Title';
    if (channelEl) channelEl.textContent = data.channel || 'Unknown';
    if (viewsEl) viewsEl.textContent = data.views || '—';
    if (durationEl) durationEl.textContent = data.duration || '';

    if (formatSelect) {
        formatSelect.innerHTML = '';
        (data.formats || []).forEach(fmt => {
            const opt = document.createElement('option');
            opt.value = fmt.format_id;
            opt.textContent = fmt.label;
            formatSelect.appendChild(opt);
        });
    }

    resetDownloadState();
    if (videoCard) {
        videoCard.style.display = 'block';
        videoCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

function hideVideoCard() {
    if (videoCard) videoCard.style.display = 'none';
    resetDownloadState();
}

/* ============================================================
   DOWNLOAD Logic
   ============================================================ */
if (downloadBtn) downloadBtn.addEventListener('click', startDownload);

async function startDownload() {
    if (isDownloading || !currentVideoUrl) return;

    const formatId = formatSelect ? formatSelect.value : '';
    if (!formatId) { showError('Please select a quality/format.'); return; }

    isDownloading = true;
    sessionId = 'sess_' + Date.now();

    if (downloadBtn) {
        downloadBtn.disabled = true;
        if (downloadBtnText) downloadBtnText.textContent = 'Preparing...';
    }
    
    if (progressSection) progressSection.style.display = 'block';
    if (progressStatus) progressStatus.textContent = 'Server pe video download ho raha hai...';
    hideError();

    const params = new URLSearchParams({ 
        url: currentVideoUrl, 
        format_id: formatId, 
        session_id: sessionId,
        cookies: localStorage.getItem('yt_cookies') || ''
    });
    const downloadUrl = `${API_BASE}/download?${params.toString()}`;

    const a = document.createElement('a');
    a.href = downloadUrl;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    if (downloadBtnText) downloadBtnText.textContent = 'Downloading...';

    try {
        await pollUntilDone(sessionId);
    } catch (err) {
        showError(err.message || 'Download failed.');
        resetDownloadState();
    } finally {
        clearProgressPolling();
        isDownloading = false;
        setTimeout(() => {
            if (downloadBtn) downloadBtn.disabled = false;
            if (downloadBtnText) downloadBtnText.textContent = 'Download Now';
        }, 4000);
    }
}

function pollUntilDone(sid) {
    return new Promise((resolve, reject) => {
        const POLL_MS = 1000;
        progressInterval = setInterval(async () => {
            try {
                const res = await fetch(`${API_BASE}/progress?session_id=${sid}`);
                if (!res.ok) return;
                const data = await res.json();

                switch (data.status) {
                    case 'downloading':
                        const pct = Math.min(95, data.percent || 0);
                        setProgress(pct);
                        if (progressStatus) progressStatus.textContent = 'Server pe download ho raha hai...';
                        if (progressSpeed && data.speed) progressSpeed.textContent = data.speed;
                        if (progressEta && data.eta) progressEta.textContent = `ETA: ${data.eta}`;
                        break;

                    case 'processing':
                        setProgress(97);
                        if (progressStatus) progressStatus.textContent = 'Video + Audio merge ho raha hai (ffmpeg)...';
                        break;

                    case 'done':
                        clearProgressPolling();
                        setProgress(100);
                        if (progressStatus) progressStatus.textContent = 'Download complete!';
                        if (downloadBtnText) downloadBtnText.textContent = 'Downloaded!';
                        showSuccess('File aapke Downloads folder me save ho gayi!');
                        resolve();
                        break;

                    case 'error':
                        clearProgressPolling();
                        reject(new Error('Server error during download.'));
                        break;
                }
            } catch { }
        }, POLL_MS);
    });
}

function setProgress(percent) {
    const p = Math.min(100, Math.max(0, percent));
    if (progressBar) progressBar.style.width = p + '%';
    if (progressPercent) progressPercent.textContent = p.toFixed(0) + '%';
}

function resetDownloadState() {
    isDownloading = false;
    if (downloadBtn) downloadBtn.disabled = false;
    if (downloadBtnText) downloadBtnText.textContent = 'Download Now';
    if (progressSection) progressSection.style.display = 'none';
    setProgress(0);
    clearProgressPolling();
}

function clearProgressPolling() {
    if (progressInterval) { clearInterval(progressInterval); progressInterval = null; }
}

/* ============================================================
   Toast Notifications
   ============================================================ */
function showError(msg) {
    if (!errorMessage || !errorToast) return;
    errorMessage.textContent = msg;
    const oldBtn = errorToast.querySelector('.error-action-btn');
    if (oldBtn) oldBtn.remove();
    errorToast.style.display = 'flex';
    if (successToast) successToast.style.display = 'none';
}

function showErrorWithAction(msg, actionText) {
    showError(msg);
    const actionBtn = document.createElement('button');
    actionBtn.className = 'error-action-btn';
    actionBtn.textContent = actionText;
    actionBtn.onclick = () => {
        hideError();
        if (settingsBtn) settingsBtn.click();
    };
    errorToast.appendChild(actionBtn);
}

function hideError() { if (errorToast) errorToast.style.display = 'none'; }

function showSuccess(msg) {
    if (!successMessage || !successToast) return;
    successMessage.textContent = msg;
    successToast.style.display = 'flex';
    setTimeout(() => { successToast.style.display = 'none'; }, 6000);
}
function hideSuccess() { if (successToast) successToast.style.display = 'none'; }

/* ============================================================
   Cookie Setup Logic
   ============================================================ */
if (settingsBtn && setupModal) {
    settingsBtn.addEventListener('click', () => {
        console.log("Settings opened");
        if (cookieInput) cookieInput.value = localStorage.getItem('yt_cookies') || '';
        setupModal.style.display = 'flex';
    });

    if (closeModal) {
        closeModal.addEventListener('click', () => setupModal.style.display = 'none');
    }

    setupModal.addEventListener('click', (e) => {
        if (e.target === setupModal) setupModal.style.display = 'none';
    });
}

if (setupTabs) {
    setupTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            setupTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const target = tab.dataset.tab;
            const pc = document.getElementById('pcContent');
            const mobile = document.getElementById('mobileContent');
            if (pc) pc.style.display = target === 'pc' ? 'block' : 'none';
            if (mobile) mobile.style.display = target === 'mobile' ? 'block' : 'none';
        });
    });
}

if (saveCookiesBtn) {
    saveCookiesBtn.addEventListener('click', () => {
        const val = cookieInput ? cookieInput.value.trim() : '';
        localStorage.setItem('yt_cookies', val);
        initCookieState();
        showSuccess(val ? 'Setup saved!' : 'Settings cleared.');
        setupModal.style.display = 'none';
    });
}

if (clearCookiesBtn) {
    clearCookiesBtn.addEventListener('click', () => {
        if (cookieInput) cookieInput.value = '';
        localStorage.removeItem('yt_cookies');
        initCookieState();
        showSuccess('Cleared!');
        setupModal.style.display = 'none';
    });
}

/* ============================================================
   Init
   ============================================================ */
document.addEventListener('DOMContentLoaded', () => {
    createParticles();
    checkServerHealth();
    initCookieState();
    setInterval(checkServerHealth, 15000);
    if (urlInput) urlInput.focus();
    console.log("YT Downloader Initialized");
});
