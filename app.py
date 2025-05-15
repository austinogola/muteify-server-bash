
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

dummy_waveform = np.zeros((220500, 2), dtype=np.float32)
separator.separate(dummy_waveform)
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


PLAN_LIMITS = {
    "Trial": 10,   # 10 minutes/day
    "Basic": 30,   # 30 minutes/day
    "Pro": 9999    # (unlimited for now)
}

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
DOWNLOAD_DIR = 'downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


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



def download_mp3_from_youtube(url,max_retries=3):
    # API endpoint to get the download link
    #api_url = f'https://{MP3_DOWNLOADER_HOST}/dl?id={url}'
    api_url = f'https://{MP3_DOWN}/download/mp3'
    print(api_url)
    headers = {
          'Content-Type': "application/json",
        'x-rapidapi-key': RAPIDAPI_KEY,  # Replace with your RapidAPI key
        'x-rapidapi-host':MP3_DOWN,  # Replace with your RapidAPI host
    }
    payload = {"url":f"https://www.youtube.com/watch?v={url}"}
    start_time = time.time()
    print(payload)
    attempt = 0
    result = None

    response = ''
    result = ''

    while attempt < max_retries:
        try:
            print(f'ATTEMPT {attempt}')
            response = requests.get(api_url, headers=headers,params=payload)
            #response.raise_for_status()
            result = response.json()
            print(result)
            download_link = result.get('downloadUrl')
            response.raise_for_status()
            if download_link:  # Valid link received
                break
            else:
                print(f"Attempt {attempt + 1}: No valid link returned, retrying...")
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt + 1} failed with error: {e}")
        attempt += 1

    if not result or not result.get('downloadUrl'):
        print("Failed to get a valid MP3 link after retries.")
        return None, None


    try:
        # Make the request to get the MP3 link
        #response = requests.get(api_url, headers=headers)
        #response.raise_for_status()  # Check for errors in the response
        #result = response.json()  # Parse JSON response
        #print(result)
        # Extract download link
        download_link = result.get('downloadUrl')


        #file_name = result.get('title', 'downloaded_song') + '.mp3'
        file_name =f"{url}.mp3"
        file_path = os.path.join(DOWNLOAD_DIR, file_name)

        # Send a request to download the MP3 file
        mp3_response = requests.get(download_link, stream=True)
        #mp3_response.raise_for_status()  # Ensure the download was successful
        #print("Response status:", mp3_response.status_code)
        #print("Response headers:", mp3_response.headers)
        #print("Response content (first 300 chars):", mp3_response.text[:300])
        #mp3_response.raise_for_status()  # Ensure the download was successful
        mp3_response.raise_for_status()  # Ensure the download was successful
        # Determine the file path and write the content to a file
        #file_name = result.get('title', 'downloaded_song') + '.mp3'
        with open(file_path, 'wb') as file:
            for chunk in mp3_response.iter_content(chunk_size=1048576):
                if chunk:
                    file.write(chunk)

        # Calculate the time it took to download
        download_time = time.time() - start_time

        # Return the file path and download time
        #return file_name, download_time
        print(file_path)
        return ({
            'file_path': file_path,
            'download_time_seconds': download_time
        })

    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None, None



