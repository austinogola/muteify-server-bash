
from io import BytesIO
import requests
import os
from dotenv import load_dotenv
import time
import threading
from b2_helper import upload_to_b2,file_exists_in_b2,download_from_b2

load_dotenv()

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

print(RAPIDAPI_KEY)


DOWNLOAD_DIR = 'downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# print(RAPIDAPI_KEY)
def streamMethod23(vidId,max_retries=1):
    start_time = time.time()
    
    api_url = f'https://youtube-audio-stream2.p.rapidapi.com/stream/{vidId}'
    print(api_url)
    headers = {
          'Content-Type': "application/json",
        'x-rapidapi-key': RAPIDAPI_KEY,  # Replace with your RapidAPI key
        'x-rapidapi-host':'youtube-audio-stream2.p.rapidapi.com',  # Replace with your RapidAPI host
    }
    
    
    
    
    file_name =f"{vidId}.mp3"
    
    file_path = os.path.join(DOWNLOAD_DIR, file_name)
   
    print('fetching')
    mp3_response = requests.get(api_url, headers=headers)
    
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


def donwloader_one(vidId,max_retries=1):
    start_time = time.time()
    
    url = "https://youtube-info-download-api.p.rapidapi.com/ajax/download.php"

    querystring = {"format":"mp3","add_info":"0","url":f"https://www.youtube.com/watch?v={vidId}","audio_quality":"128"}

    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "youtube-info-download-api.p.rapidapi.com"
    }

    print('fetching video')
    
    mp3_response = requests.get(url, headers=headers, params=querystring)
    
    # print(mp3_response)
  
        
    mp3_response.raise_for_status() 
    
    response_json = mp3_response.json()
    
    
    
    progress_url = response_json['progress_url']
    
    progress_response = requests.get(progress_url)
    
    progress_json = progress_response.json()
    
    
    progress_text = progress_json['text']
    
    trial = 0
    
    while (progress_text.lower() != 'finished') and trial<10:
        print('progress_text',progress_text.lower())
        print('trial',trial)
    
        progress_response = requests.get(progress_url)
    
        progress_json = progress_response.json()
    
        print('progress_json',progress_json)
        
        progress_text = progress_json['text']
        
    download_url = progress_json['download_url']
    
    print("download_url",download_url)
    
    
    file_name =f"{vidId}.mp3"
    
    file_path = os.path.join(DOWNLOAD_DIR, file_name)

    mp3_response = requests.get(download_url)
    
    print(mp3_response)
  
        
    mp3_response.raise_for_status()  # Ensure the download was successful
      
    with open(file_path, 'wb') as file:
           for chunk in mp3_response.iter_content(chunk_size=1048576):
               if chunk:
                   file.write(chunk)
                    
                    
    download_time = time.time() - start_time
   
    print('Downloadded in',download_time)
    
    return ({
        'file_path': file_path,
        'download_time_seconds': download_time
    }) 
     


# donwloader_one('k5KxoG-Oi-A')

method_one_host = os.getenv('METHOD_ONE_HOST')
method_two_host = os.getenv('METHOD_TWO_HOST')
method_three_host = os.getenv('METHOD_THREE_HOST')
def download_method_one(vidId,sStart=None,sEnd=None,max_retries=3):
   
    start_time = time.time()
    url = f"https://{method_one_host}/dl"
    
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
def major_downloader(vidId,start=None,end=None):
    
    start_time = time.time()
    
    file_name =f"{vidId}.mp3"
        
    file_path = os.path.join(DOWNLOAD_DIR, file_name)
    
    file_in_global = file_exists_in_b2(file_name,DOWNLOAD_BUCKET_NAME)
    
    #check if file exists locally
    if os.path.exists(file_path):
        #if exists loally but not globally, upload
        if not file_in_global:
            print("Uploading file")
            thread = threading.Thread(target=upload_to_b2, args=( file_path,file_name, os.getenv("DOWNLOAD_BUCKET_NAME")))
            thread.start()
        return ({
            'file_path': file_path,
            'download_time_seconds': 'immediate'
        })
    else:
        if(file_in_global):
            print("File exists in bucket. Fetching")
            ans = download_from_b2(file_name,DOWNLOAD_BUCKET_NAME,file_path,start_time)
            
            return ans
    
    trial = 0
    
    
    
    while(trial<1):
        
        answer = download_method_one(vidId,start,end)
        print(answer)
        if('file_path' in answer):
           break 
       
        time.sleep(5) 
       
        trial=trial+1
        
        
    if 'file_path' not in answer:
        trial=0
        while(trial<1):
        
            answer = download_method_two(vidId)
            print(answer)
            if('file_path' in answer):
                break 
            
            time.sleep(5) 
        
            trial=trial+1
    
    if 'file_path' not in answer:
        trial=0
        while(trial<1):
        
            answer = download_method_three(vidId)
            print(answer)
            if('file_path' in answer):
                break 
            
            time.sleep(5) 
        
            trial=trial+1
    
    if "file_path" in answer:
        print('Uploading file')
        thread = threading.Thread(target=upload_to_b2, args=( answer['file_path'],file_name, os.getenv("DOWNLOAD_BUCKET_NAME")))
        thread.start()

    
    return answer
    
    
# ll = major_downloader('UxxajLWwzqY',"00:10:00")
# print(ll)
