import os
import threading
import subprocess
import requests
import json
import feedparser
import textwrap
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
from bing_image_downloader import downloader
from time import sleep
from flask import Flask, render_template, request, redirect, url_for
from pyngrok import ngrok

# Initialize Flask app
app = Flask(__name__)

# Ensure directories exist
output_dir = Path("images")
output_dir.mkdir(parents=True, exist_ok=True)
os.makedirs('static/images', exist_ok=True)

# Track processed keywords to avoid repetition
processed_keywords = set()

rss_feeds = [
    {"name": "General News", "url": "https://feeds.feedburner.com/NDTV-LatestNews"},
    {"name": "International News", "url": "https://www.thehindu.com/news/international/feeder/default.rss"},
    {"name": "Entertainment", "url": "https://www.thehindu.com/entertainment/movies/feeder/default.rss"},
    {"name": "Education", "url": "https://feeds.bbci.co.uk/news/education/rss.xml"},
    {"name": "Sports", "url": "https://timesofindia.indiatimes.com/rssfeeds/913168846.cms"},
    {"name": "Science", "url": "https://moxie.foxnews.com/google-publisher/science.xml"},
    {"name": "Business", "url": "https://b2b.economictimes.indiatimes.com/rss/news.xml"}
]

# Start Ollama server
def ollama_server():
    print("🟠 Starting Ollama server...")
    os.environ['OLLAMA_HOST'] = '0.0.0.0:11434'
    os.environ['OLLAMA_ORIGINS'] = '*'
    subprocess.Popen(["ollama", "serve"])
    print("🟢 Ollama server started")

# Get response from Ollama API
def get_ollama_response(prompt_text, max_retries=3):
    """Robust API communication with retries and validation"""
    url = 'http://localhost:11434/api/generate'
    data = {
        "model": "deepseek-r1:8b",
        "prompt": prompt_text,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.3, "top_p": 0.9}
    }

    for attempt in range(max_retries):
        print(f"\n📤 Attempt {attempt+1}/{max_retries} - Sending request...")
        try:
            response = requests.post(url, json=data, timeout=30)
            response.raise_for_status()
            json_response = response.json()

            if 'response' not in json_response:
                print(f"⚠️ Unexpected response format: {json_response}")
                continue

            print(f"📥 Received response: {json_response['response'][:200]}...")
            return json_response['response']

        except requests.exceptions.RequestException as e:
            print(f"🔴 Connection error: {str(e)}")
            if attempt < max_retries - 1:
                sleep(2)
        except json.JSONDecodeError:
            print("🔴 Invalid JSON response")
        except Exception as e:
            print(f"🔴 Unexpected error: {str(e)}")

    print("⏭️ Max retries reached. Giving up.")
    return None

# Create news image with text overlay
def create_news_image(text, keyword, filename):
    """Create an image with text overlay and proper image handling"""
    print(f"\n🖼️ Creating image for keyword: {keyword}")

    # Ensure a single keyword for search
    keyword = str(keyword).split(',')[0].strip()[:25]  # Take first keyword and limit length
    keyword = ''.join(c for c in keyword if c.isalnum() or c in (' ', '-', '_'))  # Sanitize

    try:
        # Download two images using Bing Image Downloader
        print(f"🔍 Searching images for: {keyword}")
        downloader.download(
            f"{keyword}",
            limit=2,  # Download two images
            output_dir=str(output_dir),  # Use string path for compatibility
            adult_filter_off=True,
            force_replace=False,
            timeout=30
        )

        # Find downloaded images
        img_dir = output_dir / keyword
        images = list(img_dir.glob('*'))
        if images:
            # Select a random image from the downloaded images
            image_path = random.choice(images)
            print(f"✅ Selected image at: {image_path}")
            img = Image.open(image_path).convert('RGB')
        else:
            raise FileNotFoundError("No images downloaded")

    except Exception as e:
        print(f"🔴 Image download failed: {str(e)}")
        print("⚠️ Using fallback background")
        img = Image.new('RGB', (600, 1000), color=(255, 255, 255))  # White background as fallback

    # Create a white blank canvas
    canvas_width, canvas_height = 600, 1000
    canvas = Image.new('RGB', (canvas_width, canvas_height), color=(255, 255, 255))

    # Resize the image to have height 1000 while maintaining aspect ratio
    img_ratio = img.width / img.height
    new_height = 1000
    new_width = int(img_ratio * new_height)
    img = img.resize((new_width, new_height), Image.LANCZOS)

    # If the resized image width is greater than 600, center-crop it
    if new_width > canvas_width:
        left = (new_width - canvas_width) // 2
        right = left + canvas_width
        img = img.crop((left, 0, right, new_height))
    else:
        # If the width is less than 600, paste it centered on the white canvas
        paste_x = (canvas_width - new_width) // 2
        paste_y = 0  # Top aligned
        canvas.paste(img, (paste_x, paste_y))
        img = canvas

    # If the image width is exactly 600, use it as is
    if img.width == canvas_width:
        canvas = img

    # Continue with the image-processing steps
    # Create a transparent black overlay
    overlay = Image.new('RGBA', canvas.size, (0, 0, 0, 128))  # 50% transparency
    canvas = canvas.convert('RGBA')
    canvas.paste(overlay, (0, 0), overlay)

    # Prepare text
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("/content/fonts/Muroslant.otf", 36)
    except:
        font = ImageFont.load_default()

    # Wrap text to fit within 600px width, adjust the width value as needed
    wrapped_text = textwrap.wrap(text, width=40)  # Adjust to fit within 600px width

    # Calculate text position (centered)
    text_height = sum(draw.textbbox((0, 0), line, font=font)[3] for line in wrapped_text)
    y = (canvas_height - text_height) // 2  # Center vertically in 1000px height

    # Draw each line of text (centered horizontally)
    for line in wrapped_text:
        text_width = draw.textbbox((0, 0), line, font=font)[2]
        x = (canvas_width - text_width) // 2  # Center horizontally in 600px width
        draw.text((x, y), line, font=font, fill="white")
        y += draw.textbbox((0, 0), line, font=font)[3] + 5

    # Save the final image
    canvas = canvas.convert('RGB')  # Remove alpha for saving in JPG format
    canvas.save(f"static/images/{filename}")
    print(f"✅ Saved image: static/images/{filename}")

