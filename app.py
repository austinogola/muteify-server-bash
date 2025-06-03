
from flask import Flask, request, jsonify, send_file, make_response
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
from spleeter.audio.adapter import AudioAdapter
from werkzeug.utils import secure_filename
import time
from dotenv import load_dotenv
from flask_cors import CORS
from flask_pymongo import PyMongo
from flask_bcrypt import Bcrypt
import jwt
import wget
from storage_utils import upload_to_b2, upload_bytes_to_b2, download_b2_to_local,file_exists_in_b2
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
import multiprocessing


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

cpu_threads = multiprocessing.cpu_count()

print('threads count',cpu_threads)

# threads=cpu_threads

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



# def separate_full_vocals(mp3_input) -> bytes:
#     """Run full Spleeter separation and return vocal stem as wav bytes."""
    
#     # Save input (bytes or path) to a temp file
#     if isinstance(mp3_input, bytes):
#         temp_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
#         temp_mp3.write(mp3_input)
#         temp_mp3.close()
#         mp3_path = temp_mp3.name
#     else:
#         mp3_path = mp3_input

#     # Run Spleeter to separate vocals
#     audio_loader = AudioAdapter.default()
#     waveform, _ = audio_loader.load(mp3_path, sample_rate=44100)
    # with separator_lock:
    #     prediction = separator.separate(waveform)
#     # prediction = separator.separate(waveform)

#     vocals = prediction['vocals']
    
#     # Convert vocals to WAV in memory
#     temp_wav = BytesIO()
#     write_wav(temp_wav, 44100, vocals)
#     temp_wav.seek(0)

#     # Clean up temp file if created
#     if isinstance(mp3_input, bytes):
#         os.unlink(mp3_path)

#     return temp_wav.read()
separator_lock = threading.Lock()

def separate_full_vocals(mp3_input) -> bytes:
    """Run full Spleeter separation and return vocal stem as MP3 bytes."""
    # Save input (bytes or path) to a temp file
    if isinstance(mp3_input, bytes):
        temp_mp3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_mp3.write(mp3_input)
        temp_mp3.close()
        mp3_path = temp_mp3.name
    else:
        mp3_path = mp3_input

    # Run Spleeter
    audio_loader = AudioAdapter.default()
    waveform, _ = audio_loader.load(mp3_path, sample_rate=44100)
    with separator_lock:
        prediction = separator.separate(waveform)
        
    vocals = prediction['vocals']

    # Convert vocals to WAV
    temp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    write_wav(temp_wav.name, 44100, vocals)

    # Convert to MP3 using ffmpeg
    temp_mp3_out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    # ffmpeg.input(temp_wav.name).output(temp_mp3_out.name, audio_bitrate='128k').run(quiet=True, overwrite_output=True)
    ffmpeg.input(temp_wav.name).output(
        temp_mp3_out.name,
        audio_bitrate='128k',
        threads=0 
    ).run(quiet=True, overwrite_output=True)

    # Read MP3 bytes
    with open(temp_mp3_out.name, "rb") as f:
        vocal_mp3_bytes = f.read()

    # Cleanup
    os.remove(temp_wav.name)
    os.remove(temp_mp3_out.name)
    if isinstance(mp3_input, bytes):
        os.unlink(mp3_path)

    return vocal_mp3_bytes



separator_lock = threading.Lock()

