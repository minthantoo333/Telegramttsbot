import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import edge_tts
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# --- CONFIGURATION ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
DEFAULT_VOICE = "my-MM-ThihaNeural"

# --- VOICE DATABASE ---
VOICES = {
    "🌟 Multilingual (Best AI)": {
        "Ava (Female)": "en-US-AvaMultilingualNeural",
        "Andrew (Male)": "en-US-AndrewMultilingualNeural",
        "Remy (French/Multi)": "fr-FR-RemyMultilingualNeural",
        "Giuseppe (Italian/Multi)": "it-IT-GiuseppeMultilingualNeural",
        "Emma (Female)": "en-US-EmmaMultilingualNeural",
        "Brian (Male)": "en-US-BrianMultilingualNeural",
    },
    "🇲🇲 Myanmar": {
        "Thiha (Male)": "my-MM-ThihaNeural",
        "Nular (Female)": "my-MM-NularNeural",
    },
    "🌏 Asia": {
        "Thai (Premwadee)": "th-TH-PremwadeeNeural",
        "Indonesian (Gadis)": "id-ID-GadisNeural",
        "Vietnamese (NamMinh)": "vi-VN-NamMinhNeural",
        "Japanese (Nanami)": "ja-JP-NanamiNeural",
        "Korean (SunHi)": "ko-KR-SunHiNeural",
        "Chinese (Xiaoxiao)": "zh-CN-XiaoxiaoNeural",
        "Hindi (Swara)": "hi-IN-SwaraNeural",
    },
    "🇪🇺 Europe": {
        "British (Sonia)": "en-GB-SoniaNeural",
        "French (Denise)": "fr-FR-DeniseNeural",
        "German (Katja)": "de-DE-KatjaNeural",
        "Spanish (Paloma)": "es-US-PalomaNeural",
    }
}

# --- LOGGING ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# Silence network logs
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- STATES ---
COLLECTING, CONFIRMING = range(2)

# --- DUMMY SERVER (Keep Alive) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Active")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    try:
        HTTPServer(("0.0.0.0", port), SimpleHandler).serve_forever()
    except Exception as e:
        print(f"Web server error: {e}")

# --- HELPERS ---
def get_settings_markup(data):
    speed = data.get("rate", 0)
    pitch = data.get("pitch", 0)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🐢 Slower", callback_data="rate_-10"),
         InlineKeyboardButton(f"🚀 Faster ({speed}%)", callback_data="rate_+10")],
        [InlineKeyboardButton(f"🔉 Lower", callback_data="pitch_-5"),
         InlineKeyboardButton(f"🔊 Higher ({pitch}Hz)", callback_data="pitch_+5")],
        [InlineKeyboardButton("✨ Crisp & Clear", callback_data="preset_crisp")],
        [InlineKeyboardButton("🔄 Reset Normal", callback_data="preset_reset")],
        [InlineKeyboardButton("✅ Close Settings", callback_data="close_settings")]
    ])

# --- MAIN COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Explicit start command."""
    context.user_data["text_buffer"] = []
    # Set defaults if missing
    context.user_data.setdefault("voice", DEFAULT_VOICE)
    context.user_data.setdefault("voice_name", "Burmese (Thiha)")
    context.user_data.setdefault("rate", 0)
    context.user_data.setdefault("pitch", 0)

    await update.message.reply_text(
        "👋 **Burmese TTS Bot Ready**\n\n"
        "Just send me your text! I will collect it.\n"
        "Type /done when finished.\n"
        "Type /voice to change speaker.\n"
        "Type /settings for speed/pitch.",
        parse_mode=ParseMode.MARKDOWN
    )
    return COLLECTING

