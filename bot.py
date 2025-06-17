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
import matplotlib.dates as mdates
from bs4 import BeautifulSoup
from PyPDF2 import PdfMerger
import pytz, asyncio
from datetime import datetime, timezone
from discord import app_commands
import pytz
import yfinance as yf
import matplotlib.pyplot as plt

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
        if isinstance(data, list):
            return [s.upper() for s in data if isinstance(s, str)]
        elif isinstance(data, dict):
            return [s.upper() for s in data.keys()]
        else:
            print("⚠️ Invalid format in stocks.json")
            return []
    except Exception as e:
        print(f"⚠️ Error loading stock list: {e}")
        return ["AAPL", "MSFT", "TSLA"]


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
        #else:
        #    errors.append(f"{ticker}: No usable news found")

    if errors:
        error_msg = "⚠️ **error while retrieving stock news**\n" + "\n".join(errors)
        send_error_webhook(error_msg)

    return "\n\n".join(all_news) #if all_news else "✅ No new messages found."

def generate_daily_report(text_content, date_str):
    try:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": "Fasse die folgenden Finanznachrichten professionell und strukturiert zusammen."},
                {"role": "user", "content": f"Erstelle einen daily report aus diesen Aktiennews:\n{text_content}"}
            ]
        )
        summary = response.choices[0].message.content
        # 🆕 Speichere die Artikel-Zusammenfassung in Datei
        article_path = f"/opt/stock-bot/articles/{date_str}.txt"
        os.makedirs(os.path.dirname(article_path), exist_ok=True)
        with open(article_path, "w", encoding="utf-8") as f:
            # Entfernt führende Leerzeichen je Zeile
            clean_summary = "\n".join(line.lstrip() for line in summary.splitlines())
            f.write(clean_summary.strip())


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
    path = f"/opt/stock-bot/articles/{date_str}.txt"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "⚠️ No article data available for this day."

def load_daily_prices(date_str):
    path = f"/opt/stock-bot/prices/{date_str}.txt"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "⚠️ No price data available for this day."


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
            news_sections.append(f"**{get_symbol_name(symbol)} ({symbol})**\\n" + "\\n".join(news))

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
    await interaction.response.defer()
    stocks = load_stocks()
    news = fetch_news(stocks)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    await interaction.followup.send(f"🗞 **Current stock news ({now})**\n{news}")

def get_symbol_type(symbol):
    try:
        with open("/opt/stock-bot/stocks.json", "r") as f:
            data = json.load(f)
        # Nur wenn Datei ein dict ist (dein Format)
        if isinstance(data, dict):
            return data.get(symbol.upper(), "Unknown")
    except Exception as e:
        print(f"⚠️ Error reading stocks.json in get_symbol_type(): {e}")
    return "Unknown"


@bot.tree.command(name="addstock", description="Add stock or ETF (with type detection)")
async def add_stock(interaction: discord.Interaction, symbol: str):
    symbol = symbol.upper()
    stocks = load_stocks()

    if symbol in stocks:
        await interaction.response.send_message(f"⚠️ `{symbol}` is already registered as `{stocks[symbol]}`.")
        return

    symbol_type = get_symbol_type(symbol)
    if not symbol_type or symbol_type == "Unknown":
        await interaction.response.send_message(f"❌ Symbol `{symbol}` could not be identified as a stock or ETF.")
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
        result += f"❌ {len(failed)} invalid symbols removed:\n" + ", ".join(failed)

    await interaction.followup.send(result)

