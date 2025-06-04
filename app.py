import os
import time
import tempfile
import threading
import multiprocessing
from flask import Flask, request, jsonify, send_file, make_response
import redis
import ffmpeg
from io import BytesIO
from spleeter.separator import Separator
from spleeter.audio.adapter import AudioAdapter
from scipy.io.wavfile import write as write_wav
from downloaders import major_downloader

from cpu_sep import cpu_worker_loop,cpu_separator,cpu_separate_segment

DOWNLOAD_DIR = "downloads"
VOCALS_DIR = "vocals"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(VOCALS_DIR, exist_ok=True)


os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(VOCALS_DIR, exist_ok=True)

# Redis connection (multiprocessing-safe as long as separate connections are used in processes)
redis_client = redis.Redis(decode_responses=False)

app = Flask(__name__)

# Instantiate a global separator lock for threading in main process if needed
separator_lock = threading.Lock()

# Initialize Separator instances globally to share in workers
# GPU Separator: default, uses GPU if available
gpu_separator = Separator('spleeter:2stems')



@app.route("/separate/status", methods=["POST"])
def check_separation_status():
    video_id = request.json.get("video_id")
    start = request.json.get("start",0)
    end = request.json.get("end",0)
    
    print(type(video_id))
    
    vocal_key = f"vocals:{video_id}-{start}|{end}"
    
    print("exists", vocal_key,redis_client.exists(vocal_key))
    if not video_id:
        return jsonify({"error": "Missing video_id"}), 400
    if redis_client.exists(vocal_key):
        return jsonify({"status": "section_separated", "video_id": video_id}), 200
    else:
       return jsonify({"status": "not_separated", "video_id": video_id}), 200 
   
   
@app.route("/separate", methods=["POST"])
def start_separation():
    video_id = request.json.get("video_id")
    start = request.json.get("start",0)
    end = request.json.get("end",9999)
    next_chunk =request.json.get("next_chunk",False)
    
    vocal_key = f"vocals:{video_id}-{start}|{end}"
    
    if not video_id:
        return jsonify({"error": "Missing video_id"}), 400
    
    
    if redis_client.exists(vocal_key):
        vocal_mp3 = redis_client.get(vocal_key)
        response = make_response(send_file(BytesIO(vocal_mp3), mimetype='audio/mpeg', as_attachment=True, download_name=f"{video_id}_vocals.mp3"))
        if(next_chunk):
            redis_client.lpush("separation_cpu_queue", f"{video_id}|{end}|{end+30}")
        # next_vocal_key = f"vocals:{video_id}-{end}|{start}"
        return response
    else:
       return jsonify({"status": "not_separated", "video_id": video_id}), 200 
    


def downloader_thread():
    """Background thread to pop video IDs from download queue, download audio, then queue CPU separation."""
    while True:
        #let eldest in download_queue
        video_id = redis_client.lpop("download_queue")
        if video_id:
            try:
                print(f"[DOWNLOADER] Downloading audio for {video_id}")
                # Your major_downloader should save mp3 to DOWNLOAD_DIR/{video_id}.mp3
                ress = major_downloader(video_id)
                mp3_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")

                if os.path.exists(mp3_path):
                    redis_client.sadd("downloaded_videos", video_id)
                    print(f"[DOWNLOADER] Download completed: {video_id}")
                    
                    # vocal_bytes_for_30_secs = cpu_separate_segment(mp3_path,0,30,cpu_separator)

                    # Queue CPU separation after download for full audio (0 to duration)
                    redis_client.rpush("separation_cpu_queue", f"{video_id}|0|30")

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
    
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
    
    