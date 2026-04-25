# OpenClaw Research Bot

## Overview

| Script | Role |
|---|---|
| `webscraper.py` | Scrapes arXiv & PubMed, builds a compact Gemini payload, saves ranked output to `data/latest_evaluation.json`. |
| `telegram_bot.py` | Reads the latest evaluation, deduplicates against a 7-day URL history, and sends new papers to a Telegram chat. Runs on a daily 8:00 AM local-time schedule (or immediately with `RUN_ONCE`). |

---

## Environment Variables

### Scraper (`webscraper.py`)
| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | ✅ | — | API key for Gemini 2.5 Flash evaluation. |

### Telegram Bot (`telegram_bot.py`)
| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Bot token from [@BotFather](https://t.me/BotFather). |
| `TELEGRAM_CHAT_ID` | ✅ | — | Target chat or channel ID (use `@channelusername` or a numeric ID). |
| `RUN_ONCE` | ❌ | `false` | Set to `true`, `1`, or `yes` to send immediately and exit (skips the scheduler). Useful for manual runs or cron jobs. |

---

## Run

```bash
# 1. Run the scraper to fetch & evaluate papers
python webscraper.py

# 2a. Start the Telegram bot scheduler (runs every day at 08:00 local time)
python telegram_bot.py

# 2b. Or send immediately (manual / one-shot / cron mode)
RUN_ONCE=true python telegram_bot.py

# 3. (Legacy) Start the WhatsApp webhook server
python whatsapp_bot.py
```

---

## Data Files

| Path | Description |
|---|---|
| `data/abstracts_YYYY-MM-DD.json` | Normalised scraped papers for a given date. |
| `data/latest_evaluation.json` | Latest structured Gemini ranking output used by both bots. |
| `data/sent_papers_history.json` | **NEW** — Telegram URL history (rolling 7-day window). Maps `url → UTC ISO timestamp`. Pruned automatically on each run. |
| `data/pending_gemini_payload.json` | Saved Gemini request payload when a 429 is received; overwritten then securely deleted after a successful resend. |

---

## Telegram Bot — Behaviour Details

### 7-Day Deduplication
`data/sent_papers_history.json` stores every URL successfully sent to Telegram alongside a UTC ISO-8601 timestamp. On each run:

1. Entries older than 7 days are pruned.
2. Papers whose URL already exists in the history are filtered out.
3. Only genuinely new papers are included in the message.
4. After a successful send, all newly sent URLs are recorded with the current timestamp.

### All-Duplicates Fallback
If every paper in the current evaluation was sent within the last 7 days, the bot sends a single plain fallback message instead of an empty payload:

> 🔁 *No new papers today* — all top results were already sent within the last 7 days. Check back tomorrow!

### Scheduler
The default mode wakes once per day, sleeps until 08:00 local time, fires `run_send()`, then sleeps for 61 seconds before re-arming (preventing a double-fire within the same minute). Setting `RUN_ONCE=true` bypasses the loop entirely — the bot executes once and exits, which is compatible with `cron`, `systemd` timers, or CI pipelines.

---

## Validation Checklist

### Scraper
1. `python webscraper.py` completes without errors.
2. `data/latest_evaluation.json` exists and each entry contains `rank`, `title`, `authors`, `source`, `url`, `score`, `reason`.

### Telegram Bot
3. `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set.
4. `RUN_ONCE=true python telegram_bot.py` delivers a formatted MarkdownV2 message to the target chat.
5. Verify `data/sent_papers_history.json` now contains the sent URLs.
6. Run a second time with `RUN_ONCE=true` — confirm the fallback "no new papers" message is sent (deduplication working).
7. Manually add an old timestamp (> 7 days ago) to `sent_papers_history.json` for one URL and re-run — confirm that entry is pruned and the paper is sent again.
8. Start without `RUN_ONCE` and verify the console prints the next scheduled send time at 08:00 local time.
