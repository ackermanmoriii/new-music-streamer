from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import yt_dlp
import time
import requests
import os
import traceback

app = Flask(__name__)

# Use Koyeb's port environment variable
PORT = int(os.environ.get('PORT', 8000))

# SIMPLIFIED YouTube options for Koyeb compatibility
YDL_OPTS = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'geo_bypass': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web'],
            'player_skip': ['js', 'webpage']
        }
    },
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.youtube.com/'
    }
}

# Cache for audio URLs (simple in-memory cache)
audio_cache = {}

def format_duration(seconds):
    """Format duration from seconds to MM:SS"""
    if not seconds:
        return 'N/A'
    try:
        seconds = int(seconds)
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes}:{seconds:02d}"
    except:
        return 'N/A'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/prefetch')
def prefetch():
    """Simple prefetch endpoint - does nothing in this version"""
    video_id = request.args.get('id')
    return jsonify({'status': 'ok'})

@app.route('/search')
def search():
    """Search for YouTube videos"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'No query provided'}), 400
    
    try:
        # Simple search using yt-dlp
        search_query = f"ytsearch5:{query}"
        
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            # Enable flat extraction for faster search
            ydl.params['extract_flat'] = True
            
            result = ydl.extract_info(search_query, download=False)
            results = []
            
            if 'entries' in result:
                for entry in result['entries']:
                    if entry:
                        results.append({
                            'id': entry['id'],
                            'title': entry.get('title', 'Unknown'),
                            'uploader': entry.get('uploader', 'Unknown'),
                            'thumbnail': f"https://i.ytimg.com/vi/{entry['id']}/hqdefault.jpg",
                            'duration': format_duration(entry.get('duration'))
                        })
            
            return jsonify(results)
            
    except Exception as e:
        print(f"Search error: {e}")
        return jsonify({'error': f'Search failed: {str(e)[:50]}'}), 500

@app.route('/stream')
def stream():
    """Stream audio from YouTube"""
    video_id = request.args.get('id')
    if not video_id:
        return jsonify({'error': 'No video ID'}), 400
    
    print(f"Stream request for: {video_id}")
    
    try:
        # Check cache first
        if video_id in audio_cache:
            cache_time, audio_url = audio_cache[video_id]
            if time.time() - cache_time < 3600:  # 1 hour cache
                print(f"Using cached URL for {video_id}")
                return redirect_to_audio(audio_url)
        
        # Extract audio URL
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Get the best audio URL
            if 'url' in info:
                audio_url = info['url']
            else:
                # Try to find audio-only format
                formats = info.get('formats', [])
                audio_formats = [f for f in formats if f.get('vcodec') == 'none']
                if audio_formats:
                    # Prefer m4a format (better browser support)
                    m4a_formats = [f for f in audio_formats if f.get('ext') == 'm4a']
                    if m4a_formats:
                        audio_url = m4a_formats[0]['url']
                    else:
                        audio_url = audio_formats[0]['url']
                else:
                    # Fallback to any format
                    audio_url = info['formats'][0]['url']
            
            # Cache the URL
            audio_cache[video_id] = (time.time(), audio_url)
            
            print(f"Extracted audio URL: {audio_url[:100]}...")
            return redirect_to_audio(audio_url)
            
    except Exception as e:
        print(f"Stream extraction error: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Could not extract audio stream'}), 500

def redirect_to_audio(audio_url):
    """Redirect to the audio URL (simplest method)"""
    return Response(
        stream_with_context(requests.get(audio_url, stream=True).iter_content(chunk_size=8192)),
        content_type='audio/mp4'  # Most YouTube audio is m4a (mp4 container)
    )

@app.route('/download')
def download():
    """Download audio file"""
    video_id = request.args.get('id')
    title = request.args.get('title', 'audio')
    
    if not video_id:
        return jsonify({'error': 'No video ID'}), 400
    
    try:
        # Get audio URL (same as streaming)
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Find best audio format
            formats = info.get('formats', [])
            audio_formats = [f for f in formats if f.get('vcodec') == 'none']
            if audio_formats:
                audio_url = audio_formats[0]['url']
            else:
                audio_url = info['formats'][0]['url']
            
            # Clean filename
            safe_title = ''.join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
            filename = f"{safe_title or 'audio'}.mp3"
            
            # Stream the download
            req = requests.get(audio_url, stream=True)
            
            def generate():
                for chunk in req.iter_content(chunk_size=8192):
                    yield chunk
            
            response = Response(generate(), content_type='audio/mpeg')
            response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
            
    except Exception as e:
        print(f"Download error: {e}")
        return jsonify({'error': 'Download failed'}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'time': time.time()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)
