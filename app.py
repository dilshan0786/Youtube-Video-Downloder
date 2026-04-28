import os
import sys
import glob
import tempfile
import time
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

TEMP_DIR = tempfile.gettempdir()
download_progress = {}

# ──────────────────────────────────────────────
# Auto-detect ffmpeg
# ──────────────────────────────────────────────
def find_ffmpeg():
    import shutil
    p = shutil.which("ffmpeg")
    if p: return os.path.dirname(p)
    local_app = os.environ.get("LOCALAPPDATA", "")
    patterns = [
        os.path.join(local_app, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin"),
        os.path.join(local_app, "Microsoft", "WinGet", "Links"),
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\ProgramData\chocolatey\bin",
    ]
    for pattern in patterns:
        if "*" in pattern or "?" in pattern:
            matches = glob.glob(pattern, recursive=True)
            for m in matches:
                if os.path.isfile(os.path.join(m, "ffmpeg.exe")): return m
        else:
            if os.path.isfile(os.path.join(pattern, "ffmpeg.exe")): return pattern
    return None

FFMPEG_LOCATION = find_ffmpeg()
if FFMPEG_LOCATION:
    os.environ["PATH"] = FFMPEG_LOCATION + os.pathsep + os.environ.get("PATH", "")

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def create_temp_cookies(cookies_str):
    if not cookies_str or len(cookies_str) < 20: return None
    try:
        fd, path = tempfile.mkstemp(suffix='.txt', prefix='yt_cookie_')
        with os.fdopen(fd, 'w') as f:
            f.write(cookies_str)
        return path
    except: return None

def get_common_opts(temp_cookie_file=None):
    return {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'ffmpeg_location': FFMPEG_LOCATION,
        'cookiefile': temp_cookie_file,
        # IMPORTANT: Bypass bot detection by spoofing client
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'skip': ['dash', 'hls']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
        }
    }

def format_filesize(b):
    if b is None: return ""
    for u in ["B","KB","MB","GB"]:
        if b < 1024: return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} TB"

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
    ydl_opts = get_common_opts(temp_cookie_file)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        raw_formats = info.get('formats', [])
        best_audio_size = 0
        for f in raw_formats:
            if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                asize = f.get('filesize') or f.get('filesize_approx') or 0
                if asize > best_audio_size: best_audio_size = asize

        height_map = {}
        for f in raw_formats:
            h = f.get('height')
            if h and f.get('vcodec') != 'none':
                vsize = f.get('filesize') or f.get('filesize_approx') or 0
                if h not in height_map or vsize > height_map[h]:
                    height_map[h] = vsize

        formats = []
        # Best Quality
        formats.append({
            "format_id": "bestvideo+bestaudio/best",
            "label": f"Best Quality (Recommended)",
            "ext": "mp4",
        })

        # Presets
        for h, label in [(1080, "1080p Full HD"), (720, "720p HD"), (480, "480p SD"), (360, "360p")]:
            if any(vh >= h for vh in height_map.keys()):
                formats.append({
                    "format_id": f"bestvideo[height<={h}]+bestaudio/best[height<={h}]",
                    "label": label, "ext": "mp4"
                })

        formats.append({
            "format_id": "bestaudio/best",
            "label": "Audio Only (MP3)", "ext": "mp3"
        })

        return jsonify({
            "title": info.get('title', 'Video'),
            "thumbnail": info.get('thumbnail', ''),
            "duration": time.strftime('%H:%M:%S', time.gmtime(info.get('duration', 0))),
            "formats": formats
        })
    except Exception as e:
        msg = str(e)
        if "Sign in" in msg: msg = "Sign-in Required! Browser se cookies export karke paste karein."
        return jsonify({"error": msg[:500]}), 400
    finally:
        if temp_cookie_file and os.path.exists(temp_cookie_file): os.remove(temp_cookie_file)

@app.route('/download')
def download_video():
    url = request.args.get('url', '').strip()
    format_id = request.args.get('format_id', 'bestvideo+bestaudio/best')
    session_id = request.args.get('session_id', 'default')
    user_cookies = request.args.get('cookies')
    
    temp_cookie_file = create_temp_cookies(user_cookies)
    output_template = os.path.join(TEMP_DIR, f'yt_{session_id}_%(title)s.%(ext)s')
    
    download_progress[session_id] = {'status': 'starting', 'percent': 0}

    def progress_hook(d):
        if d['status'] == 'downloading':
            try: pct = float(d.get('_percent_str','0%').strip().replace('%',''))
            except: pct = 0
            download_progress[session_id].update({'status': 'downloading', 'percent': pct})
        elif d['status'] == 'finished':
            download_progress[session_id].update({'status': 'processing', 'percent': 99})

    ydl_opts = get_common_opts(temp_cookie_file)
    ydl_opts.update({
        'format': format_id,
        'outtmpl': output_template,
        'progress_hooks': [progress_hook],
        'merge_output_format': 'mp4' if 'bestaudio' not in format_id else None,
    })

    if 'bestaudio' in format_id and 'bestvideo' not in format_id:
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            actual = ydl.prepare_filename(info)
            # Fix ext for merged files
            base = os.path.splitext(actual)[0]
            for e in ['.mp4', '.mkv', '.mp3', '.webm', '.m4a']:
                if os.path.exists(base + e):
                    actual = base + e
                    break

        if not os.path.exists(actual): return jsonify({"error": "File not found"}), 500

        download_progress[session_id].update({'status': 'done', 'percent': 100})
        
        file_size = os.path.getsize(actual)
        download_name = os.path.basename(actual).replace(f"yt_{session_id}_", "")

        def stream_and_clean():
            with open(actual, 'rb') as f:
                while chunk := f.read(1024*1024): yield chunk
            try: os.remove(actual)
            except: pass
            if temp_cookie_file and os.path.exists(temp_cookie_file): os.remove(temp_cookie_file)

        return Response(
            stream_and_clean(), 
            mimetype='application/octet-stream',
            headers={'Content-Disposition': f'attachment; filename="{download_name}"', 'Content-Length': str(file_size)}
        )
    except Exception as e:
        download_progress[session_id] = {'status': 'error'}
        return jsonify({"error": str(e)[:500]}), 500
    finally:
        if temp_cookie_file and os.path.exists(temp_cookie_file):
            try: os.remove(temp_cookie_file)
            except: pass

@app.route('/progress')
def get_progress():
    sid = request.args.get('session_id', 'default')
    return jsonify(download_progress.get(sid, {'status': 'idle'}))

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), threaded=True)
