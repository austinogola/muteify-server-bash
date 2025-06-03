
from io import BytesIO
import requests
import os
from dotenv import load_dotenv
import time
import threading
# from b2_helper import upload_to_b2,file_exists_in_b2,download_from_b2

from storage_utils import upload_to_b2, upload_bytes_to_b2, download_b2_to_local,file_exists_in_b2

load_dotenv()

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

print(RAPIDAPI_KEY)


DOWNLOAD_DIR = 'downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)



method_one_host = os.getenv('METHOD_ONE_HOST')
method_two_host = os.getenv('METHOD_TWO_HOST')
method_three_host = os.getenv('METHOD_THREE_HOST')
def download_method_one(vidId,sStart=None,sEnd=None,max_retries=3):
   
    start_time = time.time()
    url = f"https://{method_one_host}/dl"
    
    print(url)
    
    try:
        querystring = {"id":vidId}
    
        if sStart is not None:
            querystring["sStart"]=sStart
            
        if sEnd is not None:
            querystring["sEnd"]=sEnd
            
        print(querystring)

        headers = {
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": method_one_host
        }
        
        response = requests.get(url, headers=headers, params=querystring)
    
        response_json = response.json()
        
        print(response_json)
        
        download_link = response_json["link"]
        
        file_name =f"{vidId}.mp3"
        
        file_path = os.path.join(DOWNLOAD_DIR, file_name)
    
        
        mp3_response = requests.get(download_link)
        
        print(mp3_response)
    
        
        mp3_response.raise_for_status()  # Ensure the download was successful
        
        with open(file_path, 'wb') as file:
           for chunk in mp3_response.iter_content(chunk_size=1048576):
               if chunk:
                   file.write(chunk)
                    
                    
        download_time = time.time() - start_time

        # Return the file path and download time
        #return file_name, download_time
        print('Downloadded in',download_time)
        return ({
            'file_path': file_path,
            'download_time_seconds': download_time
        })
    except Exception as e:
        return({
            "error":True,
            "message":repr(e)
        })


def the_one_download_method(vidId,sStart=None,sEnd=None,max_retries=3):
   
    start_time = time.time()
    url = f"https://{method_one_host}/dl"
    
    print(url)
    
    try:
        querystring = {"id":vidId}
    
        if sStart is not None:
            querystring["sStart"]=sStart
            
        if sEnd is not None:
            querystring["sEnd"]=sEnd
            
        print(querystring)

        headers = {
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": method_one_host
        }
        
        response = requests.get(url, headers=headers, params=querystring)
    
        response_json = response.json()
        
        print(response_json)
        
        download_link = response_json["link"]
        
        file_name =f"{vidId}.mp3"
        
        file_path = os.path.join(DOWNLOAD_DIR, file_name)
    
        
        mp3_response = requests.get(download_link)
        
        print(mp3_response)
    
        
        mp3_response.raise_for_status()  # Ensure the download was successful
        
        with open(file_path, 'wb') as file:
           for chunk in mp3_response.iter_content(chunk_size=1048576):
               if chunk:
                   file.write(chunk)
                    
                    
        download_time = time.time() - start_time

        # Return the file path and download time
        #return file_name, download_time
        print('Downloadded in',download_time)
        return ({
            'file_path': file_path,
            'download_time_seconds': download_time
        })
    except Exception as e:
        return({
            "error":True,
            "message":repr(e),
            'download_link':download_link
        })

def major_downloader(vidId, start=None, end=None, max_retries=3):
    file_name = f"{vidId}.mp3"
    file_path = os.path.join(DOWNLOAD_DIR, file_name)

    # Check if valid local file exists
    if os.path.exists(file_path) and os.path.getsize(file_path) > 1_000:  # size sanity check
        print("File exists locally")
        # if not file_exists_in_b2(f"raw_mp3/{vidId}.mp3"):
        #     threading.Thread(target=upload_to_b2, args=(file_path, f"raw_mp3/{vidId}.mp3")).start()
        return {'file_path': file_path, 'download_time_seconds': 'immediate'}
    
    
    methods = [the_one_download_method]
    for method in methods:
        for attempt in range(max_retries):
            try:
                print(f"Trying {method.__name__}, attempt {attempt + 1}")
                result = method(vidId, start, end) if 'start' in method.__code__.co_varnames else method(vidId)

                if result and 'file_path' in result and os.path.getsize(result['file_path']) > 1_000 :
                    print("Download successful. Uploading to B2...")
                    threading.Thread(target=upload_to_b2, args=(result['file_path'], f"raw_mp3/{vidId}.mp3")).start()
                    return result

                print(f"Download attempt {attempt + 1} failed. Retrying...")
                time.sleep(2.5)
            except Exception as e:
                print(f"Error in {method.__name__}: {e}")
                time.sleep(2.5)

    return {"error": True, "message": f"All methods failed for video ID: {vidId}","download_link":result['download_link']}
   
    