def extract_segment_from_mp3(mp3_bytes: bytes, start: float, end: float) -> bytes:
    """Extract segment from full MP3 (bytes) using ffmpeg, return MP3 bytes."""
    input_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    input_temp.write(mp3_bytes)
    input_temp.close()

    segment_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    # ffmpeg.input(input_temp.name, ss=start, to=end).output(segment_temp.name, audio_bitrate='128k').run(quiet=True, overwrite_output=True)
    ffmpeg.input(input_temp.name, ss=start, to=end).output(
        segment_temp.name,
        audio_bitrate='128k',
        threads=0  # Or use threads=0
    ).run(quiet=True, overwrite_output=True)

    with open(segment_temp.name, "rb") as f:
        segment_mp3_bytes = f.read()

    os.remove(input_temp.name)
    os.remove(segment_temp.name)

    return segment_mp3_bytes


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

    vocals_key = f"vocals:{video_id}"
    raw_key = f"raw:{video_id}"
    file_name = f"{video_id}.mp3"
    file_path = os.path.join(DOWNLOAD_DIR, file_name)

    # if not os.path.exists(file_path):
    #     result = major_downloader(video_id)
    #     if "file_path" not in result:
    #         return jsonify({"error": "Download failed", "detail": result}), 500
    #     file_path = result['file_path']
        
        
    if not os.path.exists(file_path) or os.path.getsize(file_path) < 1_000:
        print("Raw vocal not in local files, Checking B2 for existing MP3...")
        if not download_b2_to_local(f"raw_mp3/{video_id}.mp3", file_path):
            print("Not found in B2. Downloading...")
            result = major_downloader(video_id)
            if "file_path" not in result:
                return jsonify({"error": "Download failed", "detail": result}), 500
            file_path = result['file_path']
            threading.Thread(target=upload_to_b2, args=(file_path, f"raw_mp3/{video_id}.mp3")).start()
            
        else:
            print("Ws found and Downloaded raw MP3 from B2.")
            if not os.path.exists(file_path) or os.path.getsize(file_path) < 1_000:
                print("Still not downloaded form b2 . Using api")
                result = major_downloader(video_id)
                if "file_path" not in result:
                    return jsonify({"error": "Download failed", "detail": result}), 500

    # Store raw MP3 to Redis if not cached
    if not redis_client.exists(raw_key):
        with open(file_path, "rb") as f:
            # redis_client.set(raw_key, f.read())
            redis_client.setex(raw_key, 3600, f.read())

    def background_full_processing(video_id, file_path):
        try:
            vocal_mp3_bytes = separate_full_vocals(file_path)
            # redis_client.set(f"vocals:{video_id}", vocal_mp3_bytes)
            redis_client.setex(f"vocals:{video_id}", 3600, vocal_mp3_bytes)
            upload_bytes_to_b2(vocal_mp3_bytes, f"vocals/{video_id}.mp3")
        except Exception as e:
            print(f"Background processing failed: {e}")

    # Start background processing
    if not redis_client.exists(vocals_key):
        local_vocal_path = f"/tmp/{video_id}_vocals.mp3"
        if os.path.exists(local_vocal_path):
            redis_client.setex(vocals_key, 3600, open(local_vocal_path, "rb").read())
        elif download_b2_to_local(f"vocals/{video_id}.mp3", local_vocal_path):
            redis_client.setex(vocals_key, 3600, open(local_vocal_path, "rb").read())
        else:
            threading.Thread(target=background_full_processing, args=(video_id, file_path)).start()

    if s_start is not None and s_end is not None:
        # Extract segment from full vocal MP3 (cached or fallback)
        if redis_client.exists(vocals_key):
            full_vocals_mp3 = redis_client.get(vocals_key)
            redis_client.expire(vocals_key, 3600)
            try:
                segment_mp3 = extract_segment_from_mp3(full_vocals_mp3, s_start, s_end)
                response = make_response(send_file(BytesIO(segment_mp3), mimetype='audio/mpeg', as_attachment=True, download_name=f"{video_id}_segment.mp3"))
                response.headers['FILE-READY'] = redis_client.exists(vocals_key)
                return response
            except Exception as e:
                return jsonify({"error": "Segment processing failed", "detail": str(e)}), 500
        else:
            # fallback: process segment directly (rarely reached)
            try:
                vocal_mp3 = separate_full_vocals(file_path)
                # redis_client.set(vocals_key, vocal_mp3)
                redis_client.setex(vocals_key, 3600, vocal_mp3)
                segment_mp3 = extract_segment_from_mp3(vocal_mp3, s_start, s_end)
                response = make_response(send_file(BytesIO(segment_mp3), mimetype='audio/mpeg', as_attachment=True, download_name=f"{video_id}_segment.mp3"))
                response.headers['FILE-READY'] = redis_client.exists(vocals_key)
                return response
            except Exception as e:
                return jsonify({"error": "Segment processing failed", "detail": str(e)}), 500
    else:
        # Full vocal requested
        if redis_client.exists(vocals_key):
            response = make_response(send_file(BytesIO(redis_client.get(vocals_key)), mimetype='audio/mpeg', as_attachment=True, download_name=f"{video_id}_vocals.mp3"))
            response.headers['FILE-READY'] = redis_client.exists(vocals_key)
            return response
        else:
            vocal_mp3 = separate_full_vocals(file_path)
            # redis_client.set(vocals_key, vocal_mp3)
            redis_client.setex(vocals_key, 3600, vocal_mp3)
            response = make_response(send_file(BytesIO(vocal_mp3), mimetype='audio/mpeg', as_attachment=True, download_name=f"{video_id}_vocals.mp3"))
            response.headers['FILE-READY'] = redis_client.exists(vocals_key)
            return response




if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