from gtts import gTTS
import os

# Ensure the audio directory exists
os.makedirs('static/images', exist_ok=True)

# Function to create audio files
def create_audio(text, filename):
    """Create an audio file from text using gTTS"""
    try:
        tts = gTTS(text=text, lang='en')
        tts.save(f"static/images/{filename}.mp3")
        print(f"✅ Saved audio: static/audio/{filename}.mp3")
    except Exception as e:
        print(f"🔴 Audio creation failed: {str(e)}")

# Modify the process_rss_entries function to include audio creation
def process_rss_entries(rss_url):
    """Enhanced RSS processing with better validation"""
    print(f"\n📰 Processing RSS feed: {rss_url}")
    try:
        print("🔍 Fetching RSS entries...")
        feed = feedparser.parse(rss_url)

        if feed.bozo:
            print(f"🔴 RSS parsing error: {feed.bozo_exception}")
            return

        entries = feed.entries[:5]
        print(f"✅ Found {len(entries)} entries")

        for i, entry in enumerate(entries):
            print(f"\n📄 Processing entry {i+1}/{len(entries)}")
            title = entry.get('title', '').strip()
            description = entry.get('description', '').strip()

            if not title and not description:
                print("⏭️ Skipping empty entry")
                continue

            print(f"📝 Title: {title[:50]}...")
            print(f"📝 Description: {description[:50]}...")

            prompt = """Generate JSON with:
            - "text": short single line 1-line summary (plain text)
            - "keyword": A single term (2 words max) closely related to the text, prioritizing the inclusion of a person's name if mentioned.

            News:
            Title: {title}
            Description: {description}

            JSON:""".format(title=title, description=description)

            output = get_ollama_response(prompt)
            if not output:
                continue

            try:
                print("🔨 Parsing response...")
                result = json.loads(output)
                print(output)

                if not all(k in result for k in ['text', 'keyword']):
                    raise ValueError("Missing required fields")

                keyword = result['keyword']
                if keyword in processed_keywords:
                    print(f"🔁 Keyword '{keyword}' already processed. Skipping to avoid repetition.")
                    continue  # Skip processing if keyword has been used

                processed_keywords.add(keyword)  # Mark keyword as processed

                print(f"📋 Summary: {result['text']}")
                print(f"🔑 Keyword: {keyword}")
                create_news_image(
                    result['text'],
                    keyword,
                    f"news_summary_{i+1}.jpg"
                )
                create_audio(result['text'], f"news_summary_{i+1}")  # Create audio file

            except json.JSONDecodeError:
                print(f"🔴 Invalid JSON: {output}")
            except Exception as e:
                print(f"🔴 Processing error: {str(e)}")

    except Exception as e:
        print(f"🔴 RSS processing failed: {str(e)}")
# Flask routes
@app.route('/')
def index():
    return render_template('index.html', rss_feeds=rss_feeds)

@app.route('/process', methods=['POST'])
def process_feed():
    selected_index = int(request.form['feed']) - 1
    selected_url = rss_feeds[selected_index]['url']
    processed_keywords.clear()
    
    # Clear previous images
    for f in Path('static/images').glob('*.jpg'):
        f.unlink()
    
    process_rss_entries(selected_url)
    return redirect(url_for('gallery'))

@app.route('/gallery')
def gallery():
    images = sorted(Path('static/images').glob('*.jpg'), key=os.path.getmtime)
    return render_template('gallery.html', images=images)

# Main entry point
if __name__ == "__main__":
    # Start Ollama server in a separate thread
    ollama_thread = threading.Thread(target=ollama_server)
    ollama_thread.start()
    sleep(5)

    # Start ngrok tunnel
    public_url = ngrok.connect(5000)
    print(f"🌐 Public URL: {public_url}")

    # Run Flask app
    app.run(host="0.0.0.0", port=5000)
