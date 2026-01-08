import os
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaDocument
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from .database import db

ADMIN_ID = int(os.getenv("ADMIN_ID"))
BACKUP_CHANNEL = int(os.getenv("BACKUP_CHANNEL_ID")) # Compulsory Backup

# --- UTILS ---
async def is_subscribed(user_id, bot):
    channels = await db.get_force_sub_channels()
    not_joined = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch["_id"], user_id=user_id)
            if member.status in ['left', 'kicked']:
                not_joined.append(ch)
        except BadRequest:
            continue
    return not_joined

# --- USER HANDLERS ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.add_user(user.id, user.first_name)
    
    args = context.args
    payload = args[0] if args else None

    # Force Sub Check
    pending = await is_subscribed(user.id, context.bot)
    if pending:
        btns = [[InlineKeyboardButton("Join Here", url=ch["invite_link"])] for ch in pending]
        
        # Reconstruction of deep link for "Try Again"
        url_suffix = f"?start={payload}" if payload else ""
        try_url = f"https://t.me/{context.bot.username}{url_suffix}"
        
        btns.append([InlineKeyboardButton("🔄 Try Again", url=try_url)])
        await update.message.reply_text("⚠️ **Please join our channels first!**", reply_markup=InlineKeyboardMarkup(btns), parse_mode="Markdown")
        return

    # Deliver Content
    if payload and payload.startswith("batch_"):
        batch_id = payload.replace("batch_", "")
        data = await db.get_batch(batch_id)
        if data:
            await db.update_stats(batch_id)
            files = data['file_ids']
            caption = data.get('caption', f"📁 **Batch:** {batch_id}")
            
            if len(files) == 1:
                await context.bot.send_document(chat_id=user.id, document=files[0], caption=caption, parse_mode="Markdown")
            else:
                # Send in chunks of 10
                for i in range(0, len(files), 10):
                    chunk = files[i:i+10]
                    media = [InputMediaDocument(f) for f in chunk]
                    # Attach caption only to the first item of the first chunk
                    if i == 0: media[0].parse_mode = "Markdown"; media[0].caption = caption
                    await context.bot.send_media_group(chat_id=user.id, media=media)
        else:
            await update.message.reply_text("❌ Link Expired.")
    else:
        await update.message.reply_text(f"👋 Welcome {user.first_name}!\nI am a bot to store and share files.")

# --- ADMIN HANDLERS ---

