import json
import random
import datetime
import discord
import aiosqlite
from discord import ui, SelectOption
from typing import List, Dict, Any

from giveaway_utils import format_giveaway_config, format_duration, parse_hex_color
from helpers import check_entry_eligibility


class GiveawayMessageView(ui.LayoutView):

    def __init__(self, giveaway_id, prize, winners, ends_at, host_id, config, entry_count=0):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        self.prize = prize
        self.winners = winners
        self.ends_at = ends_at
        self.host_id = host_id
        self.config = config
        self.entry_count = entry_count
        self._build()

    def _build(self):
        self.clear_items()
        color = discord.Color(parse_hex_color(self.config.get("color", "#5865F2")))
        lines = [
            f"# 🎉 {self.prize}",
            "",
            f"**🏆 Winners:** {self.winners}",
            f"**⏰ Ends:** <t:{int(self.ends_at)}:R> (<t:{int(self.ends_at)}:f>)",
            f"**👤 Host:** <@{self.host_id}>",
            f"**🎟️ Entries:** {self.entry_count}",
        ]
        req = format_giveaway_config(self.config)
        if req != "No requirements":
            lines += ["", "**📋 Requirements:**", req]
        btn = ui.Button(
            label=f"Enter ({self.entry_count})",
            style=discord.ButtonStyle.primary,
            emoji="🎉",
            custom_id=f"gw_enter_{self.giveaway_id}",
        )
        btn.callback = self.on_enter
        self.add_item(ui.Container(
            ui.TextDisplay("\n".join(lines)),
            ui.Separator(),
            ui.ActionRow(btn),
            accent_color=color,
        ))

    async def on_enter(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user
        async with aiosqlite.connect("db/giveaways.db") as db:
            cur = await db.execute(
                "SELECT ended, config FROM Giveaways WHERE id = ?", (self.giveaway_id,)
            )
            row = await cur.fetchone()
        if not row or row[0]:
            await interaction.response.send_message(
                view=_quick("❌ **Error**", "This giveaway has already ended.", discord.Color.red()),
                ephemeral=True,
            )
            return
        config = json.loads(row[1])
        eligible, reason = await check_entry_eligibility(guild, member, config)
        if not eligible:
            await interaction.response.send_message(
                view=_quick("❌ **Cannot Enter**", reason, discord.Color.red()),
                ephemeral=True,
            )
            return
        async with aiosqlite.connect("db/giveaways.db") as db:
            cur = await db.execute(
                "SELECT id FROM GiveawayEntries WHERE giveaway_id=? AND user_id=?",
                (self.giveaway_id, member.id),
            )
            existing = await cur.fetchone()
            if existing:
                await db.execute(
                    "DELETE FROM GiveawayEntries WHERE giveaway_id=? AND user_id=?",
                    (self.giveaway_id, member.id),
                )
                await db.commit()
                cur2 = await db.execute(
                    "SELECT COUNT(*) FROM GiveawayEntries WHERE giveaway_id=?", (self.giveaway_id,)
                )
                self.entry_count = (await cur2.fetchone())[0]
                self._build()
                await interaction.response.edit_message(view=self)
                await interaction.followup.send(
                    view=_quick("✅ **Entry Removed**", "You have left the giveaway.", discord.Color.orange()),
                    ephemeral=True,
                )
            else:
                await db.execute(
                    "INSERT INTO GiveawayEntries (giveaway_id, user_id, entered_at) VALUES (?,?,?)",
                    (self.giveaway_id, member.id, datetime.datetime.now().timestamp()),
                )
                await db.commit()
                cur2 = await db.execute(
                    "SELECT COUNT(*) FROM GiveawayEntries WHERE giveaway_id=?", (self.giveaway_id,)
                )
                self.entry_count = (await cur2.fetchone())[0]
                self._build()
                await interaction.response.edit_message(view=self)
                await interaction.followup.send(
                    view=_quick("🎉 **Entered!**", "You are in the giveaway. Good luck!", discord.Color.green()),
                    ephemeral=True,
                )


class GiveawayEndedView(ui.LayoutView):

    def __init__(self, giveaway_id, prize, winners_ids, ends_at, host_id, entry_count, config):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        self.prize = prize
        self.winners_ids = winners_ids
        self.ends_at = ends_at
        self.host_id = host_id
        self.entry_count = entry_count
        self.config = config
        self._build()

    def _build(self):
        self.clear_items()
        color = discord.Color(parse_hex_color(self.config.get("end_color", "#000000")))
        if self.winners_ids:
            w_txt = " ".join(f"<@{uid}>" for uid in self.winners_ids)
            label = "Winner" if len(self.winners_ids) == 1 else "Winners"
            winners_line = f"**🏆 {label}:** {w_txt}"
        else:
            winners_line = "**😢 No winners** — not enough participants."
        lines = [
            f"# 🎉 {self.prize} — ENDED",
            "",
            winners_line,
            f"**👤 Host:** <@{self.host_id}>",
            f"**🎟️ Total entries:** {self.entry_count}",
            f"**⏰ Ended:** <t:{int(self.ends_at)}:R>",
        ]
        reroll_btn = ui.Button(
            label="🔄 Re-roll",
            style=discord.ButtonStyle.secondary,
            custom_id=f"gw_reroll_{self.giveaway_id}",
        )
        reroll_btn.callback = self.on_reroll
        self.add_item(ui.Container(
            ui.TextDisplay("\n".join(lines)),
            ui.Separator(),
            ui.ActionRow(reroll_btn),
            accent_color=color,
        ))

    async def on_reroll(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                view=_quick("❌ **No Permission**", "You need **Manage Server** to re-roll.", discord.Color.red()),
                ephemeral=True,
            )
            return
        async with aiosqlite.connect("db/giveaways.db") as db:
            cur = await db.execute("SELECT winners FROM Giveaways WHERE id=?", (self.giveaway_id,))
            row = await cur.fetchone()
            if not row:
                await interaction.response.send_message(
                    view=_quick("❌ **Error**", "Giveaway not found.", discord.Color.red()),
                    ephemeral=True,
                )
                return
            winner_count = row[0]
            cur2 = await db.execute(
                "SELECT user_id FROM GiveawayEntries WHERE giveaway_id=?", (self.giveaway_id,)
            )
            entries = [r[0] for r in await cur2.fetchall()]
        if not entries:
            await interaction.response.send_message(
                view=_quick("❌ **Error**", "No participants to draw from.", discord.Color.red()),
                ephemeral=True,
            )
            return
        new_winners = random.sample(entries, min(winner_count, len(entries)))
        self.winners_ids = new_winners
        async with aiosqlite.connect("db/giveaways.db") as db:
            await db.execute("DELETE FROM GiveawayWinners WHERE giveaway_id=?", (self.giveaway_id,))
            for uid in new_winners:
                await db.execute(
                    "INSERT INTO GiveawayWinners (giveaway_id, user_id) VALUES (?,?)",
                    (self.giveaway_id, uid),
                )
            await db.commit()
        self._build()
        await interaction.response.edit_message(view=self)
        mentions = " ".join(f"<@{uid}>" for uid in new_winners)
        await interaction.followup.send(
            view=_quick("🔄 **Re-roll Complete**", f"New winners: {mentions}", discord.Color.blurple()),
            allowed_mentions=discord.AllowedMentions(users=True),
        )


class GiveawayCreateModal(discord.ui.Modal, title="🎉 Create Giveaway"):
    prize = discord.ui.TextInput(label="Prize", placeholder="Nitro, Gift Card, VIP Role...", max_length=200)
    duration = discord.ui.TextInput(label="Duration (e.g. 30m, 2h, 1d, 1w)", placeholder="1h", max_length=10)
    winners = discord.ui.TextInput(label="Number of winners", placeholder="1", default="1", max_length=3)
    color = discord.ui.TextInput(label="Border color (hex or name)", placeholder="#5865F2 or gold", required=False, default="#5865F2", max_length=30)
    image_url = discord.ui.TextInput(label="Image URL (optional)", placeholder="https://...", required=False, max_length=500)

    def __init__(self, target_channel, cog):
        super().__init__()
        self.target_channel = target_channel
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        from giveaway_utils import validate_giveaway_duration
        valid, seconds, msg = validate_giveaway_duration(self.duration.value.strip())
        if not valid:
            await interaction.response.send_message(
                view=_quick("❌ **Invalid Duration**", msg, discord.Color.red()), ephemeral=True
            )
            return
        try:
            winner_count = max(1, int(self.winners.value.strip()))
        except ValueError:
            await interaction.response.send_message(
                view=_quick("❌ **Error**", "Invalid number of winners.", discord.Color.red()), ephemeral=True
            )
            return
        ends_at = (datetime.datetime.now() + datetime.timedelta(seconds=seconds)).timestamp()
        config = {
            "color": self.color.value.strip() or "#5865F2",
            "image": self.image_url.value.strip() or None,
        }
        from giveaway_utils import get_giveaway_settings
        settings = await get_giveaway_settings(interaction.guild_id)
        ping_content = f"<@&{settings['ping_role_id']}>" if settings.get("ping_role_id") else None

        # Send the Discord message first to get the real message_id, avoiding UNIQUE constraint errors
        tmp_view = GiveawayMessageView(
            giveaway_id=0, prize=self.prize.value.strip(), winners=winner_count,
            ends_at=ends_at, host_id=interaction.user.id, config=config, entry_count=0,
        )
        msg_obj = await self.target_channel.send(
            content=ping_content, view=tmp_view, allowed_mentions=discord.AllowedMentions(roles=True)
        )

        async with aiosqlite.connect("db/giveaways.db") as db:
            cur = await db.execute(
                "INSERT INTO Giveaways "
                "(guild_id, channel_id, message_id, host_id, prize, winners, ends_at, ended, config, created_at) "
                "VALUES (?,?,?,?,?,?,?,0,?,?)",
                (
                    interaction.guild_id, self.target_channel.id, msg_obj.id, interaction.user.id,
                    self.prize.value.strip(), winner_count, ends_at,
                    json.dumps(config), datetime.datetime.now().timestamp(),
                ),
            )
            await db.commit()
            giveaway_id = cur.lastrowid

        real_view = GiveawayMessageView(
            giveaway_id=giveaway_id, prize=self.prize.value.strip(), winners=winner_count,
            ends_at=ends_at, host_id=interaction.user.id, config=config, entry_count=0,
        )
        await msg_obj.edit(view=real_view)
        self.cog.bot.add_view(real_view, message_id=msg_obj.id)
        await interaction.response.send_message(
            view=_quick(
                "✅ **Giveaway Started!**",
                f"Posted in {self.target_channel.mention}\nEnds <t:{int(ends_at)}:R>.",
                discord.Color.green(),
            ),
            ephemeral=True,
        )
        import asyncio
        asyncio.create_task(self.cog._schedule_end(giveaway_id, seconds))


class GiveawayListView(ui.LayoutView):
    PAGE_SIZE = 5

    def __init__(self, giveaways, author):
        super().__init__(timeout=120)
        self.giveaways = giveaways
        self.author = author
        self.page = 0
        self._build()

    def _build(self):
        self.clear_items()
        total = max(1, -(-len(self.giveaways) // self.PAGE_SIZE))
        start = self.page * self.PAGE_SIZE
        page_items = self.giveaways[start: start + self.PAGE_SIZE]
        lines = [f"# 📋 Active Giveaways  —  Page {self.page + 1}/{total}", ""]
        if not page_items:
            lines.append("*No active giveaways at the moment.*")
        else:
            for g in page_items:
                lines.append(
                    f"🎉 **{g['prize']}** · {g['winners']} winner{'s' if g['winners'] != 1 else ''}\n"
                    f"Ends <t:{int(g['ends_at'])}:R> · Host <@{g['host_id']}>\n"
                    f"[→ Jump](https://discord.com/channels/{g['guild_id']}/{g['channel_id']}/{g['message_id']})\n"
                )
        prev_btn = ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary,
                             disabled=self.page == 0, custom_id="list_prev")
        next_btn = ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary,
                             disabled=self.page >= total - 1, custom_id="list_next")
        prev_btn.callback = self.on_prev
        next_btn.callback = self.on_next
        self.add_item(ui.Container(
            ui.TextDisplay("\n".join(lines)),
            ui.Separator(),
            ui.ActionRow(prev_btn, next_btn),
            accent_color=discord.Color.blurple(),
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                view=_quick("❌ **Not Yours**", "Run `/glist` yourself to use this menu.", discord.Color.red()),
                ephemeral=True,
            )
            return False
        return True

    async def on_prev(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self._build()
        await interaction.response.edit_message(view=self)

    async def on_next(self, interaction: discord.Interaction):
        total = max(1, -(-len(self.giveaways) // self.PAGE_SIZE))
        self.page = min(total - 1, self.page + 1)
        self._build()
        await interaction.response.edit_message(view=self)


class GiveawayInfoView(ui.LayoutView):
    def __init__(self, giveaway, entry_count):
        super().__init__(timeout=60)
        g = giveaway
        config = json.loads(g["config"]) if isinstance(g["config"], str) else g["config"]
        req = format_giveaway_config(config)
        status = "✅ Active" if not g["ended"] else "🔴 Ended"
        lines = [
            f"# 🎉 {g['prize']}",
            "",
            f"**Status:** {status}",
            f"**Giveaway ID:** `{g['id']}`",
            f"**Winners:** {g['winners']}",
            f"**Host:** <@{g['host_id']}>",
            f"**Entries:** {entry_count}",
            f"**Ends/Ended:** <t:{int(g['ends_at'])}:R>",
        ]
        if req != "No requirements":
            lines += ["", f"**📋 Requirements:**\n{req}"]
        link_btn = ui.Button(
            label="Jump to message",
            style=discord.ButtonStyle.link,
            url=f"https://discord.com/channels/{g['guild_id']}/{g['channel_id']}/{g['message_id']}",
        )
        color = discord.Color.blurple() if not g["ended"] else discord.Color.dark_grey()
        self.add_item(ui.Container(
            ui.TextDisplay("\n".join(lines)),
            ui.Separator(),
            ui.ActionRow(link_btn),
            accent_color=color,
        ))


class TemplateManagerView(ui.LayoutView):
    def __init__(self, templates, author):
        super().__init__(timeout=120)
        self.templates = templates
        self.author = author
        self._build(selected=None)

    def _build(self, selected=None):
        self.clear_items()
        if not self.templates:
            self.add_item(ui.Container(
                ui.TextDisplay("# 📄 Giveaway Templates"),
                ui.Separator(),
                ui.TextDisplay("*No templates saved.*\nUse `/gtemplate save` to create one."),
                accent_color=discord.Color.blurple(),
            ))
            return
        if selected:
            t = next((x for x in self.templates if x["name"] == selected), None)
            d = t["data"] if t else {}
            detail = [
                f"# 📄 Template: {selected}", "",
                f"**Prize:** {d.get('prize', 'N/A')}",
                f"**Winners:** {d.get('winners', 1)}",
                f"**Duration:** {format_duration(d.get('duration_seconds', 3600))}",
            ]
            req = format_giveaway_config(d.get("config", {}))
            if req != "No requirements":
                detail += ["", f"**Requirements:**\n{req}"]
            header = "\n".join(detail)
            accent = discord.Color.gold()
        else:
            rows = [
                f"**{t['name']}** — {t['data'].get('prize','?')} · "
                f"{t['data'].get('winners',1)} winner{'s' if t['data'].get('winners',1) != 1 else ''} · "
                f"{format_duration(t['data'].get('duration_seconds',3600))}"
                for t in self.templates
            ]
            header = "# 📄 Giveaway Templates\n\n" + "\n".join(rows)
            accent = discord.Color.blurple()
        options = [
            SelectOption(label=t["name"], value=t["name"],
                         description=t["data"].get("prize", ""),
                         default=(t["name"] == selected))
            for t in self.templates[:25]
        ]
        dropdown = ui.Select(placeholder="Select a template...", options=options)
        dropdown.callback = self.on_select
        self.add_item(ui.Container(
            ui.TextDisplay(header),
            ui.Separator(),
            ui.ActionRow(dropdown),
            accent_color=accent,
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                view=_quick("❌ **Not Yours**", "Run the command yourself to use this menu.", discord.Color.red()),
                ephemeral=True,
            )
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        self._build(selected=interaction.data["values"][0])
        await interaction.response.edit_message(view=self)


class GiveawaySettingsView(ui.LayoutView):
    def __init__(self, settings, author):
        super().__init__(timeout=60)
        self.author = author
        manager = f"<@&{settings['manager_role_id']}>" if settings.get("manager_role_id") else "*Not set*"
        log_ch  = f"<#{settings['log_channel_id']}>"   if settings.get("log_channel_id")   else "*Not set*"
        ping    = f"<@&{settings['ping_role_id']}>"    if settings.get("ping_role_id")      else "*Not set*"
        dm      = "✅ Enabled" if settings.get("dm_winners", 1) else "❌ Disabled"
        color   = settings.get("default_color", "#5865F2")
        lines = [
            "# ⚙️ Giveaway Settings", "",
            f"**Manager Role:** {manager}",
            f"**Log Channel:** {log_ch}",
            f"**Ping Role:** {ping}",
            f"**DM Winners:** {dm}",
            f"**Default Color:** `{color}`",
            "",
            "-# Use `/gset` to modify these settings.",
        ]
        self.add_item(ui.Container(
            ui.TextDisplay("\n".join(lines)),
            accent_color=discord.Color.blurple(),
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                view=_quick("❌ **Not Yours**", "This panel belongs to someone else.", discord.Color.red()),
                ephemeral=True,
            )
            return False
        return True


HELP_DATA = {
    "🎉 Giveaway": [
        ("`/gcreate`",          "Create a giveaway (opens a modal)"),
        ("`/gend`",             "End a giveaway immediately"),
        ("`/greroll`",          "Re-roll the winners"),
        ("`/glist`",            "List active giveaways"),
        ("`/ginfo`",            "Details of a giveaway"),
        ("`/gdelete`",          "Delete a giveaway from the DB"),
    ],
    "📄 Templates": [
        ("`/gtemplate list`",   "Browse saved templates"),
        ("`/gtemplate save`",   "Save a new template"),
        ("`/gtemplate use`",    "Start a giveaway from a template"),
        ("`/gtemplate delete`", "Delete a template"),
    ],
    "⚙️ Settings": [
        ("`/gset view`",        "Show settings panel"),
        ("`/gset managerrole`", "Set the manager role"),
        ("`/gset logchannel`",  "Set the log channel"),
        ("`/gset pingrole`",    "Set the ping role"),
        ("`/gset dmwinners`",   "Toggle DMs to winners"),
    ],
    "🛠️ Utility": [
        ("`/help`", "This help menu"),
        ("`/ping`", "Bot latency"),
    ],
}


class HelpView(ui.LayoutView):
    def __init__(self, bot, author):
        super().__init__(timeout=120)
        self.bot = bot
        self.author = author
        self._build(selected=None)

    def _build(self, selected=None):
        self.clear_items()
        if selected and selected in HELP_DATA:
            cmds = HELP_DATA[selected]
            lines = [f"# {selected}", ""]
            for cmd, desc in cmds:
                lines.append(f"{cmd}\n-# {desc}\n")
            header = "\n".join(lines)
        else:
            total_cmds = sum(len(v) for v in HELP_DATA.values())
            header = (
                "# 🎉 Giveaway Bot — Help\n\n"
                "Select a category from the dropdown to browse commands.\n\n"
                f"-# {total_cmds} commands · {len(HELP_DATA)} categories"
            )
        options = [
            SelectOption(label=cat, description=f"{len(cmds)} commands", value=cat,
                         default=(cat == selected))
            for cat, cmds in HELP_DATA.items()
        ]
        dropdown = ui.Select(placeholder="Select a category...", options=options)
        dropdown.callback = self.on_select
        section = ui.Section(
            ui.TextDisplay(header),
            accessory=ui.Thumbnail(
                media=discord.UnfurledMediaItem(url=self.bot.user.display_avatar.url),
                description="Bot icon",
            ),
        )
        self.add_item(ui.Container(
            section,
            ui.Separator(),
            ui.ActionRow(dropdown),
            accent_color=discord.Color.blurple(),
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                view=_quick("❌ **Not Yours**", "Use `/help` yourself to open your own menu.", discord.Color.red()),
                ephemeral=True,
            )
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        self._build(selected=interaction.data["values"][0])
        await interaction.response.edit_message(view=self)


def _quick(title: str, body: str, color: discord.Color) -> ui.LayoutView:
    class V(ui.LayoutView):
        def __init__(self):
            super().__init__(timeout=20)
            self.add_item(ui.Container(
                ui.TextDisplay(title),
                ui.Separator(),
                ui.TextDisplay(body),
                accent_color=color,
            ))
    return V()
