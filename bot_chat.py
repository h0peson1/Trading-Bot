"""
bot_chat.py - Interactive Conversational Companion for Trading Bot
Provides friendly, natural dialogue, market banter, and optional Gemini LLM chat.
"""

import re
import random
from typing import Optional
import requests
import config

# Friendly personality system prompt for AI fallback (if Gemini API key is configured)
SYSTEM_PROMPT = (
    "You are a friendly, witty, and supportive professional trading companion bot named Axiory Bot. "
    "You monitor BTC, Gold, and Forex markets 24/7 using price action. "
    "Speak warmly and casually like a disciplined trading buddy. Keep replies concise (1-3 sentences max) "
    "suitable for Telegram. Never give financial guarantees, but be encouraging and friendly."
)


def call_gemini_api(user_message: str, user_name: str, api_key: str) -> Optional[str]:
    """Call Google Gemini free REST API for natural conversational AI."""
    models_to_try = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-latest"]
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"The trader's name is {user_name}.\n"
        f"Trader says: \"{user_message}\"\n\n"
        f"Your response:"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 150,
            "temperature": 0.7,
        }
    }
    headers = {"Content-Type": "application/json"}

    for model in models_to_try:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            res = requests.post(url, headers=headers, json=payload, timeout=8)
            if res.status_code == 200:
                data = res.json()
                candidates = data.get("candidates", [])
                if candidates:
                    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                    if text:
                        return text
        except Exception as e:
            print(f"[Gemini Chat Error ({model})]: {e}")
    return None


