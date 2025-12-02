from flask import Flask, render_template, request, jsonify, Response
import yt_dlp
import os

app = Flask(__name__)

PORT = int(os.environ.get('PORT', 8000))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search')
def search():
    """Simple search that returns dummy data for testing"""
    query = request.args.get('q', '').strip()
    
    # Return dummy/test data to see if frontend works
    dummy_results = [
        {
            'id': 'dQw4w9WgXcQ',  # Rick Astley - Never Gonna Give You Up
            'title': 'Never Gonna Give You Up',
            'uploader': 'Rick Astley',
            'thumbnail': 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg',
            'duration': '3:33'
        },
        {
            'id': 'kJQP7kiw5Fk',  # Luis Fonsi - Despacito
            'title': 'Despacito',
            'uploader': 'Luis Fonsi',
            'thumbnail': 'https://i.ytimg.com/vi/kJQP7kiw5Fk/hqdefault.jpg',
            'duration': '4:41'
        }
    ]
    
    # If query is provided, filter results
    if query:
        filtered = [r for r in dummy_results if query.lower() in r['title'].lower() or query.lower() in r['uploader'].lower()]
        return jsonify(filtered)
    
    return jsonify(dummy_results)

@app.route('/stream')
def stream():
    """Simplest possible streaming endpoint"""
    video_id = request.args.get('id')
    
    # Just return a direct YouTube audio URL (may not work due to CORS/blocking)
    # This is for testing only
    audio_url = f"https://rr1---sn-8pxuuxa-n8vl.googlevideo.com/videoplayback?key=yt6&id={video_id}&itag=140"
    
    # Return a redirect response
    return Response(
        f'Redirecting to audio stream...',
        status=302,
        headers={'Location': audio_url}
    )

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)