def download_method_three(vidId):
    start_time = time.time()
    try:
        
        url = f"https://{method_three_host}/dl"

        print(url)
        querystring = {"id":vidId}

        headers = {
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": method_three_host
        }

        response = requests.get(url, headers=headers, params=querystring)
        
        response_json = response.json()
        
        # print(response_json)
        
        adaptiveFormats = response_json['adaptiveFormats']
        
        audio_formats = [item for item in adaptiveFormats if 'audio' in item['mimeType']]
        
        sorted_audio_formats = sorted(audio_formats, key=lambda item: item['bitrate'])
        sorted_audio_bitrates = sorted(item['bitrate'] for item in sorted_audio_formats )
        chosen_format = sorted_audio_formats[0]
        
        print(sorted_audio_bitrates)
        print('chosen_format',chosen_format['bitrate'],chosen_format['averageBitrate'])
        
        download_link = chosen_format["url"]
        
        file_name =f"{vidId}.mp3"
        
        file_path = os.path.join(DOWNLOAD_DIR, file_name)
        
        print('Starting download 2')
        
        mp3_response = requests.get(download_link)
        
        print(mp3_response)
    
        
        mp3_response.raise_for_status()  # Ensure the download was successful
        
        with open(file_path, 'wb') as file:
           for chunk in mp3_response.iter_content(chunk_size=1048576):
               if chunk:
                   file.write(chunk)
                    
                    
        download_time = time.time() - start_time

        # Return the file path and download time
        #return file_name, download_time
        print('Downloadded in',download_time)
        return ({
            'file_path': file_path,
            'download_time_seconds': download_time
        })
     
     
    except Exception as e:
        return({
            "error":True,
            "message":repr(e)
        })
    
    
def download_method_two(vidId):
    start_time = time.time()
    try:
        
        url = f"https://{method_two_host}/download"

        print(url)
        querystring = {"url":f"https://www.youtube.com/watch?v={vidId}","format":"mp3"}

        payload = {}
        headers = {
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host":method_two_host ,
            "Content-Type": "application/json"
        }

        response = requests.post(url, headers=headers, params=querystring)
     
        
        response_json = response.json()
        
        print(response_json)
        
        
        item_id= response_json['id']
        
        print(item_id)
        
        status_url=  f"https://{method_two_host}/status/{item_id}"
        
        status= ''
        
        while(status != 'AVAILABLE'):
            print(status)
            response = requests.get(status_url, headers=headers)
            response_json = response.json()
            # print('response_json',response_json)
            print(response_json['status'])
            status = response_json['status']
            
            time.sleep(2.5)
            
        
            
        
        download_link = response_json["downloadUrl"]
        
        file_name =f"{vidId}.mp3"
        
        file_path = os.path.join(DOWNLOAD_DIR, file_name)
        
        print('Starting download 2')
        
        mp3_response = requests.get(download_link)
        
        print(mp3_response)
    
        
        mp3_response.raise_for_status()  # Ensure the download was successful
        
        with open(file_path, 'wb') as file:
           for chunk in mp3_response.iter_content(chunk_size=1048576):
               if chunk:
                   file.write(chunk)
                    
                    
        download_time = time.time() - start_time

        # Return the file path and download time
        #return file_name, download_time
        print('Downloadded in',download_time)
        return ({
            'file_path': file_path,
            'download_time_seconds': download_time
        })
     
     
    except Exception as e:
        return({
            "error":True,
            "message":repr(e)
        })

DOWNLOAD_BUCKET_NAME = os.getenv("DOWNLOAD_BUCKET_NAME")
def major_downloader2(vidId, start=None, end=None, max_retries=3):
    file_name = f"{vidId}.mp3"
    file_path = os.path.join(DOWNLOAD_DIR, file_name)

    # Check if valid local file exists
    if os.path.exists(file_path) and os.path.getsize(file_path) > 1_000:  # size sanity check
        print("File exists locally")
        # if not file_exists_in_b2(f"raw_mp3/{vidId}.mp3"):
        #     threading.Thread(target=upload_to_b2, args=(file_path, f"raw_mp3/{vidId}.mp3")).start()
        return {'file_path': file_path, 'download_time_seconds': 'immediate'}

    # Retry logic
    methods = [download_method_one, download_method_two, download_method_three]
    for method in methods:
        for attempt in range(max_retries):
            try:
                print(f"Trying {method.__name__}, attempt {attempt + 1}")
                result = method(vidId, start, end) if 'start' in method.__code__.co_varnames else method(vidId)

                if result and 'file_path' in result and os.path.getsize(result['file_path']) > 1_000 :
                    print("Download successful. Uploading to B2...")
                    threading.Thread(target=upload_to_b2, args=(result['file_path'], f"raw_mp3/{vidId}.mp3")).start()
                    return result

                print(f"Download attempt {attempt + 1} failed. Retrying...")
                time.sleep(2.5)
            except Exception as e:
                print(f"Error in {method.__name__}: {e}")
                time.sleep(2.5)

    return {"error": True, "message": f"All methods failed for video ID: {vidId}"}
    
    
# ll = major_downloader('UxxajLWwzqY',"00:10:00")
# print(ll)
