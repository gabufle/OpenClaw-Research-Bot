# OpenClaw Research Bot

## Overview
- `webscraper.py` scrapes papers, builds a compact Gemini payload, and saves ranked output to `data/latest_evaluation.json`.
- `whatsapp_bot.py` exposes a Meta WhatsApp Cloud API webhook and supports `/top` command replies.

## Environment Variables

### Scraper
- `GEMINI_API_KEY` (recommended instead of hardcoding in code)

### WhatsApp Bot (Meta Cloud API)
- `WHATSAPP_VERIFY_TOKEN`: token used for Meta webhook verification challenge.
- `WHATSAPP_ACCESS_TOKEN`: permanent/long-lived access token for Graph API.
- `WHATSAPP_PHONE_NUMBER_ID`: WhatsApp phone number ID from Meta app.
- `WHATSAPP_API_VERSION` (optional): defaults to `v22.0`.
- `WHATSAPP_BOT_PORT` (optional): defaults to `8080`.

## Run
- Scraper:
  - `python webscraper.py`
- WhatsApp webhook server:
  - `python whatsapp_bot.py`

## Data Files
- `data/abstracts_YYYY-MM-DD.json`: normalized scraped papers.
- `data/latest_evaluation.json`: latest structured Gemini ranking output used by `/top`.
- `data/pending_gemini_payload.json`: saved request payload if Gemini returns `429`; overwritten then deleted after successful resend.

## Command Support
- `/top`: returns top-ranked papers from `data/latest_evaluation.json`.

## Validation Checklist
1. Run scraper and confirm `data/latest_evaluation.json` exists.
2. Open `data/latest_evaluation.json` and confirm each top paper includes `authors`.
3. Configure Meta webhook URL to `GET/POST` endpoint of `whatsapp_bot.py`.
4. Complete verification handshake using `WHATSAPP_VERIFY_TOKEN`.
5. Send `/top` to the bot and confirm response includes title, authors, score, and link.
