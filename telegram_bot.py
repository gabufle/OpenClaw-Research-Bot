import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
import requests

# ─────────────────────────────────────────
# PATHS & CONSTANTS
# ─────────────────────────────────────────
LATEST_EVALUATION_PATH = os.path.join("data", "latest_evaluation.json")
HISTORY_PATH           = os.path.join("data", "sent_papers_history.json")
HISTORY_DAYS           = 7
SEND_HOUR_LOCAL        = 8   # 8:00 AM local time

# ─────────────────────────────────────────
# ENV VARS
# ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
RUN_ONCE           = os.environ.get("RUN_ONCE", "").lower() in ("1", "true", "yes")

# plain text formatting 
def format_top_message_plain(papers: list[dict]) -> str:
    date_str = datetime.now().strftime("%b %d, %Y")
    lines = [f"Top {len(papers)} papers — {date_str}\n"]
    
    for i, paper in enumerate(papers, start=1):
        lines.append(f"{i}. {paper.get('title', 'Untitled')}")
        lines.append(f"   Authors: {paper.get('authors', 'Unknown')}")
        lines.append(f"   Score: {paper.get('score', 'N/A')} | {paper.get('source', '')}")
        lines.append(f"   {paper.get('reason', '')}")
        lines.append(f"   {paper.get('url', '')}")
        lines.append("")
    
    return "\n".join(lines)




# ==========================================
# 1. MARKDOWNV2 FORMATTING HELPERS
# ==========================================

# All characters that Telegram MarkdownV2 requires to be escaped
_MDV2_SPECIAL = r"\_*[]()~`>#+-=|{}.!"


# def escape_mdv2(text: str) -> str:
#     """Escape every MarkdownV2 reserved character in a plain-text string."""
#     return re.sub(r"([\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!])", r"\\\1", str(text))


# def format_paper_mdv2(paper: dict, display_rank: int | None = None) -> str:
#     """
#     Render a single paper dict as a MarkdownV2-safe Telegram message block.

#     Uses display_rank for the visible number so re-ranked new-only lists still
#     show 1, 2, 3 … rather than the raw Gemini rank field.
#     """
#     rank    = display_rank if display_rank is not None else paper.get("rank", "?")
#     title   = escape_mdv2(paper.get("title",   "Untitled"))
#     authors = escape_mdv2(paper.get("authors", "Unknown Authors"))
#     score   = escape_mdv2(str(paper.get("score", "N/A")))
#     source  = escape_mdv2(paper.get("source",  ""))
#     reason  = escape_mdv2(paper.get("reason",  ""))
#     url     = paper.get("url", "")  # URLs must NOT be escaped

#     lines = [
#         f"*{escape_mdv2(str(rank))}\\.* [{title}]({url})",
#         f"👥 {authors}",
#         f"📊 Score: *{score}* \\| 🗂 {source}",
#         f"💡 _{reason}_",
#     ]
#     return "\n".join(lines)


# def format_top_message_mdv2(papers: list[dict]) -> str:
#     """Build the full MarkdownV2 message for a list of (already-filtered) papers."""
#     date_str = escape_mdv2(datetime.now().strftime("%b %d, %Y"))
#     count    = escape_mdv2(str(len(papers)))
#     header   = f"*🔬 Top {count} papers — {date_str}*"

#     blocks = [header]
#     for i, paper in enumerate(papers, start=1):
#         blocks.append("")
#         blocks.append(format_paper_mdv2(paper, display_rank=i))
#     return "\n".join(blocks)


# ==========================================
# 2. URL HISTORY PERSISTENCE (7-day window)
# ==========================================

def load_history() -> dict:
    """
    Load sent-URL history from disk.
    Returns a dict of {url: iso_timestamp_utc}.
    """
    if not os.path.exists(HISTORY_PATH):
        return {}
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  ⚠️  Could not load history ({exc}); starting fresh.")
        return {}


