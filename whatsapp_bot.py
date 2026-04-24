import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests

LATEST_EVALUATION_PATH = os.path.join("data", "latest_evaluation.json")
VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
API_VERSION = os.environ.get("WHATSAPP_API_VERSION", "v22.0")
BOT_PORT = int(os.environ.get("WHATSAPP_BOT_PORT", "8080"))


def send_whatsapp_text(to_number, message):
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        raise ValueError("Missing WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID.")

    url = f"https://graph.facebook.com/{API_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message},
    }
    response = requests.post(url, headers=headers, json=payload, timeout=20)
    response.raise_for_status()


def load_top_papers(limit=5):
    if not os.path.exists(LATEST_EVALUATION_PATH):
        return []

    with open(LATEST_EVALUATION_PATH, "r", encoding="utf-8") as file_obj:
        data = json.load(file_obj)
    top_papers = data.get("topPapers", [])
    return top_papers[:limit]


def format_top_message(limit=5):
    top_papers = load_top_papers(limit=limit)
    if not top_papers:
        return (
            "No evaluation data is available yet. "
            "Run the scraper first to generate ranked papers."
        )

    lines = [f"Top {len(top_papers)} papers:"]
    for item in top_papers:
        rank = item.get("rank", "?")
        title = item.get("title", "Untitled")
        authors = item.get("authors", "Unknown Authors")
        score = item.get("score", "N/A")
        url = item.get("url", "")
        lines.append(f"{rank}. {title}")
        lines.append(f"   Authors: {authors}")
        lines.append(f"   Score: {score}")
        if url:
            lines.append(f"   Link: {url}")
    return "\n".join(lines)


def extract_command(payload):
    entries = payload.get("entry", [])
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            for message in messages:
                text_body = message.get("text", {}).get("body", "").strip()
                from_number = message.get("from")
                if text_body and from_number:
                    return text_body, from_number
    return None, None


class WhatsAppWebhookHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code, body):
        body_bytes = json.dumps(body).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        mode = params.get("hub.mode", [""])[0]
        token = params.get("hub.verify_token", [""])[0]
        challenge = params.get("hub.challenge", [""])[0]

        if mode == "subscribe" and token == VERIFY_TOKEN:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(challenge.encode("utf-8"))
            return
        self._send_json(403, {"error": "Verification failed"})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length).decode("utf-8")
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON payload"})
            return

        command, sender = extract_command(payload)
        if not command or not sender:
            self._send_json(200, {"status": "ignored", "reason": "No message command"})
            return

        try:
            lowered = command.lower()
            if lowered.startswith("/top"):
                message = format_top_message(limit=5)
            else:
                message = "Supported command: /top"
            send_whatsapp_text(sender, message)
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})
            return

        self._send_json(200, {"status": "ok"})


def run_server():
    server = HTTPServer(("0.0.0.0", BOT_PORT), WhatsAppWebhookHandler)
    print(f"WhatsApp bot listening on port {BOT_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
