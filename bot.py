import os
import logging
import threading
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
)

# --- CONFIGURATION ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
DEFAULT_VOICE = "my-MM-ThihaNeural"

# --- FULL VOICE DATABASE ---
VOICES = {
    "🌟 Best Multilingual AI": {
        "Ava (Female)": "en-US-AvaMultilingualNeural",
        "Andrew (Male)": "en-US-AndrewMultilingualNeural",
        "Emma (Female)": "en-US-EmmaMultilingualNeural",
        "Brian (Male)": "en-US-BrianMultilingualNeural",
    },
    "🇲🇲 Myanmar": {
        "Thiha (Male)": "my-MM-ThihaNeural",
        "Nilar (Female)": "my-MM-NilarNeural",
    },
    "🌏 Asia": {
        "Thai (Premwadee - F)": "th-TH-PremwadeeNeural",
        "Thai (Niwat - M)": "th-TH-NiwatNeural",
        "Indonesian (Gadis - F)": "id-ID-GadisNeural",
        "Vietnamese (HoaiMy - F)": "vi-VN-HoaiMyNeural",
        "Japanese (Nanami - F)": "ja-JP-NanamiNeural",
        "Korean (SunHi - F)": "ko-KR-SunHiNeural",
        "Chinese (Xiaoxiao - F)": "zh-CN-XiaoxiaoNeural",
        "Hindi (Swara - F)": "hi-IN-SwaraNeural",
    },
    "🇪🇺 Europe": {
        "British (Sonia - F)": "en-GB-SoniaNeural",
        "British (Ryan - M)": "en-GB-RyanNeural",
        "French (Denise - F)": "fr-FR-DeniseNeural",
        "German (Katja - F)": "de-DE-KatjaNeural",
        "Spanish (Paloma - F)": "es-US-PalomaNeural",
        "Russian (Svetlana - F)": "ru-RU-SvetlanaNeural",
    }
}

# --- LOGGING ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- DUMMY SERVER (Render Keep-Alive) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Active")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    print(f"🌍 Web server listening on port {port}")
    server.serve_forever()

# --- HELPER FUNCTIONS ---
def preprocess_text(text, mode="fast"):
    if not text: return ""

    # Mode 1: ORIGINAL PAUSED (Forces new lines)
    if mode == "original":
        text = text.replace("။", "။\n") 
        text = text.replace("、", "、\n") 
        text = text.replace(".", ".\n")
        return text

    # Mode 2: FAST FLUENT (Removes new lines for smooth flow)
    else:
        text = text.replace("။", "။ ") 
        text = text.replace("、", "、 ") 
        text = text.replace(".", ". ") 
        # Remove extra spaces/newlines to make it one block
        return " ".join(text.split())

def get_control_keyboard(total_chars):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Generate Audio ({total_chars} chars)", callback_data="generate")],
        [InlineKeyboardButton("🗑 Clear All", callback_data="clear_buffer")],
        [InlineKeyboardButton("🗣 Change Voice", callback_data="open_voice_menu"),
         InlineKeyboardButton("⚙️ Settings", callback_data="open_settings")]
    ])

def get_settings_markup(data):
    speed = data.get("rate", 10)
    pitch = data.get("pitch", 0)
    mode = data.get("mode", "fast")
    
    # Toggle Button Text
    mode_text = "🐢 Mode: Original (Paused)" if mode == "original" else "🐇 Mode: Fast (Fluent)"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(mode_text, callback_data="toggle_mode")],
        [InlineKeyboardButton(f"🐢 Slower", callback_data="rate_-10"),
         InlineKeyboardButton(f"🚀 Faster ({speed}%)", callback_data="rate_+10")],
        [InlineKeyboardButton(f"🔉 Lower", callback_data="pitch_-5"),
         InlineKeyboardButton(f"🔊 Higher ({pitch}Hz)", callback_data="pitch_+5")],
        [InlineKeyboardButton("✅ Close Settings", callback_data="close_settings")]
    ])

