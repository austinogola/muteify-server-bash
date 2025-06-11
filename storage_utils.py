import os
from b2sdk.v2 import InMemoryAccountInfo, B2Api
from dotenv import load_dotenv

load_dotenv()


bucket_name = os.getenv("DOWNLOAD_BUCKET_NAME")

application_key_id = os.getenv("B2_APP_KEY_ID")
application_key = os.getenv("B2_APP_KEY")

info = InMemoryAccountInfo()
b2_api = B2Api(info)
b2_api.authorize_account("production", application_key_id, application_key)

bucket = b2_api.get_bucket_by_name(bucket_name)


def upload_to_b2(file_path: str, b2_path: str):
    """Upload local file to B2."""
    print(f'Uploading {file_path} bytes to {b2_path}')
    with open(file_path, 'rb') as f:
        bucket.upload_bytes(f.read(), b2_path)
        
        
def upload_bytes_to_b2(data: bytes, b2_path: str):
    """Upload bytes directly to B2."""
    print(f'Uploading bytes to {b2_path}')
    bucket.upload_bytes(data, b2_path)
    
    
def download_b2_to_local(b2_path: str, local_path: str) -> bool:
    """Try downloading a file from B2 to a local path."""
    print(f'Downloading from {b2_path}')
    try:
        file = bucket.download_file_by_name(b2_path)
        # print(file_info.file_info)
        print (file)
        with open(local_path, 'wb') as f:
            file.save(f)
        return True
    except Exception as e:
        print(e)
        return False
    
    
def file_exists_in_b2(file_name):
    
    try:
        bucket.get_file_info_by_name(file_name)
        return True
    except Exception as e:
        return False
