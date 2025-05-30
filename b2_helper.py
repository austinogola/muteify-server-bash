from b2sdk.v2 import *
import os
from dotenv import load_dotenv
import time

load_dotenv()


# Initialize B2 API
def init_b2():
    info = InMemoryAccountInfo()
    print(info)
    b2_api = B2Api(info)

    app_key_id = os.getenv("B2_APP_KEY_ID")
    app_key = os.getenv("B2_APP_KEY")
    
    print(app_key_id,app_key)
    b2_api.authorize_account("production", app_key_id, app_key)

    return b2_api

# Upload a file
def upload_to_b2(file_path, file_name, bucket_name):
    print('UPloading to b2',file_path, file_name, bucket_name)
   
    b2_api = init_b2()
    print(b2_api)
    bucket = b2_api.get_bucket_by_name(bucket_name)

    with open(file_path, 'rb') as file:
        bucket.upload_bytes(file.read(), file_name)
        print(f"Uploaded {file_name} to B2 bucket: {bucket_name}")
        
        
        
def file_exists_in_b2(file_name, bucket_name):
    b2_api = init_b2()
    print(b2_api)
    bucket = b2_api.get_bucket_by_name(bucket_name)
    
    try:
        bucket.get_file_info_by_name(file_name)
        return True
    except Exception as e:
        return False


def download_from_b2(file_name, bucket_name, save_path,start_time):
    # start_time = time.time()
 
    b2_api = init_b2()
    bucket = b2_api.get_bucket_by_name(bucket_name)

    # Get file version info by name
    file_version = bucket.get_file_info_by_name(file_name)

    # Open a local file in write-binary mode and download to it
    try:
        
        with open(save_path, 'wb') as f:
            print(type(file_version))
            file_version.download_to_file(f)
    except Exception as e:
        print(e)

    print(f"Downloaded '{file_name}' from bucket '{bucket_name}' to '{save_path}'")
    
   
    return ({
            'file_path': save_path,
            'download_time_seconds': time.time() - start_time
        })
    
    
    
# init_b2()