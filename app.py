from flask import Flask, request, jsonify
import threading
import time
import redis
import os
from downloaders import (major_downloader)

app = Flask(__name__)
redis_client = redis.Redis(decode_responses=True)
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# === THREAD WORKER ===
def downloader_thread():
    while True:
        video_id = redis_client.lpop("download_queue")
        if video_id:
            try:
                print(f"[DOWNLOADER] Processing {video_id}")
                download_audio(video_id)
                redis_client.srem("download_tracking", video_id)
                redis_client.sadd("downloaded_videos", video_id)
                print(f"[DOWNLOADER] Done {video_id}")
            except Exception as e:
                print(f"[ERROR] Download failed for {video_id}: {e}")
        else:
            time.sleep(1)


def download_audio(video_id):
    major_downloader(video_id)


# === ENDPOINTS ===

@app.route("/download", methods=["POST"])
def add_to_download_queue():
    video_id = request.json.get("video_id")
    if not video_id:
        return jsonify({"error": "Missing video_id"}), 400

    # Already downloaded?
    if redis_client.sismember("downloaded_videos", video_id):
        return jsonify({"status": "already_downloaded", "video_id": video_id}), 200

    # Already in queue?
    if redis_client.sismember("download_tracking", video_id):
        return jsonify({"status": "already_queued", "video_id": video_id}), 200

    # Add to end of queue
    redis_client.rpush("download_queue", video_id)
    redis_client.sadd("download_tracking", video_id)
    return jsonify({"status": "queued", "video_id": video_id}), 202


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


@app.route("/download/status/<video_id>", methods=["GET"])
def check_status(video_id):
    if redis_client.sismember("downloaded_videos", video_id):
        return jsonify({"status": "downloaded", "video_id": video_id})
    elif redis_client.sismember("download_tracking", video_id):
        return jsonify({"status": "queued", "video_id": video_id})
    else:
        return jsonify({"status": "not_queued", "video_id": video_id})


# === START THREADS ===
for _ in range(4):  # Tune this based on load and vCPUs
    threading.Thread(target=downloader_thread, daemon=True).start()


if __name__ == "__main__":
    app.run(debug=True)
