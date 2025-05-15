
from io import BytesIO
import requests
import os
from dotenv import load_dotenv
import time

load_dotenv()

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")



DOWNLOAD_DIR = 'downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

print(RAPIDAPI_KEY)
def donwloader_one(vidId,max_retries=1):
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
    


# donwloader_one('eJdqObrd1JI')