async def file_receiver_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    1. Forward to Backup Channel (Compulsory).
    2. Check if Admin is in Batch Mode (via MongoDB).
    3. Save/Reply.
    """
    msg = update.message
    user_id = msg.from_user.id
    
    if user_id != ADMIN_ID: return

    # Extract File ID
    file_id = None
    if msg.document: file_id = msg.document.file_id
    elif msg.video: file_id = msg.video.file_id
    elif msg.audio: file_id = msg.audio.file_id
    elif msg.photo: file_id = msg.photo[-1].file_id
    
    if not file_id: return

    # 1. COMPULSORY BACKUP (Forward to Channel)
    try:
        backup_msg = await context.bot.forward_message(chat_id=BACKUP_CHANNEL, from_chat_id=user_id, message_id=msg.message_id)
        # OPTIONAL: Use the file_id from the backup channel (safer persistence)
        # file_id = backup_msg.document.file_id 
    except Exception as e:
        await msg.reply_text(f"⚠️ **Backup Failed:** {e}\nCheck channel permissions!")
        return

    # 2. Check Admin State in Mongo
    state = await db.get_admin_mode(user_id)
    
    if state["mode"] == "batch":
        await db.add_file_to_batch_state(user_id, file_id)
        current_count = len(state["data"]) + 1
        await msg.reply_text(f"➕ Added to Batch. (Total: {current_count})")
    else:
        # Instant Single Link
        batch_id = str(uuid.uuid4())[:8]
        await db.create_batch(batch_id, [file_id], caption=msg.caption)
        link = f"https://t.me/{context.bot.username}?start=batch_{batch_id}"
        
        # Admin Tools Reply
        await msg.reply_text(
            f"✅ **File Saved & Backed Up!**\n\n🔗 `{link}`\n\nReply with `/publish <channel_id>` to post this.",
            parse_mode="Markdown"
        )

async def cmd_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Controls Batch Mode: /batch start, /batch done"""
    if update.effective_user.id != ADMIN_ID: return
    
    args = context.args
    if not args:
        await update.message.reply_text("Usage:\n`/batch start` - Start collecting files\n`/batch done` - Create link", parse_mode="Markdown")
        return

    action = args[0].lower()
    user_id = update.effective_user.id
    
    if action == "start":
        await db.set_admin_mode(user_id, "batch")
        await update.message.reply_text("🟢 **Batch Mode ON**.\nSend your files now. They will be auto-backed up.")
        
    elif action == "done":
        state = await db.get_admin_mode(user_id)
        if state["mode"] != "batch" or not state["data"]:
            await update.message.reply_text("⚠️ You are not in batch mode or no files sent.")
            return
            
        files = state["data"]
        batch_id = str(uuid.uuid4())[:8]
        await db.create_batch(batch_id, files, caption="Batch Collection")
        
        # Reset mode
        await db.set_admin_mode(user_id, "normal")
        
        link = f"https://t.me/{context.bot.username}?start=batch_{batch_id}"
        await update.message.reply_text(f"🏁 **Batch Created!** ({len(files)} files)\n🔗 `{link}`\n\nReply with `/publish <channel_id>` to post.", parse_mode="Markdown")
        
    elif action == "cancel":
        await db.set_admin_mode(user_id, "normal")
        await update.message.reply_text("❌ Batch cancelled.")

async def cmd_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Reply to a bot message containing a link to broadcast it to a channel.
    Usage: Reply to message -> /publish -10012345678 Custom Caption
    """
    if update.effective_user.id != ADMIN_ID: return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Reply to a message containing the link/file you want to publish.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("⚠️ Usage: `/publish <channel_id> <Optional Caption>`", parse_mode="Markdown")
        return

    try:
        channel_id = int(args[0])
        custom_caption = " ".join(args[1:]) if len(args) > 1 else None
        
        reply_msg = update.message.reply_to_message.text or update.message.reply_to_message.caption
        
        # Attempt to extract link
        link = None
        if "t.me/" in reply_msg:
            # Simple extraction of the first link found
            import re
            links = re.findall(r'(https?://t\.me/\S+)', reply_msg)
            if links: link = links[0]

        if not link:
            await update.message.reply_text("❌ Could not find a link in the replied message.")
            return

        # Prepare the message
        text_to_send = f"{custom_caption}\n\n📥 **Download:** [Click Here]({link})" if custom_caption else f"🎬 **New File Uploaded**\n\n📥 **Download:** [Click Here]({link})"
        
        # Check if user replied to a photo to use as thumbnail
        if update.message.reply_to_message.photo:
            photo_id = update.message.reply_to_message.photo[-1].file_id
            await context.bot.send_photo(chat_id=channel_id, photo=photo_id, caption=text_to_send, parse_mode="Markdown")
        else:
            # Text only
            await context.bot.send_message(chat_id=channel_id, text=text_to_send, parse_mode="Markdown")

        await update.message.reply_text(f"✅ Posted to `{channel_id}`!")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    txt = (
        "🛠 **Admin Commands**\n"
        "-------------------\n"
        "• `/batch start` - Start batch\n"
        "• `/batch done` - Finish batch\n"
        "• `/addchannel <id> <link>` - Add force sub\n"
        "• `/publish <id> <caption>` - Post (Reply to link)\n"
        "• `/stat <batch_id>` - Check views"
    )
    await update.message.reply_text(txt, parse_mode="Markdown")
  
