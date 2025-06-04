import os
import time
import tempfile
import threading
import multiprocessing
from flask import Flask, request, jsonify
import redis
import ffmpeg

from spleeter.separator import Separator
from spleeter.audio.adapter import AudioAdapter
from scipy.io.wavfile import write as write_wav
from downloaders import major_downloader

DOWNLOAD_DIR = "downloads"
VOCALS_DIR = "vocals"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(VOCALS_DIR, exist_ok=True)

# Redis connection (multiprocessing-safe as long as separate connections are used in processes)
redis_client = redis.Redis(decode_responses=True)

app = Flask(__name__)

# Instantiate a global separator lock for threading in main process if needed
separator_lock = threading.Lock()

# Initialize Separator instances globally to share in workers
# GPU Separator: default, uses GPU if available
gpu_separator = Separator('spleeter:2stems')

# CPU Separator: use environment variable to disable GPU usage
# We'll instantiate inside the CPU worker process for isolation

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

# Redis key to track separation status
SEPARATION_STATUS_KEY = "separation_status"  # Redis set to track video status

def downloader_thread():
    """Background thread to pop video IDs from download queue, download audio, then queue CPU separation."""
    while True:
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

                    # Queue CPU separation after download for full audio (0 to duration)
                    redis_client.rpush("separation_cpu_queue", f"{video_id}|0|30")

                redis_client.srem("download_tracking", video_id)

            except Exception as e:
                print(f"[DOWNLOADER] Error downloading {video_id}: {e}")
        else:
            time.sleep(1)

def cpu_worker_loop():
    """Process CPU separation queue with CPU-only Spleeter."""
    import os
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    print("[CPU WORKER] Starting CPU-only Spleeter instance...")
    cpu_separator = Separator('spleeter:2stems')  # CPU only

    while True:
        item = redis_client.lpop("separation_cpu_queue")
        if item:
            video_id, start, end = item.split("|")
            try:
                mp3_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
                if not os.path.exists(mp3_path):
                    print(f"[CPU WORKER] MP3 not found for {video_id}")
                    continue

                print(f"[CPU WORKER] Separating vocals CPU: {video_id} [{start}-{end}]")
                vocal_bytes, vocal_path = separate_segment(mp3_path, float(start), float(end), cpu_separator)

                # Update separation status in Redis to "completed_cpu"
                redis_client.hset(SEPARATION_STATUS_KEY, video_id, "completed_cpu")

                redis_client.sadd("separated_vocals_cpu", vocal_path)
                print(f"[CPU WORKER] Separation done: {vocal_path}")

            except Exception as e:
                print(f"[CPU WORKER] Error processing {video_id}: {e}")
        else:
            time.sleep(1)

def gpu_worker_loop():
    """Process GPU separation queue with GPU-based Spleeter."""
    global gpu_separator  # use the pre-initialized GPU separator

    while True:
        item = redis_client.lpop("separation_gpu_queue")
        if item:
            video_id, start, end = item.split("|")
            try:
                mp3_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
                if not os.path.exists(mp3_path):
                    print(f"[GPU WORKER] MP3 not found for {video_id}")
                    continue

                print(f"[GPU WORKER] Separating vocals GPU: {video_id} [{start}-{end}]")
                vocal_bytes, vocal_path = separate_segment(mp3_path, float(start), float(end), gpu_separator)

                # Update separation status in Redis to "completed_gpu"
                redis_client.hset(SEPARATION_STATUS_KEY, video_id, "completed_gpu")

                redis_client.sadd("separated_vocals_gpu", vocal_path)
                print(f"[GPU WORKER] Separation done: {vocal_path}")

            except Exception as e:
                print(f"[GPU WORKER] Error processing {video_id}: {e}")
        else:
            time.sleep(1)

# Add the new Flask endpoint to check separation status
@app.route("/separation-status/<video_id>", methods=["GET"])
def separation_status(video_id):
    status = redis_client.hget(SEPARATION_STATUS_KEY, video_id)

    if status:
        return jsonify({"video_id": video_id, "status": status}), 200
    else:
        # Video is not found in the separation status table, check other queues
        if redis_client.sismember("separation_cpu_queue", video_id):
            return jsonify({"video_id": video_id, "status": "in_cpu_queue"}), 200
        elif redis_client.sismember("separation_gpu_queue", video_id):
            return jsonify({"video_id": video_id, "status": "in_gpu_queue"}), 200
        else:
            return jsonify({"video_id": video_id, "status": "not_queued"}), 404

# Flask routes for download and queue management

@app.route("/download", methods=["POST"])
def add_to_download_queue():
    video_id = request.json.get("video_id")
    if not video_id:
        return jsonify({"error": "Missing video_id"}), 400

    if redis_client.sismember("downloaded_videos", video_id):
        return jsonify({"status": "already_downloaded", "video_id": video_id}), 200

    if redis_client.sismember("download_tracking", video_id):
        return jsonify({"status": "already_queued", "video_id": video_id}), 200

    redis_client.rpush("download_queue", video_id)
    redis_client.sadd("download_tracking", video_id)
    return jsonify({"status": "queued", "video_id": video_id}), 202

@app.route("/separate", methods=["POST"])
def add_to_gpu_separation_queue():
    video_id = request.json.get("video_id")
    start = float(request.json.get("start", 0))
    end = float(request.json.get("end", 99999))

    # Add job to GPU separation queue
    redis_client.rpush("separation_gpu_queue", f"{video_id}|{start}|{end}")
    return jsonify({"status": "queued_for_gpu_separation", "video_id": video_id})

@app.route("/status/<video_id>", methods=["GET"])
def status(video_id):
    if redis_client.sismember("downloaded_videos", video_id):
        return jsonify({"status": "downloaded"})
    elif redis_client.sismember("download_tracking", video_id):
        return jsonify({"status": "download_queued"})
    else:
        return jsonify({"status": "not_queued"})

if __name__ == '__main__':
    # Start downloader thread (runs in background)
    threading.Thread(target=downloader_thread, daemon=True).start()

    # Start CPU and GPU separation workers in separate processes
    cpu_worker = multiprocessing.Process(target=cpu_worker_loop, daemon=True)
    gpu_worker = multiprocessing.Process(target=gpu_worker_loop, daemon=True)

    cpu_worker.start()
    gpu_worker.start()

    # Run Flask app (main process)
    app.run(host='0.0.0.0', port=5000)
