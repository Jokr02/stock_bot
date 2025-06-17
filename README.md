# Stock Market Discord Bot

This Discord bot tracks selected stock symbols, retrieves related news, generates daily summaries and reports, and posts periodic updates to a configured Discord channel.

## Features

- 📈 Retrieves intraday price data for configured stock tickers
- 🗞 Fetches and summarizes stock-related news using GPT-4
- 🧾 Generates daily PDF reports with charts and summaries
- ⏰ Supports scheduled posting of news and reports
- 🧹 Includes slash command to clean up channels
- ⚙️ Fully configurable via environment variables and stock JSON

## Requirements

- Python 3.10+
- Dependencies (see `requirements.txt`):
  - `discord.py`
  - `yfinance`
  - `weasyprint`
  - `openai`
  - `matplotlib`
  - `PyPDF2`
  - `pytz`

## Setup

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Create `.env` file**:
   ```env
   DISCORD_TOKEN=your_discord_bot_token
   OPENAI_API_KEY=your_openai_key
   CHANNEL_ID=your_discord_channel_id
   STOCK_GRAPH_WEBHOOK_URL=optional_webhook_url
   REPORT_HOUR=22
   ```

3. **Create your stock list file**:
   Example: `stocks.json`
   ```json
   {
     "AAPL": "Stock",
     "NVDA": "Stock",
     "AMD": "Stock",
     "URTH": "ETF"
   }
   ```

4. **Run the bot**:
   ```bash
   python bot.py
   ```

## Slash Commands

- `/news` – Post current stock news (even previously posted ones)
- `/report` – Generate and send a daily report PDF
- `/graphs` – Generate and send today's stock charts
- `/addstock`, `/removestock`, `/liststocks` – Manage stock symbols
- `/clear` – Delete all messages in the current channel (admin only)

## File Structure

```
/opt/stock-bot/
├── bot.py
├── .env
├── stocks.json
├── /data/
│   ├── prices/YYYY-MM-DD.txt
│   └── articles/YYYY-MM-DD.txt
├── /reports/
│   └── report_YYYY-MM-DD.pdf
├── /pngs/
│   └── SYMBOL_intraday.png
```

## Notes

- Scheduled tasks use `discord.ext.tasks`.
- The bot uses a local cache to avoid reposting duplicate news.
- All reports are automatically saved and archived.

## License

MIT License
