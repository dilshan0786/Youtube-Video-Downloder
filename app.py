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
# Auto-detect ffmpeg on Windows (winget / choco / system PATH)
# ──────────────────────────────────────────────
def find_ffmpeg():
    # 1. Check if already in PATH
    import shutil
    p = shutil.which("ffmpeg")
    if p:
        return os.path.dirname(p)

    # 2. Winget install locations
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
                if os.path.isfile(os.path.join(m, "ffmpeg.exe")):
                    return m
        else:
            if os.path.isfile(os.path.join(pattern, "ffmpeg.exe")):
                return pattern
    return None

FFMPEG_LOCATION = find_ffmpeg()
if FFMPEG_LOCATION:
    # Add to PATH for this process so yt-dlp can find it
    os.environ["PATH"] = FFMPEG_LOCATION + os.pathsep + os.environ.get("PATH", "")
    print(f"  ffmpeg found: {FFMPEG_LOCATION}")
else:
    print("  WARNING: ffmpeg not found. 1080p+ downloads need ffmpeg.")


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

@app.route('/api')
def api_index():
    return jsonify({
        "status": "online",
        "message": "YT Downloader API is running successfully!"
    }), 200

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "ffmpeg": FFMPEG_LOCATION or "not found"
    }), 200


@app.route('/info', methods=['POST'])
def get_info():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({"error": "URL is required"}), 400
    url = data['url'].strip()

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ffmpeg_location': FFMPEG_LOCATION,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info is None:
            return jsonify({"error": "Could not fetch video information"}), 400

        raw = info.get('formats', [])

        # --- Calculate Sizes ---
        # Find best audio size (for merging)
        best_audio_size = 0
        for f in raw:
            if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                asize = f.get('filesize') or f.get('filesize_approx') or 0
                if asize > best_audio_size: best_audio_size = asize

        # Map height to best video size
        height_map = {}
        for f in raw:
            h = f.get('height')
            if h and f.get('vcodec') != 'none':
                vsize = f.get('filesize') or f.get('filesize_approx') or 0
                if h not in height_map or vsize > height_map[h]:
                    height_map[h] = vsize

        # Build clean format presets
        formats = []

        # ── Best Quality ──
        max_h = max(height_map.keys()) if height_map else 0
        best_total = height_map.get(max_h, 0) + best_audio_size
        size_str = f" (~{format_filesize(best_total)})" if best_total else ""
        
        formats.append({
            "format_id": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
            "label": f"Best Quality (Highest Available) - Recommended{size_str}",
            "ext": "mp4",
        })

        # ── Fixed-height presets ──
        presets = [
            (2160, "4K Ultra HD (2160p)"),
            (1440, "2K QHD (1440p)"),
            (1080, "Full HD (1080p)"),
            (720,  "HD (720p)"),
            (480,  "SD (480p)"),
            (360,  "Low (360p)"),
            (240,  "Very Low (240p)"),
        ]
        for h, label in presets:
            if any(vh >= h for vh in height_map.keys()):
                # Estimate size: video at this height + best audio
                v_size = height_map.get(h)
                if not v_size: # if exact h not found, find closest lower
                    v_size = next((height_map[vh] for vh in sorted(height_map.keys(), reverse=True) if vh <= h), 0)
                
                total = v_size + best_audio_size
                s_str = f" (~{format_filesize(total)})" if total else ""
                
                formats.append({
                    "format_id": f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={h}]+bestaudio/best[height<={h}]",
                    "label": f"{label}{s_str}",
                    "ext": "mp4",
                })

        # ── Audio only ──
        a_str = f" (~{format_filesize(best_audio_size)})" if best_audio_size else ""
        formats.append({
            "format_id": "bestaudio[ext=m4a]/bestaudio/best",
            "label": f"Audio Only - MP3 (best quality){a_str}",
            "ext": "mp3",
        })

        result = {
            "title":      info.get('title', 'Unknown Title'),
            "channel":    info.get('uploader', info.get('channel', 'Unknown')),
            "duration":   format_duration(info.get('duration')),
            "views":      format_views(info.get('view_count')),
            "thumbnail":  info.get('thumbnail', ''),
            "formats":    formats,
        }
        return jsonify(result)

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if 'Private'      in msg: return jsonify({"error": "This video is private."}), 400
        if 'unavailable'  in msg: return jsonify({"error": "This video is unavailable."}), 400
        if 'Sign in'      in msg: return jsonify({"error": "This video requires sign-in."}), 400
        return jsonify({"error": msg[:250]}), 400
    except Exception as e:
        return jsonify({"error": str(e)[:250]}), 500


