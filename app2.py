
from flask import Flask, request, jsonify, send_file
import os
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
import threading
import datetime
import glob
import numpy as np
from pydub.utils import mediainfo
from b2_helper import upload_to_b2,file_exists_in_b2,download_from_b2

app = Flask(__name__)
CORS(app)
load_dotenv()


raw_audio_cache = LRUCache(maxsize=32)

#separator = Separator('spleeter:2stems','multiprocess:True')
separator = Separator('spleeter:2stems', multiprocess=False)

dummy_waveform = np.zeros((220500, 2), dtype=np.float32)
separator.separate(dummy_waveform)
print("SEPARATOR",separator)
# UPLOAD_FOLDER = 'uploads'
# OUTPUT_FOLDER = 'separated'



# os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# os.makedirs(OUTPUT_FOLDER, exist_ok=True)



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

        audio_info = major_downloader(video_id)
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


DOWNLOAD_BUCKET_NAME = os.getenv("DOWNLOAD_BUCKET_NAME")
@app.route("/download/<video_url>", methods=["GET"])
def downloadVid(video_url):
    # data = request.json
    videoUrl = video_url
    
    if "youtube.com" in videoUrl or "youtu.be" in videoUrl:
        video_id = videoUrl.split("v=")[-1] if "v=" in videoUrl else videoUrl.split("/")[-1]
        major_downloader(video_id)
    else:
        return jsonify({"error": "Invalid YouTube URL or ID"}), 400

    return jsonify({"error":False})






def update_account_usage(current_user,videoUrl,start,end):
    users = mongo.db.users
    accounts = mongo.db.accounts
    
    user = users.find_one({"email": current_user})
    account = accounts.find_one({"userId": str(user["_id"])})
    
    usage_records = account.get("usage", [])
    
    requested_duration_seconds = (end - start) / 1000.0
    requested_duration_minutes = requested_duration_seconds / 60.0
    
    today_date = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    
    new_usage = {
        "date": today_date,
        "videoUrl":videoUrl,
        "minutes": requested_duration_minutes,  # example field
    }
    
    accounts.update_one(
        {"userId": str(user["_id"])},
        {"$push": {"usage": new_usage}}
    )
    
    return 'Usage updated'
    
    
def get_cached_audio(video_id, mp3_path):
    if video_id in raw_audio_cache:
        print(f"Using cached audio for {video_id}")
        return raw_audio_cache[video_id]
    else:
        print(f"Caching new audio for {video_id}")
        audio = AudioSegment.from_file(mp3_path)
        raw_audio_cache[video_id] = audio
        return audio
    
@app.route("/separate/partial/YT", methods=["POST"])
@token_required
def partialSeparateYoutubeAudio(current_user):
  
    data = request.json
    videoUrl = data.get("videoUrl")
    start=data.get("start","0")
    end=data.get("end","10000")


    if "youtube.com" in videoUrl or "youtu.be" in videoUrl:
        video_id = videoUrl.split("v=")[-1] if "v=" in videoUrl else videoUrl.split("/")[-1]
    else:
        return jsonify({"error": "Invalid YouTube URL or ID"}), 400


    start_time = time.time()
    
    mp3_name = f"{video_id}.mp3" 
    mp3_path = os.path.join(DOWNLOAD_DIR, mp3_name)
    
    
    vocal_clip_name = f"{video_id}_{start/1000}_{end/1000}.mp3"
    vocal_clip_path = os.path.join(OUTPUT_DIR, vocal_clip_name)
    
    #boolean file exists in global cache
    vocal_file_exists_in_storage = file_exists_in_b2(vocal_clip_name,DOWNLOAD_BUCKET_NAME)
    mp3_file_exists_storage = file_exists_in_b2(mp3_name,DOWNLOAD_BUCKET_NAME)
    
    #if file exists locally
    if(os.path.exists(vocal_clip_path)):
        print("voice exists locally, sending file")
        response = send_file(vocal_clip_path, mimetype="audio/mpeg", as_attachment=True, download_name=vocal_clip_name)  
    else:
        print("voice clip doesn't exist LOCALLY, checking global cache")
        if vocal_file_exists_in_storage and False:
            print('voice clip exists in global cache, downloading')
            download_result = download_from_b2(vocal_clip_name, DOWNLOAD_BUCKET_NAME, vocal_clip_path,start_time)
            response = send_file(vocal_clip_path, mimetype="audio/mpeg", as_attachment=True, download_name=vocal_clip_name)
        else:
            print("voice clip doesn't exist in GLOBAL cache too, processing") 
            
            if not os.path.exists(mp3_path):
                print('YT MP3 DOES NOT EXIST LOCALLY')
                
                if(mp3_file_exists_storage and False):
                    print('YT MP3 EXISTS IN GLOBAL, PULLING')
                    download_result = download_from_b2(mp3_name, DOWNLOAD_BUCKET_NAME, mp3_path,start_time)
                else:
                    print('YT MP3 DOES NOT EXIST IN GLOBAL EITHER, DOWNLOADING')
                    mp3_audio_info = major_downloader(video_id)
                    if (mp3_audio_info.get('file_path') is None) or not  os.path.exists(mp3_audio_info.get('file_path')):
                        print("MP3 FILE STILL NOT DOWNLOADED, RETURNING ERROR")
                        return jsonify({"error": "MP3 download failed"}), 500

            # mp3_clip_name = f"{video_id}_{start/1000}_{end/1000}."
            print('Starting trim of raw audio')
            input_path_trimmed = os.path.join(UPLOAD_DIR, vocal_clip_name)
            
            # audio = AudioSegment.from_file(mp3_path)
            audio = get_cached_audio(video_id, mp3_path)
            audio_segment = audio[start:end]  
        
            audio_segment.export(input_path_trimmed, format="mp3")
     
            
            output_path = os.path.join(OUTPUT_DIR, f"{video_id}_{start/1000}_{end/1000}")

            # Separate trimmed audio
            print('SEPARATING STARTING')
            separator.separate_to_file(input_path_trimmed, OUTPUT_DIR,codec="mp3", bitrate="128k")
    
            vocal_path = os.path.join(output_path, "vocals.mp3")
            new_vocal_path = vocal_clip_path
            if not os.path.exists(vocal_path):
                print('PATH DOES NOT EXIST')
                return jsonify({"error": "Vocal separation failed"}), 500
        
            os.rename(vocal_path, new_vocal_path)

            response = send_file(new_vocal_path, mimetype="audio/mpeg", as_attachment=True, download_name=vocal_clip_name)
            
    update_account_usage(current_user,videoUrl,start,end)
    if(not vocal_file_exists_in_storage):
        thread = threading.Thread(target=upload_to_b2, args=( vocal_clip_path,vocal_clip_name, os.getenv("DOWNLOAD_BUCKET_NAME")))
        thread.start()
    return response

@app.route('/get_duration/<video_id>', methods=['GET'])
def get_audio_duration(video_id):
    try:
        # Look for a matching audio file with common extensions
        #file_name =f"{url}.mp3"
        #file_path = os.path.join(DOWNLOAD_DIR, file_name)
        
        mp3_name = f"{video_id}.mp3" 
        mp3_path = os.path.join(DOWNLOAD_DIR, mp3_name)
        
        # audio_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3"))
        # if not audio_files:
        #     return jsonify({"error": "File not found"}), 404

        # audio_file = audio_files[0]

        # Get duration using pydub/mediainfo (uses ffprobe)
        # info = mediainfo(audio_file)
        # duration = float(info['duration'])
        duration= 120

        return jsonify({
            "video_id": video_id,
            "duration_seconds": duration
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
