import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# --- LOGGING ---
# We enable DEBUG logs to see EXACTLY what Telegram sends us
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG
)
# Silence the noisy network logs
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- DUMMY SERVER (Keep Render Happy) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.wfile.write(b"Debug Bot Active")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), SimpleHandler).serve_forever()

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ I am alive! Send me any text.")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    print(f"Received: {user_text}")  # This will show in Render logs
    await update.message.reply_text(f"I heard you say: {user_text}")

def main():
    if not TOKEN:
        print("❌ ERROR: No TELEGRAM_TOKEN found!")
        return

    application = Application.builder().token(TOKEN).build()

    # Simple handlers: No conversation states, just direct replies
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    print("🤖 Debug Bot Started...")
    application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    main()