@app.route('/download')
def download_video():
    url       = request.args.get('url', '').strip()
    format_id = request.args.get('format_id', 'bestvideo+bestaudio/best')
    session_id= request.args.get('session_id', 'default')

    if not url:
        return jsonify({"error": "URL is required"}), 400

    output_template = os.path.join(TEMP_DIR, f'yt_{session_id}_%(title)s.%(ext)s')
    download_progress[session_id] = {'status': 'starting', 'percent': 0, 'speed': '', 'eta': ''}

    is_audio_only = ('bestaudio' in format_id) and ('bestvideo' not in format_id)

    def progress_hook(d):
        if d['status'] == 'downloading':
            try:   pct = float(d.get('_percent_str','0%').strip().replace('%',''))
            except: pct = 0
            download_progress[session_id].update({
                'status': 'downloading', 'percent': pct,
                'speed': d.get('_speed_str','').strip(),
                'eta':   d.get('_eta_str','').strip(),
            })
        elif d['status'] == 'finished':
            download_progress[session_id].update({'status': 'processing', 'percent': 99, 'eta': 'Merging...'})

    ydl_opts = {
        'format':           format_id,
        'outtmpl':          output_template,
        'quiet':            True,
        'no_warnings':      True,
        'progress_hooks':   [progress_hook],
        'ffmpeg_location':  FFMPEG_LOCATION,
        'merge_output_format': 'mp4' if not is_audio_only else None,
    }

    if is_audio_only:
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '0',
        }]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            base_path = ydl.prepare_filename(info)

        # Find the actual output file
        actual = None
        extensions = ['.mp4', '.mp3', '.webm', '.mkv', '.m4a', '.opus']
        base_noext = os.path.splitext(base_path)[0]
        for ext in extensions:
            candidate = base_noext + ext
            if os.path.exists(candidate):
                actual = candidate
                break

        if not actual or not os.path.exists(actual):
            # Fallback: search temp dir for our session file
            for f in os.listdir(TEMP_DIR):
                if f.startswith(f'yt_{session_id}_'):
                    actual = os.path.join(TEMP_DIR, f)
                    break

        if not actual or not os.path.exists(actual):
            return jsonify({"error": "Downloaded file not found after processing."}), 500

        download_progress[session_id].update({'status': 'done', 'percent': 100})

        # Clean filename
        safe_title = info.get('title', 'video')
        for ch in r'\/:*?"<>|': safe_title = safe_title.replace(ch, '_')
        file_ext = os.path.splitext(actual)[1]
        download_name = f"{safe_title}{file_ext}"

        file_size = os.path.getsize(actual)

        def stream_file():
            with open(actual, 'rb') as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk: break
                    yield chunk
            try: os.remove(actual)
            except: pass

        mime = 'video/mp4' if file_ext in ['.mp4','.webm','.mkv'] else 'audio/mpeg'
        return Response(
            stream_file(), mimetype=mime,
            headers={
                'Content-Disposition': f'attachment; filename="{download_name}"',
                'Content-Length': str(file_size),
            }
        )

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        download_progress[session_id] = {'status': 'error', 'percent': 0, 'speed': '', 'eta': ''}
        if 'ffmpeg' in msg.lower():
            return jsonify({"error": "ffmpeg not found! Server could not locate ffmpeg. Restart start.bat."}), 500
        return jsonify({"error": msg[:300]}), 500
    except Exception as e:
        download_progress[session_id] = {'status': 'error', 'percent': 0, 'speed': '', 'eta': ''}
        return jsonify({"error": str(e)[:300]}), 500


@app.route('/progress')
def get_progress():
    sid = request.args.get('session_id', 'default')
    return jsonify(download_progress.get(sid, {'status': 'idle', 'percent': 0}))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 60)
    print("  YouTube Downloader Server")
    print(f"  ffmpeg: {FFMPEG_LOCATION or 'NOT FOUND'}")
    print(f"  Running at: http://0.0.0.0:{port}")
    print("=" * 60)
    app.run(debug=False, host='0.0.0.0', port=port, threaded=True)
