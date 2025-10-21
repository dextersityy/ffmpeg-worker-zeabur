from flask import Flask, request, jsonify, send_file
import subprocess
import os
import time
import math
import logging

# --- IMPORT LIBRARY YOUTUBE TRANSCRIPT YANG BENAR ---
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

app = Flask(__name__)
# Menghilangkan logging default agar log Zeabur lebih bersih
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Direktori Tempat Menyimpan Klip yang Dipotong (Wajib: /data sesuai Volume Zeabur)
TEMP_DIR = "/data/clips"
# Buat folder jika belum ada (Zeabur harusnya sudah mount /data)
try:
    os.makedirs(TEMP_DIR, exist_ok=True)
except Exception as e:
    print(f"Error creating TEMP_DIR {TEMP_DIR}: {e}")
    # Jika gagal, container mungkin akan crash. Pastikan volume Zeabur terpasang!

# Fungsi Pembantu untuk Ekstraksi Video ID
def extract_video_id(url):
    try:
        # Mencari ID setelah v= dan sebelum & (jika ada)
        return url.split('v=')[-1].split('&')[0]
    except:
        return None

# Fungsi Pembantu untuk mendapatkan URL Worker
def get_worker_base_url(host):
    # Menggunakan ZEABUR_URL jika tersedia (lebih stabil) atau host request
    zeabur_url = os.environ.get("ZEABUR_URL")
    if zeabur_url:
        return zeabur_url
    return host.split(':')[0] # Ambil domain/IP tanpa port

# ----------------------------------------------------
# ENDPOINT 1: /get-transcript
# Dipanggil oleh n8n untuk mendapatkan transkrip.
# ----------------------------------------------------
@app.route('/get-transcript', methods=['POST'])
def get_transcript():
    try:
        youtube_url = request.json.get('youtube_url')
        video_id = extract_video_id(youtube_url)
        
        if not video_id:
            return jsonify({"status": "fail", "error": "Invalid or missing YouTube URL."}), 400

        try:
            # Panggil library youtube-transcript-api
            # Menggunakan YouTubeTranscriptApi.get_transcript() secara statis
            transcript_list = YouTubeTranscriptApi.get_transcript(
                video_id, 
                languages=['id', 'en', 'auto'] # Prioritas: Indonesia, Inggris, Otomatis
            )

            formatted_transcript = []
            for segment in transcript_list:
                formatted_transcript.append({
                    'start': segment['start'],
                    'text': segment['text']
                })

            return jsonify({
                "status": "success", 
                "transcript": formatted_transcript
            })

        except TranscriptsDisabled:
            return jsonify({"status": "fail", "error": "Transkrip dimatikan untuk video ini oleh kreator."}), 400
        
        except NoTranscriptFound:
            return jsonify({"status": "fail", "error": "Transkrip tidak tersedia (manual/otomatis) dalam bahasa ID atau EN."}), 400

        except Exception as e:
            return jsonify({"status": "fail", "error": f"Kesalahan API Internal: {str(e)}", "video_id": video_id}), 500

    except Exception as e:
        return jsonify({"status": "fail", "error": f"Kesalahan Permintaan Umum: {str(e)}"}), 400

# ----------------------------------------------------
# ENDPOINT 2: /cut-video
# Dipanggil oleh n8n untuk memotong klip dan menyimpannya.
# ----------------------------------------------------
@app.route('/cut-video', methods=['POST'])
def cut_video():
    try:
        data = request.json
        youtube_url = data.get('youtube_url')
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        
        if not all([youtube_url, start_time, end_time]):
            return jsonify({"error": "Missing parameters"}), 400

        duration = float(end_time) - float(start_time)
        
        # Membuat nama file unik
        unique_id = int(time.time() * 1000)
        output_filename = f"clip-{unique_id}.mp4"
        output_path = os.path.join(TEMP_DIR, output_filename)

        # 1. Mendapatkan Stream URL dari YouTube menggunakan yt-dlp
        get_url_cmd = [
            "yt-dlp", youtube_url, "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]", 
            "--get-url", "--no-warnings"
        ]
        
        stream_url = subprocess.check_output(get_url_cmd, text=True).strip().split('\n')[0] # Ambil URL pertama

        # 2. Perintah FFmpeg Kritis: Memotong Langsung dari Stream URL
        cut_command = [
            "ffmpeg", 
            "-ss", str(math.floor(float(start_time))), # Potong dari detik awal terdekat
            "-i", stream_url,          
            "-t", str(duration),       
            "-c:v", "copy",            
            "-c:a", "aac",             
            "-b:a", "128k",
            output_path                
        ]
        
        subprocess.run(cut_command, check=True)

        # Mengembalikan URL publik
        worker_base_url = get_worker_base_url(request.host)
        clip_public_url = f"https://{worker_base_url}/clips/{output_filename}"

        return jsonify({
            "status": "success",
            "file_name": output_filename,
            "clip_url_public": clip_public_url 
        })

    except subprocess.CalledProcessError as e:
        return jsonify({"error": "FFmpeg/yt-dlp crash", "details": str(e)}), 500
    except Exception as e:
        return jsonify({"error": f"Kesalahan Internal Server: {str(e)}"}), 500

# ----------------------------------------------------
# ENDPOINT 3: /clips/<filename>
# Dipanggil oleh TikTok (mode PULL) untuk menarik klip.
# ----------------------------------------------------
@app.route('/clips/<filename>')
def serve_clip(filename):
    file_path = os.path.join(TEMP_DIR, filename)
    if os.path.exists(file_path):
        return send_file(file_path, mimetype='video/mp4')
    else:
        return jsonify({"error": "File not found"}), 404

# ----------------------------------------------------
# ENDPOINT 4: /cleanup-clip
# Dipanggil oleh n8n setelah klip berhasil di-upload ke TikTok.
# ----------------------------------------------------
@app.route('/cleanup-clip', methods=['POST'])
def cleanup_clip():
    try:
        file_name = request.json.get('file_name')
        if not file_name:
            return jsonify({"status": "fail", "error": "File name missing"}), 400

        file_path = os.path.join(TEMP_DIR, file_name)

        if os.path.exists(file_path):
            os.remove(file_path)
            return jsonify({"status": "success", "message": f"File {file_name} deleted."})
        else:
            return jsonify({"status": "warning", "message": f"File {file_name} not found."})
    except Exception as e:
        return jsonify({"status": "fail", "error": f"Cleanup error: {str(e)}"}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
