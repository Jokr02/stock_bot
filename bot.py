import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import json
import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- Konfiguration ---
DISCORD_TOKEN = "your-discord-token"
NEWS_API_KEY = "your-bing-news-api-key"
CHANNEL_ID = 123456789012345678  # Ziel-Channel für News
LOG_WEBHOOK_URL = "https://discord.com/api/webhooks/your-webhook-url"

# --- Bot-Setup ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Logging Funktion ---
async def log_event(message: str):
    payload = {
        "embeds": [{
            "title": "📋 Bot Log",
            "description": message,
            "color": 0x3498db,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(LOG_WEBHOOK_URL, json=payload) as resp:
                if resp.status != 204:
                    print(f"Logging failed with status {resp.status}")
    except Exception as e:
        print(f"Logging error: {e}")

# --- Dateibezogene Hilfsfunktionen ---
def load_stocks():
    try:
        with open("stocks.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_stocks(stocks):
    with open("stocks.json", "w") as f:
        json.dump(stocks, f)

# --- News abrufen ---
async def fetch_news(query):
    try:
        url = f"https://api.bing.microsoft.com/v7.0/news/search?q={query}&mkt=en-US&count=2"
        headers = {"Ocp-Apim-Subscription-Key": NEWS_API_KEY}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                articles = data.get("value", [])
                return [
                    f"**{a['name']}**\n{a['url']}" for a in articles
                ]
    except Exception as e:
        await log_event(f"❌ Failed to fetch news for `{query}`: {e}")
        return []

# --- Automatischer täglicher News-Post ---
async def post_news():
    stocks = load_stocks()
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        await log_event("⚠️ Channel not found for daily news post.")
        return

    await channel.send("📰 **Daily Stock News**")
    for stock in stocks:
        news = await fetch_news(stock)
        if news:
            await channel.send(f"**{stock}**:\n" + "\n\n".join(news))
    await log_event(f"✅ Daily news posted for {len(stocks)} stock(s).")

# Scheduler starten
scheduler = AsyncIOScheduler()
scheduler.add_job(post_news, "cron", hour=9)  # 9:00 UTC
scheduler.start()

# --- Events & Slash Commands ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await log_event(f"✅ Bot started as **{bot.user}**")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        await log_event(f"❌ Slash command sync failed: {e}")

@bot.tree.command(name="news", description="Get latest news for tracked stocks")
async def news(interaction: discord.Interaction):
    await interaction.response.defer()
    stocks = load_stocks()
    msg = "📰 **Latest News**\n"
    for stock in stocks:
        articles = await fetch_news(stock)
        msg += f"\n**{stock}**:\n" + "\n\n".join(articles) + "\n"
    await interaction.followup.send(msg[:2000])

@bot.tree.command(name="add", description="Add a stock to track")
@app_commands.describe(name="Name of the stock to add")
async def add(interaction: discord.Interaction, name: str):
    stocks = load_stocks()
    if name in stocks:
        await interaction.response.send_message(f"{name} is already being tracked.")
    else:
        stocks.append(name)
        save_stocks(stocks)
        await interaction.response.send_message(f"✅ Added {name} to stock list.")
        await log_event(f"➕ Stock added: `{name}`")

@bot.tree.command(name="remove", description="Remove a stock")
@app_commands.describe(name="Name of the stock to remove")
async def remove(interaction: discord.Interaction, name: str):
    stocks = load_stocks()
    if name in stocks:
        stocks.remove(name)
        save_stocks(stocks)
        await interaction.response.send_message(f"✅ Removed {name}.")
        await log_event(f"➖ Stock removed: `{name}`")
    else:
        await interaction.response.send_message(f"{name} not found.")

@bot.tree.command(name="list", description="List all tracked stocks")
async def list_stocks(interaction: discord.Interaction):
    stocks = load_stocks()
    await interaction.response.send_message("📈 Tracked stocks:\n" + ", ".join(stocks) if stocks else "No stocks being tracked.")

# --- Bot starten ---
bot.run(DISCORD_TOKEN)
