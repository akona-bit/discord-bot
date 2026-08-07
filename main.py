import logging
import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("DISCORD_TOKEN")

log_path = Path(__file__).with_name("discord.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(filename=log_path, encoding="utf-8", mode="w"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("discord")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

if not token:
    logger.error("DISCORD_TOKEN is not set. Please configure the environment variable.")
    raise RuntimeError("DISCORD_TOKEN is not set")


@bot.event
async def on_ready():
    logger.info("Bot is ready.")
    logger.info(f"Logged in as {bot.user} ({bot.user.id})")


@bot.command(name="ping")
async def ping(ctx: commands.Context):
    """A simple ping command to verify the bot is responsive."""
    await ctx.reply("Pong!")


if __name__ == "__main__":
    bot.run(token)
