from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import yt_dlp
import time
from threading import Lock
import requests
import sys
import os
import traceback
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

app = Flask(__name__)

# --- FIX: Use environment port for Koyeb ---
PORT = int(os.environ.get('PORT', 8000))

# --- OPTIMIZED CONFIGURATION FOR KOYEB ---
# Simpler options that work better with server environments
YDL_OPTS = {
    'format': 'bestaudio[filesize<30M]/bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'geo_bypass': True,
    'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
    'socket_timeout': 30,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-us,en;q=0.5',
        'Accept-Encoding': 'gzip,deflate',
        'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
        'Connection': 'keep-alive',
    },
    'cookiefile': 'cookies.txt'  # Optional: helps with age-restricted content
}

# Use the same options for both search and stream to simplify
YDL_SEARCH_OPTS = YDL_OPTS.copy()
YDL_SEARCH_OPTS['extract_flat'] = True

YDL_STREAM_OPTS = YDL_OPTS.copy()

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
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
    except: return str(seconds)

def safe_extract(video_id):
    """Safer extraction with multiple fallbacks"""
    fallback_urls = [
        f"https://www.youtube.com/watch?v={video_id}",
        f"https://youtube.com/watch?v={video_id}",
        f"https://youtu.be/{video_id}"
    ]
    
    for url in fallback_urls:
        try:
            print(f"Trying to extract from: {url}")
            with yt_dlp.YoutubeDL(YDL_STREAM_OPTS) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Get the audio URL
                if 'url' in info:
                    audio_url = info['url']
                    print(f"Successfully extracted URL for {video_id}")
                    
                    # Cache it
                    with cache_lock:
                        url_cache[video_id] = {'url': audio_url, 'time': time.time()}
                    
                    return audio_url
                else:
                    # Try to find audio in formats
                    formats = info.get('formats', [])
                    audio_formats = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']
                    
                    if audio_formats:
                        # Prefer m4a format for better browser compatibility
                        m4a_formats = [f for f in audio_formats if f.get('ext') == 'm4a']
                        if m4a_formats:
                            audio_url = m4a_formats[0]['url']
                        else:
                            audio_url = audio_formats[0]['url']
                        
                        print(f"Found audio format for {video_id}")
                        
                        with cache_lock:
                            url_cache[video_id] = {'url': audio_url, 'time': time.time()}
                        
                        return audio_url
        except Exception as e:
            print(f"Failed with {url}: {str(e)[:100]}")
            continue
    
    return None

def get_or_extract_audio_url(video_id):
    """Simplified and more robust URL extraction"""
    # Check cache first
    with cache_lock:
        if video_id in url_cache:
            cache_data = url_cache[video_id]
            if time.time() - cache_data['time'] < 7200:  # 2 hours cache
                return cache_data['url']
    
    # Extract with timeout protection
    try:
        return safe_extract(video_id)
    except Exception as e:
        print(f"Extraction failed for {video_id}: {e}")
        traceback.print_exc()
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
        search_query = f"ytsearch5:{query}"  # Limit to 5 results for speed
        
        with yt_dlp.YoutubeDL(YDL_SEARCH_OPTS) as ydl:
            result = ydl.extract_info(search_query, download=False)
            results = []
            
            if result and 'entries' in result:
                for entry in result['entries']:
                    if entry:
                        results.append({
                            'id': entry['id'],
                            'title': entry['title'][:80],  # Limit title length
                            'uploader': entry.get('uploader', 'Unknown')[:40],
                            'thumbnail': f"https://i.ytimg.com/vi/{entry['id']}/hqdefault.jpg",
                            'duration': format_duration(entry.get('duration'))
                        })
            
            with cache_lock:
                search_cache[query] = (time.time(), results)
            
            return jsonify(results)
            
    except Exception as e:
        print(f"Search error: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Search failed', 'details': str(e)[:100]}), 500

@app.route('/stream')
def stream():
    """Stream with better error handling and compatibility"""
    video_id = request.args.get('id')
    if not video_id: 
        return jsonify({'error': 'No ID provided'}), 400

    print(f"Stream request for video ID: {video_id}")
    
    real_audio_url = get_or_extract_audio_url(video_id)
    if not real_audio_url:
        print(f"No audio URL found for {video_id}")
        return jsonify({'error': 'Could not extract audio URL'}), 500

    try:
        print(f"Proxying stream from: {real_audio_url[:100]}...")
        
        # Stream with smaller chunks for better performance
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Encoding': 'identity',  # Important: disable compression for streaming
            'Range': 'bytes=0-',  # Support range requests
        }
        
        req = requests.get(real_audio_url, stream=True, timeout=30, headers=headers)
        
        if req.status_code != 200:
            print(f"Upstream returned {req.status_code}")
            return jsonify({'error': f'Upstream error: {req.status_code}'}), 500

        def generate():
            chunk_size = 1024 * 16  # 16KB chunks
            try:
                for chunk in req.iter_content(chunk_size=chunk_size):
                    if chunk:
                        yield chunk
            except Exception as e:
                print(f"Stream generation error: {e}")

        # Determine content type
        content_type = req.headers.get('content-type', 'audio/mpeg')
        if 'm4a' in real_audio_url or 'mp4' in real_audio_url:
            content_type = 'audio/mp4'
        elif 'webm' in real_audio_url:
            content_type = 'audio/webm'

        response_headers = {
            'Content-Type': content_type,
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
            'Accept-Ranges': 'bytes',
            'Content-Length': req.headers.get('content-length', ''),
        }

        return Response(
            generate(),
            headers=response_headers,
            status=req.status_code,
            direct_passthrough=True
        )
        
    except requests.exceptions.Timeout:
        print(f"Stream timeout for {video_id}")
        return jsonify({'error': 'Stream timeout'}), 500
    except Exception as e:
        print(f"Stream error for {video_id}: {e}")
        traceback.print_exc()
        return jsonify({'error': f'Stream failed: {str(e)[:100]}'}), 500

@app.route('/download')
def download():
    """Download endpoint with simpler logic"""
    video_id = request.args.get('id')
    title = request.args.get('title', 'track')
    
    if not video_id: 
        return jsonify({'error': 'No ID provided'}), 400

    real_audio_url = get_or_extract_audio_url(video_id)
    if not real_audio_url:
        return jsonify({'error': 'Could not extract audio URL'}), 500

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        req = requests.get(real_audio_url, stream=True, timeout=60, headers=headers)
        
        def generate():
            for chunk in req.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip() or 'audio'
        filename = f"{safe_title}.mp3"
        
        response = Response(generate(), content_type='audio/mpeg')
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.headers["Content-Length"] = req.headers.get('content-length', '')
        
        return response
        
    except Exception as e:
        print(f"Download error: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Download failed'}), 500

@app.route('/health')
def health():
    """Health check endpoint for Koyeb"""
    return jsonify({'status': 'healthy', 'timestamp': time.time()})

if __name__ == '__main__':
    # Create cookies.txt if it doesn't exist (empty file)
    if not os.path.exists('cookies.txt'):
        open('cookies.txt', 'w').close()
    
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
