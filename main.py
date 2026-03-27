import os
import sys
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Add src/ to path so all modules inside are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from helper_initdb import init_all
from views import HelpView

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    print("❌ BOT_TOKEN not found in .env file.")
    print("   Rename .env.example → .env and add your token.")
    sys.exit(1)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True


class GiveawayBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        await init_all()
        await self.load_extension("src.giveaway")
        print("[Bot] Cog 'GiveawayCog' loaded.")
        synced = await self.tree.sync()
        print(f"[Bot] {len(synced)} slash command(s) synced.")

    async def on_ready(self):
        print(f"\n{'='*45}")
        print(f"  🤖  {self.user} is online!")
        print(f"  🏠  Servers: {len(self.guilds)}")
        print(f"{'='*45}\n")
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="🎉 Giveaways | /help"))
        cog = self.get_cog("GiveawayCog")
        if cog:
            await cog.restore_views()

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        from helpers import error_view
        if isinstance(error, app_commands.CommandNotFound):
            return
        msg = str(error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(view=error_view(msg), ephemeral=True)
            else:
                await interaction.response.send_message(view=error_view(msg), ephemeral=True)
        except Exception:
            pass


bot = GiveawayBot()


@bot.tree.command(name="help", description="Show the interactive help menu")
async def help_cmd(interaction: discord.Interaction):
    view = HelpView(bot=bot, author=interaction.user)
    await interaction.response.send_message(view=view, ephemeral=True)


@bot.tree.command(name="ping", description="Check bot latency")
async def ping_cmd(interaction: discord.Interaction):
    ms = round(bot.latency * 1000)
    color = discord.Color.green() if ms < 100 else discord.Color.orange()

    class PingView(discord.ui.LayoutView):
        def __init__(self):
            super().__init__(timeout=15)
            self.add_item(discord.ui.Container(
                discord.ui.TextDisplay(f"🏓 **Pong!**\nLatency: **{ms}ms**"),
                accent_color=color,
            ))

    await interaction.response.send_message(view=PingView(), ephemeral=True)


if __name__ == "__main__":
    bot.run(TOKEN, log_handler=None)
