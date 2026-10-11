import feedparser
import datetime
import config

# URL for ForexFactory weekly economic calendar RSS feed
FF_RSS_URL = "https://www.forexfactory.com/ffcal_weekly.xml"

def fetch_macro_news(limit: int = 5) -> str:
    """Fetch latest macro news headlines from ForexFactory RSS.
    Returns a formatted string with up to `limit` most recent items.
    """
    try:
        feed = feedparser.parse(FF_RSS_URL)
    except Exception as e:
        return f"[Error fetching macro news]: {e}"
    if not feed or not getattr(feed, "entries", None):
        return "No macro news entries found."
    entries = feed.entries[:limit]
    lines = []
    for entry in entries:
        title = entry.get("title", "No Title")
        published = entry.get("published", "")
        try:
            dt = datetime.datetime.strptime(published, "%a, %d %b %Y %H:%M:%S %z")
            date_str = dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            date_str = published
        lines.append(f"• <b>{date_str}</b> – {title}")
    return "\n".join(lines)
