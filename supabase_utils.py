# supabase_utils.py

import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()


# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_PUBLIC_KEY")  # Use service key for server-side scripts
BUCKET_NAME = "mutify-vocals-audios"

print('SUPABASE_URL',SUPABASE_URL)
print('SUPABASE_KEY',SUPABASE_KEY)
# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

print(supabase)
def upload_audio_to_supabase(file_path: str, delete_after_upload: bool = False, bucket_folder: str = "") -> dict:
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}
    print("UPLOADING AUDIO TO SUPABASE")
    filename = os.path.basename(file_path)
    destination_path = f"{bucket_folder.strip().strip('/')}/{filename}" if bucket_folder else filename

    try:
        with open(file_path, "rb") as f:
            file_data = f.read()

        response = supabase.storage.from_(BUCKET_NAME).upload(
            destination_path,
            file_data,
            file_options={"content-type": "audio/mpeg"}
        )

        if delete_after_upload:
            os.remove(file_path)

        return response
    except Exception as e:
        return {"error": str(e)}

def check_file_exists_in_bucket(filename: str, bucket_folder: str = "") -> bool:
    path = f"{bucket_folder.strip().strip('/')}/{filename}" if bucket_folder else filename
    print("CHECKING IF AUDIO FILE IS IN BUCKET ")
    try:
        response = supabase.storage.from_(BUCKET_NAME).list(bucket_folder)
        if isinstance(response, list):
            return any(obj['name'] == filename for obj in response)
        return False
    except Exception as e:
        print(f"Error checking file: {e}")
        return False

def download_file_from_bucket(bucket_folder: str, filename: str) -> bytes:
    path = f"{bucket_folder.strip().strip('/')}/{filename}" if bucket_folder else filename

    try:
        response = supabase.storage.from_(BUCKET_NAME).download(path)
        return response
    except Exception as e:
        print(f"Error downloading file: {e}")
        return None