def save_history(history: dict) -> None:
    """Persist the history dict to disk."""
    os.makedirs("data", exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def prune_history(history: dict) -> dict:
    """Drop entries older than HISTORY_DAYS days (keeps the dict lean)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)
    pruned = {}
    for url, ts in history.items():
        try:
            if datetime.fromisoformat(ts) >= cutoff:
                pruned[url] = ts
        except ValueError:
            pass  # drop malformed timestamps
    removed = len(history) - len(pruned)
    if removed:
        print(f"  🗑  Pruned {removed} expired URL(s) from history.")
    return pruned


def record_sent_urls(urls: list[str], history: dict) -> dict:
    """Mark a batch of URLs as sent right now (UTC)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    for url in urls:
        if url:
            history[url] = now_iso
    return history


# ==========================================
# 3. DUPLICATE FILTERING
# ==========================================

def filter_new_papers(papers: list[dict], history: dict) -> list[dict]:
    """Return only papers whose URL is NOT already in the history window."""
    new = [p for p in papers if p.get("url", "") not in history]
    dupes = len(papers) - len(new)
    if dupes:
        print(f"  🔁  Filtered {dupes} duplicate paper(s) (seen in last {HISTORY_DAYS} days).")
    return new


# ==========================================
# 4. TELEGRAM SEND
# ==========================================

def send_telegram_message(text: str, parse_mode: str = "None") -> None:
    """POST a message to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID. "
            "Set both environment variables before running."
        )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":                  TELEGRAM_CHAT_ID,
        "text":                     text,
        #"parse_mode":               parse_mode,
        "disable_web_page_preview": True,
    }
    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()


# ==========================================
# 5. MAIN SEND LOGIC
# ==========================================

def load_top_papers(limit: int = 5) -> list[dict]:
    """Read ranked papers from the latest Gemini evaluation file."""
    if not os.path.exists(LATEST_EVALUATION_PATH):
        return []
    with open(LATEST_EVALUATION_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("topPapers", [])[:limit]


def run_send() -> None:
    """
    Full send pipeline:
      1. Load latest evaluation.
      2. Prune + load URL history.
      3. Filter out already-sent papers.
      4. Send new papers OR a fallback 'all duplicates' message.
      5. Record sent URLs and persist history.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] Running send pipeline...")

    # --- Load evaluation ---
    papers = load_top_papers()
    if not papers:
        print("  ❌  No evaluation data found. Run webscraper.py first.")
        return

    # --- Deduplicate ---
    history     = prune_history(load_history())
    new_papers  = filter_new_papers(papers, history)

    # --- All duplicates fallback ---
    if not new_papers:
        fallback = (
            f"🔁 *No new papers today* — all top results were already sent "
            f"within the last {HISTORY_DAYS} days\\. Check back tomorrow\\!"
        )
        print("  ℹ️   All papers are duplicates. Sending fallback message.")
        send_telegram_message(fallback)
        return

    # --- Send new papers ---
    message = format_top_message_plain(new_papers)
    send_telegram_message(message)

    # --- Update history ---
    sent_urls = [p.get("url", "") for p in new_papers]
    history   = record_sent_urls(sent_urls, history)
    save_history(history)
    print(f"  ✅  Sent {len(new_papers)} new paper(s). History saved to {HISTORY_PATH}.")


# ==========================================
# 6. SCHEDULER (8:00 AM local, or RUN_ONCE)
# ==========================================

def seconds_until_next_8am() -> float:
    """Return seconds until the next 8:00 AM in local time."""
    now    = datetime.now()
    target = now.replace(hour=SEND_HOUR_LOCAL, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def main() -> None:
    if RUN_ONCE:
        print("▶  RUN_ONCE=true — executing immediately and exiting.")
        run_send()
        return

    print(
        f"📅  Scheduler started. "
        f"Will send daily at {SEND_HOUR_LOCAL:02d}:00 local time."
    )
    while True:
        wait     = seconds_until_next_8am()
        next_run = datetime.now() + timedelta(seconds=wait)
        print(
            f"  ⏳  Next send at {next_run.strftime('%Y-%m-%d %H:%M:%S')} "
            f"(in {wait / 3600:.2f} h)"
        )
        time.sleep(wait)

        try:
            run_send()
        except Exception as exc:
            print(f"  ❌  Send failed: {exc}")

        # Brief pause so the scheduler doesn't fire twice in the same minute
        time.sleep(61)


if __name__ == "__main__":
    main()