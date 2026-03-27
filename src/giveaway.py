import json
import random
import asyncio
import datetime
import discord
import aiosqlite
from discord import app_commands
from discord.ext import commands, tasks
from typing import Optional

from giveaway_utils import (
    validate_giveaway_duration,
    format_duration,
    get_giveaway_settings,
    set_giveaway_settings,
    get_giveaway_templates,
    save_giveaway_template,
    delete_giveaway_template,
)
from helpers import has_giveaway_permission, error_view, success_view
from views import (
    GiveawayMessageView,
    GiveawayEndedView,
    GiveawayCreateModal,
    GiveawayListView,
    GiveawayInfoView,
    TemplateManagerView,
    GiveawaySettingsView,
)


class GiveawayCog(commands.Cog, name="GiveawayCog"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._active_tasks: dict[int, asyncio.Task] = {}
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()
        for t in self._active_tasks.values():
            t.cancel()

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        now = datetime.datetime.now().timestamp()
        try:
            async with aiosqlite.connect("db/giveaways.db") as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(
                    "SELECT * FROM Giveaways WHERE ended=0 AND ends_at<=?", (now,)
                )
                rows = [dict(r) for r in await cur.fetchall()]
            for g in rows:
                if g["id"] not in self._active_tasks:
                    await self._end_giveaway(g["id"])
        except Exception as e:
            print(f"[Giveaway] Task error")

    @check_giveaways.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    async def restore_views(self):
        try:
            async with aiosqlite.connect("db/giveaways.db") as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute("SELECT * FROM Giveaways WHERE ended=0")
                rows = [dict(r) for r in await cur.fetchall()]
            for g in rows:
                config = json.loads(g["config"])
                async with aiosqlite.connect("db/giveaways.db") as db:
                    cur = await db.execute(
                        "SELECT COUNT(*) FROM GiveawayEntries WHERE giveaway_id=?", (g["id"],)
                    )
                    cnt = (await cur.fetchone())[0]
                view = GiveawayMessageView(
                    giveaway_id=g["id"], prize=g["prize"], winners=g["winners"],
                    ends_at=g["ends_at"], host_id=g["host_id"], config=config, entry_count=cnt,
                )
                self.bot.add_view(view, message_id=g["message_id"])
                print(f"[Giveaway] View restored #{g['id']} — {g['prize']}")
        except Exception as e:
            print(f"[Giveaway] Error in restore_views: {e}")

    async def _schedule_end(self, giveaway_id: int, seconds: int):
        await asyncio.sleep(seconds)
        await self._end_giveaway(giveaway_id)
        self._active_tasks.pop(giveaway_id, None)

    async def _end_giveaway(self, giveaway_id: int):
        try:
            async with aiosqlite.connect("db/giveaways.db") as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(
                    "SELECT * FROM Giveaways WHERE id=? AND ended=0", (giveaway_id,)
                )
                row = await cur.fetchone()
                if not row:
                    return
                g = dict(row)
                now = datetime.datetime.now().timestamp()
                await db.execute(
                    "UPDATE Giveaways SET ended=1, ends_at=? WHERE id=?", (now, giveaway_id)
                )
                await db.commit()
                cur2 = await db.execute(
                    "SELECT user_id FROM GiveawayEntries WHERE giveaway_id=?", (giveaway_id,)
                )
                entries = [r[0] for r in await cur2.fetchall()]
            config = json.loads(g["config"])
            winners_ids = random.sample(entries, min(g["winners"], len(entries))) if entries else []
            async with aiosqlite.connect("db/giveaways.db") as db:
                for uid in winners_ids:
                    await db.execute(
                        "INSERT INTO GiveawayWinners (giveaway_id, user_id) VALUES (?,?)",
                        (giveaway_id, uid),
                    )
                await db.commit()
            try:
                channel = self.bot.get_channel(g["channel_id"]) or await self.bot.fetch_channel(g["channel_id"])
                message = await channel.fetch_message(g["message_id"])
            except Exception:
                return
            ended_view = GiveawayEndedView(
                giveaway_id=giveaway_id, prize=g["prize"], winners_ids=winners_ids,
                ends_at=now, host_id=g["host_id"], entry_count=len(entries), config=config,
            )
            await message.edit(view=ended_view)
            self.bot.add_view(ended_view, message_id=message.id)
            if winners_ids:
                mentions = " ".join(f"<@{uid}>" for uid in winners_ids)
                ann = discord.ui.LayoutView()
                ann.add_item(discord.ui.Container(
                    discord.ui.TextDisplay(
                        f"# 🎉 Giveaway Ended!\n\n"
                        f"**Prize:** {g['prize']}\n"
                        f"**Winner{'s' if len(winners_ids) > 1 else ''}:** {mentions}\n\n"
                        f"Congratulations! Contact <@{g['host_id']}> to claim your prize."
                    ),
                    accent_color=discord.Color.gold(),
                ))
                await channel.send(
                    view=ann,
                    allowed_mentions=discord.AllowedMentions(users=True),
                )
            else:
                ann = discord.ui.LayoutView()
                ann.add_item(discord.ui.Container(
                    discord.ui.TextDisplay(
                        f"# 😢 Giveaway Ended — No Winners\n\n"
                        f"**Prize:** {g['prize']}\n\n"
                        f"Not enough participants entered."
                    ),
                    accent_color=discord.Color.dark_grey(),
                ))
                await channel.send(view=ann)
            settings = await get_giveaway_settings(g["guild_id"])
            if settings.get("dm_winners", 1):
                for uid in winners_ids:
                    try:
                        user = self.bot.get_user(uid) or await self.bot.fetch_user(uid)
                        dm_view = discord.ui.LayoutView()
                        dm_view.add_item(discord.ui.Container(
                            discord.ui.TextDisplay(
                                f"# 🎉 You Won!\n\n"
                                f"**Prize:** {g['prize']}\n\n"
                                f"Contact <@{g['host_id']}> to claim your prize."
                            ),
                            accent_color=discord.Color.gold(),
                        ))
                        await user.send(view=dm_view)
                    except Exception:
                        pass
            if settings.get("log_channel_id"):
                log_ch = self.bot.get_channel(settings["log_channel_id"])
                if log_ch:
                    winners_str = ", ".join(f"<@{uid}>" for uid in winners_ids) or "None"
                    log_view = discord.ui.LayoutView()
                    log_view.add_item(discord.ui.Container(
                        discord.ui.TextDisplay(
                            f"# 📋 Giveaway Ended\n\n"
                            f"**Prize:** {g['prize']}\n"
                            f"**Winners:** {winners_str}\n"
                            f"**Total Entries:** {len(entries)}"
                        ),
                        accent_color=discord.Color.blurple(),
                    ))
                    await log_ch.send(view=log_view)
            print(f"[Giveaway] #{giveaway_id} ({g['prize']}) ended. Winners: {winners_ids}")
        except Exception as e:
            print(f"[Giveaway] Error ending #{giveaway_id}: {e}")

    @app_commands.command(name="gcreate", description="Create a new giveaway (opens a modal)")
    @app_commands.describe(channel="Channel to post the giveaway in (default: current channel)")
    @app_commands.check(has_giveaway_permission)
    @app_commands.guild_only()
    async def gcreate(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        target = channel or interaction.channel
        modal = GiveawayCreateModal(target_channel=target, cog=self)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="gend", description="End an active giveaway immediately")
    @app_commands.describe(message_id="Message ID of the giveaway")
    @app_commands.check(has_giveaway_permission)
    @app_commands.guild_only()
    async def gend(self, interaction: discord.Interaction, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message(view=error_view("Invalid message ID."), ephemeral=True)
            return
        async with aiosqlite.connect("db/giveaways.db") as db:
            cur = await db.execute(
                "SELECT id, guild_id, ended FROM Giveaways WHERE message_id=?", (mid,)
            )
            row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(view=error_view("Giveaway not found."), ephemeral=True)
            return
        if row[1] != interaction.guild_id:
            await interaction.response.send_message(view=error_view("This giveaway belongs to another server."), ephemeral=True)
            return
        if row[2]:
            await interaction.response.send_message(view=error_view("This giveaway has already ended."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self._end_giveaway(row[0])
        await interaction.followup.send(
            view=success_view(f"Giveaway `{message_id}` ended successfully!"), ephemeral=True
        )

    @app_commands.command(name="greroll", description="Re-roll the winners of an ended giveaway")
    @app_commands.describe(
        message_id="Message ID of the giveaway",
        winners="Number of winners to re-roll (default: same as original)",
    )
    @app_commands.check(has_giveaway_permission)
    @app_commands.guild_only()
    async def greroll(self, interaction: discord.Interaction, message_id: str, winners: Optional[int] = None):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message(view=error_view("Invalid message ID."), ephemeral=True)
            return
        async with aiosqlite.connect("db/giveaways.db") as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM Giveaways WHERE message_id=? AND guild_id=?",
                (mid, interaction.guild_id),
            )
            row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(view=error_view("Giveaway not found."), ephemeral=True)
            return
        g = dict(row)
        if not g["ended"]:
            await interaction.response.send_message(view=error_view("The giveaway is still active."), ephemeral=True)
            return
        n = winners or g["winners"]
        async with aiosqlite.connect("db/giveaways.db") as db:
            cur = await db.execute(
                "SELECT user_id FROM GiveawayEntries WHERE giveaway_id=?", (g["id"],)
            )
            entries = [r[0] for r in await cur.fetchall()]
        if not entries:
            await interaction.response.send_message(view=error_view("No participants to draw from."), ephemeral=True)
            return
        new_winners = random.sample(entries, min(n, len(entries)))
        async with aiosqlite.connect("db/giveaways.db") as db:
            await db.execute("DELETE FROM GiveawayWinners WHERE giveaway_id=?", (g["id"],))
            for uid in new_winners:
                await db.execute(
                    "INSERT INTO GiveawayWinners (giveaway_id, user_id) VALUES (?,?)", (g["id"], uid)
                )
            await db.commit()
        mentions = " ".join(f"<@{uid}>" for uid in new_winners)
        await interaction.response.send_message(
            view=success_view(f"Re-roll for **{g['prize']}** complete!\nNew winners: {mentions}"),
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    @app_commands.command(name="glist", description="Show all active giveaways in this server")
    @app_commands.guild_only()
    async def glist(self, interaction: discord.Interaction):
        async with aiosqlite.connect("db/giveaways.db") as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM Giveaways WHERE guild_id=? AND ended=0 ORDER BY ends_at ASC",
                (interaction.guild_id,),
            )
            rows = [dict(r) for r in await cur.fetchall()]
        view = GiveawayListView(giveaways=rows, author=interaction.user)
        await interaction.response.send_message(view=view, ephemeral=True)

    @app_commands.command(name="ginfo", description="Show details of a giveaway")
    @app_commands.describe(message_id="Message ID of the giveaway")
    @app_commands.guild_only()
    async def ginfo(self, interaction: discord.Interaction, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message(view=error_view("Invalid message ID."), ephemeral=True)
            return
        async with aiosqlite.connect("db/giveaways.db") as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM Giveaways WHERE message_id=? AND guild_id=?",
                (mid, interaction.guild_id),
            )
            row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(view=error_view("Giveaway not found."), ephemeral=True)
            return
        g = dict(row)
        async with aiosqlite.connect("db/giveaways.db") as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM GiveawayEntries WHERE giveaway_id=?", (g["id"],)
            )
            cnt = (await cur.fetchone())[0]
        view = GiveawayInfoView(giveaway=g, entry_count=cnt)
        await interaction.response.send_message(view=view, ephemeral=True)

    @app_commands.command(name="gdelete", description="Delete an ended giveaway from the database")
    @app_commands.describe(message_id="Message ID of the giveaway")
    @app_commands.check(has_giveaway_permission)
    @app_commands.guild_only()
    async def gdelete(self, interaction: discord.Interaction, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message(view=error_view("Invalid message ID."), ephemeral=True)
            return
        async with aiosqlite.connect("db/giveaways.db") as db:
            cur = await db.execute(
                "SELECT id, ended FROM Giveaways WHERE message_id=? AND guild_id=?",
                (mid, interaction.guild_id),
            )
            row = await cur.fetchone()
        if not row:
            await interaction.response.send_message(view=error_view("Giveaway not found."), ephemeral=True)
            return
        if not row[1]:
            await interaction.response.send_message(
                view=error_view("The giveaway is still active! End it first with `/gend`."), ephemeral=True
            )
            return
        async with aiosqlite.connect("db/giveaways.db") as db:
            await db.execute("DELETE FROM Giveaways WHERE id=?", (row[0],))
            await db.commit()
        await interaction.response.send_message(
            view=success_view(f"Giveaway `{message_id}` deleted from the database."), ephemeral=True
        )

    gtemplate = app_commands.Group(name="gtemplate", description="Manage giveaway templates for this server", guild_only=True)

    @gtemplate.command(name="list", description="Browse saved templates")
    async def gtemplate_list(self, interaction: discord.Interaction):
        templates = await get_giveaway_templates(interaction.guild_id)
        view = TemplateManagerView(templates=templates, author=interaction.user)
        await interaction.response.send_message(view=view, ephemeral=True)

    @gtemplate.command(name="save", description="Save a new giveaway template")
    @app_commands.describe(
        name="Template name", prize="Giveaway prize",
        duration="Duration e.g. 30m, 2h, 1d, 1w", winners="Number of winners (default 1)",
    )
    @app_commands.check(has_giveaway_permission)
    async def gtemplate_save(self, interaction: discord.Interaction, name: str, prize: str, duration: str, winners: int = 1):
        valid, seconds, msg = validate_giveaway_duration(duration)
        if not valid:
            await interaction.response.send_message(view=error_view(msg), ephemeral=True)
            return
        data = {"prize": prize, "duration_seconds": seconds, "winners": max(1, winners), "config": {}}
        ok = await save_giveaway_template(interaction.guild_id, name, data)
        if ok:
            await interaction.response.send_message(
                view=success_view(f"Template **{name}** saved!"), ephemeral=True
            )
        else:
            await interaction.response.send_message(
                view=error_view("Failed to save template."), ephemeral=True
            )

    @gtemplate.command(name="use", description="Start a giveaway from a saved template")
    @app_commands.describe(name="Template name", channel="Channel to post it in (default: current channel)")
    @app_commands.check(has_giveaway_permission)
    async def gtemplate_use(self, interaction: discord.Interaction, name: str, channel: Optional[discord.TextChannel] = None):
        templates = await get_giveaway_templates(interaction.guild_id)
        template = next((t for t in templates if t["name"] == name), None)
        if not template:
            await interaction.response.send_message(
                view=error_view(f"Template **{name}** not found."), ephemeral=True
            )
            return
        d = template["data"]
        target = channel or interaction.channel
        ends_at = (datetime.datetime.now() + datetime.timedelta(seconds=d["duration_seconds"])).timestamp()
        config = d.get("config", {})

        # Send the Discord message first to get the real message_id, avoiding UNIQUE constraint errors
        tmp_view = GiveawayMessageView(
            giveaway_id=0, prize=d["prize"], winners=d["winners"],
            ends_at=ends_at, host_id=interaction.user.id, config=config, entry_count=0,
        )
        msg = await target.send(view=tmp_view)

        async with aiosqlite.connect("db/giveaways.db") as db:
            cur = await db.execute(
                "INSERT INTO Giveaways "
                "(guild_id, channel_id, message_id, host_id, prize, winners, ends_at, ended, config, created_at) "
                "VALUES (?,?,?,?,?,?,?,0,?,?)",
                (interaction.guild_id, target.id, msg.id, interaction.user.id, d["prize"],
                 d["winners"], ends_at, json.dumps(config), datetime.datetime.now().timestamp()),
            )
            await db.commit()
            giveaway_id = cur.lastrowid

        real_view = GiveawayMessageView(
            giveaway_id=giveaway_id, prize=d["prize"], winners=d["winners"],
            ends_at=ends_at, host_id=interaction.user.id, config=config, entry_count=0,
        )
        await msg.edit(view=real_view)
        self.bot.add_view(real_view, message_id=msg.id)
        duration_str = format_duration(d["duration_seconds"])
        await interaction.response.send_message(
            view=success_view(
                f"Giveaway from template **{name}** started in {target.mention}!\nDuration: {duration_str}"
            ),
            ephemeral=True,
        )
        self._active_tasks[giveaway_id] = asyncio.create_task(
            self._schedule_end(giveaway_id, d["duration_seconds"])
        )

    @gtemplate.command(name="delete", description="Delete a saved template")
    @app_commands.describe(name="Template name to delete")
    @app_commands.check(has_giveaway_permission)
    async def gtemplate_delete(self, interaction: discord.Interaction, name: str):
        ok = await delete_giveaway_template(interaction.guild_id, name)
        if ok:
            await interaction.response.send_message(
                view=success_view(f"Template **{name}** deleted."), ephemeral=True
            )
        else:
            await interaction.response.send_message(
                view=error_view(f"Template **{name}** not found."), ephemeral=True
            )

    gset = app_commands.Group(name="gset", description="Giveaway settings for this server (Admin only)", guild_only=True)

    @gset.command(name="view", description="Show the giveaway settings panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def gset_view(self, interaction: discord.Interaction):
        settings = await get_giveaway_settings(interaction.guild_id)
        view = GiveawaySettingsView(settings=settings, author=interaction.user)
        await interaction.response.send_message(view=view, ephemeral=True)

    @gset.command(name="managerrole", description="Set the giveaway manager role")
    @app_commands.describe(role="Role to set as manager")
    @app_commands.checks.has_permissions(administrator=True)
    async def gset_managerrole(self, interaction: discord.Interaction, role: discord.Role):
        await set_giveaway_settings(interaction.guild_id, manager_role_id=role.id)
        await interaction.response.send_message(
            view=success_view(f"Manager role set to {role.mention}."), ephemeral=True
        )

    @gset.command(name="logchannel", description="Set the log channel for giveaway events")
    @app_commands.describe(channel="Text channel for logs")
    @app_commands.checks.has_permissions(administrator=True)
    async def gset_logchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await set_giveaway_settings(interaction.guild_id, log_channel_id=channel.id)
        await interaction.response.send_message(
            view=success_view(f"Log channel set to {channel.mention}."), ephemeral=True
        )

    @gset.command(name="pingrole", description="Set the role to ping when a giveaway starts")
    @app_commands.describe(role="Role to ping")
    @app_commands.checks.has_permissions(administrator=True)
    async def gset_pingrole(self, interaction: discord.Interaction, role: discord.Role):
        await set_giveaway_settings(interaction.guild_id, ping_role_id=role.id)
        await interaction.response.send_message(
            view=success_view(f"Ping role set to {role.mention}."), ephemeral=True
        )

    @gset.command(name="dmwinners", description="Enable or disable DMs to winners")
    @app_commands.describe(enabled="True = enabled, False = disabled")
    @app_commands.checks.has_permissions(administrator=True)
    async def gset_dmwinners(self, interaction: discord.Interaction, enabled: bool):
        await set_giveaway_settings(interaction.guild_id, dm_winners=int(enabled))
        state = "enabled ✅" if enabled else "disabled ❌"
        await interaction.response.send_message(
            view=success_view(f"DMs to winners {state}."), ephemeral=True
        )

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            msg = str(error)
        elif isinstance(error, app_commands.MissingPermissions):
            msg = "You don't have permission to use this command."
        else:
            msg = f"An error occurred: {error}"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(view=error_view(msg), ephemeral=True)
            else:
                await interaction.response.send_message(view=error_view(msg), ephemeral=True)
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(GiveawayCog(bot))
