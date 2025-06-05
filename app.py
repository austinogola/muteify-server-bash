import os
import time
import tempfile
import threading
import multiprocessing
from flask import Flask, request, jsonify, send_file, make_response
from flask_cors import CORS
import redis
import ffmpeg
from io import BytesIO
from spleeter.separator import Separator
from spleeter.audio.adapter import AudioAdapter
from scipy.io.wavfile import write as write_wav
from downloaders import major_downloader
from functools import wraps
from cpu_sep import cpu_worker_loop,cpu_separator,cpu_separate_segment

from storage_utils import upload_to_b2, upload_bytes_to_b2, download_b2_to_local,file_exists_in_b2

from flask_pymongo import PyMongo
from flask_bcrypt import Bcrypt
import jwt
import datetime

DOWNLOAD_DIR = "downloads"
VOCALS_DIR = "vocals"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(VOCALS_DIR, exist_ok=True)


os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(VOCALS_DIR, exist_ok=True)

# Redis connection (multiprocessing-safe as long as separate connections are used in processes)
redis_client = redis.Redis(decode_responses=False)

app = Flask(__name__)
CORS(app,expose_headers=["FILE-READY"])

app.config["MONGO_URI"] = os.getenv("MONGO_DB_URL")
mongo = PyMongo(app)
bcrypt = Bcrypt(app)
SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key")


# Instantiate a global separator lock for threading in main process if needed
separator_lock = threading.Lock()

# Initialize Separator instances globally to share in workers
# GPU Separator: default, uses GPU if available
gpu_separator = Separator('spleeter:2stems')


ALL_PLANS = [
    {"name":'Basic-Trial',"minutes":60,"days":3,"test_prod_id":'prod_SIWSeodkjoYwtQ',"live_prod_id":'prod_SIvTcRCZbWzxMk'},
    {"name":'Premium-Trial',"minutes":60,"days":3,"test_prod_id":'prod_SIXfHdO7F14kgZ',"live_prod_id":'prod_SIvSsVTJBsFv1O'},
    {"name":'Basic',"minutes":45,"days":35,"test_prod_id":'prod_SIv7fc6J9GgW5Q',"live_prod_id":'prod_SIvOpOnPDR0pYn'},
    {"name":'Premium',"minutes":9999,"days":35,"test_prod_id":'prod_SIv58GHgV6gnWy',"live_prod_id":'prod_SIvQywR4mFMLzA'},
]


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({"error": "Token is missing"}), 403

        try:
            token = token.split(" ")[1] if " " in token else token
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            current_user = data["email"]
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 403
        except Exception as e:
            print(e)
            return jsonify({"error": "Invalid token"}), 403

        # ✅ Pass current_user into kwargs so other decorators can access it
        return f(*args, current_user=current_user, **kwargs)
    return decorated


def usage_check(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        current_user = kwargs.get("current_user")
        print(current_user)
        if not current_user:
            return jsonify({"error": "Unauthorized"}), 403
        try:
            json_body = request.get_json()
            start = json_body.get("start", 0)
            end = json_body.get("end", 30)

            users = mongo.db.users
            accounts = mongo.db.accounts

            user = users.find_one({"email": current_user})
            account = accounts.find_one({"userId": str(user["_id"])})

            usage_records = account.get("usage", [])
            today_date = datetime.datetime.utcnow().strftime('%Y-%m-%d')
            today_usage_minutes = sum(u["minutes"] for u in usage_records if u["date"] == today_date)

            plan = account.get("plan")
            the_plan_obj = [it for it in ALL_PLANS if it["name"] == plan][0]
            allowed_minutes = the_plan_obj['minutes']
            remaining_minutes = max(allowed_minutes - today_usage_minutes, 0)

            requested_duration_seconds = (end - start) / 1000.0
            requested_duration_minutes = requested_duration_seconds / 60.0

            if requested_duration_minutes > remaining_minutes:
                return jsonify({"error": "Usage limit exceeded"}), 402

            return f(*args, **kwargs)

        except Exception as e:
            print(e)
            return jsonify({"error": "Usage check failed"}), 400
    return decorated


@app.route("/update/usage", methods=["POST"])
@token_required
def update_account_usage(current_user):
    video_id = request.json.get("video_id")
    start = request.json.get("start",0)
    end = request.json.get("end",30)
    
    
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
        "video_id":video_id,
        "minutes": requested_duration_minutes,  # example field
    }
    
    accounts.update_one(
        {"userId": str(user["_id"])},
        {"$push": {"usage": new_usage}}
    )
    
    return jsonify({"status":'Usage updated'}),200