async def collect_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Collects text. Works as an Entry Point too (Auto-Start)."""
    text = update.message.text
    
    # Initialize if this is the first message
    if "text_buffer" not in context.user_data:
        context.user_data["text_buffer"] = []
        # Ensure defaults exist
        context.user_data.setdefault("voice", DEFAULT_VOICE)
        context.user_data.setdefault("voice_name", "Burmese (Thiha)")
    
    context.user_data["text_buffer"].append(text)
    total_len = sum(len(t) for t in context.user_data["text_buffer"])
    
    await update.message.reply_text(
        f"📥 **Saved.** (Total: {total_len} chars)\n"
        "Send more parts or type /done."
    )
    return COLLECTING

async def done_collecting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if "text_buffer" not in context.user_data or not context.user_data["text_buffer"]:
        await update.message.reply_text("⚠️ You haven't sent any text yet.")
        return COLLECTING

    full_text = "\n".join(context.user_data["text_buffer"])
    context.user_data["final_text"] = full_text
    
    # Preview Info
    v_name = context.user_data.get("voice_name", "Default")
    rate = context.user_data.get("rate", 0)
    pitch = context.user_data.get("pitch", 0)

    keyboard = [[InlineKeyboardButton("✅ Generate Audio", callback_data="generate"),
                 InlineKeyboardButton("❌ Cancel / Clear", callback_data="cancel_gen")]]
    
    await update.message.reply_text(
        f"📝 **Text Ready:** {len(full_text)} chars\n"
        f"🗣 **Voice:** {v_name}\n"
        f"⚙️ **Settings:** Speed {rate}% | Pitch {pitch}Hz\n\n"
        "Generate now?", 
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    return CONFIRMING

# --- GENERATION ---
async def generate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_gen":
        context.user_data["text_buffer"] = []
        await query.edit_message_text("❌ Cancelled. Memory cleared. Send new text.")
        return COLLECTING

    await query.edit_message_text("⏳ Generating audio... Please wait.")
    
    try:
        text = context.user_data["final_text"]
        voice = context.user_data.get("voice", DEFAULT_VOICE)
        rate = context.user_data.get("rate", 0)
        pitch = context.user_data.get("pitch", 0)

        # Format for EdgeTTS
        rate_str = f"+{rate}%" if rate >= 0 else f"{rate}%"
        pitch_str = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"

        output_file = f"tts_{query.from_user.id}.mp3"
        
        # Generate
        communicate = edge_tts.Communicate(text, voice, rate=rate_str, pitch=pitch_str)
        await communicate.save(output_file)

        # Send
        await context.bot.send_audio(
            chat_id=update.effective_chat.id,
            audio=open(output_file, "rb"),
            caption=f"🗣 {context.user_data.get('voice_name')}\n⚡ {rate_str} | 🎵 {pitch_str}",
            title="TTS Audio"
        )
        
        # Cleanup
        os.remove(output_file)
        context.user_data["text_buffer"] = [] # Clear buffer only after success
        
    except Exception as e:
        logging.error(f"Generation Error: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text="⚠️ Error generating audio. Please try shorter text or a different voice."
        )

    return COLLECTING

# --- MENUS (VOICE & SETTINGS) ---
async def voice_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for Voice Menu."""
    keyboard = [[InlineKeyboardButton(r, callback_data=f"menu_{r}")] for r in VOICES.keys()]
    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="cancel_voice")])
    await update.message.reply_text("🗣 **Select Voice Category:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for Settings Menu."""
    # Ensure defaults exist before showing menu
    context.user_data.setdefault("rate", 0)
    context.user_data.setdefault("pitch", 0)
    await update.message.reply_text("⚙️ **Audio Settings:**", reply_markup=get_settings_markup(context.user_data))

async def menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles ALL button clicks for Voices and Settings."""
    query = update.callback_query
    await query.answer()
    data = query.data

    # --- VOICE LOGIC ---
    if data == "cancel_voice":
        await query.edit_message_text("✅ Voice selection closed.")
        return

    if data.startswith("menu_"):
        region = data.replace("menu_", "")
        keyboard = [[InlineKeyboardButton(n, callback_data=f"set_{c}|{n}")] for n, c in VOICES[region].items()]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_main")])
        await query.edit_message_text(f"📂 **{region}**", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "back_main":
        keyboard = [[InlineKeyboardButton(r, callback_data=f"menu_{r}")] for r in VOICES.keys()]
        keyboard.append([InlineKeyboardButton("❌ Close", callback_data="cancel_voice")])
        await query.edit_message_text("🗣 **Select Voice Category:**", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("set_"):
        code, name = data.replace("set_", "").split("|")
        context.user_data["voice"] = code
        context.user_data["voice_name"] = name
        await query.edit_message_text(f"✅ Voice set to: **{name}**")

    # --- SETTINGS LOGIC ---
    elif data == "close_settings":
        await query.delete_message()
        return

    elif data.startswith("rate_") or data.startswith("pitch_"):
        key, val = data.split("_")
        val = int(val)
        # Updates Rate or Pitch
        current = context.user_data.get(key, 0)
        # Limits: Rate +/- 100, Pitch +/- 50
        context.user_data[key] = max(-100, min(100, current + val)) if key == "rate" else max(-50, min(50, current + val))
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))

    elif data == "preset_crisp":
        context.user_data["rate"] = 10
        context.user_data["pitch"] = 5
        await query.answer("✨ Crisp Mode: ON")
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))

    elif data == "preset_reset":
        context.user_data["rate"] = 0
        context.user_data["pitch"] = 0
        await query.answer("🔄 Reset to Normal")
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("🚫 Reset. Send text to start.")
    return ConversationHandler.END

# --- APP SETUP ---
def main():
    if not TOKEN:
        print("❌ Error: TELEGRAM_TOKEN is missing!")
        return

    application = Application.builder().token(TOKEN).build()

    # The Logic Brain
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            # MAGIC FIX: Filters text so you don't HAVE to type /start
            MessageHandler(filters.TEXT & ~filters.COMMAND, collect_text)
        ],
        states={
            COLLECTING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_text),
                CommandHandler("done", done_collecting),
                CommandHandler("voice", voice_menu),
                CommandHandler("settings", settings_menu)
            ],
            CONFIRMING: [CallbackQueryHandler(generate_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Handlers
    application.add_handler(conv_handler)
    
    # Standalone commands (if accessed outside conversation)
    application.add_handler(CommandHandler("voice", voice_menu))
    application.add_handler(CommandHandler("settings", settings_menu))
    
    # Callback handler for Voice/Settings menus (Separate from Conversation)
    application.add_handler(CallbackQueryHandler(menu_callback_handler, pattern="^(menu_|set_|back_|rate_|pitch_|preset_|close_)"))

    print("🤖 Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    main()