# --- SHARED MENU FUNCTIONS ---
async def show_voice_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, is_new_message=False):
    keyboard = [[InlineKeyboardButton(r, callback_data=f"menu_{r}")] for r in VOICES.keys()]
    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="close_settings")])
    markup = InlineKeyboardMarkup(keyboard)
    text = "🗣 **Select Voice Category:**"

    if is_new_message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)

async def show_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, is_new_message=False):
    # Initialize defaults
    context.user_data.setdefault("rate", 10)
    context.user_data.setdefault("pitch", 0)
    context.user_data.setdefault("mode", "fast")
    
    markup = get_settings_markup(context.user_data)
    text = "⚙️ **Audio Settings:**"

    if is_new_message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)

# --- COMMAND HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["text_buffer"] = []
    context.user_data["voice"] = DEFAULT_VOICE
    context.user_data["voice_name"] = "Burmese (Thiha)"
    context.user_data["rate"] = 10 
    context.user_data["pitch"] = 0
    context.user_data["mode"] = "fast" # Default to the better one

    await update.message.reply_text(
        "👋 **Bot Restarted!**\n\n"
        "Send me text OR upload a `.txt` file.\n"
        "Current Mode: **🐇 Fast (Fluent)**",
        parse_mode=ParseMode.MARKDOWN
    )

async def command_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_voice_menu(update, context, is_new_message=True)

async def command_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_settings_menu(update, context, is_new_message=True)

async def collect_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "text_buffer" not in context.user_data:
        context.user_data["text_buffer"] = []
        context.user_data.setdefault("voice", DEFAULT_VOICE)
        context.user_data.setdefault("voice_name", "Burmese (Thiha)")
        context.user_data.setdefault("mode", "fast")
        context.user_data.setdefault("rate", 10)
        context.user_data.setdefault("pitch", 0)

    context.user_data["text_buffer"].append(text)
    total_len = sum(len(t) for t in context.user_data["text_buffer"])
    
    await update.message.reply_text(
        f"📥 **Saved Text.** (Total: {total_len} chars)",
        reply_markup=get_control_keyboard(total_len),
        parse_mode=ParseMode.MARKDOWN
    )

