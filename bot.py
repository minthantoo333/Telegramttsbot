import os
import logging
import re
import threading
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
import edge_tts
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
        "Nular (Female)": "my-MM-NularNeural",
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

# --- DUMMY SERVER ---
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

def preprocess_text_smart(text):
    """
    1. Protects Abbreviations (Dr., No.) & Decimals (3.5).
    2. Converts Real Sentences & Paragraphs to commas for fast flow.
    """
    if not text: return ""
    
    # 1. Normalize Newlines
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    # 2. Protect Abbreviations & Decimals
    protected = {
        "Dr.": "Dr_DOT", "Mr.": "Mr_DOT", "Mrs.": "Mrs_DOT", "Ms.": "Ms_DOT",
        "No.": "No_DOT", "St.": "St_DOT", "vs.": "vs_DOT", "etc.": "etc_DOT"
    }
    for k, v in protected.items():
        text = text.replace(k, v)
        text = text.replace(k.lower(), v)

    # 3. Mark Paragraphs (Enter key) -> Convert directly to comma
    text = text.replace("\n", ", ")

    # 4. Mark Myanmar Punctuation -> Convert directly to comma
    text = text.replace("။", ", ")
    text = text.replace("。", ", ")
    
    # 5. Mark English Punctuation -> Convert directly to comma
    text = text.replace("!", ", ")
    text = text.replace("?", ", ")
    
    # 6. Smart Period Replacement (Ignore 3.5 or v2.0)
    # Regex: Find dot NOT preceded by digit AND NOT followed by digit
    text = re.sub(r'(?<!\d)\.(?!\d)', ', ', text)
    
    # 7. Restore Protected Words
    for k, v in protected.items():
        original_word = k 
        text = text.replace(v, original_word)
        
    # 8. Clean up double commas
    text = text.replace(", ,", ",")
    text = text.replace(",  ,", ",")
    
    return text

async def generate_audio(text, voice, rate_str, pitch_str, final_filename):
    """Generates audio in ONE PASS (No splitting)."""
    
    # 1. Process text to enforce fast flow (200ms)
    final_text = preprocess_text_smart(text)
    
    try:
        # 2. Generate directly
        communicate = edge_tts.Communicate(final_text, voice, rate=rate_str, pitch=pitch_str)
        await communicate.save(final_filename)
        return True
    except Exception as e:
        logging.error(f"Generation Error: {e}")
        return False

# --- KEYBOARDS & MENUS ---
def get_control_keyboard(total_chars):
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
        [InlineKeyboardButton("✅ Close Settings", callback_data="close_settings")]
    ])

async def show_voice_menu(update, context, is_new_message=False):
    keyboard = [[InlineKeyboardButton(r, callback_data=f"menu_{r}")] for r in VOICES.keys()]
    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="close_settings")])
    markup = InlineKeyboardMarkup(keyboard)
    text = "🗣 **Select Voice Category:**"
    if is_new_message: await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    else: await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)

async def show_settings_menu(update, context, is_new_message=False):
    context.user_data.setdefault("rate", 0)
    context.user_data.setdefault("pitch", 0)
    markup = get_settings_markup(context.user_data)
    text = "⚙️ **Audio Settings:**"
    if is_new_message: await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    else: await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["text_buffer"] = []
    context.user_data.setdefault("voice", DEFAULT_VOICE)
    context.user_data.setdefault("voice_name", "Burmese (Thiha)")
    await update.message.reply_text("👋 **Bot Restarted!**\n\nSend me text or a .txt file to begin.", parse_mode=ParseMode.MARKDOWN)

async def command_voice(update, context): await show_voice_menu(update, context, True)
async def command_settings(update, context): await show_settings_menu(update, context, True)

async def collect_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "text_buffer" not in context.user_data:
        context.user_data["text_buffer"] = []
        context.user_data.setdefault("voice", DEFAULT_VOICE)
        context.user_data.setdefault("voice_name", "Burmese (Thiha)")

    context.user_data["text_buffer"].append(text)
    total_len = sum(len(t) for t in context.user_data["text_buffer"])
    
    await update.message.reply_text(f"📥 **Saved.** (Total: {total_len} chars)", reply_markup=get_control_keyboard(total_len), parse_mode=ParseMode.MARKDOWN)

