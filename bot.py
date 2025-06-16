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
import yfinance as yf

def get_symbol_name(symbol):
    try:
        info = yf.Ticker(symbol).info
        return info.get("shortName") or symbol
    except Exception:
        return symbol


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
    output_path = os.path.join(POSTED_PDF_DIR, f"report_{date_str}.pdf")
    merger.write(output_path)
    merger.close()
    return output_path

load_dotenv()
MARKET_TIMEZONE = pytz.timezone(os.getenv("MARKET_TIMEZONE", "Europe/Berlin"))


TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
ERROR_WEBHOOK_URL = os.getenv("ERROR_WEBHOOK_URL")
NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY")
POSTED_NEWS_PATH = "posted_news.json"
openai.api_key = os.getenv("OPENAI_API_KEY")
STOCKS_FILE = "stocks.json"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


def load_stocks():
    try:
        with open("/opt/stock-bot/stocks.json", "r") as f:
            data = json.load(f)
        # Erwartet Liste wie: ["AAPL", "MSFT", "TSLA"]
        if isinstance(data, list):
            return [s.upper() for s in data if isinstance(s, str) and s.strip()]
        # Oder Format: {"stocks": [...]}
        elif isinstance(data, dict) and "stocks" in data:
            return [s.upper() for s in data["stocks"] if isinstance(s, str) and s.strip()]
        else:
            print("⚠️ Ungültiges Format in stocks.json")
            return []
    except Exception as e:
        print(f"⚠️ Fehler beim Laden von stocks.json: {e}")
        return ["AAPL", "MSFT", "TSLA"]  # Fallback


def save_stocks(stocks: dict):
    with open(STOCKS_FILE, "w") as f:
        json.dump(stocks, f, indent=2)



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
            all_news.append(f"**{get_symbol_name(ticker)} ({ticker})**\n" + "\n".join(news))
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
        print("✅ GPT-Zusammenfassung erhalten.")

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
    os.makedirs(POSTED_PDF_DIR, exist_ok=True)
    output_path = os.path.join(POSTED_PDF_DIR, f"report_{date_str}.pdf")
    HTML(string=html).write_pdf(output_path)
    return output_path

def load_daily_articles(date_str):
    path = f"/opt/stock-bot/data/articles/{date_str}.txt"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "⚠️ Keine Artikeldaten für diesen Tag vorhanden."

def load_daily_prices(date_str):
    path = f"/opt/stock-bot/data/prices/{date_str}.txt"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "⚠️ Keine Preisdaten für diesen Tag vorhanden."


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



@tasks.loop(hours=2)
async def periodic_news():
    if not is_market_open(): return
    channel = bot.get_channel(CHANNEL_ID)
    tickers = load_stocks()
    news_sections = []

    for symbol in tickers:
        news = get_news_for_symbol(symbol)
        if news:
            news_sections.append(f"**{get_symbol_name(ticker)} ({ticker})**\\n" + "\\n".join(news))

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
    #if not is_market_open():
    #    await interaction.response.send_message("⚠️ The market is currently closed. Data is available Mon–Fri, 08:00–22:00 Europe/Berlin time.")
    #    return
    #await interaction.response.defer()
    stocks = load_stocks()
    news = fetch_news(stocks)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    await interaction.followup.send(f"🗞 **Current stock news ({now})**\n{news}")

def get_symbol_type(symbol):
    # Du kannst diese Logik später verfeinern.
    if symbol.upper().endswith(".DE"):
        return "ETF"
    return "Stock"

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