def get_chat_response(user_text: str, user_name: str = "trader") -> str:
    """
    Analyzes incoming user message and returns a natural, friendly reply.
    Uses rule-based conversational intelligence first (instant, reliable, no API required).
    If Gemini API key is provided in config, uses Gemini for open-ended queries.
    """
    clean_name = user_name if user_name and user_name != "trader" else "friend"
    text = user_text.strip()
    lower = text.lower()

    # Clean punctuation for pattern matching
    normalized = re.sub(r"[^\w\s]", "", lower).strip()

    # 1. Greetings (Hi, Hello, Hey, Yo, Good morning, etc.)
    greetings_patterns = [
        r"^(hi|hello|hey|heya|hiya|howdy|yo|hola|greetings)\b",
        r"^good\s+(morning|afternoon|evening|day)\b",
        r"^(sup|whats\s*up|what\s+up|wassup)\b",
    ]
    for pat in greetings_patterns:
        if re.search(pat, normalized):
            if "morning" in normalized:
                replies = [
                    f"Good morning {clean_name}! 🌅 Ready for today's market action. I'm keeping a sharp eye on all pairs for you!",
                    f"Morning {clean_name}! ☕ Markets are active. I'll alert you the moment a high-probability setup confirms.",
                    f"Good morning! Hope you slept well. I've been monitoring the charts all night and everything is set for today! 🚀",
                ]
            elif "evening" in normalized or "night" in normalized:
                replies = [
                    f"Good evening {clean_name}! 🌙 Relax and enjoy your evening. I'm watching the overnight candles for you.",
                    f"Good evening! I'm on duty monitoring the charts 24/7 so you don't have to stress. 🍵",
                ]
            elif "afternoon" in normalized:
                replies = [
                    f"Good afternoon {clean_name}! ☀️ Hope your day is going great. Still tracking all our key pairs for clean setups!",
                    f"Afternoon {clean_name}! Keeping the focus sharp through the sessions. Let's see what the charts give us today.",
                ]
            else:
                replies = [
                    f"Hey {clean_name}! 👋 Great to hear from you! How's your trading day going?",
                    f"Hello {clean_name}! ☕ Always right here watching the charts for you. What's on your mind today?",
                    f"Hey there! 👋 I'm actively scanning the markets for our next clean entry. How are you doing today?",
                    f"Hi {clean_name}! Ready to catch some good moves whenever the market gives us the green light! 📈",
                ]
            return random.choice(replies)

    # 2. Well-being inquiries ("How are you?", "How are you doing?", "You good?")
    how_are_you_patterns = [
        r"how\s+are\s+you",
        r"how\s+you\s+doing",
        r"hows\s+it\s+going",
        r"how\s+is\s+it\s+going",
        r"are\s+you\s+good",
        r"how\s+have\s+you\s+been",
        r"you\s+doing\s+good",
        r"you\s+alright",
    ]
    for pat in how_are_you_patterns:
        if re.search(pat, normalized):
            replies = [
                f"I'm feeling great and laser-focused, {clean_name}! ⚡ Scanning BTC, Gold, and Forex 24/7 so you never miss a move. How are you doing?",
                f"Running at 100%! 🚀 No emotions, no fatigue—just pure chart discipline. How has your day been, {clean_name}?",
                f"Doing fantastic, thank you for asking! 📊 Watching every 15m candle close attentively. How's everything on your side?",
                f"All systems green and running smoothly! 🟢 Always ready for the next setup. How's trading treating you today?",
            ]
            return random.choice(replies)

    # 3. Night / Bedtime ("Good night", "Going to sleep", "Going to bed")
    goodnight_patterns = [
        r"^(good\s*night|gn|sleep\s+well|going\s+to\s+bed|going\s+to\s+sleep)\b",
    ]
    for pat in goodnight_patterns:
        if re.search(pat, normalized):
            replies = [
                f"Good night {clean_name}! 🌙 Rest well. Don't worry about the charts—I'll be watching and will buzz you if a trade triggers!",
                f"Sleep tight {clean_name}! 🛌 I've got the night watch covered across all pairs. Talk to you tomorrow!",
                f"Good night! 😴 Rest your mind—disciplined trading starts with good sleep. I'll keep the bot engine running 24/7.",
            ]
            return random.choice(replies)

    # 4. Gratitude, Compliments & Well Wishes
    thanks_patterns = [
        r"\b(thanks|thank\s+you|thx|ty|appreciate\s+it|bless\s+you)\b",
        r"\b(good\s+job|great\s+job|well\s+done|nice\s+work|awesome|you\s+rock|love\s+you)\b",
        r"\b(have\s+a\s+(great|good|nice)\s+day|take\s+care)\b",
    ]
    for pat in thanks_patterns:
        if re.search(pat, normalized):
            replies = [
                f"You're very welcome, {clean_name}! 🙌 Always here in your corner. Let's keep winning together!",
                f"Anytime! 🤝 That's what a good trading buddy is for. Let me know whenever you need anything!",
                f"Thank you, {clean_name}! You have a wonderful day too. Staying disciplined and patient pays off in the long run! 💎",
                f"Glad to help! 🚀 Let's stay focused and wait for the best entries.",
            ]
            return random.choice(replies)

    # 5. Market & Strategy questions ("How's the market?", "How is the market?", "Any setups?", "What are you watching?")
    market_patterns = [
        r"how(\s*is|\s*are|\s*s)\s+(the\s+)?market",
        r"what\s+are\s+you\s+watching",
        r"any\s+(trades|setups|signals)",
        r"how\s+(do|are)\s+the\s+charts",
        r"is\s+the\s+market\s+good",
        r"what\s+pairs",
        r"market\s+status|market\s+update",
    ]
    for pat in market_patterns:
        if re.search(pat, normalized):
            pairs_list = ", ".join(config.SYMBOLS.keys())
            replies = [
                f"I'm actively tracking <b>{len(config.SYMBOLS)} pairs</b> ({pairs_list})! 📊 As soon as a rejection candle confirms with the trend, you'll get an alert with Entry, TP, and SL. Tap '🔍 Scan for Signals' to check right now!",
                f"The markets are flowing! 📈 We're sticking to high-probability setups—waiting for clean candlestick rejections. You can tap '🔍 Scan for Signals' anytime for an instant check!",
                f"Watching {pairs_list} closely! We wait patiently for the market to come to our zones. Quality setups only! 💎",
            ]
            return random.choice(replies)

    # 6. Identity & Fun ("Who are you?", "What do you do?", "Tell me a joke")
    if re.search(r"who\s+are\s+you|what\s+are\s+you|what\s+do\s+you\s+do", normalized):
        return (
            f"I'm your personal Price Action Trading Companion, {clean_name}! 🤖\n\n"
            f"• I scan 15-minute and 4-hour candles 24/7.\n"
            f"• I look for clean rejection patterns aligned with market structure.\n"
            f"• Whenever a setup is ready, I send you the exact Entry, TP, SL, and Reason!\n\n"
            f"And best of all, I'm always here to chat when you want company on the charts! ☕"
        )

    if re.search(r"joke|make\s+me\s+laugh", normalized):
        jokes = [
            "Why did the trader break up with the trendline? Because it kept breaking his support! 😂",
            "Why do day traders make terrible poker players? Because they always show their stops! 🃏",
            "What's a trader's favorite music genre? Swing! 🎶",
        ]
        return random.choice(jokes)

    # 7. Check-in / Liveness ("Are you there?", "Are you awake?", "Ping")
    if re.search(r"^(are\s+you\s+(there|awake|alive|running)|ping|test)\b", normalized):
        return f"I'm right here with you, {clean_name}! 🟢 Fully awake, listening, and scanning the markets 24/7."

    # 8. If Gemini API Key is available in config, use Gemini for open-ended questions
    gemini_key = getattr(config, "GEMINI_API_KEY", None)
    if gemini_key and gemini_key != "YOUR_GEMINI_API_KEY_HERE":
        ai_reply = call_gemini_api(user_text, clean_name, gemini_key)
        if ai_reply:
            return ai_reply

    # 9. Natural conversational fallback
    fallback_replies = [
        f"I hear you, {clean_name}! 💬 I'm right here with you keeping an eye on the charts. Feel free to chat with me anytime, or tap '🔍 Scan for Signals' to check the pairs!",
        f"Got that, {clean_name}! 👍 I'm staying focused on the markets for our next clean trade setup. How can I help you right now?",
        f"Always listening, {clean_name}! 📈 While we chat, I'm making sure we don't miss any high-probability entries. Let's catch some pips!",
    ]
    return random.choice(fallback_replies)
