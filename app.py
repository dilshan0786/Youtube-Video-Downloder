import os
import sys
import glob
import tempfile
import time
import shutil
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

# Cloud-friendly Temp Directory
TEMP_DIR = tempfile.gettempdir()
download_progress = {}

# ──────────────────────────────────────────────
# FFmpeg Detection (Windows & Linux Support)
# ──────────────────────────────────────────────
def find_ffmpeg():
    # 1. Check system PATH (Common for Linux/Cloud)
    p = shutil.which("ffmpeg")
    if p: return os.path.dirname(p)
    
    # 2. Windows-specific fallback
    if os.name == 'nt':
        local_app = os.environ.get("LOCALAPPDATA", "")
        patterns = [
            os.path.join(local_app, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin"),
            r"C:\ffmpeg\bin",
            r"C:\Program Files\ffmpeg\bin",
        ]
        for pattern in patterns:
            matches = glob.glob(pattern, recursive=True)
            for m in matches:
                if os.path.isfile(os.path.join(m, "ffmpeg.exe")): return m
    return None

FFMPEG_PATH = find_ffmpeg()
if FFMPEG_PATH:
    os.environ["PATH"] = FFMPEG_PATH + os.pathsep + os.environ.get("PATH", "")

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def create_temp_cookies(cookies_str):
    if not cookies_str or len(cookies_str) < 20: return None
    try:
        fd, path = tempfile.mkstemp(suffix='.txt', prefix='yt_cookie_', dir=TEMP_DIR)
        with os.fdopen(fd, 'w') as f: f.write(cookies_str)
        return path
    except: return None

def get_ydl_opts(temp_cookie_file=None):
    return {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'ffmpeg_location': FFMPEG_PATH,
        'cookiefile': temp_cookie_file,
        'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'http_headers': {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
        }
    }

# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────
@app.route('/')
def home(): return send_from_directory(os.getcwd(), 'index.html')

@app.route('/<path:path>')
def static_files(path): return send_from_directory(os.getcwd(), path)

@app.route('/info', methods=['POST'])
def get_info():
    data = request.get_json()
    url = data.get('url', '').strip()
    if not url: return jsonify({"error": "URL missing"}), 400
    
    temp_cookie_file = create_temp_cookies(data.get('cookies'))
    
    try:
        with yt_dlp.YoutubeDL(get_ydl_opts(temp_cookie_file)) as ydl:
            info = ydl.extract_info(url, download=False)
        
        # Super robust format choices
        formats = [
            {"format_id": "bestvideo+bestaudio/best", "label": "Best Quality (Default)", "ext": "mp4"},
            {"format_id": "bestvideo[height<=1080]+bestaudio/best[height<=1080]", "label": "1080p Full HD", "ext": "mp4"},
            {"format_id": "bestvideo[height<=720]+bestaudio/best[height<=720]", "label": "720p HD", "ext": "mp4"},
            {"format_id": "bestvideo[height<=480]+bestaudio/best[height<=480]", "label": "480p SD", "ext": "mp4"},
            {"format_id": "bestaudio/best", "label": "Audio Only (MP3)", "ext": "mp3"}
        ]

        return jsonify({
            "title": info.get('title', 'Video'),
            "thumbnail": info.get('thumbnail', ''),
            "duration": time.strftime('%H:%M:%S', time.gmtime(info.get('duration', 0))),
            "formats": formats
        })
    except Exception as e:
        return jsonify({"error": str(e)[:500]}), 400
    finally:
        if temp_cookie_file and os.path.exists(temp_cookie_file):
            try: os.remove(temp_cookie_file)
            except: pass

@app.route('/download')
def download_video():
    url = request.args.get('url')
    format_id = request.args.get('format_id', 'bestvideo+bestaudio/best')
    session_id = request.args.get('session_id', 'cloud')
    user_cookies = request.args.get('cookies')
    
    temp_cookie_file = create_temp_cookies(user_cookies)
    output_template = os.path.join(TEMP_DIR, f'yt_{session_id}_%(title)s.%(ext)s')
    
    download_progress[session_id] = {'status': 'downloading', 'percent': 0}

    def hook(d):
        if d['status'] == 'downloading':
            try: p = float(d.get('_percent_str','0%').replace('%',''))
            except: p = 0
            download_progress[session_id]['percent'] = p

    ydl_opts = get_ydl_opts(temp_cookie_file)
    ydl_opts.update({
        'format': format_id,
        'outtmpl': output_template,
        'progress_hooks': [hook],
        'merge_output_format': 'mp4' if 'bestaudio' not in format_id else None
    })

    if 'bestaudio' in format_id and 'bestvideo' not in format_id:
        ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3'}]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
            # Find merged file
            base = os.path.splitext(path)[0]
            for ext in ['.mp4', '.mkv', '.mp3', '.webm', '.m4a']:
                if os.path.exists(base + ext):
                    path = base + ext
                    break

        download_progress[session_id]['status'] = 'done'
        
        file_size = os.path.getsize(path)
        download_name = os.path.basename(path).replace(f"yt_{session_id}_", "")

        def stream():
            with open(path, 'rb') as f:
                while chunk := f.read(1024*1024): yield chunk
            try: os.remove(path)
            except: pass
            if temp_cookie_file and os.path.exists(temp_cookie_file):
                try: os.remove(temp_cookie_file)
                except: pass

        return Response(stream(), mimetype='application/octet-stream', headers={
            'Content-Disposition': f'attachment; filename="{download_name}"',
            'Content-Length': str(file_size)
        })
    except Exception as e:
        download_progress[session_id]['status'] = 'error'
        return jsonify({"error": str(e)[:500]}), 500
    finally:
        if temp_cookie_file and os.path.exists(temp_cookie_file):
            try: os.remove(temp_cookie_file)
            except: pass

@app.route('/progress')
def get_progress():
    sid = request.args.get('session_id', 'cloud')
    return jsonify(download_progress.get(sid, {'status': 'idle'}))

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
