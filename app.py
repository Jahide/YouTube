from flask import Flask, jsonify, request, send_file, send_from_directory
import yt_dlp
import os
import shutil
import logging
from logging.handlers import RotatingFileHandler
import time
from functools import wraps
import re
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Configuration
class Config:
    DOWNLOAD_FOLDER = 'downloads'
    MAX_FILESIZE = 500 * 1024 * 1024  # 500MB
    CLEANUP_THRESHOLD = 24 * 60 * 60   # 24 hours in seconds
    MAX_CONCURRENT_DOWNLOADS = 3
    VALID_YOUTUBE_URL = re.compile(
        r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+$'
    )

# Setup logging
if not os.path.exists('logs'):
    os.makedirs('logs')

logging.basicConfig(level=logging.INFO)
handler = RotatingFileHandler(
    'logs/app.log', maxBytes=10000000, backupCount=5)
handler.setFormatter(logging.Formatter(
    '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
))
app.logger.addHandler(handler)

# Ensure download directory exists
if not os.path.exists(Config.DOWNLOAD_FOLDER):
    os.makedirs(Config.DOWNLOAD_FOLDER)

# Rate limiting
download_times = {}

def rate_limit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        ip = request.remote_addr
        current_time = time.time()
        
        # Clean old entries
        download_times.update(
            {k: v for k, v in download_times.items() 
             if current_time - v[-1] < 3600}
        )
        
        if ip in download_times:
            times = download_times[ip]
            if len(times) >= Config.MAX_CONCURRENT_DOWNLOADS:
                if current_time - times[0] < 3600:  # 1 hour
                    return jsonify({
                        'error': 'Download limit reached. Please try again later.'
                    }), 429
                times.pop(0)
        else:
            download_times[ip] = []
            
        download_times[ip].append(current_time)
        return func(*args, **kwargs)
    return wrapper

def check_ffmpeg():
    """Check if ffmpeg is installed and accessible"""
    return shutil.which('ffmpeg') is not None

def cleanup_downloads():
    """Remove old downloads"""
    current_time = time.time()
    for filename in os.listdir(Config.DOWNLOAD_FOLDER):
        filepath = os.path.join(Config.DOWNLOAD_FOLDER, filename)
        if current_time - os.path.getctime(filepath) > Config.CLEANUP_THRESHOLD:
            try:
                os.remove(filepath)
                app.logger.info(f"Cleaned up old file: {filename}")
            except Exception as e:
                app.logger.error(f"Error cleaning up {filename}: {str(e)}")

@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/check-ffmpeg')
def ffmpeg_status():
    return jsonify({'installed': check_ffmpeg()})

@app.route('/download', methods=['POST'])
@rate_limit
def download_video():
    cleanup_downloads()  # Clean up old files before new download
    
    if not check_ffmpeg():
        return jsonify({
            'error': 'FFmpeg is not installed. Please install FFmpeg to download media.'
        }), 500

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        url = data.get('url', '').strip()
        format_type = data.get('format', 'video')

        if not url:
            return jsonify({'error': 'No URL provided'}), 400

        if not Config.VALID_YOUTUBE_URL.match(url):
            return jsonify({'error': 'Invalid YouTube URL'}), 400

        if format_type == 'audio':
            ydl_opts = {
                'outtmpl': os.path.join(Config.DOWNLOAD_FOLDER, '%(title)s.mp3'),
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'max_filesize': Config.MAX_FILESIZE,
                'verbose': True
            }
        else:
            ydl_opts = {
                'outtmpl': os.path.join(Config.DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
                'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
                'merge_output_format': 'mp4',
                'max_filesize': Config.MAX_FILESIZE,
                'verbose': True
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if format_type == 'audio' and not filename.endswith('.mp3'):
                filename = os.path.splitext(filename)[0] + '.mp3'
            
            app.logger.info(f"Successfully downloaded: {os.path.basename(filename)}")
            
            return jsonify({
                'download_url': f'/download-file/{os.path.basename(filename)}'
            })

    except yt_dlp.utils.DownloadError as e:
        app.logger.error(f"Download error: {str(e)}")
        return jsonify({'error': 'Video unavailable or restricted'}), 400
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred'}), 500

@app.route('/download-file/<filename>')
def download_file(filename):
    try:
        return send_file(
            os.path.join(Config.DOWNLOAD_FOLDER, filename),
            as_attachment=True,
            max_age=0
        )
    except Exception as e:
        app.logger.error(f"Error serving file {filename}: {str(e)}")
        return jsonify({'error': 'File not found'}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))