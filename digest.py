"""
Daily Influencer Digest
Collects today's X (Twitter) posts from AI-in-QA thought leaders
and sends them to a Telegram channel via a bot.

Env vars (set as GitHub Actions secrets):
  TWITTERAPI_KEY      - API key from https://twitterapi.io
  TELEGRAM_BOT_TOKEN  - token from @BotFather
  TELEGRAM_CHAT_ID    - @your_channel_username  (or -100... id for private channels)
Optional:
  DIGEST_TZ           - timezone that defines "today" (default Asia/Yerevan)
"""

import html
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

API_URL = "https://api.twitterapi.io/twitter/user/last_tweets"
TZ = ZoneInfo(os.getenv("DIGEST_TZ", "Asia/Yerevan"))
EXCERPT_LEN = 600


def load_handles(path="influencers.txt"):
    handles = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            handle = line.split("#", 1)[0].strip().lstrip("@")
            if handle:
                handles.append(handle)
    return handles


def http_get_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_latest_tweets(handle, api_key):
    """Return the latest ~20 tweets of a user (no replies)."""
    query = urllib.parse.urlencode({"userName": handle, "includeReplies": "false"})
    data = http_get_json(f"{API_URL}?{query}", {"X-API-Key": api_key})
    # The API sometimes nests results under "data"
    tweets = data.get("tweets") or (data.get("data") or {}).get("tweets") or []
    return tweets


def parse_created_at(value):
    # Format: "Tue Dec 10 07:00:30 +0000 2024"
    return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")


def is_today(tweet, today):
    try:
        return parse_created_at(tweet["createdAt"]).astimezone(TZ).date() == today
    except (KeyError, ValueError):
        return False


def format_message(tweet):
    author = tweet.get("author") or {}
    name = html.escape(author.get("name") or author.get("userName", "Unknown"))
    user = html.escape(author.get("userName", ""))
    text = tweet.get("text", "")
    if len(text) > EXCERPT_LEN:
        text = text[:EXCERPT_LEN].rstrip() + "…"
    posted = parse_created_at(tweet["createdAt"]).astimezone(TZ).strftime("%H:%M")
    url = tweet.get("url") or f"https://x.com/{user}/status/{tweet.get('id', '')}"
    return (
        f"👤 <b>{name}</b> (@{user}) · {posted}\n\n"
        f"{html.escape(text)}\n\n"
        f'🔗 <a href="{html.escape(url)}">Open original post</a>'
    )


def send_telegram(token, chat_id, text):
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=payload
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(f"Telegram error: {result}")
    time.sleep(1)  # stay well under Telegram rate limits


def main():
    api_key = os.environ["TWITTERAPI_KEY"]
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    today = datetime.now(TZ).date()
    print(f"Collecting posts for {today} ({TZ.key})")

    todays = []
    for handle in load_handles():
        try:
            tweets = fetch_latest_tweets(handle, api_key)
        except Exception as e:  # one bad account shouldn't kill the whole run
            print(f"  ! @{handle}: {e}", file=sys.stderr)
            continue
        fresh = [t for t in tweets if not t.get("isRetweet") and is_today(t, today)]
        print(f"  @{handle}: {len(tweets)} fetched, {len(fresh)} from today")
        todays.extend(fresh)

    todays.sort(key=lambda t: parse_created_at(t["createdAt"]))

    if not todays:
        send_telegram(bot_token, chat_id, f"📭 No new posts today ({today:%d %b %Y}).")
        print("No posts today - sent notice.")
        return

    send_telegram(
        bot_token,
        chat_id,
        f"🧪 <b>AI in QA — Daily Digest</b>\n{today:%A, %d %B %Y} · {len(todays)} new post(s)",
    )
    for tweet in todays:
        send_telegram(bot_token, chat_id, format_message(tweet))
    print(f"Sent {len(todays)} post(s).")


if __name__ == "__main__":
    main()
