import os
import logging
import threading
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
import edge_tts
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.constants import ParseMode, ChatAction
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
    "🌟 Best Multilingual AI": {
        # All these voices handle ANY language (Burmese, English, etc.)
        "Ava (Female)": "en-US-AvaMultilingualNeural",
        "Andrew (Male)": "en-US-AndrewMultilingualNeural",
        "Emma (Female)": "en-US-EmmaMultilingualNeural",
        "Brian (Male)": "en-US-BrianMultilingualNeural",
        "Florian (German/Multi)": "de-DE-FlorianMultilingualNeural",
        "Remy (French/Multi)": "fr-FR-RemyMultilingualNeural",
        "Giuseppe (Italian/Multi)": "it-IT-GiuseppeMultilingualNeural",
        "Hyunsu (Korean/Multi)": "ko-KR-HyunsuMultilingualNeural",
        "William (Australian/Multi)": "en-AU-WilliamMultilingualNeural",
    },
    "🇲🇲 Myanmar": {
        "Thiha (Male)": "my-MM-ThihaNeural",
        "Nilar (Female)": "my-MM-NularNeural",
    },
    "🌏 Asia": {
        "Thai (Premwadee - F)": "th-TH-PremwadeeNeural",
        "Thai (Niwat - M)": "th-TH-NiwatNeural",
        "Indonesian (Gadis - F)": "id-ID-GadisNeural",
        "Indonesian (Ardi - M)": "id-ID-ArdiNeural",
        "Vietnamese (HoaiMy - F)": "vi-VN-HoaiMyNeural",
        "Vietnamese (NamMinh - M)": "vi-VN-NamMinhNeural",
        "Japanese (Nanami - F)": "ja-JP-NanamiNeural",
        "Japanese (Keita - M)": "ja-JP-KeitaNeural",
        "Korean (SunHi - F)": "ko-KR-SunHiNeural",
        "Korean (InJoon - M)": "ko-KR-InJoonNeural",
        "Chinese (Xiaoxiao - F)": "zh-CN-XiaoxiaoNeural",
        "Chinese (Yunxi - M)": "zh-CN-YunxiNeural",
        "Hindi (Swara - F)": "hi-IN-SwaraNeural",
        "Hindi (Madhur - M)": "hi-IN-MadhurNeural",
    },
    "🇪🇺 Europe": {
        "British (Sonia - F)": "en-GB-SoniaNeural",
        "British (Ryan - M)": "en-GB-RyanNeural",
        "French (Denise - F)": "fr-FR-DeniseNeural",
        "French (Henri - M)": "fr-FR-HenriNeural",
        "German (Katja - F)": "de-DE-KatjaNeural",
        "German (Conrad - M)": "de-DE-ConradNeural",
        "Spanish (Paloma - F)": "es-US-PalomaNeural",
        "Spanish (Alonso - M)": "es-US-AlonsoNeural",
        "Russian (Svetlana - F)": "ru-RU-SvetlanaNeural",
        "Russian (Dmitry - M)": "ru-RU-DmitryNeural",
    }
}

# --- LOGGING ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- STATES ---
COLLECTING = 1

# --- DUMMY SERVER (FIXED FOR UPTIME) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Active")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    # Listen on 0.0.0.0 is crucial for Render
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    print(f"🌍 Web server listening on port {port}")
    server.serve_forever()

# --- HELPER: MAKE AUDIO HUMAN ---
def preprocess_text_for_pauses(text):
    """Adds slight pauses to make speech less robotic."""
    # Replace standard punctuation with a version that encourages pauses
    text = text.replace("။", "။\n") # Burmese full stop -> New line (Pause)
    text = text.replace("、", "、 ") # Japanese comma
    text = text.replace(".", ".\n") # English period -> New line
    return text