@app.route("/separate/status", methods=["POST"])
def check_separation_status():
    video_id = request.json.get("video_id")
    start = request.json.get("start",0)
    end = request.json.get("end",0)
    
    my_bytes = video_id.encode('utf-8')
    
    print(type(video_id))
    
    vocal_key = f"vocals-{my_bytes}-{start}|{end}"
    
    print("exists", vocal_key,redis_client.exists(vocal_key))
    if not video_id:
        return jsonify({"error": "Missing video_id"}), 400
    if redis_client.exists(vocal_key):
        return jsonify({"status": "section_separated", "video_id": video_id}), 200
    else:
       return jsonify({"status": "not_separated", "video_id": video_id}), 200 
   
   
@app.route("/separate", methods=["POST"])
@token_required
@usage_check
def start_separation(current_user,):
    video_id = request.json.get("video_id")
    start = request.json.get("start",0)
    end = request.json.get("end",9999)
    next_chunk =request.json.get("next_chunk",False)
    prioritize_separation = request.json.get("prioritize",False)
    
    # vocal_key = f"vocals-{video_id}-{start}|{end}"
    
    if not video_id:
        return jsonify({"error": "Missing video_id"}), 400
    
    vidd= video_id.encode('utf-8')
    print(type(video_id))
    vocal_key = f"vocals-{vidd}-{start}|{end}"
    print("exists", vocal_key,redis_client.exists(vocal_key))
    if redis_client.exists(vocal_key):
        vocal_mp3 = redis_client.get(vocal_key)
        response = make_response(send_file(BytesIO(vocal_mp3), mimetype='audio/mpeg', as_attachment=True, download_name=f"{video_id}_vocals.mp3"))
        if(next_chunk):
            redis_client.lpush("separation_cpu_queue", f"{vidd}|{end}|{end+30}")
        # next_vocal_key = f"vocals-{video_id}-{end}|{start}"
        return response
    else:
        if prioritize_separation:
            redis_client.rpush("separation_gpu_queue", f"{vidd}|{start}|{end}")
            if(next_chunk):
                redis_client.lpush("separation_cpu_queue", f"{vidd}|{end}|{end+30}")
            
        return jsonify({"status": "not_separated", "video_id": video_id}), 200 
    
    
    
def write_mp3_from_wav(wav_path: str, mp3_path: str):
    ffmpeg.input(wav_path).output(mp3_path, audio_bitrate='192k', threads=0).run(quiet=True, overwrite_output=True)
    
def separate_full_vocals(mp3_input_path: str, separator: Separator) -> bytes:
    """Run Spleeter separation on given MP3 path using provided separator, return vocal MP3 bytes."""
    audio_loader = AudioAdapter.default()
    waveform, _ = audio_loader.load(mp3_input_path, sample_rate=44100)

    prediction = separator.separate(waveform)
    vocals = prediction['vocals']

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_wav:
        write_wav(temp_wav.name, 44100, vocals)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_mp3_out:
            write_mp3_from_wav(temp_wav.name, temp_mp3_out.name)

            with open(temp_mp3_out.name, "rb") as f:
                vocal_mp3_bytes = f.read()

            # Save vocal MP3 permanently to VOCALS_DIR
            vocal_filename = os.path.basename(mp3_input_path).replace(".mp3", "_vocals.mp3")
            vocal_path = os.path.join(VOCALS_DIR, vocal_filename)
            with open(vocal_path, "wb") as out_f:
                out_f.write(vocal_mp3_bytes)

            # Cleanup temp files
            os.remove(temp_wav.name)
            os.remove(temp_mp3_out.name)

            return vocal_mp3_bytes, vocal_path