async def handle_txt_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    if update.message.document.file_size > 5 * 1024 * 1024:
        await update.message.reply_text("⚠️ File too large.")
        return
    file_bytes = await file.download_as_bytearray()
    try: text_content = file_bytes.decode('utf-8')
    except: text_content = file_bytes.decode('cp1252', errors='ignore')

    if not text_content.strip(): return
    if "text_buffer" not in context.user_data:
        context.user_data["text_buffer"] = []
        context.user_data.setdefault("voice", DEFAULT_VOICE)
        context.user_data.setdefault("voice_name", "Burmese (Thiha)")

    context.user_data["text_buffer"].append(text_content)
    await update.message.reply_text(f"📄 **File Read.**\nTotal: {sum(len(t) for t in context.user_data['text_buffer'])} chars", reply_markup=get_control_keyboard(len(text_content)), parse_mode=ParseMode.MARKDOWN)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "open_voice_menu": await show_voice_menu(update, context, False); return
    if data == "open_settings": await show_settings_menu(update, context, False); return
    if data == "clear_buffer":
        context.user_data["text_buffer"] = []
        await query.edit_message_text("🗑 **Memory Cleared.**")
        return

    if data == "generate":
        if not context.user_data.get("text_buffer"): await query.edit_message_text("⚠️ No text."); return
        await query.edit_message_text("⏳ **Generating...** (One Pass)")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VOICE)

        try:
            # JOIN ALL TEXT
            raw_text = "\n".join(context.user_data["text_buffer"])
            voice = context.user_data.get("voice", DEFAULT_VOICE)
            output_file = f"tts_{query.from_user.id}.mp3"
            
            rate, pitch = context.user_data.get("rate", 0), context.user_data.get("pitch", 0)
            rate_str, pitch_str = f"+{rate}%" if rate >=0 else f"{rate}%", f"+{pitch}Hz" if pitch >=0 else f"{pitch}Hz"

            # ONE PASS GENERATION
            success = await generate_audio(raw_text, voice, rate_str, pitch_str, output_file)
            if not success: raise Exception("Gen failed")
            
            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=open(output_file, "rb"),
                caption=f"🗣 {context.user_data.get('voice_name')}\n⚡ {rate_str} | 🎵 {pitch_str} | ⏩ Fast Flow",
                title="TTS Audio"
            )
            os.remove(output_file)
            context.user_data["text_buffer"] = []
            await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Done!")
        except Exception as e:
            logging.error(f"TTS Error: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Error.")
        return

    if data.startswith("menu_"):
        region = data.replace("menu_", "")
        keyboard = [[InlineKeyboardButton(n, callback_data=f"set_{c}|{n}")] for n, c in VOICES[region].items()]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="open_voice_menu")])
        await query.edit_message_text(f"📂 **{region}**", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("set_"):
        code, name = data.replace("set_", "").split("|")
        context.user_data["voice"], context.user_data["voice_name"] = code, name
        await query.edit_message_text(f"✅ Set to: **{name}**", reply_markup=get_control_keyboard(sum(len(t) for t in context.user_data.get("text_buffer", []))), parse_mode=ParseMode.MARKDOWN)
        return

    if "rate_" in data or "pitch_" in data:
        key, val = data.split("_")
        context.user_data[key] = max(-100, min(100, context.user_data.get(key, 0) + int(val)))
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))
        return

    if data == "preset_crisp":
        context.user_data.update({"rate": 10, "pitch": 5})
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))
        return
    if data == "preset_reset":
        context.user_data.update({"rate": 0, "pitch": 0})
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))
        return
    if data == "close_settings":
        await query.delete_message()
        return

async def post_init(application: Application):
    await application.bot.set_my_commands([("start", "Reset"), ("voice", "Voices"), ("settings", "Settings")])

def main():
    if not TOKEN: print("❌ TELEGRAM_TOKEN missing"); return
    application = Application.builder().token(TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("voice", command_voice))
    application.add_handler(CommandHandler("settings", command_settings))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_text))
    application.add_handler(MessageHandler(filters.Document.FileExtension("txt"), handle_txt_file))
    application.add_handler(CallbackQueryHandler(button_handler))
    print("🤖 Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    main()
