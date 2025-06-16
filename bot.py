import os
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime
import requests
import json
from pathlib import Path
import openai
from hashlib import sha1
from pathlib import Path
from weasyprint import HTML
from datetime import timezone, timedelta

from bs4 import BeautifulSoup
from PyPDF2 import PdfMerger

from datetime import datetime, timezone
from discord import app_commands
import pytz


POSTED_PDF_DIR = "/opt/stock-bot/posted_pdfs"
os.makedirs(POSTED_PDF_DIR, exist_ok=True)

def sanitize_filename(title):
    return "".join(c for c in title if c.isalnum() or c in " _-").rstrip()

def save_article_as_pdf(symbol, title, url):
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.content, "html.parser")
        content = soup.get_text()
        filename = sanitize_filename(f"{symbol}_{title[:40]}.pdf")
        filepath = os.path.join(POSTED_PDF_DIR, filename)
        html_content = f"<h1>{symbol}: {title}</h1><p><a href='{url}'>{url}</a></p><pre>{content}</pre>"
        HTML(string=html_content).write_pdf(filepath)
        return filepath
    except Exception as e:
        print(f"[PDF error] {symbol}: {e}")
        return None


def clear_posted_pdfs():
    for file in Path(POSTED_PDF_DIR).glob("*.pdf"):
        try:
            file.unlink()
        except Exception as e:
            print(f"[Cleanup error] {file}: {e}")


def generate_daily_report_from_pdfs(date_str):
    merger = PdfMerger()
    for file in sorted(Path(POSTED_PDF_DIR).glob("*.pdf")):
        merger.append(str(file))
    output_path = os.path.join(PDF_REPORT_PATH, f"report_{date_str}.pdf")
    merger.write(output_path)
    merger.close()
    return output_path

load_dotenv()
MARKET_TIMEZONE = pytz.timezone(os.getenv("MARKET_TIMEZONE", "Europe/Berlin"))


TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
ERROR_WEBHOOK_URL = os.getenv("ERROR_WEBHOOK_URL")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY")
POSTED_NEWS_PATH = "posted_news.json"
openai.api_key = os.getenv("OPENAI_API_KEY")
STOCKS_FILE = "stocks.json"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

