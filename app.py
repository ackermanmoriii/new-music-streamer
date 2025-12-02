from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import yt_dlp
import time
from threading import Lock
import requests
import sys
import os
from concurrent.futures import ThreadPoolExecutor

# Try to import pyngrok for mobile access
try:
    from pyngrok import ngrok
except ImportError:
    ngrok = None

app = Flask(__name__)

# --- CONFIGURATION ---

# 1. SEARCH OPTIONS (FAST - Metadata Only): 
YDL_SEARCH_OPTS = {
    'format': 'bestaudio/best',
    'extract_flat': True,
    'noplaylist': True,
    'quiet': True,
    'geo_bypass': True,
    'extractor_args': {'youtube': {'player_client': ['default']}}
}

# 2. STREAM/DOWNLOAD OPTIONS (DETAILED - Get Actual URL):
YDL_STREAM_OPTS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'geo_bypass': True,
    'extractor_args': {'youtube': {'player_client': ['default']}}
}

# --- PERFORMANCE ENHANCEMENTS ---
search_cache = {}
url_cache = {} # Stores actual audio URLs (id -> {url, time})
cache_lock = Lock()
CACHE_LIFETIME = 1800  # 30 minutes

# Background Worker Pool for Pre-fetching
executor = ThreadPoolExecutor(max_workers=4)

def format_duration(seconds):
    if not seconds: return 'N/A'
    try:
        seconds = int(seconds)
        m, s = divmod(seconds, 60)
        return f"{m}:{s:02d}"
    except: return str(seconds)

def get_or_extract_audio_url(video_id):
    """
    Helper: Checks cache for a direct audio URL, or extracts it if missing.
    Returns: The direct audio URL (string) or None if failed.
    """
    # 1. Fast Path: Check Cache
    with cache_lock:
        if video_id in url_cache:
            # Check validity (YouTube URLs expire ~6 hours, we use 4h safety)
            if time.time() - url_cache[video_id]['time'] < 14400:
                print(f"CACHE HIT (URL): {video_id}")
                return url_cache[video_id]['url']

    # 2. Slow Path: Extract
    print(f"CACHE MISS (URL): {video_id} - Extracting...")
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(YDL_STREAM_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
            real_audio_url = info['url']
            
            with cache_lock:
                url_cache[video_id] = {'url': real_audio_url, 'time': time.time()}
            return real_audio_url
    except Exception as e:
        print(f"Extraction failed for {video_id}: {e}")
        return None

def background_extract_task(video_id):
    """Worker task wrapper for the executor."""
    get_or_extract_audio_url(video_id)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/prefetch')
def prefetch():
    """API to trigger background caching."""
    video_id = request.args.get('id')
    if video_id:
        executor.submit(background_extract_task, video_id)
    return jsonify({'status': 'queued'})

@app.route('/search')
def search():
    query = request.args.get('q', '').strip().lower()
    if not query: return jsonify({'error': 'No query provided'}), 400

    # 1. Search Cache
    with cache_lock:
        if query in search_cache:
            timestamp, results = search_cache[query]
            if time.time() - timestamp < CACHE_LIFETIME:
                print(f"CACHE HIT (Search): {query}")
                return jsonify(results)
            else:
                del search_cache[query]
    
    # 2. Perform Fresh Search
    print(f"CACHE MISS (Search): {query}")
    search_query = f"ytsearch20:{query}"
    
    with yt_dlp.YoutubeDL(YDL_SEARCH_OPTS) as ydl:
        try:
            result = ydl.extract_info(search_query, download=False)
            results = []
            if 'entries' in result:
                for entry in result['entries']:
                    duration_sec = entry.get('duration')
                    results.append({
                        'id': entry['id'],
                        'title': entry['title'],
                        'uploader': entry.get('uploader', 'Unknown'),
                        'thumbnail': entry.get('thumbnail') or f"https://i.ytimg.com/vi/{entry['id']}/hqdefault.jpg", 
                        'duration': format_duration(duration_sec)
                    })
            
            with cache_lock:
                search_cache[query] = (time.time(), results)
            
            # 3. Speculative Pre-fetching (Top 2 results)
            if len(results) > 0: executor.submit(background_extract_task, results[0]['id'])
            if len(results) > 1: executor.submit(background_extract_task, results[1]['id'])
                
            return jsonify(results)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/stream')
def stream():
    """Proxies the audio stream for playback."""
    video_id = request.args.get('id')
    if not video_id: return "No ID", 400

    real_audio_url = get_or_extract_audio_url(video_id)
    if not real_audio_url:
        return "Error extracting stream", 500

    try:
        req = requests.get(real_audio_url, stream=True)
        return Response(
            stream_with_context(req.iter_content(chunk_size=8192)),
            content_type=req.headers.get('content-type', 'audio/mpeg'),
            status=req.status_code
        )
    except Exception as e:
        return f"Stream failed: {e}", 500

@app.route('/download')
def download():
    """
    NEW: Proxies the stream as a file attachment for downloading.
    Uses the same cache logic as streaming, so it's instant if already playing.
    """
    video_id = request.args.get('id')
    title = request.args.get('title', 'track')
    
    if not video_id: return "No ID", 400

    real_audio_url = get_or_extract_audio_url(video_id)
    if not real_audio_url:
        return "Error extracting download link", 500

    # Sanitize title for filename
    safe_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c==' ']).rstrip()
    filename = f"{safe_title}.mp3"

    try:
        req = requests.get(real_audio_url, stream=True)
        
        # Create response with headers that trigger download
        response = Response(
            stream_with_context(req.iter_content(chunk_size=8192)),
            content_type=req.headers.get('content-type', 'audio/mpeg')
        )
        response.headers["Content-Disposition"] = f"attachment; filename=\"{filename}\""
        return response
    except Exception as e:
        return f"Download failed: {e}", 500

if __name__ == '__main__':
    PORT = 5001
    
    # Initialize pyngrok if available (for Mobile/VPN access)
    if ngrok:
        if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
            try:
                public_url = ngrok.connect(PORT).public_url
                print("\n" + "="*60)
                print(f" MOBILE ACCESS URL: {public_url}")
                print("="*60 + "\n")
            except Exception as e:
                print(f"Ngrok warning: {e}")

    app.run(host='0.0.0.0', port=PORT, debug=True)