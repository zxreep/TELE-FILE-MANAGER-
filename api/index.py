import os
import asyncio
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# Import core modules
from core.handlers import start_handler, file_receiver, cmd_batch, cmd_add_channel, stats_handler
from core.database import db

# Env Variables
TOKEN = os.getenv("BOT_TOKEN")

app = FastAPI()

# Initialize Bot App (Global to reuse in serverless context if possible)
ptb_app = Application.builder().token(TOKEN).build()

# Add Handlers
ptb_app.add_handler(CommandHandler("start", start_handler))
ptb_app.add_handler(CommandHandler("batch", cmd_batch))
ptb_app.add_handler(CommandHandler("addchannel", cmd_add_channel))
ptb_app.add_handler(CommandHandler("stat", stats_handler))
ptb_app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO, file_receiver))
ptb_app.add_handler(CommandHandler("start", start_handler))
ptb_app.add_handler(CommandHandler("batch", cmd_batch))
ptb_app.add_handler(CommandHandler("publish", cmd_publish))  # NEW
ptb_app.add_handler(CommandHandler("admin", cmd_admin))      # NEW
@app.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Vercel sends the update here. We feed it to python-telegram-bot.
    """
    try:
        data = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        
        # Initialize the app for this request
        await ptb_app.initialize()
        
        # Process the update
        await ptb_app.process_update(update)
        
        return {"status": "ok"}
    except Exception as e:
        # In production, send this error to the admin Log Channel
        print(f"Error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/")
def index():
    return {"status": "Bot is running"}
    