def load_stocks():
    if Path(STOCKS_FILE).exists():
        with open(STOCKS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_stocks(stocks: dict):
    with open(STOCKS_FILE, "w") as f:
        json.dump(stocks, f, indent=2)

def get_symbol_type(symbol: str) -> str:
    """Returns the type of the symbol according to Finnhub (Stock, ETF, etc.)"""
    try:
        url = "https://finnhub.io/api/v1/search"
        params = {"q": symbol, "token": FINNHUB_API_KEY}
        response = requests.get(url, params=params)
        if response.status_code != 200:
            return None
        for entry in response.json().get("result", []):
            if entry.get("symbol", "").upper() == symbol.upper():
                return entry.get("type", "Unknown").capitalize()
    except Exception as e:
        print(f"[Type detection error] {symbol}: {e}")
    return None


def send_error_webhook(message):
    try:
        requests.post(ERROR_WEBHOOK_URL, json={"content": message})
    except Exception as e:
        print(f"[Webhook Error] {e}")
from datetime import timedelta

def get_news_for_symbol(symbol):
    today = datetime.now(timezone.utc).date()
    news_items = []

    posted = load_posted_news()

    # === 1. Finnhub ===
    try:
        url = f"https://finnhub.io/api/v1/company-news"
        params = {
            "symbol": symbol,
            "from": str(today),
            "to": str(today),
            "token": FINNHUB_API_KEY
        }
        r = requests.get(url, params=params)
        if r.status_code == 200:
            data = r.json()
            for item in data[:5]:  # Max 5 Messageen prüfen
                headline = item.get("headline")
                source = item.get("source")
                url = item.get("url")
                timestamp = item.get("datetime")
                date = datetime.fromtimestamp(timestamp, timezone.utc).date() if timestamp else None

                if not (headline and url and date == today):
                    continue

                news_id = hash_news(headline, url)
                if news_id in posted:
                    continue
                posted[news_id] = True
                news_items.append(f"📰 [{headline}]({url}) ({source})")
    except Exception as e:
        print(f"[Finnhub Error] {symbol}: {e}")

    # === 2. Newsdata.io ===
    try:
        url = f"https://newsdata.io/api/1/news"
        params = {
            "apikey": NEWSDATA_API_KEY,
            "q": symbol,
            "language": "en",
            "country": "us,de,gb",
            "category": "business"
        }
        r = requests.get(url, params=params)
        if r.status_code == 200:
            data = r.json()
            articles = data.get("results", [])
            for item in articles[:5]:
                title = item.get("title")
                link = item.get("link")
                pub_date = item.get("pubDate")  # ISO 8601 z.B. 2025-06-14T08:33:00Z
                source = item.get("source_id", "Newsdata")

                if not (title and link and pub_date):
                    continue

                pub_date_dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00")).date()
                if pub_date_dt != today:
                    continue

                news_id = hash_news(title, link)
                if news_id in posted:
                    continue
                posted[news_id] = True
                news_items.append(f"🗞️ [{title}]({link}) ({source})")
    except Exception as e:
        print(f"[Newsdata Error] {symbol}: {e}")

    # Speichere, was gepostet wurde
    save_posted_news(posted)

    return news_items if news_items else []

# === News cache for duplicate prevention ===
POSTED_NEWS_PATH = "posted_news.json"

def load_posted_news():
    if Path(POSTED_NEWS_PATH).exists():
        with open(POSTED_NEWS_PATH, "r") as f:
            return json.load(f)
    return {}

def save_posted_news(data):
    with open(POSTED_NEWS_PATH, "w") as f:
        json.dump(data, f)

def is_duplicate(news_id):
    posted = load_posted_news()
    return news_id in posted

def mark_as_posted(news_id):
    posted = load_posted_news()
    posted[news_id] = True
    save_posted_news(posted)

def hash_news(title, url):
    return sha1(f"{title}{url}".encode()).hexdigest()


def fetch_news(tickers):
    all_news = []
    errors = []

    for ticker in tickers:
        news = get_news_for_symbol(ticker)
        if news and not news[0].startswith("❌"):
            all_news.append(f"**{ticker}**\n" + "\n".join(news))
        else:
            errors.append(f"{ticker}: No usable news found")

    if errors:
        error_msg = "⚠️ **error while retrieving stock news**\n" + "\n".join(errors)
        send_error_webhook(error_msg)

    return "\n\n".join(all_news) if all_news else "✅ No new messages found."

def generate_daily_report(text_content, date_str):
    try:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Fasse die folgenden Finanznachrichten professionell und strukturiert zusammen."},
                {"role": "user", "content": f"Erstelle einen daily report aus diesen Aktiennews:\n{text_content}"}
            ]
        )
        summary = response.choices[0].message.content

        # removed: summary = response['choices'][0]['message']['content']
    except Exception as e:
        send_error_webhook(f"⚠️ Error generating report: {e}")
        summary = f"⚠️ Error generating report: {e}"

    html = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, sans-serif; padding: 20px; }}
            h1 {{ color: #333; }}
            p {{ margin: 10px 0; }}
        </style>
    </head>
    <body>
        <h1>📈 Aktien-daily report – {date_str}</h1>
        <p>{summary.replace('\n', '<br>')}</p>
    </body>
    </html>
    """
    report_dir = os.getenv("PDF_REPORT_PATH")
    os.makedirs(report_dir, exist_ok=True)
    output_path = os.path.join(report_dir, f"report_{date_str}.pdf")
    HTML(string=html).write_pdf(output_path)
    return output_path


def is_market_open():
    now = datetime.now(MARKET_TIMEZONE)
    weekday = now.weekday()
    hour = now.hour
    minute = now.minute
    # Default NYSE hours in Europe/Berlin timezone: 08:00–22:00
    if weekday >= 5:
        return False
    if (hour > 8 or (hour == 8 and minute >= 00)) and (hour < 22):
        return True
    return False


def is_valid_symbol(symbol):
    """Checks whether the symbol exists on Finnhub."""
    try:
        url = f"https://finnhub.io/api/v1/search"
        params = {"q": symbol, "token": FINNHUB_API_KEY}
        response = requests.get(url, params=params)
        if response.status_code != 200:
            return False

        results = response.json().get("result", [])
        return any(res.get("symbol", "").upper() == symbol.upper() for res in results)
    except Exception as e:
        print(f"[Symbol Check Error] {symbol}: {e}")
        return False



@tasks.loop(hours=2)
async def periodic_news():
    if not is_market_open(): return
    channel = bot.get_channel(CHANNEL_ID)
    tickers = load_stocks()
    news_sections = []

    for symbol in tickers:
        news = get_news_for_symbol(symbol)
        if news:
            news_sections.append(f"**{symbol}**\n" + "\n".join(news))

    if news_sections:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        header = f"🕑 **Current News ({now})**"
        content = "\n\n".join(news_sections)
        chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]

        await channel.send(header)
        for chunk in chunks:
            await channel.send(chunk)

@tasks.loop(hours=24)
async def daily_news():
    if not is_market_open(): return
    channel = bot.get_channel(CHANNEL_ID)
    stocks = load_stocks()
    news = fetch_news(stocks)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    await channel.send(f"🗞 **Daily Stock News ({now})**\n{news}")

@bot.tree.command(name="news", description="Manually post current stock news")
async def manual_news(interaction: discord.Interaction):
    if not is_market_open():
        await interaction.response.send_message("⚠️ The market is currently closed. Data is available Mon–Fri, 08:00–22:00 Europe/Berlin time.")
        return
    await interaction.response.defer()
    stocks = load_stocks()
    news = fetch_news(stocks)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    await interaction.followup.send(f"🗞 **Current stock news ({now})**\n{news}")

@bot.tree.command(name="addstock", description="Add stock or ETF (with type detection)")
async def add_stock(interaction: discord.Interaction, symbol: str):
    symbol = symbol.upper()
    stocks = load_stocks()

    if symbol in stocks:
        await interaction.response.send_message(f"⚠️ `{symbol}` is already registered as `{stocks[symbol]}`.")
        return

    symbol_type = get_symbol_type(symbol)
    if not symbol_type or symbol_type == "Unknown":
        await interaction.response.send_message(f"❌ Symbol `{symbol}` konnte nicht als Aktie oder ETF erkannt werden.")
        return

    stocks[symbol] = symbol_type
    save_stocks(stocks)
    await interaction.response.send_message(f"✅ `{symbol}` added as `{symbol_type}`.")



@bot.tree.command(name="removestock", description="Remove stock or ETF from list")
async def remove_stock(interaction: discord.Interaction, symbol: str):
    symbol = symbol.upper()
    stocks = load_stocks()
    if symbol not in stocks:
        await interaction.response.send_message(f"⚠️ `{symbol}` not found.")
        return
    del stocks[symbol]
    save_stocks(stocks)
    await interaction.response.send_message(f"🗑️ `{symbol}` removed.")

@bot.tree.command(name="validate_stocks", description="Validates all saved tickers for correctness and type")
async def validate_stocks(interaction: discord.Interaction):
    await interaction.response.defer()
    stocks = load_stocks()
    updated = {}
    failed = []

    for symbol in stocks.keys():
        typ = get_symbol_type(symbol)
        if typ and typ != "Unknown":
            updated[symbol] = typ
        else:
            failed.append(symbol)

    save_stocks(updated)
    result = f"✅ {len(updated)} valid symbols updated.\n"
    if failed:
        result += f"❌ {len(failed)} ungültige Symbole removed:\n" + ", ".join(failed)

    await interaction.followup.send(result)



@bot.tree.command(name="report", description="Manuell PDF-daily report generate und senden")
async def manual_report(interaction: discord.Interaction):
    await interaction.response.defer()
    date_str = datetime.now().strftime("%Y-%m-%d")
    pdf_file = generate_daily_report_from_pdfs(date_str)
    await interaction.followup.send(f"📄 **daily report {date_str} (zusammengeführt aus Artikeln)**", file=discord.File(pdf_file))

@bot.tree.command(name="liststocks", description="Displays all tracked stocks and ETFs with type")
async def list_stocks(interaction: discord.Interaction):
    stocks = load_stocks()
    if not stocks:
        await interaction.response.send_message("📭 No symbols saved yet.")
        return

    message = "📈 **Tracked symbols:**\n"
    for symbol, typ in stocks.items():
        message += f"- `{symbol}` ({typ})\n"
    await interaction.response.send_message(message)



@bot.event
async def on_ready():
    import sys
    print("✅ Bot ist online als", bot.user, file=sys.stderr)
    synced = await bot.tree.sync()
    print(f"✅ Slash-Commands synchronisiert: {[cmd.name for cmd in synced]}", file=sys.stderr)
    periodic_news.start()
    daily_news.start()
    check_for_report_time.start()
    post_daily_stock_graphs.start()



@tasks.loop(minutes=5)
async def post_daily_stock_graphs():
    if not is_market_open(): return
    now = datetime.now()
    if now.hour == 18 and now.minute < 5:
        try:
            stocks = load_stocks()
            for symbol in stocks:
                try:
                    import matplotlib.pyplot as plt
                    img_path = f"/tmp/{symbol}_chart.png"
                    end = datetime.now(timezone.utc)
                    start = end - timedelta(days=7)
                    url = f"https://finnhub.io/api/v1/stock/candle"
                    params = {
                        "symbol": symbol,
                        "resolution": "D",
                        "from": int(start.timestamp()),
                        "to": int(end.timestamp()),
                        "token": FINNHUB_API_KEY
                    }
                    r = requests.get(url, params=params)
                    data = r.json()
                    if data.get("s") == "ok":
                        plt.figure(figsize=(6, 3))
                        plt.plot([datetime.utcfromtimestamp(t) for t in data["t"]], data["c"], marker="o")
                        plt.title(f"{symbol} - 7 Day Price")
                        plt.xlabel("Date")
                        plt.ylabel("Close Price")
                        plt.grid(True)
                        plt.tight_layout()
                        plt.savefig(img_path)
                        plt.close()

                        with open(img_path, "rb") as f:
                            requests.post(os.getenv("STOCK_GRAPH_WEBHOOK_URL"), files={"file": f})
                except Exception as e:
                    send_error_webhook(f"📉 Error creating graph for {symbol}: {e}")
        except Exception as e:
            send_error_webhook(f"📊 Error in daily stock graph task: {e}")



@bot.tree.command(name="graphs", description="Manually post current stock/ETF 7-day graphs")
@app_commands.describe(format="Choose output format: pdf or images")
async def manual_post_graphs(interaction: discord.Interaction, format: str = "pdf"):
    if not is_market_open():
        await interaction.response.send_message("⚠️ The market is currently closed. Charts are available Mon–Fri, 08:00–22:00 Europe/Berlin time.")
        return
    await interaction.response.defer(thinking=True)
    stocks = load_stocks()
    chart_paths = []

    async def generate_chart(symbol):
        try:
            import matplotlib.pyplot as plt
            img_path = f"/tmp/{symbol}_manual_chart.png"
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=7)
            url = f"https://finnhub.io/api/v1/stock/candle"
            params = {
                "symbol": symbol,
                "resolution": "D",
                "from": int(start.timestamp()),
                "to": int(end.timestamp()),
                "token": FINNHUB_API_KEY
            }
            r = requests.get(url, params=params)
            data = r.json()
            if data.get("s") == "ok":
                plt.figure(figsize=(6, 3))
                plt.plot([datetime.utcfromtimestamp(t) for t in data["t"]], data["c"], marker="o")
                plt.title(f"{symbol} - 7 Day Price")
                plt.xlabel("Date")
                plt.ylabel("Close Price")
                plt.grid(True)
                plt.tight_layout()
                plt.savefig(img_path)
                plt.close()
                return symbol, img_path
        except Exception as e:
            send_error_webhook(f"📉 Error creating graph for {symbol}: {e}")
        return symbol, None

    import asyncio
    results = await asyncio.gather(*(generate_chart(sym) for sym in stocks))

    for symbol, path in results:
        if path:
            chart_paths.append((symbol, path))

    if format.lower() == "images":
        for _, path in chart_paths:
            await interaction.followup.send(file=discord.File(path))
    else:
        if not chart_paths:
            await interaction.followup.send("⚠️ No charts could be generated.")
            return

        from PyPDF2 import PdfMerger
        merger = PdfMerger()
        for _, path in chart_paths:
            merger.append(path)
        pdf_path = "/tmp/graphs_report.pdf"
        merger.write(pdf_path)
        merger.close()
        await interaction.followup.send(content="📊 All graphs combined in one PDF", file=discord.File(pdf_path))
async def manual_post_graphs(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        stocks = load_stocks()
        for symbol in stocks:
            try:
                import matplotlib.pyplot as plt
                img_path = f"/tmp/{symbol}_manual_chart.png"
                end = datetime.now(timezone.utc)
                start = end - timedelta(days=7)
                url = f"https://finnhub.io/api/v1/stock/candle"
                params = {
                    "symbol": symbol,
                    "resolution": "D",
                    "from": int(start.timestamp()),
                    "to": int(end.timestamp()),
                    "token": FINNHUB_API_KEY
                }
                r = requests.get(url, params=params)
                data = r.json()
                if data.get("s") == "ok":
                    plt.figure(figsize=(6, 3))
                    plt.plot([datetime.utcfromtimestamp(t) for t in data["t"]], data["c"], marker="o")
                    plt.title(f"{symbol} - 7 Day Price")
                    plt.xlabel("Date")
                    plt.ylabel("Close Price")
                    plt.grid(True)
                    plt.tight_layout()
                    plt.savefig(img_path)
                    plt.close()

                    await interaction.followup.send(file=discord.File(img_path))
            except Exception as e:
                send_error_webhook(f"📉 Error creating manual graph for {symbol}: {e}")
    except Exception as e:
        send_error_webhook(f"📊 Error in manual stock graph command: {e}")


async def main():
    print("🚀 Starte Stock-Bot...")
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        send_error_webhook("🛑 Bot was manually stopped.")





async def clear_channel(channel):
    def not_pinned(msg):
        return not msg.pinned
    deleted = await channel.purge(limit=100, check=not_pinned)
    print(f"{len(deleted)} Messages deleted.")



@tasks.loop(minutes=5)
async def check_for_report_time():
    now = datetime.now()
    report_hour = int(os.getenv("REPORT_HOUR", "22"))
    print(f"[DEBUG] Report check at {now.strftime('%H:%M')}")

    if now.hour == report_hour and now.minute < 5:
        print("[DEBUG] Report time reached")
        channel = bot.get_channel(CHANNEL_ID)
        posted_news = load_posted_news()

        if not posted_news:
            await channel.send("📭 No news available for today's report.")
            return

        # Preparing summary
        text_content = "\n".join(posted_news.keys())
        date_str = now.strftime("%Y-%m-%d")

        # Generate PDF
        pdf_file = generate_daily_report(text_content, date_str)

        # Send PDF
        await channel.send(f"📄 **daily report {date_str}**", file=discord.File(pdf_file))

        # Clear channel
        await clear_channel(channel)

        # Reset cache
        save_posted_news({})
        clear_posted_pdfs()
