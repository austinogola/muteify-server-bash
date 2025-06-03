
from flask import Flask, request, jsonify, send_file
import os
import redis
import base64
import threading
from io import BytesIO
import requests
from pydub import AudioSegment
from cachetools import LRUCache
import shutil
from spleeter.separator import Separator
from werkzeug.utils import secure_filename
import time
from dotenv import load_dotenv
from flask_cors import CORS
from flask_pymongo import PyMongo
from flask_bcrypt import Bcrypt
import jwt
import wget
from supabase_utils import (upload_audio_to_supabase,check_file_exists_in_bucket,download_file_from_bucket)
from functools import wraps
import datetime
import glob
import numpy as np
from pydub.utils import mediainfo
from downloaders import (major_downloader)
from b2_helper import upload_to_b2,file_exists_in_b2,download_from_b2
import numpy as np
import tempfile
from scipy.io.wavfile import write as write_wav
import ffmpeg

app = Flask(__name__)
CORS(app)
load_dotenv()

DOWNLOAD_BUCKET_NAME = os.getenv("DOWNLOAD_BUCKET_NAME")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key")

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
DOWNLOAD_DIR = 'downloads'

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.config["MONGO_URI"] = os.getenv("MONGO_DB_URL")
mongo = PyMongo(app)
bcrypt = Bcrypt(app)


redis_client = redis.Redis(decode_responses=False)

separator = Separator('spleeter:2stems')



def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({"error": "Token is missing"}), 403

        try:
            token = token.split(" ")[1] if " " in token else token  # Handle "Bearer <token>"
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            current_user = data["email"]
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 403
        except Exception as e:
            print(e)
            return jsonify({"error": "Invalid token"}), 403

        return f(current_user, *args, **kwargs)
    return decorated


def download_audio(video_id):
    result =  major_downloader(video_id)
    return result

@app.route('/download', methods=['POST'])
def download_endpoint():
    data = request.get_json()
    video_ids = data.get("video_ids")

    if not video_ids or not isinstance(video_ids, list):
        return jsonify({"error": "Missing or invalid video_ids"}), 400

    results = []

    for video_id in video_ids:
        try:
            result = major_downloader(video_id)
            results.append({
                "video_id": video_id,
                "status": "success" if 'file_path' in result else "failed",
                "detail": result
            })
        except Exception as e:
            results.append({
                "video_id": video_id,
                "status": "error",
                "detail": str(e)
            })

    return jsonify(results), 200



def separate_full_vocals(mp3_input) -> bytes:
    """Run full Spleeter separation and return vocal stem as wav bytes."""
    
    # Save input (bytes or path) to a temp file
    if isinstance(mp3_input, bytes):
        temp_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_mp3.write(mp3_input)
        temp_mp3.close()
        mp3_path = temp_mp3.name
    else:
        mp3_path = mp3_input

    # Run Spleeter to separate vocals
    waveform_dict = separator.separate_to_audio_adapter().load(mp3_path, sample_rate=44100)
    prediction = separator.separate(waveform_dict)

    vocals = prediction['vocals']
    
    # Convert vocals to WAV in memory
    temp_wav = BytesIO()
    write_wav(temp_wav, 44100, vocals)
    temp_wav.seek(0)

    # Clean up temp file if created
    if isinstance(mp3_input, bytes):
        os.unlink(mp3_path)

    return temp_wav.read()




def separate_segment(mp3_input, start: float, end: float) -> bytes:
    """Extract segment from MP3, run Spleeter on it, return vocal stem bytes."""
    
    # Save input to temp if needed
    if isinstance(mp3_input, bytes):
        input_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        input_file.write(mp3_input)
        input_file.close()
        mp3_path = input_file.name
    else:
        mp3_path = mp3_input

    # Output temp segment file
    segment_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name

    try:
        # Extract audio segment using ffmpeg
        ffmpeg.input(mp3_path, ss=start, to=end).output(segment_path).run(quiet=True, overwrite_output=True)
        return separate_full_vocals(segment_path)
    finally:
        # Clean up
        if os.path.exists(segment_path):
            os.remove(segment_path)
        if isinstance(mp3_input, bytes) and os.path.exists(mp3_path):
            os.remove(mp3_path)



@app.route('/separate', methods=['POST'])
def separate_endpoint():
    data = request.get_json()
    video_id = data.get("video_id")
    s_start = data.get("start")
    s_end = data.get("end")

    if not video_id:
        return jsonify({"error": "Missing video_id"}), 400

    # Check if processed vocals already exist in Redis
    vocals_key = f"vocals:{video_id}"
    if redis_client.exists(vocals_key):
        print("Returning cached full vocals.")
        return send_file(BytesIO(redis_client.get(vocals_key)), mimetype='audio/wav', as_attachment=True, download_name=f"{video_id}_vocals.wav")

    # Ensure raw mp3 is available
    file_name = f"{video_id}.mp3"
    file_path = os.path.join(DOWNLOAD_DIR, file_name)

    if not os.path.exists(file_path):
        print("Not found locally. Downloading...")
        result = major_downloader(video_id)
        if "file_path" not in result:
            return jsonify({"error": "Download failed", "detail": result}), 500
        file_path = result['file_path']

    # Read and cache raw MP3 into Redis memory if not already cached
    raw_key = f"raw:{video_id}"
    if not redis_client.exists(raw_key):
        with open(file_path, "rb") as f:
            redis_client.set(raw_key, f.read())
        print("Raw MP3 stored in Redis.")

    def background_full_processing(video_id, file_path):
        print("Background: Full vocal processing starting...")
        try:
            vocal_bytes = separate_full_vocals(file_path)
            redis_client.set(f"vocals:{video_id}", vocal_bytes)
            print("Background: Full vocal processing complete.")
        except Exception as e:
            print(f"Background processing failed for {video_id}: {e}")

    # Start background full processing thread
    threading.Thread(target=background_full_processing, args=(video_id, file_path)).start()

    if s_start is not None and s_end is not None:
        try:
            clip_bytes = separate_segment(file_path, s_start, s_end)
            print(f"Returning segment [{s_start}-{s_end}]")
            return send_file(BytesIO(clip_bytes), mimetype='audio/wav', as_attachment=True, download_name=f"{video_id}_segment.wav")
        except Exception as e:
            return jsonify({"error": "Segment processing failed", "detail": str(e)}), 500
    else:
        # If no segment requested, wait until full processing is done (could improve with polling later)
        print("No segment given, processing full audio and returning...")
        vocal_bytes = separate_full_vocals(file_path)
        redis_client.set(vocals_key, vocal_bytes)
        return send_file(BytesIO(vocal_bytes), mimetype='audio/wav', as_attachment=True, download_name=f"{video_id}_vocals.wav")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

