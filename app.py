from flask import Flask, request, jsonify, send_file
import os
import requests
from pydub import AudioSegment
import shutil
from spleeter.separator import Separator
from werkzeug.utils import secure_filename
#import time
from dotenv import load_dotenv
from flask_cors import CORS
from flask_pymongo import PyMongo
from flask_bcrypt import Bcrypt
import jwt
import wget


app = Flask(__name__)
CORS(app)
load_dotenv()

#separator = Separator('spleeter:2stems','multiprocess:True')
separator = Separator('spleeter:2stems', multiprocess=False)

print("SEPARATOR",separator)
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'separated'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)



RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST")
DOWNLOAD_RAPIDAPI_HOST=os.getenv("DOWNLOAD_RAPIDAPI_HOST")
MP3_DOWNLOADER_HOST=os.getenv("MP3_DOWNLOADER_HOST")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_PUBLIC_KEY = os.getenv("SUPABASE_PUBLIC_KEY")
BUCKET_NAME = "mutify-vocals-audios"


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

def download_mp3_from_youtube(url,max_retries=3):
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
    
    filename = f"{video_id}_{start}_{end}.mp3"
    #file_exists_in_storage = check_file_exists_in_bucket(filename=filename,bucket_folder=VOCALS_FOLDER)
    file_exists_in_storage = False
    print('file_exists_in_storage',file_exists_in_storage)
    
    if(file_exists_in_storage):
        print('VOCAL FILE EXISTS in STORAGE',filename)
        file_data = download_file_from_bucket(VOCALS_FOLDER, filename)
        if file_data is None:
            print('FILE DATA IS INVALID')
            #return abort(404, description="File not found or download failed")
        else:  
   
           usage_entry = {
            "date": today_date,
            "minutes": requested_duration_minutes
           }
           accounts.update_one(
            {"userId": str(user["_id"])},
            {"$push": {"usage": usage_entry}}
           )      
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

        audio_info = download_mp3_from_youtube(video_id)
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
    new_vocal_path = os.path.join(output_path, filename)
    if not os.path.exists(vocal_path):
        return jsonify({"error": "Vocal separation failed"}), 500
        
    os.rename(vocal_path, new_vocal_path)

    response = send_file(new_vocal_path, mimetype="audio/mpeg", as_attachment=True, download_name=filename)

    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
