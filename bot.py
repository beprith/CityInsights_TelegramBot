# bot.py — simple UX, location or typed area, long wait, clean Langflow text
import os
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import httpx
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# -------------------- Config --------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
LANGFLOW_API_KEY = os.getenv("LANGFLOW_API_KEY")
LANGFLOW_URL = os.getenv("LANGFLOW_URL")  # e.g. http://localhost:7860/api/v1/run/<flow-id>

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing in env")
if not LANGFLOW_API_KEY:
    raise RuntimeError("LANGFLOW_API_KEY missing in env")
if not LANGFLOW_URL:
    raise RuntimeError("LANGFLOW_URL missing in env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("telebot")

IST = timezone(timedelta(hours=5, minutes=30))  # fixed Asia/Kolkata

# Reusable HTTP client
class Clients:
    httpx_client = None  # type: Optional[httpx.AsyncClient]

async def get_client() -> httpx.AsyncClient:
    if Clients.httpx_client is None:
        Clients.httpx_client = httpx.AsyncClient(headers={"User-Agent": "LangflowTeleBot/1.0"})
    return Clients.httpx_client

# -------------------- Helpers --------------------
def today_ist() -> datetime:
    return datetime.now(IST)

def compute_range(days: int) -> Tuple[str, str]:
    """Return (date_from_iso, date_to_iso) for IST, N days from today (inclusive start)."""
    start = today_ist().date()
    end = start + timedelta(days=max(1, days))
    return start.isoformat(), end.isoformat()

async def reverse_geocode_to_area(lat: float, lon: float) -> str:
    """Turn lat/lon into an area/city name using Nominatim (free)."""
    client = await get_client()
    try:
        r = await client.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "zoom": 10, "addressdetails": 1},
            headers={"User-Agent": "LangflowTeleBot/1.0"},
            timeout=12.0,
        )
        r.raise_for_status()
        data = r.json()
        addr = data.get("address", {})
        area = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("suburb")
            or addr.get("county")
            or addr.get("state_district")
            or addr.get("state")
            or addr.get("region")
            or addr.get("country")
        )
        return area or "Unknown area"
    except Exception as e:
        log.warning("Reverse geocode failed: %s", e)
        return "Unknown area"

def build_payload_raw(user_text: str, user_data: dict) -> dict:
    """RAW pass-through for input_value; metadata adds location + date range (days)."""
    meta = {}
    area = user_data.get("area_name")
    if area:
        meta["location"] = area

    days = user_data.get("days")
    if days:
        d1, d2 = compute_range(int(days))
        meta["date_from"] = d1
        meta["date_to"] = d2

    return {
        "output_type": "chat",
        "input_type": "chat",
        "input_value": user_text or "",  # RAW, no trimming
        "metadata": meta,
    }

def _extract_langflow_text(data):
    """
    Pull the readable reply from common Langflow shapes.
    Prefers: outputs[0].outputs[0].results.message.data.text
             then ...message.text
             then any 'text' string found via deep search.
    """

    # 1) Exact path (common)
    try:
        text = data["outputs"][0]["outputs"][0]["results"]["message"]["data"]["text"]
        if isinstance(text, str) and text.strip():
            return text.strip()
    except Exception:
        pass

    # 2) Variant: message["text"]
    try:
        text = data["outputs"][0]["outputs"][0]["results"]["message"]["text"]
        if isinstance(text, str) and text.strip():
            return text.strip()
    except Exception:
        pass

    # 3) Deep search for a 'text' field
    def deep_find_text(obj):
        if isinstance(obj, dict):
            if "text" in obj and isinstance(obj["text"], str) and obj["text"].strip():
                return obj["text"].strip()
            for v in obj.values():
                found = deep_find_text(v)
                if found:
                    return found
        elif isinstance(obj, list):
            for it in obj:
                found = deep_find_text(it)
                if found:
                    return found
        return None

    found = deep_find_text(data)
    if isinstance(found, str) and found.strip():
        return found.strip()

    # 4) Last resort: compact JSON
    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return "No readable text in response."

async def call_langflow_clean(user_text: str, user_data: dict) -> str:
    """Call Langflow and return a CLEAN human string. Generous timeouts for slow flows."""
    client = await get_client()
    payload = build_payload_raw(user_text, user_data)
    headers = {"Content-Type": "application/json", "x-api-key": LANGFLOW_API_KEY}

    timeout = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)

    log.info("Calling Langflow %s with metadata=%s", LANGFLOW_URL, payload.get("metadata"))
    try:
        r = await client.post(LANGFLOW_URL, headers=headers, json=payload, timeout=timeout)
        r.raise_for_status()

        # Prefer JSON parse + extraction; fallback to raw text
        try:
            data = r.json()
            clean = _extract_langflow_text(data)
            # Trim trailing spaces on lines
            clean = "\n".join(line.rstrip() for line in clean.splitlines())
            return clean[:4000] if clean else "Empty response."
        except json.JSONDecodeError:
            text = r.text or "Empty response."
            return text[:4000]
    except httpx.HTTPStatusError as e:
        body = e.response.text if e.response else ""
        return "Langflow HTTP {}: {}".format(
            e.response.status_code if e.response else "", (body or "")[:900]
        )
    except httpx.RequestError as e:
        return "Couldn’t reach Langflow: {}".format(e)