@bot.tree.command(name="report", description="Tagesreport mit Kursveränderungen & GPT-Zusammenfassung")
async def manual_report(interaction: discord.Interaction):
    await interaction.response.defer()
    date_str = datetime.now().strftime("%Y-%m-%d")
    await interaction.followup.send("📊 Starte Erstellung des Reports...")

    # Artikel & Kurse
    articles = load_daily_articles(date_str)
    prices = load_daily_prices(date_str)
    combined_text = articles + "\n\n📈 Kurse:\n" + prices

    # 📉 Kursveränderungen sicher abfragen
    import pytz
    import asyncio
    berlin_tz = pytz.timezone("Europe/Berlin")
    today = datetime.now(berlin_tz).date()

    # 📉 Kursveränderungen mit Discord-Fortschritt & Timeout
    import pytz, asyncio
    berlin_tz = pytz.timezone("Europe/Berlin")
    today = datetime.now(berlin_tz).date()

    async def fetch_change(symbol, index, total):
        try:
            await interaction.followup.send(f"🔍 [{index}/{total}] Lade Kursdaten für {symbol}...")
            print(f"🔄 Hole Daten für {symbol}")
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2d")
            if len(hist) >= 2:
                y_close = hist["Close"].iloc[-2]
                t_close = hist["Close"].iloc[-1]
                delta = t_close - y_close
                pct = (delta / y_close) * 100
                return f"{symbol}: {t_close:.2f} EUR ({delta:+.2f}, {pct:+.2f}%)"
            return f"{symbol}: Keine Kursdaten verfügbar."
        except Exception as e:
            return f"{symbol}: Fehler – {e}"

    stock_symbols = load_stocks()
    changes = []
    for i, symbol in enumerate(stock_symbols):
        try:
            result = await asyncio.wait_for(fetch_change(symbol, i + 1, len(stock_symbols)), timeout=5)
            changes.append(result)
        except asyncio.TimeoutError:
            timeout_msg = f"{symbol}: ❌ Timeout bei Kursabfrage"
            changes.append(timeout_msg)
            await interaction.followup.send(timeout_msg)

    combined_text += "\n\n📊 Kursveränderungen heute:\n" + "\n".join(changes)

    # 📝 Automatisches Schreiben der Textdateien für den Tag
    article_dir = "/opt/stock-bot/articles"
    price_dir = "/opt/stock-bot/prices"
    os.makedirs(article_dir, exist_ok=True)
    os.makedirs(price_dir, exist_ok=True)

    article_path = os.path.join(article_dir, f"{date_str}.txt")
    price_path = os.path.join(price_dir, f"{date_str}.txt")

    try:
        # ✍️ Speichere Artikeltext (falls von GPT generiert)
        with open(article_path, "w", encoding="utf-8") as f:
            f.write(articles.strip() if articles else "Keine Artikeldaten.")
    except Exception as e:
        print(f"⚠️ Fehler beim Schreiben von {article_path}: {e}")

    try:
        # ✍️ Speichere Tagespreise (aus load_daily_prices + Preisveränderungen)
        with open(price_path, "w", encoding="utf-8") as f:
            f.write(prices.strip() + "\n\n" + "\n".join(changes))
    except Exception as e:
        print(f"⚠️ Fehler beim Schreiben von {price_path}: {e}")



    # GPT-Zusammenfassung mit Timeout & Fehlerbehandlung
    try:
        await interaction.followup.send("🧠 Erstelle GPT-Zusammenfassung...")
        import openai
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        safe_input = combined_text[:3000]
        response = await asyncio.wait_for(
            asyncio.to_thread(client.chat.completions.create,
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "Fasse die folgenden Finanznachrichten und Kursdaten professionell zusammen."},
                    {"role": "user", "content": safe_input}
                ]
            ),
            timeout=30
        )
        summary = response.choices[0].message.content
        print("✅ GPT-Zusammenfassung erfolgreich.")
    except asyncio.TimeoutError:
        summary = "⚠️ GPT-Zusammenfassung: Timeout"
        send_error_webhook(summary)
    except Exception as e:
        summary = f"⚠️ GPT-Zusammenfassung: Fehler – {e}"
        send_error_webhook(summary)

    # PDF generieren
    await interaction.followup.send("📝 Erzeuge PDF-Datei...")
    from weasyprint import HTML
    POSTED_PDF_DIR = "/opt/stock-bot/reports"
    os.makedirs(POSTED_PDF_DIR, exist_ok=True)
    pdf_path = os.path.join(POSTED_PDF_DIR, f"report_{date_str}.pdf")
    html = f"""
    <html><body>
        <h1>📈 Aktien-Tagesreport – {date_str}</h1>
        <h2>🔎 GPT-Zusammenfassung</h2>
        <p>{summary.replace('\\n', '<br>')}</p>
        <h2>🗞 Einzelne News, Kurse & Veränderungen</h2>
        <pre>{combined_text}</pre>
    </body></html>
    """
    HTML(string=html).write_pdf(pdf_path)

    await interaction.followup.send(f"📄 **daily report {date_str}**", file=discord.File(pdf_path))



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
                    img_path = f"/opt/stock-bot/pngs/{symbol}_chart.png"
                    ticker = yf.Ticker(symbol)
                    hist = ticker.history(period="7d")
                    if not hist.empty:
                        plt.figure(figsize=(6, 3))
                        plt.plot(hist.index, hist["Close"], marker="o")
                        plt.title(f"{get_symbol_name(symbol)} ({symbol}) - 7 Day Price")
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
async def manual_post_graphs(interaction: discord.Interaction, format: str = "pdf"):
    #if not is_market_open():
    #    await interaction.response.send_message("⚠️ The market is currently closed. Charts are available Mon–Fri, 08:00–22:00 Europe/Berlin time.")
    #    return
    #await interaction.response.defer(thinking=True)
    stocks = load_stocks()
    chart_paths = []

    async def generate_chart(symbol):
        try:
            import matplotlib.pyplot as plt
            img_path = f"/opt/stock-bot/pngs/{symbol}_manual_chart.png"
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="7d")
            if not hist.empty:
                plt.figure(figsize=(6, 3))
                plt.plot(hist.index, hist["Close"], marker="o")
                plt.title(f"{get_symbol_name(symbol)} ({symbol}) - 7 Day Price")
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

    if not chart_paths:
        await interaction.followup.send("⚠️ No charts could be generated.")
        return

    from weasyprint import HTML
    from PyPDF2 import PdfMerger

    try:
        merger = PdfMerger()
        for _, path in chart_paths:
            if Path(path).exists():
                pdf_path = path.replace(".png", ".pdf")
                HTML(string=f"<img src='file://{path}' width='600'>").write_pdf(pdf_path)
                merger.append(pdf_path)
        pdf_path = "/opt/stock-bot/reports/graphs_report.pdf"
        merger.write(pdf_path)
        merger.close()
        await interaction.followup.send(content="📊 Combined PDF generated", file=discord.File(pdf_path))
    except Exception as e:
        send_error_webhook(f"❌ Error creating PDF: {e}")
        await interaction.followup.send("❌ Failed to generate PDF.")
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
