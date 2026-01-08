import os
import motor.motor_asyncio
from datetime import datetime

class Database:
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col_users = self.db.users
        self.col_batches = self.db.batches
        self.col_channels = self.db.channels
        self.col_settings = self.db.settings # New: To store admin state

    # --- USER & CHANNEL MANAGMENT ---
    async def add_user(self, user_id, first_name):
        await self.col_users.update_one(
            {"_id": user_id}, 
            {"$set": {"first_name": first_name, "last_active": datetime.now()}}, 
            upsert=True
        )

    async def get_force_sub_channels(self):
        return await self.col_channels.find().to_list(length=20)
    
    async def add_force_sub_channel(self, channel_id, invite_link):
        await self.col_channels.update_one({"_id": channel_id}, {"$set": {"invite_link": invite_link}}, upsert=True)

    async def remove_force_sub_channel(self, channel_id):
        await self.col_channels.delete_one({"_id": channel_id})

    # --- BATCH & FILE MANAGEMENT ---
    async def create_batch(self, batch_id, file_ids, caption=None):
        await self.col_batches.insert_one({
            "batch_id": batch_id,
            "file_ids": file_ids,
            "caption": caption,
            "views": 0,
            "created_at": datetime.now()
        })

    async def get_batch(self, batch_id):
        return await self.col_batches.find_one({"batch_id": batch_id})

    async def update_stats(self, batch_id):
        await self.col_batches.update_one({"batch_id": batch_id}, {"$inc": {"views": 1}})

    # --- ADMIN STATE MANAGEMENT (CRITICAL FOR VERCEL) ---
    async def set_admin_mode(self, user_id, mode, data=None):
        # mode: 'batch', 'normal', etc.
        # data: list of files for batch
        await self.col_settings.update_one(
            {"_id": "admin_state_" + str(user_id)},
            {"$set": {"mode": mode, "data": data or []}},
            upsert=True
        )

    async def get_admin_mode(self, user_id):
        doc = await self.col_settings.find_one({"_id": "admin_state_" + str(user_id)})
        return doc if doc else {"mode": "normal", "data": []}

    async def add_file_to_batch_state(self, user_id, file_id):
        await self.col_settings.update_one(
            {"_id": "admin_state_" + str(user_id)},
            {"$push": {"data": file_id}}
        )

# Init
MONGO_URL = os.getenv("MONGO_URL")
db = Database(MONGO_URL, "TelegramFileBot")
          
