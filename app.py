from flask import Flask, render_template, request, jsonify, Response, redirect
import requests
import time
import json
import os
from urllib.parse import quote

app = Flask(__name__)

# Use Koyeb's port
PORT = int(os.environ.get('PORT', 8000))

# External MP3 conversion APIs (free tier)
MP3_API_ENDPOINTS = [
    "https://co.wuk.sh/api/json",
    "https://yt5s.com/api/ajaxSearch/index",
    "https://api.dlyoutube.com/api/converter",
]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search')
def search():
    """Search YouTube using external API"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'No query'}), 400
    
    try:
        # Using YouTube Data API via RapidAPI (free alternative)
        # You can get a free API key from: https://rapidapi.com/ytdlfree/api/youtube-v3-alternative
        headers = {
            'X-RapidAPI-Key': 'your-free-api-key-here',  # Get from RapidAPI
            'X-RapidAPI-Host': 'youtube-v3-alternative.p.rapidapi.com'
        }
        
        response = requests.get(
            f'https://youtube-v3-alternative.p.rapidapi.com/search?query={quote(query)}&type=video',
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            results = []
            
            for item in data.get('data', [])[:10]:  # Limit to 10 results
                video_id = item.get('videoId')
                if video_id:
                    results.append({
                        'id': video_id,
                        'title': item.get('title', 'Unknown')[:100],
                        'uploader': item.get('channelTitle', 'Unknown')[:50],
                        'thumbnail': item.get('thumbnail', [{}])[0].get('url', 
                                   f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'),
                        'duration': format_duration(item.get('lengthSeconds', 0))
                    })
            
            return jsonify(results)
        else:
            # Fallback to returning some popular songs
            return jsonify(get_fallback_results(query))
            
    except Exception as e:
        print(f"Search error: {e}")
        return jsonify(get_fallback_results(query))

def format_duration(seconds):
    """Format seconds to MM:SS"""
    if not seconds:
        return 'N/A'
    try:
        seconds = int(seconds)
        m, s = divmod(seconds, 60)
        return f"{m}:{s:02d}"
    except:
        return 'N/A'

def get_fallback_results(query):
    """Fallback results when API fails"""
    fallback_songs = [
        {
            'id': 'dQw4w9WgXcQ',
            'title': 'Never Gonna Give You Up',
            'uploader': 'Rick Astley',
            'thumbnail': 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg',
            'duration': '3:33'
        },
        {
            'id': 'kJQP7kiw5Fk',
            'title': 'Despacito',
            'uploader': 'Luis Fonsi',
            'thumbnail': 'https://i.ytimg.com/vi/kJQP7kiw5Fk/hqdefault.jpg',
            'duration': '4:41'
        },
        {
            'id': '09R8_2nJtjg',
            'title': 'Shape of You',
            'uploader': 'Ed Sheeran',
            'thumbnail': 'https://i.ytimg.com/vi/09R8_2nJtjg/hqdefault.jpg',
            'duration': '4:24'
        }
    ]
    
    if query:
        filtered = [song for song in fallback_songs 
                   if query.lower() in song['title'].lower() 
                   or query.lower() in song['uploader'].lower()]
        return filtered if filtered else fallback_songs[:2]
    
    return fallback_songs[:2]

@app.route('/stream')
def stream():
    """Get MP3 stream URL using external conversion service"""
    video_id = request.args.get('id')
    
    if not video_id:
        return jsonify({'error': 'No video ID'}), 400
    
    try:
        # Method 1: Use y2mate-style API
        mp3_url = get_mp3_from_api(video_id)
        
        if mp3_url:
            # Redirect to the MP3 URL (browser will play it directly)
            return redirect(mp3_url, code=302)
        
        # Method 2: Use alternative service
        mp3_url = get_mp3_from_alternative(video_id)
        if mp3_url:
            return redirect(mp3_url, code=302)
        
        # Method 3: Return a dummy audio for testing
        return jsonify({
            'error': 'Could not convert to MP3',
            'alternative': f'https://your-app-name.koyeb.app/download?id={video_id}'
        }), 500
        
    except Exception as e:
        print(f"Stream error: {e}")
        return jsonify({'error': 'Stream service unavailable'}), 500

def get_mp3_from_api(video_id):
    """Get MP3 URL from y2mate-style API"""
    try:
        # Try y2mate API
        response = requests.post(
            'https://api.y2mate.guru/api/convert',
            json={'url': f'https://youtu.be/{video_id}', 'format': 'mp3'},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'url' in data:
                return data['url']
    except:
        pass
    
    # Try another API
    try:
        response = requests.get(
            f'https://api.dlyoutube.com/api/converter/getFormats?videoId={video_id}',
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            if 'url' in data:
                return data['url']
    except:
        pass
    
    return None

def get_mp3_from_alternative(video_id):
    """Alternative method to get MP3"""
    try:
        # Use onlinevideoconverter API
        response = requests.post(
            'https://onlinevideoconverter.pro/api/convert',
            data={'url': f'https://www.youtube.com/watch?v={video_id}', 'format': 'mp3'},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'downloadUrl' in data:
                return data['downloadUrl']
    except:
        pass
    
    return None

@app.route('/download')
def download():
    """Download MP3 file"""
    video_id = request.args.get('id')
    title = request.args.get('title', 'song')
    
    if not video_id:
        return jsonify({'error': 'No video ID'}), 400
    
    try:
        # Get MP3 URL
        mp3_url = get_mp3_from_api(video_id)
        
        if not mp3_url:
            mp3_url = get_mp3_from_alternative(video_id)
        
        if mp3_url:
            # Fetch the MP3 file
            response = requests.get(mp3_url, stream=True, timeout=30)
            
            # Clean filename
            safe_title = ''.join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
            filename = f"{safe_title or 'song'}.mp3"
            
            return Response(
                response.iter_content(chunk_size=8192),
                content_type='audio/mpeg',
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Content-Length': response.headers.get('content-length', '')
                }
            )
        else:
            return jsonify({'error': 'Could not generate download link'}), 500
            
    except Exception as e:
        print(f"Download error: {e}")
        return jsonify({'error': 'Download service unavailable'}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': time.time()})

@app.route('/play/<video_id>')
def direct_play(video_id):
    """Direct play using iframe embedding"""
    return f'''
    <html>
    <head><title>Direct Play</title></head>
    <body style="margin:0;padding:0;">
        <iframe width="100%" height="100%" 
                src="https://www.youtube.com/embed/{video_id}?autoplay=1&controls=1"
                frameborder="0" 
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowfullscreen>
        </iframe>
    </body>
    </html>
    '''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)
