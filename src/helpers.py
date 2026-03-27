import discord
import aiosqlite
from typing import Tuple
from discord import app_commands
from discord import ui

from giveaway_utils import check_user_level, check_user_messages


async def has_giveaway_permission(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    try:
        async with aiosqlite.connect("db/giveaways.db") as db:
            cur = await db.execute(
                "SELECT manager_role_id FROM GiveawaySettings WHERE guild_id = ?",
                (interaction.guild_id,),
            )
            row = await cur.fetchone()
            if row and row[0]:
                role = interaction.guild.get_role(row[0])
                if role and role in interaction.user.roles:
                    return True
    except Exception:
        pass
    raise app_commands.CheckFailure("You don't have permission. You need the **Giveaway Manager** role or administrator permissions.")


async def check_entry_eligibility(
    guild: discord.Guild,
    member: discord.Member,
    config: dict,
) -> Tuple[bool, str]:
    if config.get("requirement_bypass_role"):
        bypass = guild.get_role(config["requirement_bypass_role"])
        if bypass and bypass in member.roles:
            return True, ""
    if config.get("required_role"):
        req_role = guild.get_role(config["required_role"])
        if req_role and req_role not in member.roles:
            return False, f"You need the **{req_role.name}** role to enter."
    if config.get("required_level"):
        lvl = await check_user_level(guild.id, member.id)
        if lvl < config["required_level"]:
            return False, f"You need level **{config['required_level']}** to enter. Your level: **{lvl}**."
    if config.get("required_daily_messages"):
        cnt = await check_user_messages(guild.id, member.id, days=1)
        if cnt < config["required_daily_messages"]:
            return False, f"You need **{config['required_daily_messages']}** messages today. You have **{cnt}**."
    if config.get("required_weekly_messages"):
        cnt = await check_user_messages(guild.id, member.id, days=7)
        if cnt < config["required_weekly_messages"]:
            return False, f"You need **{config['required_weekly_messages']}** messages this week. You have **{cnt}**."
    if config.get("required_monthly_messages"):
        cnt = await check_user_messages(guild.id, member.id, days=30)
        if cnt < config["required_monthly_messages"]:
            return False, f"You need **{config['required_monthly_messages']}** messages this month. You have **{cnt}**."
    if config.get("required_total_messages"):
        cnt = await check_user_messages(guild.id, member.id)
        if cnt < config["required_total_messages"]:
            return False, f"You need **{config['required_total_messages']}** total messages. You have **{cnt}**."
    return True, ""


# Error & Success Views

def error_view(message: str) -> ui.LayoutView:
    class V(ui.LayoutView):
        def __init__(self):
            super().__init__(timeout=20)
            self.add_item(ui.Container(
                ui.TextDisplay("❌ **Error**"),
                ui.Separator(),
                ui.TextDisplay(message),
                accent_color=discord.Color.red(),
            ))
    return V()


def success_view(message: str) -> ui.LayoutView:
    class V(ui.LayoutView):
        def __init__(self):
            super().__init__(timeout=20)
            self.add_item(ui.Container(
                ui.TextDisplay("✅ **Success**"),
                ui.Separator(),
                ui.TextDisplay(message),
                accent_color=discord.Color.green(),
            ))
    return V()
