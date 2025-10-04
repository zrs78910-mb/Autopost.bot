import json
import os
import requests
import time
from telegram import Bot, ChatAction
from telegram.error import Unauthorized, BadRequest

# --- कॉन्फ़िगरेशन (CONFIGURATION) ---
# GitHub Actions से सीक्रेट्स लोड करें
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GIST_ID = os.environ.get("GIST_ID")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# --- Gist में फाइलों के नाम ---
POST_FILENAME = "posts.txt"      # पोस्ट्स के लिए
CHANNELS_FILE = "/var/data/admin_channels.json" # चैनल लिस्ट के लिए

# ========= Gist हैंडलिंग फंक्शन =========
def get_gist_files():
    """Gist से सभी फाइलों का कंटेंट प्राप्त करता है।"""
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    url = f"https://api.github.com/gists/{GIST_ID}"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json()["files"]
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Gist: {e}")
        return {}

def update_gist_file(filename, content):
    """Gist में एक विशिष्ट फ़ाइल को अपडेट करता है।"""
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    url = f"https://api.github.com/gists/{GIST_ID}"
    data = {"files": {filename: {"content": content}}}
    try:
        response = requests.patch(url, headers=headers, json=data, timeout=15)
        response.raise_for_status()
        print(f"Successfully updated {filename} in Gist.")
    except requests.exceptions.RequestException as e:
        print(f"Error updating Gist: {e}")

# ========= चैनल मैनेजमेंट फंक्शन =========
def load_channels(gist_files):
    """Gist से एडमिन चैनलों की लिस्ट लोड करता है।"""
    if CHANNELS_FILENAME in gist_files:
        try:
            return json.loads(gist_files[CHANNELS_FILENAME]["content"])
        except json.JSONDecodeError:
            return []
    return []

def save_channels(channels):
    """चैनलों की लिस्ट को Gist में सेव करता है।"""
    update_gist_file(CHANNELS_FILENAME, json.dumps(list(set(channels)), indent=4))

# ========= पोस्टिंग फंक्शन =========
def parse_post_text(post_text):
    lines = post_text.strip().split('\n')
    if not lines or not lines[0].strip().lower().startswith('http'):
        return None, None
    image_url = lines[0].strip()
    caption = '\n'.join(lines[1:]).strip()
    return image_url, caption if caption else " "

def broadcast_post(bot: Bot, post_text: str, channels_to_post: list):
    """नए पोस्ट को दिए गए चैनलों पर भेजता है।"""
    image_url, caption = parse_post_text(post_text)
    if not image_url:
        print(f"Skipping invalid post format: {post_text[:50]}...")
        return channels_to_post # कोई बदलाव नहीं हुआ

    original_channels = list(channels_to_post)
    print(f"Broadcasting post to {len(channels_to_post)} channels...")
    
    for chat_id in original_channels:
        try:
            bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
            bot.send_photo(chat_id=chat_id, photo=image_url, caption=caption, timeout=60)
            print(f"Successfully posted to channel: {chat_id}")
            time.sleep(2)
        except Unauthorized:
            print(f"Unauthorized in {chat_id}. Removing channel.")
            if chat_id in channels_to_post:
                channels_to_post.remove(chat_id)
        except BadRequest as e:
            print(f"Bad Request for {chat_id}: {e}. Skipping.")
        except Exception as e:
            print(f"An unexpected error for {chat_id}: {e}")
    
    return channels_to_post # अपडेटेड लिस्ट लौटाएं

# ========= मुख्य लॉजिक =========
def main():
    if not all([TELEGRAM_BOT_TOKEN, GITHUB_TOKEN, GIST_ID]):
        print("Error: Missing one or more environment variables.")
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    # Gist से पिछला और वर्तमान कंटेंट प्राप्त करें
    gist_files = get_gist_files()
    if not gist_files:
        print("Could not fetch Gist files. Exiting.")
        return

    # चैनल मैनेजमेंट (यह अब वेबहुक के बिना काम नहीं करेगा, आपको मैन्युअल रूप से Gist में चैनल ID जोड़ने होंगे)
    # ऑटो-डिटेक्शन के लिए, आपको एक वेबहुक-आधारित बॉट की आवश्यकता होगी, जिसे Heroku जैसे प्लेटफॉर्म पर होस्ट किया जा सकता है।
    # अभी के लिए, आपको admin_channels.json फाइल Gist में खुद बनानी होगी।
    
    current_channels = load_channels(gist_files)
    if not current_channels:
        print("No channels found in Gist. Please add channel IDs to 'admin_channels.json' in your Gist.")

    # पोस्ट ब्रॉडकास्टिंग
    last_post_content = gist_files.get("last_run_posts.txt", {}).get("content", "")
    current_post_content = gist_files.get(POST_FILENAME, {}).get("content", "")

    if current_post_content and current_post_content != last_post_content:
        print("Gist content has changed. Broadcasting post.")
        updated_channels = broadcast_post(bot, current_post_content, current_channels)
        
        # अगर ब्रॉडकास्ट के दौरान कोई चैनल हटाया गया हो
        if updated_channels != current_channels:
            print("Channel list updated. Saving to Gist.")
            save_channels(updated_channels)
            
        # भविष्य की जाँच के लिए वर्तमान पोस्ट कंटेंट को सेव करें
        update_gist_file("last_run_posts.txt", current_post_content)
    else:
        print("No new post content found. Nothing to do.")

if __name__ == "__main__":
    main()