@bot.tree.command(name="clear", description="Deletes all messages in the current channel (nur Admins!)")
@app_commands.checks.has_permissions(administrator=True)
async def clear(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    channel = interaction.channel
    deleted = 0

    try:
        async for message in channel.history(limit=None):
            try:
                await message.delete()
                deleted += 1
            except Exception as e:
                print(f"❌ Error while deleting: {e}")

        await interaction.followup.send(f"🧹 {deleted} Messages deleted.")
    except Exception as e:
        await interaction.followup.send(f"⚠️ Error while deleting: {e}")


@bot.tree.command(name="report", description="Daily report with price changes & GPT summary")
async def manual_report(interaction: discord.Interaction):
    await interaction.response.defer()
    date_str = datetime.now().strftime("%Y-%m-%d")
    stock_symbols = load_stocks()
    #await interaction.followup.send("📊 Starting report generation...")

    # Lade bestehende Artikel/Kurse
    articles = load_daily_articles(date_str)
    prices_today = []  # NEU: Preise für Kursteil
    chart_html_blocks = []
    chart_dir = "/opt/stock-bot/pngs"
    os.makedirs(chart_dir, exist_ok=True)

    #await interaction.followup.send("📈 Generating intraday charts for today...")

    import asyncio

    async def generate_intraday_chart(symbol):
        try:
            def plot_chart():
                try:
                    ticker = yf.Ticker(symbol)
                    hist = ticker.history(period="1d", interval="15m")
                    if hist.empty:
                        return None

                    plt.figure(figsize=(6, 3))
                    plt.plot(hist.index, hist["Close"], marker="o")
                    plt.title(f"{get_symbol_name(symbol)} ({symbol}) – Tagesverlauf")
                    plt.xlabel("Zeit")
                    plt.ylabel("Kurs")
                    plt.grid(True)
                    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
                    plt.gcf().autofmt_xdate(rotation=45)

                    img_path = os.path.join(chart_dir, f"{symbol}_intraday.png")
                    plt.tight_layout()
                    plt.savefig(img_path)
                    plt.close()

                    return f"<h3>{symbol}</h3><img src='file://{img_path}' width='600'>"
                except Exception as e:
                    print(f"❌ Fehler bei Chart für {symbol}: {e}")
                    return f"<p>⚠️ {symbol}: Error creating chart</p>"

            return await asyncio.wait_for(asyncio.to_thread(plot_chart), timeout=10)
        except asyncio.TimeoutError:
            print(f"⚠️ Timeout bei {symbol}")
            return f"<p>⚠️ {symbol}: Chart creation timeout</p>"

    chart_html_blocks = []
    for i, symbol in enumerate(stock_symbols, 1):
        #await interaction.followup.send(f"📊 [{i}/{len(stock_symbols)}] Erzeuge Chart für {symbol}...")
        try:
            html_block = await generate_intraday_chart(symbol)
            if html_block:
                chart_html_blocks.append(html_block)
        except Exception as e:
            print(f"❌ Fehler bei {symbol}: {e}")


    
    changes = []
    
    await interaction.followup.send(f"🔄 Loading price data for {len(stock_symbols)} Aktien...")

    
    berlin_tz = pytz.timezone("Europe/Berlin")
    today = datetime.now(berlin_tz).date()

    async def fetch_change(symbol):
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2d")
            if len(hist) >= 2:
                y_close = hist["Close"].iloc[-2]
                t_close = hist["Close"].iloc[-1]
                delta = t_close - y_close
                pct = (delta / y_close) * 100
                return f"{symbol}: {t_close:.2f} EUR ({delta:+.2f}, {pct:+.2f}%)"
            return f"{symbol}: No price data available."
        except Exception as e:
            return f"{symbol}: Fehler – {e}"

    for symbol in stock_symbols:
        try:
            result = await asyncio.wait_for(fetch_change(symbol), timeout=5)
            changes.append(result)
        except asyncio.TimeoutError:
            changes.append(f"{symbol}: ❌ Timeout bei Kursabfrage")
    # NEU innerhalb der Kurs-Abfrage-Schleife
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="2d")
    ...
    # Nach der Verarbeitung der Kursveränderung:
    # Hole aktuellen Kurs für Preis-Liste
    today_hist = ticker.history(period="1d")
    if not today_hist.empty:
        close = today_hist["Close"].iloc[-1]
        prices_today.append(f"{symbol}: {close:.2f} EUR")
    else:
        prices_today.append(f"{symbol}: ❌ No price data")


    combined_text = articles + "\n\n📊 Kursveränderungen heute:\n" + "\n".join(changes)

    # Speichere zusammengefasste Artikel und Kursdaten für späteren Zugriff
    article_path = f"/opt/stock-bot/articles/{date_str}.txt"
    os.makedirs(os.path.dirname(article_path), exist_ok=True)
    with open(article_path, "w", encoding="utf-8") as f:
        f.write(combined_text.strip())


    # GPT-Zusammenfassung
    try:
        #await interaction.followup.send("🧠 Creating GPT summary...")
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        safe_input = combined_text[:3000]
        response = await asyncio.wait_for(
            asyncio.to_thread(client.chat.completions.create,
                model="gpt-4.1-nano",
                messages=[
                    {"role": "system", "content": "Fasse die folgenden Finanznachrichten und Kursdaten professionell zusammen."},
                    {"role": "user", "content": safe_input}
                ]
            ),
            timeout=30
        )
        summary = response.choices[0].message.content
        # 🆕 Speichere die Artikel-Zusammenfassung in Datei
        article_path = f"/opt/stock-bot/articles/{date_str}.txt"
        os.makedirs(os.path.dirname(article_path), exist_ok=True)
        with open(article_path, "w", encoding="utf-8") as f:
            # Entfernt führende Leerzeichen je Zeile
            clean_summary = "\n".join(line.lstrip() for line in summary.splitlines())
            f.write(clean_summary.strip())


    except asyncio.TimeoutError:
        summary = "⚠️ GPT summary: Timeout"
        send_error_webhook(summary)
    except Exception as e:
        summary = f"⚠️ GPT summary: Error – {e}"
        send_error_webhook(summary)

    # Daten für spätere Nutzung speichern (Artikel + Preise)
    article_dir = "/opt/stock-bot/articles"
    price_dir = "/opt/stock-bot/prices"
    os.makedirs(article_dir, exist_ok=True)
    os.makedirs(price_dir, exist_ok=True)

    with open(os.path.join(article_dir, f"{date_str}.txt"), "w", encoding="utf-8") as f:
        # Entfernt führende Leerzeichen je Zeile
        clean_summary = "\n".join(line.lstrip() for line in summary.splitlines())
        f.write(clean_summary.strip())


    with open(os.path.join(price_dir, f"{date_str}.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(prices_today))

    # PDF generieren
    
    html = f"""
    <html><body>
        <h1>📈 Aktien-Tagesreport – {date_str}</h1>
        <h2>🔎 GPT-Zusammenfassung</h2>
        <p></p>
        <div style="white-space: pre-wrap; font-family: monospace;">
        {combined_text}
        </div>
        <h2>📈 Kursverläufe heute</h2>
        {''.join(chart_html_blocks)}

    </body></html>
    """

    pdf_path = f"/opt/stock-bot/reports/report_{date_str}.pdf"
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
    print("✅ Bot is online as", bot.user, file=sys.stderr)
    synced = await bot.tree.sync()
    print(f"✅ Slash commands synchronized: {[cmd.name for cmd in synced]}", file=sys.stderr)
    periodic_news.start()
    #daily_news.start()
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
                    img_path = f"/opt/stock-bot/pngs/{symbol}_chart.png"
                    ticker = yf.Ticker(symbol)
                    hist = ticker.history(period="7d")
                    if not hist.empty:
                        plt.figure(figsize=(6, 3))
                        plt.plot(hist.index, hist["Close"], marker="o")
                        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
                        plt.gcf().autofmt_xdate(rotation=45)
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
    await interaction.response.defer(thinking=True)  # ⏳ Sofortige Antwort an Discord

    stocks = load_stocks()
    chart_paths = []

    import asyncio
    async def generate_chart(symbol):
        try:
            img_path = f"/opt/stock-bot/pngs/{symbol}_manual_chart.png"
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="7d")
            if not hist.empty:
                plt.figure(figsize=(6, 3))
                plt.plot(hist.index, hist["Close"], marker="o")
                plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
                plt.gcf().autofmt_xdate(rotation=45)
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

    results = await asyncio.gather(*(generate_chart(sym) for sym in stocks))

    for symbol, path in results:
        if path:
            chart_paths.append((symbol, path))

    if not chart_paths:
        await interaction.followup.send("⚠️ Keine No charts could be generated.")
        return

    # PDF erstellen
    
    try:
        merger = PdfMerger()
        for _, path in chart_paths:
            if Path(path).exists():
                pdf_path = path.replace(".png", ".pdf")
                HTML(string=f"<img src='file://{path}' width='600'>").write_pdf(pdf_path)
                merger.append(pdf_path)
        final_pdf = "/opt/stock-bot/reports/graphs_report.pdf"
        merger.write(final_pdf)
        merger.close()
    except Exception as e:
        await interaction.followup.send(f"❌ Error creating PDF: {e}")
        return

    # Webhook senden
    webhook_url = os.getenv("STOCK_GRAPH_WEBHOOK_URL")
    if webhook_url:
        try:
            with open(final_pdf, "rb") as f:
                response = requests.post(webhook_url, files={"file": f})
                #if 200 <= response.status_code < 300:
                #    await interaction.followup.send("✅ Chart successfully sent to webhook.")
                #else:
                #    await interaction.followup.send(f"⚠️ Error during webhook upload: {response.status_code} {response.text}")
        except Exception as e:
            await interaction.followup.send(f"❌ Error sending webhook: {e}")
    else:
        await interaction.followup.send("❌ Webhook URL is not set.")

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
