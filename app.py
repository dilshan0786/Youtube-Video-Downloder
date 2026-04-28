import os
import sys
import tempfile
import time
import shutil
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

TEMP_DIR = tempfile.gettempdir()
download_progress = {}

def find_ffmpeg():
    for path in ['/usr/bin/ffmpeg', '/usr/local/bin/ffmpeg']:
        if os.path.exists(path): return path
    p = shutil.which("ffmpeg")
    return p if p else None

FFMPEG_EXE = find_ffmpeg()

def create_temp_cookies(cookies_str):
    if not cookies_str or len(cookies_str) < 20: return None
    
    # SMART CHECK: Check if cookies actually belong to YouTube
    if ".youtube.com" not in cookies_str and "google.com" not in cookies_str:
        return "INVALID_DOMAIN"
        
    try:
        fd, path = tempfile.mkstemp(suffix='.txt', prefix='yt_cookie_', dir=TEMP_DIR)
        with os.fdopen(fd, 'w') as f: f.write(cookies_str)
        return path
    except: return None

def get_ydl_opts(temp_cookie_file=None):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'ffmpeg_location': FFMPEG_EXE,
        'cookiefile': temp_cookie_file if temp_cookie_file and temp_cookie_file != "INVALID_DOMAIN" else None,
        'extractor_args': {'youtube': {'player_client': ['ios', 'web', 'mweb']}},
        'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1'
    }
    return opts

@app.route('/health')
def health(): return "OK", 200

@app.route('/')
def home(): return send_from_directory(os.getcwd(), 'index.html')

@app.route('/<path:path>')
def static_files(path): return send_from_directory(os.getcwd(), path)

@app.route('/info', methods=['POST'])
def get_info():
    data = request.get_json()
    url = data.get('url', '').strip()
    cookies_data = data.get('cookies')
    
    temp_cookie_file = create_temp_cookies(cookies_data)
    if temp_cookie_file == "INVALID_DOMAIN":
        return jsonify({"error": "Aapne galat cookies paste ki hain! Pehle YouTube.com kholiye, fir export kijiye."}), 400

    try:
        with yt_dlp.YoutubeDL(get_ydl_opts(temp_cookie_file)) as ydl:
            # First try to extract without format restriction
            info = ydl.extract_info(url, download=False)
        
        formats = [
            {"format_id": "bestvideo+bestaudio/best", "label": "Best Quality (Highest)", "ext": "mp4"},
            {"format_id": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best", "label": "1080p Full HD", "ext": "mp4"},
            {"format_id": "bestvideo[height<=720]+bestaudio/best[height<=720]/best", "label": "720p HD", "ext": "mp4"},
            {"format_id": "bestvideo[height<=480]+bestaudio/best[height<=480]/best", "label": "480p SD", "ext": "mp4"},
            {"format_id": "bestaudio/best", "label": "Audio Only (MP3)", "ext": "mp3"}
        ]

        return jsonify({
            "title": info.get('title', 'Video'),
            "thumbnail": info.get('thumbnail', ''),
            "duration": str(info.get('duration', 0)),
            "formats": formats
        })
    except Exception as e:
        msg = str(e)
        if "format is not available" in msg:
            # Fallback for some weird videos
            try:
                with yt_dlp.YoutubeDL({'quiet':True, 'no_warnings':True}) as ydl2:
                    info2 = ydl2.extract_info(url, download=False)
                    return jsonify({
                        "title": info2.get('title', 'Video'),
                        "thumbnail": info2.get('thumbnail', ''),
                        "formats": [{"format_id": "best", "label": "Standard Quality", "ext": "mp4"}]
                    })
            except: pass
        return jsonify({"error": msg[:500]}), 400
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
    if temp_cookie_file == "INVALID_DOMAIN": temp_cookie_file = None

    output_template = os.path.join(TEMP_DIR, f'yt_{session_id}_%(title)s.%(ext)s')
    download_progress[session_id] = {'status': 'downloading', 'percent': 0}

    def hook(d):
        if d['status'] == 'downloading':
            try: p = float(d.get('_percent_str','0%').replace('%',''))
            except: p = 0
            download_progress[session_id]['percent'] = p

    ydl_opts = get_ydl_opts(temp_cookie_file)
    ydl_opts.update({
        'format': f"{format_id}/best",
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
        return jsonify({"error": str(e)}), 500
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
