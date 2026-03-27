import asyncio
import aiosqlite
import os

async def init_giveaways_db():
    os.makedirs("db", exist_ok=True)
    async with aiosqlite.connect("db/giveaways.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS Giveaways (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                channel_id  INTEGER NOT NULL,
                message_id  INTEGER NOT NULL UNIQUE,
                host_id     INTEGER NOT NULL,
                prize       TEXT    NOT NULL,
                winners     INTEGER NOT NULL DEFAULT 1,
                ends_at     REAL    NOT NULL,
                ended       INTEGER NOT NULL DEFAULT 0,
                config      TEXT    NOT NULL DEFAULT '{}',
                created_at  REAL    NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS GiveawayEntries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                giveaway_id INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                entered_at  REAL    NOT NULL,
                UNIQUE(giveaway_id, user_id),
                FOREIGN KEY(giveaway_id) REFERENCES Giveaways(id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS GiveawayWinners (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                giveaway_id INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                FOREIGN KEY(giveaway_id) REFERENCES Giveaways(id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS GiveawayTemplates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                name        TEXT    NOT NULL,
                data        TEXT    NOT NULL DEFAULT '{}',
                UNIQUE(guild_id, name)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS GiveawaySettings (
                guild_id            INTEGER PRIMARY KEY,
                manager_role_id     INTEGER,
                log_channel_id      INTEGER,
                default_color       TEXT    DEFAULT '#5865F2',
                dm_winners          INTEGER DEFAULT 1,
                ping_role_id        INTEGER
            )
        """)
        await db.commit()
    print("[DB] giveaways.db Completed!")

async def init_leveling_db():
    os.makedirs("db", exist_ok=True)
    async with aiosqlite.connect("db/leveling.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS leveling (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                level       INTEGER NOT NULL DEFAULT 0,
                xp          INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(guild_id, user_id)
            )
        """)
        await db.commit()
    print("[DB] leveling.db Completed!")

async def init_tracking_db():
    os.makedirs("db", exist_ok=True)
    async with aiosqlite.connect("db/tracking.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_activity (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                timestamp   REAL    NOT NULL
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_activity_guild_user
            ON user_activity(guild_id, user_id, timestamp)
        """)
        await db.commit()
    print("[DB] tracking.db Completed!")

async def init_all():
    print("[DB] Initializing databases...")
    await init_giveaways_db()
    await init_leveling_db()
    await init_tracking_db()
    print("[DB] All databases ready.\n")

if __name__ == "__main__":
    asyncio.run(init_all())
