import json
import time
import requests
import os
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, CallbackContext, ChatMemberHandler
from telegram.chataction import ChatAction
from telegram.error import BadRequest, Unauthorized

# --- CONFIGURATION ---
GITHUB_TOKEN = "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"
GIST_ID = "5fbe77db76d9da282289ef89247d97f4"
TELEGRAM_BOT_TOKEN = "8231679051:AAFoqLilEuYVXe8oXFNZmIDvHydE5EzqvyU"
MONITORING_INTERVAL = 15 # Increased interval to avoid Telegram API limits

# --- File to save the channel list ---
CHANNELS_FILE = "admin_channels.json"

# --- GLOBAL VARIABLE ---
last_gist_content = None

# ========= File Handling Functions =========
def load_channels():
    """Loads the list of admin channels from the JSON file."""
    if not os.path.exists(CHANNELS_FILE):
        return []
    try:
        with open(CHANNELS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def save_channels(channels):
    """Saves the list of channels to the JSON file."""
    with open(CHANNELS_FILE, 'w') as f:
        json.dump(list(set(channels)), f, indent=4) # Save unique channels

# ========= Gist and Posting Functions =========
def get_gist_content():
    """Fetches the content of the first file in the Gist."""
    headers = {"Authorization": "token " + GITHUB_TOKEN, "Accept": "application/vnd.github.v3+json"}
    url = f"https://api.github.com/gists/{GIST_ID}"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        gist_data = response.json()
        filename = list(gist_data["files"].keys())[0]
        return gist_data["files"][filename]["content"]
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Gist: {e}")
        return None

def parse_post_text(post_text):
    """Parses the post text into an image URL and a caption."""
    lines = post_text.strip().split('\n')
    if not lines or not lines[0].strip().lower().startswith('http'):
        return None, None
    image_url = lines[0].strip()
    caption = '\n'.join(lines[1:]).strip()
    return image_url, caption if caption else " "

def broadcast_post(bot: Bot, post_text: str):
    """This function sends the new post to all registered channels."""
    channels_to_post = load_channels()
    if not channels_to_post:
        print("No channels registered to post to.")
        return

    image_url, caption = parse_post_text(post_text)
    if not image_url:
        print(f"Skipping invalid post format: {post_text[:50]}...")
        return
    
    print(f"Broadcasting post to {len(channels_to_post)} channels...")
    for chat_id in channels_to_post:
        try:
            bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
            bot.send_photo(
                chat_id=chat_id,
                photo=image_url,
                caption=caption,
                timeout=60
            )
            print(f"Successfully posted to channel: {chat_id}")
            time.sleep(2) # 2-second gap between posts to avoid API limits
        except Unauthorized:
            print(f"Unauthorized to post in {chat_id}. Bot might have been kicked or lost admin rights. Removing channel.")
            remove_channel(chat_id)
        except BadRequest as e:
            print(f"Bad Request for channel {chat_id}: {e}. Maybe the image URL is invalid. Skipping this channel for this post.")
        except Exception as e:
            print(f"An unexpected error occurred for channel {chat_id}: {e}")

# ========= Bot Commands and Handlers =========
def start(update: Update, context: CallbackContext):
    """/start command (only works in private messages)."""
    if update.effective_chat.type == 'private':
        channels = load_channels()
        if channels:
            message = "✅ Bot is active!\nI will automatically post updates to the following channels:\n"
            for channel_id in channels:
                message += f"- `{channel_id}`\n"
            message += "\nUse /post to manually trigger the latest post from Gist."
        else:
            message = "ℹ️ Bot is active, but no channels are registered yet.\nMake me an admin in a channel with 'Post Messages' permission to register it."
        update.message.reply_text(message, parse_mode="Markdown")

def post_command(update: Update, context: CallbackContext):
    """Manually triggers a broadcast of the latest Gist content."""
    if update.effective_chat.type != 'private':
        update.message.reply_text("This command can only be used in a private chat with the bot.")
        return
        
    update.message.reply_text("Fetching latest content from Gist and broadcasting to all channels...")
    
    post_content = get_gist_content()
    
    if post_content:
        broadcast_post(context.bot, post_content)
        update.message.reply_text("✅ Broadcast complete!")
    else:
        update.message.reply_text("❌ Could not fetch content from Gist. Please check the logs.")


def handle_chat_member_updates(update: Update, context: CallbackContext):
    """
    This function tracks when the bot is made an admin or removed.
    """
    my_member = update.my_chat_member
    if my_member is None:
        return
        
    chat = my_member.chat
    new_status = my_member.new_chat_member.status
    
    if chat.type == 'channel':
        channels = load_channels()
        
        # When the bot becomes an admin with post permissions
        if new_status == 'administrator' and my_member.new_chat_member.can_post_messages:
            if chat.id not in channels:
                print(f"Bot promoted to Admin in channel: {chat.id} ({chat.title}). Adding to list.")
                channels.append(chat.id)
                save_channels(channels)
        
        # When the bot is no longer an admin (removed or permissions changed)
        elif new_status in ['member', 'left', 'kicked']:
            if chat.id in channels:
                print(f"Bot is no longer an admin in channel: {chat.id} ({chat.title}). Removing from list.")
                channels.remove(chat.id)
                save_channels(channels)

def remove_channel(channel_id):
    """Removes a channel from the list (if an error occurs during posting)."""
    channels = load_channels()
    if channel_id in channels:
        channels.remove(channel_id)
        save_channels(channels)

def monitor_gist(context: CallbackContext):
    """Periodically checks the Gist and broadcasts new posts."""
    global last_gist_content
    
    current_gist_content = get_gist_content()

    if current_gist_content is not None:
        if last_gist_content is None:
            last_gist_content = current_gist_content
            return

        if last_gist_content != current_gist_content:
            print("Gist updated. Broadcasting new content...")
            broadcast_post(context.bot, current_gist_content)
            
            last_gist_content = current_gist_content

def main():
    """Starts the bot."""
    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Add command handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("post", post_command)) # ADDED THE NEW /post COMMAND HANDLER
    
    # This handler detects changes in the bot's status in a channel
    dispatcher.add_handler(ChatMemberHandler(handle_chat_member_updates, ChatMemberHandler.MY_CHAT_MEMBER))
    
    job_queue = updater.job_queue
    job_queue.run_repeating(monitor_gist, interval=MONITORING_INTERVAL, first=10)

    updater.start_polling(allowed_updates=Update.MY_CHAT_MEMBER) # Only poll for necessary updates
    print("Bot started! It will now auto-detect admin channels and broadcast new posts.")
    updater.idle()

if __name__ == "__main__":
    main()