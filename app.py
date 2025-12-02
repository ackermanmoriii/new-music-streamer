from flask import Flask, render_template, request, jsonify
import yt_dlp
import time
from threading import Lock

app = Flask(__name__)

# --- YT-DLP CONFIGS ---
SEARCH_OPTS = {
    "format": "bestaudio/best",
    "extract_flat": True,
    "noplaylist": True,
    "quiet": True,
    "geo_bypass": True,
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
        "Referer": "https://www.youtube.com/"
    },
    "extractor_args": {
        "youtube": {
            "player_client": ["android"]
        }
    }
}


DIRECT_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "geo_bypass": True,
    "http_headers": {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.5",
        "Sec-Fetch-Mode": "navigate",
        "Referer": "https://www.youtube.com/"
    },
    "extractor_args": {
        "youtube": {
            "player_client": ["android"]
        }
    }
}


# Caches to reduce API usage & improve speed
search_cache = {}
url_cache = {}
cache_lock = Lock()
CACHE_LIFETIME = 1800  # 30 minutes


def format_duration(seconds):
    if not seconds:
        return "N/A"
    try:
        seconds = int(seconds)
        m, s = divmod(seconds, 60)
        return f"{m}:{s:02d}"
    except:
        return str(seconds)


# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/search")
def search():
    query = request.args.get("q", "").strip().lower()
    if not query:
        return jsonify({"error": "No query provided"}), 400

    # CACHE CHECK
    with cache_lock:
        if query in search_cache:
            ts, data = search_cache[query]
            if time.time() - ts < CACHE_LIFETIME:
                return jsonify(data)
            else:
                del search_cache[query]

    # LIVE SEARCH
    try:
        with yt_dlp.YoutubeDL(SEARCH_OPTS) as ydl:
            result = ydl.extract_info(f"ytsearch15:{query}", download=False)
            items = []

            if "entries" in result:
                for e in result["entries"]:
                    items.append({
                        "id": e["id"],
                        "title": e["title"],
                        "uploader": e.get("uploader", "Unknown"),
                        "thumbnail": e.get("thumbnail") or f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg",
                        "duration": format_duration(e.get("duration"))
                    })

            with cache_lock:
                search_cache[query] = (time.time(), items)

            return jsonify(items)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -----------------------------
# GET DIRECT AUDIO URL
# -----------------------------
@app.route("/direct")
def direct():
    video_id = request.args.get("id", None)
    if not video_id:
        return jsonify({"error": "Missing ID"}), 400

    # Cache check
    with cache_lock:
        if video_id in url_cache:
            ts, url = url_cache[video_id]
            if time.time() - ts < 15000:
                return jsonify({"url": url})

    # Extract fresh audio URL
    try:
        with yt_dlp.YoutubeDL(DIRECT_OPTS) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            real_url = info["url"]

            with cache_lock:
                url_cache[video_id] = (time.time(), real_url)

            return jsonify({"url": real_url})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -----------------------------
# LOCAL DEVELOPMENT
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
