# Urban Pulse TeleBot (Langflow + Telegram)

A lightweight Telegram bot that sends user messages to a **Langflow** flow and returns a **clean, human-readable** answer.
Users can set:

* **Area** (via `/setarea <name>` or by sharing Telegram **location**),
* **Days** (via `/setdays <N>` or quick 3/7/14 buttons).

The bot adds `{ location, date_from, date_to }` to the Langflow request metadata and handles **slow responses** gracefully.

---

## ✨ Features

* Simple onboarding: prompts users to set **area** + **days** on `/start`
* **Two ways** to set area:

  * `/setarea <area name>` (typed)
  * `/share` → native Telegram **Share Location** → reverse-geocoded to an area name
* **Date range** via `/setdays <N>` (today → +N days, IST)
* Clean extraction of text from Langflow’s JSON (no giant blobs)
* Generous HTTP timeouts to handle slow flows
* Python 3.8+ compatible (no `zoneinfo` dependency)

---

## 🧰 Tech Stack

* Python `python-telegram-bot` v21+
* HTTP client: `httpx`
* Env management: `python-dotenv`
* Reverse geocoding: **Nominatim** (OpenStreetMap)

---

## 🗂️ Project Structure

```
.
├── bot.py          # Telegram bot
├── README.md
└── .env.example    # Sample environment file (copy to .env)
```

---

## 🔐 Environment Variables

Create a `.env` file (copy from `.env.example`):

```env
# Telegram
BOT_TOKEN=123456:ABC-YourTelegramBotToken

# Langflow
LANGFLOW_API_KEY=your_langflow_api_key
LANGFLOW_URL=http://localhost:7860/api/v1/run/<your-flow-id>
```

> ⚠️ **Security:** Never commit real tokens/keys. Rotate any key that was shared publicly.

---

## 📦 Installation

1. **Python & deps**

```bash
python3 -V   # should be 3.8+
pip install -r requirements.txt
```

If you don’t have a `requirements.txt`, install directly:

```bash
pip install python-telegram-bot==21.* httpx python-dotenv
```

2. **Set up your bot**

* In Telegram, open **@BotFather**
* `/newbot` → name + username → copy the **HTTP API token** → set `BOT_TOKEN` in `.env`
* Optional: `/setdescription`, `/setuserpic`, `/setcommands`

3. **Langflow**

* Run your Langflow flow and note the **full run URL**:

  * `LANGFLOW_URL=http://HOST:7860/api/v1/run/<flow-id>`
* Create/rotate an **API key** → set `LANGFLOW_API_KEY` in `.env`

---

## ▶️ Run the Bot (Polling)

```bash
python bot.py
```

You should see logs like:

```
INFO Application started
INFO Calling Langflow http://... with metadata=...
```

Open your bot in Telegram → **Start** → follow prompts.

---

## 🧪 Quick Tests

### Test Langflow with cURL

```bash
curl -i "$LANGFLOW_URL" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $LANGFLOW_API_KEY" \
  -d '{"output_type":"chat","input_type":"chat","input_value":"ping","metadata":{"location":"Bengaluru","date_from":"2025-09-01","date_to":"2025-09-07"}}'
```

### Commands to try in Telegram

```
/start
/setarea Bengaluru
/setdays 7
/show
/share   # prompts a “Share current location” button
```

Then send any message (e.g., “What’s up this week?”).

---

## 🧭 How Metadata Is Built

When you send a message, the bot posts to Langflow:

```json
{
  "output_type": "chat",
  "input_type": "chat",
  "input_value": "<RAW user text>",
  "metadata": {
    "location": "<AreaName>",
    "date_from": "YYYY-MM-DD",
    "date_to":   "YYYY-MM-DD"
  }
}
```

* `location` comes from `/setarea` or reverse-geocoding your shared Telegram location
* `date_from`/`date_to` are derived from `/setdays N` (IST timezone)

---

## 🧩 How Response Cleaning Works

Langflow often returns nested JSON. The bot extracts:

1. `outputs[0].outputs[0].results.message.data.text`, then
2. `...message.text`, else
3. first `text` string found anywhere
   If none found, it falls back to a compact JSON preview.

---

## 🚀 Deployment (Webhook optional)

Polling is fine for small bots. For production scale:

* Host on Render/Railway/Fly.io/Cloud Run/EC2, set env vars
* Switch `run_polling()` to `run_webhook(...)` (see python-telegram-bot docs)
* Ensure **Langflow URL** is reachable from the host (don’t use `localhost` across machines)

---

## 🛠️ Troubleshooting

* **Bot replies with huge JSON**
  → Your `call_langflow_clean()` handles extraction. If your flow has a different shape, tweak `_extract_langflow_text()`.

* **No response / timeout**
  → Increase read timeout in `httpx.Timeout(... read=180 ...)`
  → Check Langflow logs & `curl` directly (see test above)

* **401/403 from Langflow**
  → Wrong or missing `x-api-key`. Rotate key and update `.env`.

* **“Couldn’t reach Langflow”**
  → Host network/firewall/DNS; ensure `LANGFLOW_URL` is accessible from the bot machine

* **Group chats not triggering**
  → In groups, bot only sees commands if privacy is ON. Disable via @BotFather `/setprivacy` or test in DM.

---

## 📜 License

MIT — feel free to use and modify. Please keep attribution.

---

## 🙏 Credits

* Telegram API by **python-telegram-bot**
* HTTP via **httpx**
* Reverse geocoding by **Nominatim (OpenStreetMap)**
* Langflow for orchestration

---

## 📎 requirements.txt (optional)

```txt
python-telegram-bot==21.*
httpx>=0.27
python-dotenv>=1.0
```

---

## 🧩 Future Enhancements (optional)

* Google Maps Geocoding swap for more stable area names
* `/timeout <sec>` to adjust Langflow read timeout at runtime
* Inline menus for saved areas / presets
* Webhook deployment template (Dockerfile + Render/Fly config)

