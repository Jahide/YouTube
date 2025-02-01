
2.28 KB •78 lines
Formatting may be inconsistent from source
from flask import Flask, jsonify, request, send_file, send_from_directory
import yt_dlp
import os
import shutil

app = Flask(__name__)
DOWNLOAD_FOLDER = 'downloads'

def check_ffmpeg():
    """Check if ffmpeg is installed and accessible"""
    return shutil.which('ffmpeg') is not None

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/check-ffmpeg')
def ffmpeg_status():
    return jsonify({'installed': check_ffmpeg()})

@app.route('/download', methods=['POST'])
def download_video():
    if not check_ffmpeg():
        return jsonify({
            'error': 'FFmpeg is not installed. Please install FFmpeg to download media.'
        }), 500

    data = request.json
    url = data.get('url')
    format_type = data.get('format', 'video')

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    if format_type == 'audio':
        ydl_opts = {
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.mp3'),
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'verbose': True
        }
    else:
        ydl_opts = {
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
            'format': 'bestvideo+bestaudio/best',
            'merge_output_format': 'mp4',
            'verbose': True
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Adjust filename extension for audio downloads
            if format_type == 'audio' and not filename.endswith('.mp3'):
                filename = os.path.splitext(filename)[0] + '.mp3'
            
        return jsonify({
            'download_url': f'/download-file/{os.path.basename(filename)}'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download-file/<filename>')
def download_file(filename):
    return send_file(os.path.join(DOWNLOAD_FOLDER, filename), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