def separate_segment(mp3_path, start: float, end: float, separator: Separator):
    """Extract segment using ffmpeg, then separate vocals with provided separator."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_segment:
        ffmpeg.input(mp3_path, ss=start, to=end).output(temp_segment.name).run(quiet=True, overwrite_output=True)
        try:
            return separate_full_vocals(temp_segment.name, separator)
        finally:
            if os.path.exists(temp_segment.name):
                os.remove(temp_segment.name)
                
def gpu_worker_loop():
    """Process GPU separation queue with GPU-based Spleeter."""
    global gpu_separator  # use the pre-initialized GPU separator

    while True:
        item = redis_client.lpop("separation_gpu_queue")
        
        if item :
            item_str = item.decode("utf-8")  # Decode bytes to string
            video_id, start, end = item_str.split("|")
            
            vocal_key = f"vocals-{video_id}-{int(start)}|{int(end)}"
            
            #if segment not in redis
            if(not redis_client.exists(vocal_key)):
                #if vocal segment in b2
                local_vocal_path = f"/tmp/{vocal_key}.mp3"
                if(download_b2_to_local(f"vocals/{vocal_key}.mp3", local_vocal_path)):
                    redis_client.setex(vocal_key, 1800, open(local_vocal_path, "rb").read())
                    print(f"Segment gotten from b2: {local_vocal_path}")
                    
                else:
                    try:
                        mp3_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
                        if not os.path.exists(mp3_path):
                            print(f"[GPU WORKER] MP3 not found for {video_id}")
                            continue

                        print(f"[GPU WORKER] Separating vocals GPU: {video_id} [{start}-{end}]")
                        vocal_bytes, vocal_path = separate_segment(mp3_path, float(start), float(end), gpu_separator)

                        # Update separation status in Redis to "completed_gpu"
                        # redis_client.hset(SEPARATION_STATUS_KEY, video_id, "completed_gpu")

                        redis_client.sadd("separated_vocals_gpu", vocal_path)
                        

                        redis_client.setex(vocal_key, 1800, vocal_bytes)
                        upload_bytes_to_b2(vocal_bytes, f"vocals/{vocal_key}.mp3")
                        # print("exists",vocal_key, redis_client.exists(vocal_key))
                        print(f"[GPU WORKER] Separation done: {vocal_path}")

                    except Exception as e:
                        print(f"[GPU WORKER] Error processing {video_id}: {e}")
        else:
            time.sleep(1)


def downloader_thread():
    """Background thread to pop video IDs from download queue, download audio, then queue CPU separation."""
    while True:
        #let eldest in download_queue
        video_id = redis_client.lpop("download_queue")
        if video_id:
            try:
                print(f"[DOWNLOADER] Downloading audio for {video_id}")
                # Your major_downloader should save mp3 to DOWNLOAD_DIR/{video_id}.mp3
                
                
                mp3_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
                
                if(not os.path.exists(mp3_path)):
                    if(not download_b2_to_local(f"raw_mp3/{video_id}.mp3", mp3_path)):
                        ress = major_downloader(video_id)

                if os.path.exists(mp3_path):
                    redis_client.sadd("downloaded_videos", video_id)
                    print(f"[DOWNLOADER] Download completed: {video_id}")
                    
                    # vocal_bytes_for_30_secs = cpu_separate_segment(mp3_path,0,30,cpu_separator)

                    # Queue CPU separation after download for full audio (0 to duration)
                    redis_client.rpush("separation_cpu_queue", f"{video_id}|0|30")
                    upload_to_b2(mp3_path,f"raw_mp3/{video_id}.mp3",)

                redis_client.srem("download_tracking", video_id)

            except Exception as e:
                print(f"[DOWNLOADER] Error downloading {video_id}: {e}")
        else:
            time.sleep(1)


@app.route("/download", methods=["POST"])
def add_to_download_queue():
    video_id = request.json.get("video_id")
    if not video_id:
        return jsonify({"error": "Missing video_id"}), 400

    #if video a member of downloaded_videos set
    if redis_client.sismember("downloaded_videos", video_id):
        return jsonify({"status": "already_downloaded", "video_id": video_id}), 200

      #if video a member of download_tracking set
    if redis_client.sismember("download_tracking", video_id):
        return jsonify({"status": "already_queued", "video_id": video_id}), 200

    redis_client.rpush("download_queue", video_id)
    redis_client.sadd("download_tracking", video_id)
    return jsonify({"status": "queued", "video_id": video_id}), 202


@app.route("/download/status/<video_id>", methods=["GET"])
def check_status(video_id):
    if redis_client.sismember("downloaded_videos", video_id):
        return jsonify({"status": "downloaded", "video_id": video_id})
    elif redis_client.sismember("download_tracking", video_id):
        return jsonify({"status": "queued", "video_id": video_id})
    else:
        return jsonify({"status": "not_queued", "video_id": video_id})
    
    
    

    
@app.route("/download/prioritize", methods=["POST"])
def prioritize_download():
    video_id = request.json.get("video_id")
    if not video_id:
        return jsonify({"error": "Missing video_id"}), 400

    if redis_client.sismember("downloaded_videos", video_id):
        return jsonify({"status": "already_downloaded", "video_id": video_id}), 200

    # Remove from current queue if exists
    redis_client.lrem("download_queue", 0, video_id)
    # Push to front
    redis_client.lpush("download_queue", video_id)
    redis_client.sadd("download_tracking", video_id)

    return jsonify({"status": "prioritized", "video_id": video_id}), 202

# === START THREADS ===
for _ in range(4):  # Tune this based on load and vCPUs
    threading.Thread(target=downloader_thread, daemon=True).start()
    
    
cpu_worker = multiprocessing.Process(target=cpu_worker_loop, daemon=True)
cpu_worker.start()

gpu_worker = multiprocessing.Process(target=gpu_worker_loop, daemon=True)
gpu_worker.start()
    
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
    
    