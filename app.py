import os
import sys
import glob
import tempfile
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

TEMP_DIR = tempfile.gettempdir()
download_progress = {}

# ──────────────────────────────────────────────
# Auto-detect ffmpeg on Windows
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
# Cookie Helper
# ──────────────────────────────────────────────
def create_temp_cookies(cookies_str):
    if not cookies_str or len(cookies_str) < 10: return None
    try:
        fd, path = tempfile.mkstemp(suffix='.txt', prefix='yt_cookie_')
        with os.fdopen(fd, 'w') as f:
            f.write(cookies_str)
        return path
    except:
        return None

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def format_filesize(b):
    if b is None: return ""
    for u in ["B","KB","MB","GB"]:
        if b < 1024: return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} TB"

def format_duration(s):
    if s is None: return "Unknown"
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

def format_views(v):
    if v is None: return "Unknown"
    if v >= 1_000_000_000: return f"{v/1e9:.1f}B"
    if v >= 1_000_000:     return f"{v/1e6:.1f}M"
    if v >= 1_000:         return f"{v/1e3:.1f}K"
    return str(v)

# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────
@app.route('/')
def home():
    return send_from_directory(os.getcwd(), 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory(os.getcwd(), path)

@app.route('/health')
def health():
    return jsonify({"status": "ok", "ffmpeg": FFMPEG_LOCATION or "not found"}), 200

@app.route('/info', methods=['POST'])
def get_info():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({"error": "URL is required"}), 400
    
    url = data['url'].strip()
    user_cookies = data.get('cookies')
    temp_cookie_file = create_temp_cookies(user_cookies)

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ffmpeg_location': FFMPEG_LOCATION,
        'cookiefile': temp_cookie_file
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        if info is None:
            return jsonify({"error": "Could not fetch video information"}), 400

        raw = info.get('formats', [])
        best_audio_size = 0
        for f in raw:
            if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                asize = f.get('filesize') or f.get('filesize_approx') or 0
                if asize > best_audio_size: best_audio_size = asize

        height_map = {}
        for f in raw:
            h = f.get('height')
            if h and f.get('vcodec') != 'none':
                vsize = f.get('filesize') or f.get('filesize_approx') or 0
                if h not in height_map or vsize > height_map[h]:
                    height_map[h] = vsize

        formats = []
        max_h = max(height_map.keys()) if height_map else 0
        best_total = height_map.get(max_h, 0) + best_audio_size
        size_str = f" (~{format_filesize(best_total)})" if best_total else ""
        
        formats.append({
            "format_id": "bestvideo+bestaudio/best",
            "label": f"Best Quality (Highest Available){size_str}",
            "ext": "mp4",
        })

        presets = [(1080, "1080p"), (720, "720p"), (480, "480p"), (360, "360p")]
        for h, label in presets:
            if any(vh >= h for vh in height_map.keys()):
                v_size = height_map.get(h, 0)
                total = v_size + best_audio_size
                s_str = f" (~{format_filesize(total)})" if total else ""
                formats.append({
                    "format_id": f"bestvideo[height<={h}]+bestaudio/best[height<={h}]",
                    "label": f"{label}{s_str}", "ext": "mp4"
                })

        formats.append({
            "format_id": "bestaudio[ext=m4a]/bestaudio/best",
            "label": f"Audio Only - MP3{f' (~{format_filesize(best_audio_size)})' if best_audio_size else ''}",
            "ext": "mp3"
        })

        return jsonify({
            "title": info.get('title', 'Unknown'),
            "channel": info.get('uploader', 'Unknown'),
            "duration": format_duration(info.get('duration')),
            "views": format_views(info.get('view_count')),
            "thumbnail": info.get('thumbnail', ''),
            "formats": formats,
        })

    except Exception as e:
        return jsonify({"error": str(e)[:500]}), 400
    finally:
        if temp_cookie_file and os.path.exists(temp_cookie_file):
            try: os.remove(temp_cookie_file)
            except: pass

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
            download_progress[session_id].update({
                'status': 'downloading', 'percent': pct,
                'speed': d.get('_speed_str','').strip(),
                'eta': d.get('_eta_str','').strip(),
            })
        elif d['status'] == 'finished':
            download_progress[session_id].update({'status': 'processing', 'percent': 99})

    ydl_opts = {
        'format': format_id,
        'outtmpl': output_template,
        'quiet': True,
        'progress_hooks': [progress_hook],
        'ffmpeg_location': FFMPEG_LOCATION,
        'cookiefile': temp_cookie_file,
        'merge_output_format': 'mp4' if 'bestaudio' not in format_id else None,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            actual = ydl.prepare_filename(info)
            # Fix extension if merged
            base, ext = os.path.splitext(actual)
            if not os.path.exists(actual):
                for e in ['.mp4', '.mkv', '.mp3', '.webm', '.m4a']:
                    if os.path.exists(base + e):
                        actual = base + e
                        break

        if not os.path.exists(actual):
            return jsonify({"error": "File not found"}), 500

        download_progress[session_id].update({'status': 'done', 'percent': 100})
        
        file_size = os.path.getsize(actual)
        download_name = os.path.basename(actual).replace(f"yt_{session_id}_", "")

        def stream_file():
            with open(actual, 'rb') as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk: break
                    yield chunk
            try: os.remove(actual)
            except: pass
            if temp_cookie_file and os.path.exists(temp_cookie_file):
                try: os.remove(temp_cookie_file)
                except: pass

        return Response(
            stream_file(), 
            mimetype='application/octet-stream',
            headers={'Content-Disposition': f'attachment; filename="{download_name}"', 'Content-Length': str(file_size)}
        )

    except Exception as e:
        if temp_cookie_file and os.path.exists(temp_cookie_file):
            try: os.remove(temp_cookie_file)
            except: pass
        download_progress[session_id] = {'status': 'error'}
        return jsonify({"error": str(e)[:500]}), 500

@app.route('/progress')
def get_progress():
    sid = request.args.get('session_id', 'default')
    return jsonify(download_progress.get(sid, {'status': 'idle'}))

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), threaded=True)
