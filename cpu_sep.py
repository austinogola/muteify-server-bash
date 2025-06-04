import os
from spleeter.separator import Separator
from spleeter.audio.adapter import AudioAdapter
from scipy.io.wavfile import write as write_wav
import redis
import time
import ffmpeg
import tempfile

redis_client = redis.Redis(decode_responses=False)



os.environ["CUDA_VISIBLE_DEVICES"] = ""
print("[CPU WORKER] Starting CPU-only Spleeter instance...")



cpu_separator = Separator('spleeter:2stems')  # CPU only

DOWNLOAD_DIR = "downloads"
VOCALS_DIR = "vocals"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(VOCALS_DIR, exist_ok=True)


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


                redis_client.setex(f"vocals:{video_id}-{start}|{end}", 1800, vocal_bytes)
                redis_client.sadd("separated_vocals_cpu", vocal_path)
                print(f"[CPU WORKER] Separation done: {vocal_path}")

            except Exception as e:
                print(f"[CPU WORKER] Error processing {video_id}: {e}")
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

