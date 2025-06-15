# 📈 Discord Stock News Bot

A complete Discord bot for tracking stock and ETF news, posting updates, generating visual charts, and summarizing news with OpenAI. Includes slash commands, error reporting, PDF generation, chart visualizations, and time-based logic.

---

## 📁 Project Structure

```
/opt/stock-bot/
├── bot.py                 # Main bot script
├── .env                   # Configuration file
├── stocks.json            # Tracked symbols and types
├── posted_news.json       # Posted news tracking
├── posted_pdfs/           # Individual news PDFs
├── reports/               # Merged daily reports
├── requirements.txt       # Python dependencies
```

---

## ⚙️ Setup

### 1. Install system dependencies

```bash
sudo apt update
sudo apt install python3.12-venv libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf2.0-0 libxml2 libxslt1.1 libjpeg-dev libpng-dev build-essential
```

### 2. Create virtual environment and install Python packages

```bash
cd /opt/stock-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure `.env`

```env
DISCORD_BOT_TOKEN=...
DISCORD_GUILD_ID=...
DISCORD_CHANNEL_ID=...
ERROR_WEBHOOK_URL=...
STOCK_GRAPH_WEBHOOK_URL=...
FINNHUB_API_KEY=...
NEWSDATA_API_KEY=...
OPENAI_API_KEY=...
REPORT_HOUR=22
PDF_REPORT_PATH=/opt/stock-bot/reports/
MARKET_TIMEZONE=Europe/Berlin
```

---

## 🛠 systemd Service

```ini
[Unit]
Description=Stock Bot
After=network.target

[Service]
Type=simple
User=stockbot
WorkingDirectory=/opt/stock-bot
ExecStart=/opt/stock-bot/venv/bin/python /opt/stock-bot/bot.py
Restart=on-failure
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now stock-bot
```

---

## 💬 Slash Commands

| Command                  | Description                                          |
|--------------------------|------------------------------------------------------|
| `/addstock SYMBOL`       | Add a stock/ETF to tracking list                     |
| `/removestock`           | Remove a stock/ETF                                   |
| `/validate_stocks`       | Re-validate symbols and update types                 |
| `/liststocks`            | Show all tracked symbols with types                  |
| `/news`                  | Manually fetch and post current stock news           |
| `/report`                | Generate and send daily news summary PDF             |
| `/graphs format:pdf`     | Generate 7-day charts as combined PDF                |
| `/graphs format:images`  | Generate and send charts as separate images          |

---

## 📊 Features

- Automatic stock & ETF news fetching (2h interval)
- Daily PDF summary via OpenAI (with article content)
- Auto-generated charts (7-day line plots)
- Error reporting via Discord webhook
- Duplicate news filtering
- Slash command support
- Channel cleanup before daily summary
- Market-time aware logic (based on `MARKET_TIMEZONE`)
- Skips tasks & blocks manual commands when market is closed

---

© 2025 – Smart Market Monitoring via Discord
