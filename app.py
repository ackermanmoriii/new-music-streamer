from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import yt_dlp
import time
from threading import Lock
import requests
import sys
import os
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# --- FIX: Use environment port for Koyeb ---
PORT = int(os.environ.get('PORT', 5001))

# --- OPTIMIZED CONFIGURATION ---
YDL_SEARCH_OPTS = {
    'format': 'bestaudio/best',
    'extract_flat': True,
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'geo_bypass': True,
    'extractor_args': {'youtube': {'player_client': ['android']}},  # Use android client for mobile compatibility
    'socket_timeout': 30,
}

YDL_STREAM_OPTS = {
    'format': 'bestaudio[filesize<50M]/bestaudio/best',  # Limit file size
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'geo_bypass': True,
    'extractor_args': {'youtube': {'player_client': ['android']}},
    'socket_timeout': 30,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
}

# --- PERFORMANCE ENHANCEMENTS ---
search_cache = {}
url_cache = {}
cache_lock = Lock()
CACHE_LIFETIME = 1800

# Smaller thread pool for Koyeb
executor = ThreadPoolExecutor(max_workers=2)

def format_duration(seconds):
    if not seconds: return 'N/A'
    try:
        seconds = int(seconds)
        m, s = divmod(seconds, 60)
        return f"{m}:{s:02d}"
    except: return str(seconds)

def get_or_extract_audio_url(video_id):
    """Simplified and more robust URL extraction"""
    with cache_lock:
        if video_id in url_cache:
            cache_data = url_cache[video_id]
            if time.time() - cache_data['time'] < 14400:  # 4 hours
                return cache_data['url']

    # Extract with timeout protection
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        with yt_dlp.YoutubeDL(YDL_STREAM_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Get the best audio URL (not necessarily the first one)
            formats = info.get('formats', [])
            audio_formats = [f for f in formats if f.get('vcodec') == 'none']
            
            if audio_formats:
                # Prefer smaller files for streaming
                audio_formats.sort(key=lambda x: x.get('filesize', float('inf')))
                real_audio_url = audio_formats[0]['url']
            else:
                real_audio_url = info['url']
            
            with cache_lock:
                url_cache[video_id] = {'url': real_audio_url, 'time': time.time()}
            
            return real_audio_url
    except Exception as e:
        print(f"Extraction failed: {e}")
        return None

def background_extract_task(video_id):
    """Worker task with error handling"""
    try:
        get_or_extract_audio_url(video_id)
    except Exception as e:
        print(f"Background extraction failed: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/prefetch')
def prefetch():
    """Lightweight prefetch endpoint"""
    video_id = request.args.get('id')
    if video_id:
        executor.submit(background_extract_task, video_id)
    return jsonify({'status': 'queued'})

@app.route('/search')
def search():
    """Search with better error handling"""
    query = request.args.get('q', '').strip()
    if not query: 
        return jsonify({'error': 'No query provided'}), 400

    # Cache check
    with cache_lock:
        if query in search_cache:
            timestamp, results = search_cache[query]
            if time.time() - timestamp < CACHE_LIFETIME:
                return jsonify(results)

    # Perform search with timeout
    try:
        search_query = f"ytsearch10:{query}"  # Limit to 10 results
        
        with yt_dlp.YoutubeDL(YDL_SEARCH_OPTS) as ydl:
            result = ydl.extract_info(search_query, download=False)
            results = []
            
            if 'entries' in result:
                for entry in result['entries'][:5]:  # Only take top 5
                    if entry:
                        results.append({
                            'id': entry['id'],
                            'title': entry['title'][:100],  # Limit title length
                            'uploader': entry.get('uploader', 'Unknown')[:50],
                            'thumbnail': f"https://i.ytimg.com/vi/{entry['id']}/hqdefault.jpg",
                            'duration': format_duration(entry.get('duration'))
                        })
            
            with cache_lock:
                search_cache[query] = (time.time(), results)
            
            return jsonify(results)
            
    except Exception as e:
        print(f"Search error: {e}")
        return jsonify({'error': 'Search failed', 'details': str(e)}), 500

@app.route('/stream')
def stream():
    """Stream with chunked transfer encoding"""
    video_id = request.args.get('id')
    if not video_id: 
        return "No ID", 400

    real_audio_url = get_or_extract_audio_url(video_id)
    if not real_audio_url:
        return "Error extracting stream", 500

    try:
        # Stream with smaller chunks for better performance
        req = requests.get(real_audio_url, stream=True, timeout=30)
        
        def generate():
            chunk_size = 1024 * 32  # 32KB chunks
            for chunk in req.iter_content(chunk_size=chunk_size):
                if chunk:
                    yield chunk

        response_headers = {
            'Content-Type': req.headers.get('content-type', 'audio/mpeg'),
            'Cache-Control': 'public, max-age=3600',
            'Accept-Ranges': 'bytes'
        }

        return Response(
            generate(),
            headers=response_headers,
            status=req.status_code,
            direct_passthrough=True
        )
        
    except Exception as e:
        print(f"Stream error: {e}")
        return f"Stream failed: {str(e)}", 500

@app.route('/download')
def download():
    """Download endpoint with simpler logic"""
    video_id = request.args.get('id')
    title = request.args.get('title', 'track')
    
    if not video_id: 
        return "No ID", 400

    real_audio_url = get_or_extract_audio_url(video_id)
    if not real_audio_url:
        return "Error extracting download link", 500

    try:
        req = requests.get(real_audio_url, stream=True, timeout=60)
        
        def generate():
            for chunk in req.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        filename = f"{safe_title}.mp3" if safe_title else "audio.mp3"
        
        response = Response(generate(), content_type='audio/mpeg')
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.headers["Content-Length"] = req.headers.get('content-length', '')
        
        return response
        
    except Exception as e:
        print(f"Download error: {e}")
        return f"Download failed", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
