# 📈 Discord Stock News Bot

A complete Discord bot for tracking stock and ETF news, posting updates automatically or manually, and generating daily PDF reports with OpenAI summarization. It includes slash command support, webhook error reporting, and PDF merging.

---

## 🗂 Directory Structure

```
/opt/stock-bot/
├── bot.py                # Main bot logic
├── .env                  # Environment variables
├── stocks.json           # Tracked symbols
├── posted_news.json      # Used to prevent duplicate news
├── posted_pdfs/          # Individual article PDFs
├── reports/              # Daily merged PDF reports
├── requirements.txt      # Python dependencies
```

---

## ⚙️ Setup

### 1. System Dependencies

Install required packages:

```bash
sudo apt update
sudo apt install python3.12-venv libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf2.0-0 libxml2 libxslt1.1 libjpeg-dev libpng-dev build-essential
```

### 2. Python Setup

```bash
cd /opt/stock-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. .env Configuration

Create a `.env` file:

```env
DISCORD_BOT_TOKEN=...
DISCORD_GUILD_ID=...
DISCORD_CHANNEL_ID=...
ERROR_WEBHOOK_URL=...
FINNHUB_API_KEY=...
NEWSDATA_API_KEY=...
OPENAI_API_KEY=...
REPORT_HOUR=22
PDF_REPORT_PATH=/opt/stock-bot/reports/
```

---

## 🛠 systemd Service

To auto-run the bot:

```ini
[Unit]
Description=Discord Stock Bot
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

| Command            | Description                                 |
|--------------------|---------------------------------------------|
| `/addstock SYMBOL` | Add stock or ETF with type auto-detection   |
| `/removestock`     | Remove stock or ETF                         |
| `/validate_stocks` | Validate all stored symbols and types       |
| `/liststocks`      | Show all tracked symbols                    |
| `/news`            | Manually post current news                  |
| `/report`          | Generate and post the merged daily PDF      |

---

## 🧠 Features

- ✅ Automatic news every 2h and daily digest
- 📄 Merged daily PDF reports using OpenAI & WeasyPrint
- 📌 Duplicate news filtering via hashing
- 🧹 Clears old PDFs after report generation
- 🔔 Error notifications via webhook
- 🛠 Slash command support
- 📤 Handles manual interruption gracefully

---

© 2025 — Stock News Automation for Discord
