
from flask import Flask, request, jsonify, send_file
import os
from io import BytesIO
import requests
from pydub import AudioSegment
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
import threading
import datetime
import glob
import numpy as np
from pydub.utils import mediainfo
from downloaders import (donwloader_one)
app = Flask(__name__)
CORS(app)
load_dotenv()

#separator = Separator('spleeter:2stems','multiprocess:True')
separator = Separator('spleeter:2stems', multiprocess=False)

# dummy_waveform = np.zeros((220500, 2), dtype=np.float32)
# separator.separate(dummy_waveform)
print("SEPARATOR",separator)
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'separated'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)



RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST")
DOWNLOAD_RAPIDAPI_HOST=os.getenv("DOWNLOAD_RAPIDAPI_HOST")
MP3_DOWNLOADER_HOST=os.getenv("MP3_DOWNLOADER_HOST")
NEW_DOWN = os.getenv("NEW_DOWN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_PUBLIC_KEY = os.getenv("SUPABASE_PUBLIC_KEY")
BUCKET_NAME = "mutify-vocals-audios"

MP3_DOWN = os.getenv("MP3_DOWN")
app.config["MONGO_URI"] = os.getenv("MONGO_DB_URL")
mongo = PyMongo(app)
bcrypt = Bcrypt(app)
SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key")

AUDIO_FOLDER = 'youtube-mp3-downloads'
VOCALS_FOLDER = 'audio-vocals'

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
DOWNLOAD_DIR = 'downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)



@app.route('/download', methods=['POST'])
def download():
    data = request.json
    videoUrl = data.get("videoUrl")

    

    if "youtube.com" in videoUrl or "youtu.be" in videoUrl:
        video_id = videoUrl.split("v=")[-1] if "v=" in videoUrl else videoUrl.split("/")[-1]
    else:
        return jsonify({"error": "Invalid YouTube URL or ID"}), 400
    
    
    mp3_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
        
    if os.path.exists(mp3_path):
        print('YT MP3 ALREADY EXISTS')
        mp3_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
    else:
        print('YT MP3 DOES NOT ALREADY EXISTS, DOWNLOADING MP3')
        #audio_info = download_mp3(video_id)

        audio_info = donwloader_one(video_id)
        if (not audio_info["file_path"])or not  os.path.exists(audio_info["file_path"]):
                print("download path doesn't exists")
                return jsonify({"error": "MP3 download failed"}), 500

        mp3_path = audio_info["file_path"]
        
        
    return jsonify({"message":'downloaded'}),200

@app.route('/separate', methods=['POST'])
def separate():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    filename = secure_filename(file.filename)
    base_name = os.path.splitext(filename)[0]
    input_path = os.path.join(UPLOAD_FOLDER, filename)
    output_dir = os.path.join(OUTPUT_FOLDER, base_name)
    vocals_path = os.path.join(output_dir, 'vocals.mp3')
    start = time.time()
    # Save the uploaded file
    file.save(input_path)

    try:
        # Separate
        separator.separate_to_file(input_path, OUTPUT_FOLDER,codec="mp3", bitrate="128k")
        os.remove(input_path)
        end = time.time()

        print('FINISHED IN ',end-start)

        if not os.path.exists(vocals_path):
            return jsonify({'error': 'Vocals file not found after separation'}), 500

        # Return the vocals audio file
        return send_file(vocals_path, mimetype='audio/mpeg', as_attachment=True)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route("/separate/partial/YT", methods=["POST"])
def partialSeparateYoutubeAudio():

    # Get plan and usage
  
    data = request.json
    videoUrl = data.get("videoUrl")
    start=data.get("start","0")
    end=data.get("end","10000")


    if "youtube.com" in videoUrl or "youtu.be" in videoUrl:
        video_id = videoUrl.split("v=")[-1] if "v=" in videoUrl else videoUrl.split("/")[-1]
    else:
        return jsonify({"error": "Invalid YouTube URL or ID"}), 400

    original_mp3_name = f"{video_id}.mp3" 
    #mp3_file_exists = check_file_exists_in_bucket(filename=original_mp3_name)
    filename = f"{video_id}_{start}_{end}.mp3"
    file_exists_in_storage = check_file_exists_in_bucket(filename=filename,bucket_folder=VOCALS_FOLDER)
    #file_exists_in_storage = False
    print('file_exists_in_storage',file_exists_in_storage)
    
    if(file_exists_in_storage):
        print('VOCAL FILE EXISTS in STORAGE',filename)
        file_data = download_file_from_bucket(VOCALS_FOLDER, filename)
        if file_data is None:
            print('FILE DATA IS INVALID')
            #return abort(404, description="File not found or download failed")
        else:  
    
           return send_file(
            BytesIO(file_data),
            mimetype='audio/mpeg',
            as_attachment=True,
            download_name=filename
           )
    print('VOCAL FILE DOES NOT EXISTS',filename)

    mp3_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
        
    if os.path.exists(mp3_path):
        print('YT MP3 ALREADY EXISTS')
        mp3_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
    else:
        print('YT MP3 DOES NOT ALREADY EXISTS, DOWNLOADING MP3')
        #audio_info = download_mp3(video_id)

        audio_info = donwloader_one(video_id)
        if (not audio_info["file_path"])or not  os.path.exists(audio_info["file_path"]):
                print("download path doesn't exists")
                return jsonify({"error": "MP3 download failed"}), 500

        mp3_path = audio_info["file_path"]

    input_path_trimmed = os.path.join(UPLOAD_DIR, filename)
    output_path = os.path.join(OUTPUT_DIR, f"{video_id}_{start}_{end}")

        # Trim using pydub
    print('Starting trim')
    audio = AudioSegment.from_file(mp3_path)
    audio_segment = audio[start:end]  # 10 seconds in ms
        
    audio_segment.export(input_path_trimmed, format="mp3")
    # Separate trimmed audio
    print('SEPARATING startin')
    separator.separate_to_file(input_path_trimmed, OUTPUT_DIR,codec="mp3", bitrate="128k")
    vocal_path = os.path.join(output_path, "vocals.mp3")
    print(vocal_path)
    print("os.path.exists(vocal_path)",os.path.exists(vocal_path))
    new_vocal_path = os.path.join(output_path, filename)
    if not os.path.exists(vocal_path):
        print('PATH DOES NOT EXIST')
        return jsonify({"error": "Vocal separation failed"}), 500
        
    os.rename(vocal_path, new_vocal_path)

    response = send_file(new_vocal_path, mimetype="audio/mpeg", as_attachment=True, download_name=filename)
    return response

@app.route('/get_duration/<video_id>', methods=['GET'])
def get_audio_duration(video_id):
    try:
        # Look for a matching audio file with common extensions
        #file_name =f"{url}.mp3"
        #file_path = os.path.join(DOWNLOAD_DIR, file_name)
        audio_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3"))
        if not audio_files:
            return jsonify({"error": "File not found"}), 404

        audio_file = audio_files[0]

        # Get duration using pydub/mediainfo (uses ffprobe)
        info = mediainfo(audio_file)
        duration = float(info['duration'])

        return jsonify({
            "video_id": video_id,
            "duration_seconds": duration
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