# --- HELPER: KEYBOARDS ---
def get_control_keyboard(total_chars):
    """Shows the Generate button immediately."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Generate Audio ({total_chars} chars)", callback_data="generate")],
        [InlineKeyboardButton("🗑 Clear All", callback_data="clear_buffer")],
        [InlineKeyboardButton("🗣 Change Voice", callback_data="open_voice_menu"),
         InlineKeyboardButton("⚙️ Settings", callback_data="open_settings")]
    ])

def get_settings_markup(data):
    speed = data.get("rate", 0)
    pitch = data.get("pitch", 0)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🐢 Slower", callback_data="rate_-10"),
         InlineKeyboardButton(f"🚀 Faster ({speed}%)", callback_data="rate_+10")],
        [InlineKeyboardButton(f"🔉 Lower", callback_data="pitch_-5"),
         InlineKeyboardButton(f"🔊 Higher ({pitch}Hz)", callback_data="pitch_+5")],
        [InlineKeyboardButton("✨ Crisp & Clear", callback_data="preset_crisp")],
        [InlineKeyboardButton("🔄 Reset", callback_data="preset_reset")],
        [InlineKeyboardButton("✅ Back to Chat", callback_data="close_settings")]
    ])

# --- BOT COMMANDS SETUP ---
async def post_init(application: Application):
    """Sets the menu button commands automatically on startup."""
    commands = [
        ("start", "Restart the bot"),
        ("voice", "Change Speaker"),
        ("settings", "Adjust Speed/Pitch"),
        ("cancel", "Clear text memory")
    ]
    await application.bot.set_my_commands(commands)

# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["text_buffer"] = []
    # Defaults
    context.user_data.setdefault("voice", DEFAULT_VOICE)
    context.user_data.setdefault("voice_name", "Burmese (Thiha)")
    context.user_data.setdefault("rate", 0)
    context.user_data.setdefault("pitch", 0)

    await update.message.reply_text(
        "👋 **Burmese TTS Ready!**\n\n"
        "Send me any text. I will add it to the list.\n"
        "Click **Generate** when you are ready.",
        parse_mode=ParseMode.MARKDOWN
    )
    return COLLECTING

async def collect_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if "text_buffer" not in context.user_data:
        context.user_data["text_buffer"] = []
        context.user_data.setdefault("voice", DEFAULT_VOICE)
    
    context.user_data["text_buffer"].append(text)
    total_len = sum(len(t) for t in context.user_data["text_buffer"])
    
    # Reply with the control panel immediately
    await update.message.reply_text(
        f"📥 **Added.** (Total: {total_len} chars)\n"
        "Send more text or click below:",
        reply_markup=get_control_keyboard(total_len),
        parse_mode=ParseMode.MARKDOWN
    )
    return COLLECTING

async def generate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "clear_buffer":
        context.user_data["text_buffer"] = []
        await query.edit_message_text("🗑 **Memory Cleared.** Send new text.")
        return COLLECTING

    if query.data == "open_voice_menu":
        await voice_menu(update, context)
        return COLLECTING
        
    if query.data == "open_settings":
        await settings_menu(update, context)
        return COLLECTING

    if query.data == "generate":
        # Check if empty
        if not context.user_data.get("text_buffer"):
            await query.edit_message_text("⚠️ No text to generate. Send text first.")
            return COLLECTING

        await query.edit_message_text("⏳ **Generating...** (Please wait)")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VOICE)

        try:
            # Join text and add "Human" pauses
            raw_text = "\n".join(context.user_data["text_buffer"])
            final_text = preprocess_text_for_pauses(raw_text)
            
            voice = context.user_data.get("voice", DEFAULT_VOICE)
            rate = context.user_data.get("rate", 0)
            pitch = context.user_data.get("pitch", 0)
            rate_str = f"+{rate}%" if rate >= 0 else f"{rate}%"
            pitch_str = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"

            output_file = f"tts_{query.from_user.id}.mp3"
            
            communicate = edge_tts.Communicate(final_text, voice, rate=rate_str, pitch=pitch_str)
            await communicate.save(output_file)

            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=open(output_file, "rb"),
                caption=f"🗣 {context.user_data.get('voice_name')}",
                title="TTS Audio"
            )
            
            os.remove(output_file)
            context.user_data["text_buffer"] = [] # Clear after success
            
            # Offer to start again
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="✅ Done! Send new text to start again."
            )
            
        except Exception as e:
            logging.error(f"Error: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Error generating audio.")

        return COLLECTING

# --- VOICE & SETTINGS MENUS ---

async def voice_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Determine if called from command or button
    msg_func = update.message.reply_text if update.message else update.callback_query.edit_message_text
    
    keyboard = [[InlineKeyboardButton(r, callback_data=f"menu_{r}")] for r in VOICES.keys()]
    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="close_settings")]) # Recycle close handler
    
    await msg_func("🗣 **Select Voice Category:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_func = update.message.reply_text if update.message else update.callback_query.edit_message_text
    context.user_data.setdefault("rate", 0)
    context.user_data.setdefault("pitch", 0)
    await msg_func("⚙️ **Audio Settings:**", reply_markup=get_settings_markup(context.user_data), parse_mode=ParseMode.MARKDOWN)

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # --- VOICE NAVIGATION ---
    if data.startswith("menu_"):
        region = data.replace("menu_", "")
        keyboard = [[InlineKeyboardButton(n, callback_data=f"set_{c}|{n}")] for n, c in VOICES[region].items()]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_voice_main")])
        await query.edit_message_text(f"📂 **{region}**", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "back_voice_main":
        keyboard = [[InlineKeyboardButton(r, callback_data=f"menu_{r}")] for r in VOICES.keys()]
        keyboard.append([InlineKeyboardButton("❌ Close", callback_data="close_settings")])
        await query.edit_message_text("🗣 **Select Voice Category:**", reply_markup=InlineKeyboardMarkup(keyboard))

    # --- VOICE SELECTION + SAMPLE ---
    elif data.startswith("set_"):
        code, name = data.replace("set_", "").split("|")
        context.user_data["voice"] = code
        context.user_data["voice_name"] = name
        
        # Generate Sample
        await query.edit_message_text(f"⏳ Loading sample for **{name}**...", parse_mode=ParseMode.MARKDOWN)
        sample_file = f"sample_{query.from_user.id}.mp3"
        try:
            sample_text = "Mingalabar. This is my voice."
            await edge_tts.Communicate(sample_text, code).save(sample_file)
            await context.bot.send_voice(chat_id=update.effective_chat.id, voice=open(sample_file, "rb"))
            os.remove(sample_file)
        except:
            pass # Ignore sample errors
            
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Voice set to: **{name}**\nSend me text now!",
            reply_markup=get_control_keyboard(0) # Show control panel
        )

    # --- SETTINGS ---
    elif data == "close_settings":
        # If we are inside conversation, show the main control panel again
        total = sum(len(t) for t in context.user_data.get("text_buffer", []))
        if total > 0:
            await query.edit_message_text(f"📥 **Ready.** (Total: {total} chars)", reply_markup=get_control_keyboard(total))
        else:
            await query.delete_message()

    elif "rate_" in data or "pitch_" in data:
        key, val = data.split("_")
        val = int(val)
        context.user_data[key] = max(-100, min(100, context.user_data.get(key, 0) + val))
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))

    elif data == "preset_crisp":
        context.user_data.update({"rate": 10, "pitch": 5})
        await query.answer("✨ Crisp Mode ON")
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))

    elif data == "preset_reset":
        context.user_data.update({"rate": 0, "pitch": 0})
        await query.answer("🔄 Reset")
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("🚫 Reset done.")
    return ConversationHandler.END

# --- MAIN ---
def main():
    if not TOKEN:
        print("❌ TELEGRAM_TOKEN missing")
        return

    # Post_init sets the commands menu automatically
    application = Application.builder().token(TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, collect_text)
        ],
        states={
            COLLECTING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_text),
                CallbackQueryHandler(generate_handler, pattern="^(generate|clear_buffer|open_)"),
                CallbackQueryHandler(menu_callback, pattern="^(menu_|set_|back_|rate_|pitch_|preset_|close_)"),
                CommandHandler("voice", voice_menu),
                CommandHandler("settings", settings_menu)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    
    # Standalone command handlers
    application.add_handler(CommandHandler("voice", voice_menu))
    application.add_handler(CommandHandler("settings", settings_menu))

    print("🤖 Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    main()