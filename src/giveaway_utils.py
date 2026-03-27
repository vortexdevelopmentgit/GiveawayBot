import json
import datetime
import aiosqlite
from typing import Dict, Any, Tuple, List, Optional

def validate_giveaway_duration(duration_str: str) -> Tuple[bool, int, str]:
    time_units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

    if not duration_str or len(duration_str) < 2:
        return False, 0, "Duration must be at least 2 characters (e.g. `1h`)."

    unit = duration_str[-1].lower()
    if unit not in time_units:
        return False, 0, "Invalid time unit. Use: `s`, `m`, `h`, `d`, `w`."

    try:
        value = int(duration_str[:-1])
        if value <= 0:
            return False, 0, "Il valore deve essere positivo."
    except ValueError:
        return False, 0, "Valore numerico non valido."

    seconds = value * time_units[unit]

    if seconds < 60:
        return False, 0, "Minimum duration is **1 minute**."
    if seconds > 2678400:
        return False, 0, "Maximum duration is **31 days**."

    return True, seconds, "ok"

def parse_hex_color(color_input: str) -> int:
    if not color_input:
        return 0x5865F2

    color_input = color_input.lower().strip()

    # Color Map
    color_map = {
        "red": 0xFF0000, "green": 0x00FF00, "blue": 0x0000FF,
        "yellow": 0xFFFF00, "purple": 0x800080, "orange": 0xFFA500,
        "pink": 0xFFC0CB, "cyan": 0x00FFFF, "white": 0xFFFFFF,
        "black": 0x000000, "gold": 0xFFD700, "silver": 0xC0C0C0,
        "gray": 0x808080, "grey": 0x808080, "lime": 0x32CD32,
        "navy": 0x000080, "teal": 0x008080, "blurple": 0x5865F2,
    }

    if color_input in color_map:
        return color_map[color_input]

    color_input = color_input.lstrip("#")
    try:
        return int(color_input, 16)
    except ValueError:
        return 0x5865F2

def format_duration(seconds: int) -> str:
    
    units = [
        ("week",   "weeks",   604800),
        ("day",    "days",    86400),
        ("hour",   "hours",   3600),
        ("minute", "minutes", 60),
        ("second", "seconds", 1),
    ]
    parts = []
    for sing, plur, u in units:
        if seconds >= u:
            n = seconds // u
            seconds %= u
            parts.append(f"{n} {sing if n == 1 else plur}")
    if not parts:
        return "0 secondi"
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"

def format_giveaway_config(config: Dict[str, Any]) -> str:
    reqs = []
    if config.get("required_role"):
        reqs.append(f"Required role: <@&{config['required_role']}>")
    if config.get("required_level"):
        reqs.append(f"Minimum level: **{config['required_level']}**")
    if config.get("required_daily_messages"):
        reqs.append(f"Daily messages: **{config['required_daily_messages']}**")
    if config.get("required_weekly_messages"):
        reqs.append(f"Weekly messages: **{config['required_weekly_messages']}**")
    if config.get("required_monthly_messages"):
        reqs.append(f"Monthly messages: **{config['required_monthly_messages']}**")
    if config.get("required_total_messages"):
        reqs.append(f"Total messages: **{config['required_total_messages']}**")
    if config.get("requirement_bypass_role"):
        reqs.append(f"Bypass role: <@&{config['requirement_bypass_role']}>")
    return "\n".join(reqs) if reqs else "No requirements"

async def get_giveaway_settings(guild_id: int) -> Dict[str, Any]:
    try:
        async with aiosqlite.connect("db/giveaways.db") as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM GiveawaySettings WHERE guild_id = ?", (guild_id,)
            )
            row = await cur.fetchone()
            return dict(row) if row else {}
    except Exception:
        return {}

async def set_giveaway_settings(guild_id: int, **kwargs) -> bool:
    try:
        async with aiosqlite.connect("db/giveaways.db") as db:
            await db.execute(
                "INSERT OR IGNORE INTO GiveawaySettings (guild_id) VALUES (?)", (guild_id,)
            )
            for key, value in kwargs.items():
                await db.execute(
                    f"UPDATE GiveawaySettings SET {key} = ? WHERE guild_id = ?",
                    (value, guild_id),
                )
            await db.commit()
        return True
    except Exception:
        return False

async def get_giveaway_templates(guild_id: int) -> List[Dict[str, Any]]:
    try:
        async with aiosqlite.connect("db/giveaways.db") as db:
            cur = await db.execute(
                "SELECT name, data FROM GiveawayTemplates WHERE guild_id = ?", (guild_id,)
            )
            rows = await cur.fetchall()
            return [{"name": r[0], "data": json.loads(r[1])} for r in rows]
    except Exception:
        return []

async def save_giveaway_template(guild_id: int, name: str, data: Dict[str, Any]) -> bool:
    try:
        async with aiosqlite.connect("db/giveaways.db") as db:
            await db.execute(
                "INSERT OR REPLACE INTO GiveawayTemplates (guild_id, name, data) VALUES (?,?,?)",
                (guild_id, name, json.dumps(data)),
            )
            await db.commit()
        return True
    except Exception:
        return False

async def delete_giveaway_template(guild_id: int, name: str) -> bool:
    try:
        async with aiosqlite.connect("db/giveaways.db") as db:
            cur = await db.execute(
                "DELETE FROM GiveawayTemplates WHERE guild_id = ? AND name = ?",
                (guild_id, name),
            )
            deleted = cur.rowcount > 0
            await db.commit()
        return deleted
    except Exception:
        return False

async def check_user_level(guild_id: int, user_id: int) -> int:
    try:
        async with aiosqlite.connect("db/leveling.db") as db:
            cur = await db.execute(
                "SELECT level FROM leveling WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            row = await cur.fetchone()
            return row[0] if row else 0
    except Exception:
        return 0

async def check_user_messages(guild_id: int, user_id: int, days: int = None) -> int:
    try:
        async with aiosqlite.connect("db/tracking.db") as db:
            if days:
                since = (datetime.datetime.now() - datetime.timedelta(days=days)).timestamp()
                cur = await db.execute(
                    "SELECT COUNT(*) FROM user_activity "
                    "WHERE guild_id=? AND user_id=? AND timestamp>=?",
                    (guild_id, user_id, since),
                )
            else:
                cur = await db.execute(
                    "SELECT COUNT(*) FROM user_activity WHERE guild_id=? AND user_id=?",
                    (guild_id, user_id),
                )
            row = await cur.fetchone()
            return row[0] if row else 0
    except Exception:
        return 0
