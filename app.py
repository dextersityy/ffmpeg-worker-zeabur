from flask import Flask, request, jsonify, send_file
import subprocess
import os
import time
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

app = Flask(__name__)

# Direktori untuk menyimpan klip (Pastikan kamu membuat folder ini di Zeabur)
TEMP_DIR = "/data/clips"
os.makedirs(TEMP_DIR, exist_ok=True)

@app.route('/get-transcript', methods=['POST'])
def get_transcript():
    try:
        data = request.json
        youtube_url = data.get('youtube_url')
        
        if not youtube_url:
            return jsonify({"error": "Missing YouTube URL"}), 400

        # Ekstrak Video ID dari URL (Pastikan ini benar)
        video_id = youtube_url.split('v=')[-1].split('&')[0]

        try:
            # Panggil library youtube-transcript-api
            transcript_list = YouTubeTranscriptApi.get_transcript(
                video_id, 
                languages=['id', 'en']
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
            # Jika video memang tidak mengizinkan transkrip
            return jsonify({"status": "fail", "error": "Transcripts are disabled for this video."}), 400
        
        except NoTranscriptFound:
            # Jika transkrip tidak ada dalam bahasa ID/EN
            return jsonify({"status": "fail", "error": "No transcript found in ID or EN for this video."}), 400

        except Exception as e:
            # Untuk error lain (misal ID tidak valid)
            return jsonify({"status": "fail", "error": f"Internal API Error during fetching: {str(e)}", "video_id": video_id}), 500

    except Exception as e:
        # Error pada level Flask/request
        return jsonify({"status": "fail", "error": f"Bad Request or General Error: {str(e)}"}), 400


# ENDPOINT 1: /cut-video (Dipanggil oleh n8n)
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
        unique_id = int(time.time())
        output_filename = f"clip-{unique_id}.mp4"
        output_path = os.path.join(TEMP_DIR, output_filename)

        # 1. Mengunduh Stream URL dari YouTube
        get_stream_url_command = [
            "yt-dlp", youtube_url, "-f", "best[ext=mp4]", 
            "--get-url", "--no-warnings"
        ]

        stream_url = subprocess.check_output(get_stream_url_command, text=True).strip()

        # 2. Memotong Video dengan FFmpeg Langsung dari Stream
        cut_command = [
            "ffmpeg", 
            "-ss", start_time,          # Waktu Mulai
            "-i", stream_url,           # Input dari URL Stream
            "-t", str(duration),        # Durasi Klip
            "-c:v", "copy",             # Copy video codec (cepat)
            "-c:a", "aac",              # Convert audio
            "-b:a", "128k",
            output_path                 # Path Penyimpanan
        ]

        subprocess.run(cut_command, check=True)

        # Mendapatkan URL Publik Worker dari Zeabur
        zeabur_url = os.environ.get("ZEABUR_URL", request.host)
        clip_public_url = f"https://{zeabur_url}/clips/{output_filename}"

        return jsonify({
            "status": "success",
            "file_name": output_filename,
            "clip_url_public": clip_public_url 
        })

    except subprocess.CalledProcessError as e:
        return jsonify({"error": "FFmpeg/yt-dlp failed", "details": str(e)}), 500
    except Exception as e:
        return jsonify({"error": "Internal server error", "details": str(e)}), 500

# ENDPOINT 2: /cleanup-clip (Dipanggil n8n setelah upload)
@app.route('/cleanup-clip', methods=['POST'])
def cleanup_clip():
    data = request.json
    file_name = data.get('file_name')

    if not file_name:
        return jsonify({"error": "File name missing"}), 400

    file_path = os.path.join(TEMP_DIR, file_name)

    if os.path.exists(file_path):
        os.remove(file_path)
        return jsonify({"status": "success", "message": f"File {file_name} deleted."})
    else:
        return jsonify({"status": "warning", "message": f"File {file_name} not found."})

# ENDPOINT 3: /clips/<filename> (Dipanggil TikTok)
@app.route('/clips/<filename>')
def serve_clip(filename):
    file_path = os.path.join(TEMP_DIR, filename)
    if os.path.exists(file_path):
        return send_file(file_path, mimetype='video/mp4')
    else:
        return jsonify({"error": "File not found"}), 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