def download_mp3_from_youtube2(url,max_retries=3):
    # API endpoint to get the download link
    api_url = f'https://{MP3_DOWNLOADER_HOST}/dl?id={url}'
    print(api_url)
    headers = {
        'x-rapidapi-key': RAPIDAPI_KEY,  # Replace with your RapidAPI key
        'x-rapidapi-host':MP3_DOWNLOADER_HOST,  # Replace with your RapidAPI host
    }
    start_time = time.time()

    attempt = 0
    result = None
   
    response = ''
    result = ''

    while attempt < max_retries:
        try:
            print(f'ATTEMPT {attempt}')
            response = requests.get(api_url, headers=headers)
            response.raise_for_status()
            result = response.json()

            download_link = result.get('link')
            if download_link:  # Valid link received
                break
            else:
                print(f"Attempt {attempt + 1}: No valid link returned, retrying...")
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt + 1} failed with error: {e}")
        attempt += 1

    if not result or not result.get('link'):
        print("Failed to get a valid MP3 link after retries.")
        return None, None

    try:
        # Make the request to get the MP3 link
        #response = requests.get(api_url, headers=headers)
        #response.raise_for_status()  # Check for errors in the response
        #result = response.json()  # Parse JSON response
        print(result)
        # Extract download link
        download_link = result.get('link')
        download_link = download_link.replace('&uT=R&uN=bWhpc2hhbTM5NzM%3D', '')  

        #file_name = result.get('title', 'downloaded_song') + '.mp3'
        file_name =f"{url}.mp3"
        file_path = os.path.join(DOWNLOAD_DIR, file_name)
        print(f'Trying to get {download_link}')
        # Send a request to download the MP3 file
       
        mp3_headers = {
        'User-Agent': (
         'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
         'AppleWebKit/537.36 (KHTML, like Gecko) '
         'Chrome/122.0.0.0 Safari/537.36'
         ),
        'Referer': 'https://example.com/',  # Sometimes needed
        'Accept': '*/*',
        'Connection': 'keep-alive'
        }
        payload = {}
        hdd = {}
        mp3_response = requests.get(download_link, stream=True,headers=mp3_headers,data=payload)
        print(mp3_response)
        mp3_response.raise_for_status()  # Ensure the download was successful


        # Determine the file path and write the content to a file
        #file_name = result.get('title', 'downloaded_song') + '.mp3'
        with open(file_path, 'wb') as file:
            for chunk in mp3_response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)
        
        # Calculate the time it took to download
        download_time = time.time() - start_time
        
        # Return the file path and download time
        #return file_name, download_time
        return ({
            'file_path': file_path,
            'download_time_seconds': download_time
        })
    
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        print(f"trying wget")
        try:
            # Using subprocess to run system wget command
            #subprocess.run(['wget', download_link, '-O', file_path], check=True)
            # Or, using the Python wget module instead:
            #import wget
            wget.download(download_link, out=file_path)
            download_time = time.time() - start_time
            return ({
                'file_path': file_path,
               'download_time_seconds': download_time
            })
        except Exception as wget_error:
            print(f"wget fallback also failed: {wget_error}")
            return None, Noneprint(f"Requests failed with error: {e}")
        print("Trying wget fallback...")
        #return None, None
    




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

    requested_duration_seconds = (end - start) / 1000.0
    requested_duration_minutes = requested_duration_seconds / 60.0

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

@app.route("/signup", methods=["POST"])
def signup():
    users = mongo.db.users
    accounts = mongo.db.accounts
    data = request.json
    email = data.get("email")
    password = data.get("password")

    if users.find_one({"email":email}):
        return jsonify({"error": "User with email  already exists"}), 409

    hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
    user_result = users.insert_one({"email": email, "password": hashed_pw,"plan":"Trial"})
    print(user_result)
    user_id = str(user_result.inserted_id)
    accounts.insert_one({
        "userId": user_id,
        "usage": [],
        "payments": [],
        "plan": "Trial"  # Default to "Trial" plan
    })
    token = jwt.encode({"email": email, "exp": datetime.datetime.utcnow() + datetime.timedelta(days=21)}, SECRET_KEY, algorithm="HS256")
    return jsonify({"message": "User created successfully","success":True,"error":False,"token":token}), 201

@app.route("/login", methods=["POST"])
def login():
    users = mongo.db.users
    data = request.json
    email = data.get("email")
    password = data.get("password")
    user = users.find_one({"email": email})

    if user:
        if bcrypt.check_password_hash(user["password"], password):
            token = jwt.encode({
                "email": email,
                "exp": datetime.datetime.utcnow() + datetime.timedelta(days=21)
            }, SECRET_KEY, algorithm="HS256")
            return jsonify({"token": token,"success":True,"error":False})
        else:
            return jsonify({"error": "Invalid credentials"}), 401
    else:
        return jsonify({"error": "No user with this email"}), 401

@app.route('/config', methods=['GET'])
@token_required
def get_user_config(current_user):
    users = mongo.db.users
    accounts = mongo.db.accounts

    # Fetch user and account
    user = users.find_one({"email": current_user})
    if not user:
        return jsonify({"error": "User not found"}), 404

    account = accounts.find_one({"userId": str(user["_id"])})
    if not account:
        return jsonify({"error": "Account not found"}), 404

    # Extract plan and usage
    plan = account.get("plan", "Trial")
    usage_records = account.get("usage", [])

    today_date = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    today_usage_minutes = sum(u["minutes"] for u in usage_records if u["date"] == today_date)

    allowed_minutes = PLAN_LIMITS.get(plan, 10)  # default to 10 if not found
    remaining_minutes = max(allowed_minutes - today_usage_minutes, 0)

    return jsonify({
        "email": user.get("email"),
        "plan": plan,
        "usage_today_minutes": round(today_usage_minutes, 2)
        }) 



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