# -------------------- Handlers --------------------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Clear onboarding + quick day buttons + /share hint
    day_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("3 days", callback_data="days:3"),
        InlineKeyboardButton("7 days", callback_data="days:7"),
        InlineKeyboardButton("14 days", callback_data="days:14"),
    ]])
    msg = (
        "👋 Welcome! Please set:\n"
        "1) Your **area** → /setarea <area name> **or** /share to send your location\n"
        "2) How many **days** → /setdays <N> (or tap a quick button below)\n\n"
        "Then send any message—I’ll forward it to Langflow with your location & date range.\n\n"
        "Examples:\n"
        "• /setarea Bengaluru\n"
        "• /setdays 7"
    )
    await update.message.reply_text(msg, reply_markup=day_kb, parse_mode="Markdown")

async def share(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # One-time keyboard with Telegram's native "Share Location" button
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton(text="📍 Share current location", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text("Tap the button to share your location:", reply_markup=kb)

async def handle_location(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    if not loc:
        return
    await update.message.chat.send_action("typing")
    area = await reverse_geocode_to_area(loc.latitude, loc.longitude)
    ctx.user_data["area_name"] = area

    days = ctx.user_data.get("days")
    if days:
        d1, d2 = compute_range(int(days))
        text = "Area set from location: ✅ {}\nDates: {} → {}\nYou can change with /setdays <N>.".format(area, d1, d2)
    else:
        text = "Area set from location: ✅ {}\nTip: now set days with /setdays <N>.".format(area)

    await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())

async def on_days_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data.startswith("days:"):
        try:
            days = int(data.split(":", 1)[1])
            ctx.user_data["days"] = days
            d1, d2 = compute_range(days)
            await q.edit_message_text(
                "Days set: ✅ {} ({} → {})\nNow set area with /setarea <name> or /share, or just send a message."
                .format(days, d1, d2)
            )
        except Exception:
            await q.edit_message_text("Couldn’t set days. Use /setdays <N>.")

async def setarea(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /setarea <area name>\nExample: /setarea Bengaluru")
        return
    area = " ".join(ctx.args).strip()
    ctx.user_data["area_name"] = area
    days = ctx.user_data.get("days")
    if days:
        d1, d2 = compute_range(int(days))
        await update.message.reply_text("Area set: ✅ {}\nDates: {} → {}".format(area, d1, d2))
    else:
        await update.message.reply_text("Area set: ✅ {}\nTip: set days via /setdays <N> or use buttons on /start.".format(area))

async def setdays(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /setdays <N>\nExample: /setdays 7")
        return
    try:
        days = max(1, int(ctx.args[0]))
    except ValueError:
        await update.message.reply_text("Please provide a number (e.g., /setdays 7).")
        return
    ctx.user_data["days"] = days
    d1, d2 = compute_range(days)
    await update.message.reply_text("Days set: ✅ {} ({} → {})".format(days, d1, d2))

async def show(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    area = ctx.user_data.get("area_name", "(not set)")
    days = ctx.user_data.get("days", "(not set)")
    if isinstance(days, int):
        d1, d2 = compute_range(days)
        await update.message.reply_text("Current context:\n• Area: {}\n• Days: {} ({} → {})".format(area, days, d1, d2))
    else:
        await update.message.reply_text("Current context:\n• Area: {}\n• Days: {}".format(area, days))

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Soft nudge if context is missing
    if not ctx.user_data.get("area_name") or not ctx.user_data.get("days"):
        await update.message.reply_text(
            "Tip: set your context for better answers:\n"
            "• /setarea <area>  or  /share (send location)\n"
            "• /setdays <N>  (or use the buttons in /start)"
        )

    user_text = update.message.text or ""
    placeholder = await update.message.reply_text("⏳ Asking Langflow… this may take a moment.")
    try:
        reply_text = await call_langflow_clean(user_text, ctx.user_data)
        await placeholder.edit_text(reply_text if reply_text else "No reply.")
    except Exception as e:
        await placeholder.edit_text("Error: {}".format(e))

# -------------------- Bootstrap --------------------
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("share", share))
    app.add_handler(CallbackQueryHandler(on_days_button, pattern=r"^days:\d+$"))
    app.add_handler(CommandHandler("setarea", setarea))
    app.add_handler(CommandHandler("setdays", setdays))
    app.add_handler(CommandHandler("show", show))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()