# --- FILE HANDLER ---
async def collect_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    
    if "text_buffer" not in context.user_data:
        context.user_data["text_buffer"] = []
        context.user_data.setdefault("voice", DEFAULT_VOICE)
        context.user_data.setdefault("voice_name", "Burmese (Thiha)")
        context.user_data.setdefault("mode", "fast")
        context.user_data.setdefault("rate", 10)
        context.user_data.setdefault("pitch", 0)

    try:
        file_info = await document.get_file()
        byte_data = await file_info.download_as_bytearray()
        text_content = byte_data.decode('utf-8')
        
        context.user_data["text_buffer"].append(text_content)
        total_len = sum(len(t) for t in context.user_data["text_buffer"])
        
        await update.message.reply_text(
            f"📄 **File Loaded.** (Total: {total_len} chars)",
            reply_markup=get_control_keyboard(total_len),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text("❌ Failed to process file. Ensure it is UTF-8 .txt")

# --- BUTTON HANDLER ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # --- 1. MODE TOGGLE ---
    if data == "toggle_mode":
        current_mode = context.user_data.get("mode", "fast")
        if current_mode == "fast":
            context.user_data["mode"] = "original"
            context.user_data["rate"] = 0  # Reset speed to normal for Original
        else:
            context.user_data["mode"] = "fast"
            context.user_data["rate"] = 10 # Speed up for Fast mode
        
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))
        return

    # --- 2. MENUS ---
    if data == "open_voice_menu":
        await show_voice_menu(update, context, is_new_message=False)
        return

    if data == "open_settings":
        await show_settings_menu(update, context, is_new_message=False)
        return

    # --- 3. GENERATE ---
    if data == "generate":
        if not context.user_data.get("text_buffer"):
            await query.edit_message_text("⚠️ No text found. Send text first.")
            return

        await query.edit_message_text("⏳ **Generating...**")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VOICE)

        try:
            raw_text = "\n".join(context.user_data["text_buffer"])
            mode = context.user_data.get("mode", "fast")
            
            # Apply processing based on Mode
            final_text = preprocess_text(raw_text, mode)
            
            voice = context.user_data.get("voice", DEFAULT_VOICE)
            rate = context.user_data.get("rate", 10)
            pitch = context.user_data.get("pitch", 0)
            
            rate_str = f"+{rate}%" if rate >= 0 else f"{rate}%"
            pitch_str = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"

            output_file = f"tts_{query.from_user.id}.mp3"
            communicate = edge_tts.Communicate(final_text, voice, rate=rate_str, pitch=pitch_str)
            await communicate.save(output_file)

            mode_icon = "🐇" if mode == "fast" else "🐢"
            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=open(output_file, "rb"),
                caption=f"🗣 {context.user_data.get('voice_name', 'Unknown')}\n{mode_icon} Mode | ⚡ {rate_str} | 🎵 {pitch_str}",
                title="TTS Audio"
            )
            os.remove(output_file)
            context.user_data["text_buffer"] = [] 
            await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Done! Send new text.")

        except Exception as e:
            logging.error(f"TTS Error: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Error generating audio.")
        return

    # --- 4. NAVIGATION & SETTINGS ---
    if data == "clear_buffer":
        context.user_data["text_buffer"] = []
        await query.edit_message_text("🗑 **Memory Cleared.** Send new text.")
        return

    if data.startswith("menu_"):
        region = data.replace("menu_", "")
        keyboard = [[InlineKeyboardButton(n, callback_data=f"set_{c}|{n}")] for n, c in VOICES[region].items()]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="open_voice_menu")])
        await query.edit_message_text(f"📂 **{region}**", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("set_"):
        code, name = data.replace("set_", "").split("|")
        context.user_data["voice"] = code
        context.user_data["voice_name"] = name
        
        # Sample
        await query.edit_message_text(f"⏳ Loading sample for **{name}**...", parse_mode=ParseMode.MARKDOWN)
        sample_file = f"sample_{query.from_user.id}.mp3"
        try:
            await edge_tts.Communicate("Hello, voice test.", code).save(sample_file)
            await context.bot.send_voice(chat_id=update.effective_chat.id, voice=open(sample_file, "rb"))
            os.remove(sample_file)
        except: pass

        total = sum(len(t) for t in context.user_data.get("text_buffer", []))
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Voice set to: **{name}**",
            reply_markup=get_control_keyboard(total)
        )
        return

    if data == "close_settings":
        total = sum(len(t) for t in context.user_data.get("text_buffer", []))
        if total > 0:
            await query.edit_message_text(f"📥 **Ready.** (Total: {total} chars)", reply_markup=get_control_keyboard(total), parse_mode=ParseMode.MARKDOWN)
        else:
            await query.delete_message()
            await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Settings closed.")
        return

    if "rate_" in data or "pitch_" in data:
        key, val = data.split("_")
        val = int(val)
        current = context.user_data.get(key, 10 if key == "rate" else 0)
        context.user_data[key] = max(-100, min(100, current + val))
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))
        return

# --- INIT ---
async def post_init(application: Application):
    commands = [
        ("start", "Restart Bot"),
        ("voice", "Change Speaker"),
        ("settings", "Speed, Pitch & Mode"),
    ]
    await application.bot.set_my_commands(commands)

def main():
    if not TOKEN:
        print("❌ TELEGRAM_TOKEN missing")
        return

    application = Application.builder().token(TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("voice", command_voice))
    application.add_handler(CommandHandler("settings", command_settings))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_text))
    application.add_handler(MessageHandler(filters.Document.FileExtension("txt"), collect_file))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    main()
