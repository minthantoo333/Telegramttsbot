import os
import logging
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
CHUNK_SIZE = 2500  

# --- FULL VOICE DATABASE ---
VOICES = {
    "🌟 Best Multilingual AI": {
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

def escape_xml(text):
    """Escapes characters that break SSML/XML."""
    if not text: return ""
    # Only escape necessary XML characters.
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")

def apply_ssml_pauses(text, pause_ms):
    """
    Replaces punctuation with explicit SSML breaks.
    """
    if not text: return ""
    
    # 1. Clean the text for XML FIRST (Prevents existing < > from breaking code)
    safe_text = escape_xml(text)
    
    if pause_ms == 0:
        return safe_text

    # 2. Create the break tag
    break_tag = f'<break time="{pause_ms}ms"/>'
    
    # 3. Inject breaks at punctuation
    safe_text = safe_text.replace("။", f"။{break_tag}")
    safe_text = safe_text.replace("၊", f"၊{break_tag}")
    safe_text = safe_text.replace(".", f".{break_tag}")
    safe_text = safe_text.replace("!", f"!{break_tag}")
    safe_text = safe_text.replace("?", f"?{break_tag}")
    safe_text = safe_text.replace("\n", f"\n{break_tag}")
    
    return safe_text

def split_text_smart(text, chunk_size):
    if len(text) <= chunk_size: return [text]
    chunks = []
    while text:
        if len(text) <= chunk_size:
            chunks.append(text)
            break
        split_at = -1
        newline_pos = text.rfind('\n', 0, chunk_size)
        if newline_pos != -1: split_at = newline_pos + 1
        else:
            period_pos = text.rfind('.', 0, chunk_size)
            if period_pos != -1: split_at = period_pos + 1
            else: split_at = chunk_size
        chunks.append(text[:split_at])
        text = text[split_at:]
    return chunks

async def generate_long_audio_ssml(text, voice, rate_str, pitch_str, pause_ms, final_filename):
    """
    Generates audio using strict single-line SSML to prevent 'reading code' errors.
    """
    chunks = split_text_smart(text, CHUNK_SIZE)
    merged_audio = b""
    
    for i, chunk in enumerate(chunks):
        if not chunk.strip(): continue
        
        # 1. Prepare content with breaks
        ssml_content = apply_ssml_pauses(chunk, pause_ms)
        
        # 2. Construct Clean SSML (SINGLE LINE IS CRITICAL)
        # We include the voice tag inside to be safe, but ensure NO NEWLINES.
        final_ssml = (
            f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>"
            f"<voice name='{voice}'>"
            f"<prosody rate='{rate_str}' pitch='{pitch_str}'>"
            f"{ssml_content}"
            f"</prosody>"
            f"</voice>"
            f"</speak>"
        )

        # 3. Strip whitespace - if it doesn't start with <speak>, TTS reads the code.
        final_ssml = final_ssml.strip()

        temp_file = f"temp_chunk_{i}_{final_filename}"
        try:
            communicate = edge_tts.Communicate(final_ssml, voice)
            await communicate.save(temp_file)
            
            with open(temp_file, "rb") as f:
                merged_audio += f.read()
            os.remove(temp_file)
        except Exception as e:
            logging.error(f"Chunk error: {e}")
            if os.path.exists(temp_file): os.remove(temp_file)
            return False

    with open(final_filename, "wb") as f:
        f.write(merged_audio)
    return True

# --- KEYBOARDS ---
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
    pause = data.get("pause", 500) # Default 500ms
    
    pause_text = "Off" if pause == 0 else f"{pause}ms"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🐢 Slower", callback_data="rate_-10"),
         InlineKeyboardButton(f"🚀 Faster ({speed}%)", callback_data="rate_+10")],
        
        [InlineKeyboardButton(f"🔉 Lower", callback_data="pitch_-5"),
         InlineKeyboardButton(f"🔊 Higher ({pitch}Hz)", callback_data="pitch_+5")],
        
        # PAUSE ROW
        [InlineKeyboardButton(f"⏱ Pause: {pause_text}", callback_data="cycle_pause")],

        [InlineKeyboardButton("✨ Crisp & Clear", callback_data="preset_crisp")],
        [InlineKeyboardButton("🔄 Reset", callback_data="preset_reset")],
        [InlineKeyboardButton("✅ Close Settings", callback_data="close_settings")]
    ])

# --- MENUS ---
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
    context.user_data.setdefault("pause", 500)
    markup = get_settings_markup(context.user_data)
    text = "⚙️ **Audio Settings:**\n\n_Note: 'Pause' adds silence after every sentence._"
    if is_new_message: await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    else: await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["text_buffer"] = []
    context.user_data["voice"] = DEFAULT_VOICE
    context.user_data["voice_name"] = "Burmese (Thiha)"
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
    
    await update.message.reply_text(
        f"📥 **Saved.** (Total: {total_len} chars)",
        reply_markup=get_control_keyboard(total_len),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_txt_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    if update.message.document.file_size > 5 * 1024 * 1024:
        await update.message.reply_text("⚠️ File too large (Max 5MB).")
        return

    file_bytes = await file.download_as_bytearray()
    try: text_content = file_bytes.decode('utf-8')
    except: 
        try: text_content = file_bytes.decode('cp1252')
        except: await update.message.reply_text("⚠️ Decode failed. Use UTF-8."); return

    if not text_content.strip(): return

    if "text_buffer" not in context.user_data:
        context.user_data["text_buffer"] = []
        context.user_data.setdefault("voice", DEFAULT_VOICE)
        context.user_data.setdefault("voice_name", "Burmese (Thiha)")

    context.user_data["text_buffer"].append(text_content)
    total_len = sum(len(t) for t in context.user_data["text_buffer"])

    await update.message.reply_text(
        f"📄 **File Added.**\n📥 **Total:** {total_len} chars",
        reply_markup=get_control_keyboard(total_len),
        parse_mode=ParseMode.MARKDOWN
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "open_voice_menu": await show_voice_menu(update, context, False); return
    if data == "open_settings": await show_settings_menu(update, context, False); return

    if data == "clear_buffer":
        context.user_data["text_buffer"] = []
        await query.edit_message_text("🗑 **Memory Cleared.** Send new text.")
        return

    # --- SETTINGS LOGIC ---
    if "rate_" in data or "pitch_" in data:
        key, val = data.split("_")
        context.user_data[key] = max(-100, min(100, context.user_data.get(key, 0) + int(val)))
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))
        return

    if data == "cycle_pause":
        current = context.user_data.get("pause", 500)
        # Cycle: 500 -> 1000 -> 0 -> 100 -> 200 -> 300 -> 400 -> 500
        if current == 500: new_pause = 1000
        elif current == 1000: new_pause = 0
        elif current == 0: new_pause = 100
        elif current == 100: new_pause = 200
        elif current == 200: new_pause = 300
        elif current == 300: new_pause = 400
        else: new_pause = 500
        context.user_data["pause"] = new_pause
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))
        return

    if data == "preset_crisp":
        context.user_data.update({"rate": 10, "pitch": 5, "pause": 500})
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))
        return

    if data == "preset_reset":
        context.user_data.update({"rate": 0, "pitch": 0, "pause": 500})
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))
        return

    if data == "close_settings":
        total = sum(len(t) for t in context.user_data.get("text_buffer", []))
        if total > 0: await query.edit_message_text(f"📥 **Ready.** (Total: {total} chars)", reply_markup=get_control_keyboard(total), parse_mode=ParseMode.MARKDOWN)
        else: await query.delete_message(); await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Settings closed.")
        return

    # --- GENERATE LOGIC ---
    if data == "generate":
        if not context.user_data.get("text_buffer"):
            await query.edit_message_text("⚠️ No text found.")
            return

        await query.edit_message_text("⏳ **Generating...**")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VOICE)

        try:
            raw_text = "\n".join(context.user_data["text_buffer"])
            voice = context.user_data.get("voice", DEFAULT_VOICE)
            output_file = f"tts_{query.from_user.id}.mp3"
            
            rate = context.user_data.get("rate", 0)
            pitch = context.user_data.get("pitch", 0)
            pause = context.user_data.get("pause", 500)
            
            rate_str = f"+{rate}%" if rate >= 0 else f"{rate}%"
            pitch_str = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"

            # Check if user already provided their own SSML
            if raw_text.strip().startswith("<speak>"):
                await edge_tts.Communicate(raw_text, voice).save(output_file)
                caption = f"🗣 {context.user_data.get('voice_name')}\n(Manual SSML)"
            else:
                success = await generate_long_audio_ssml(
                    raw_text, voice, rate_str, pitch_str, pause, output_file
                )
                if not success: raise Exception("SSML Generation failed")
                
                pause_lbl = f"{pause}ms" if pause > 0 else "Off"
                caption = f"🗣 {context.user_data.get('voice_name')}\n⚡ {rate_str} | 🎵 {pitch_str} | ⏱ {pause_lbl}"

            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=open(output_file, "rb"),
                caption=caption,
                title="TTS Audio"
            )
            os.remove(output_file)
            context.user_data["text_buffer"] = []
            await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Done!")

        except Exception as e:
            logging.error(f"TTS Error: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Error generating audio.")
        return
        
    # --- VOICE SELECTION ---
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
        
        await query.edit_message_text(f"⏳ Loading sample for **{name}**...", parse_mode=ParseMode.MARKDOWN)
        sample_file = f"sample_{query.from_user.id}.mp3"
        try:
            sample_text = "မင်္ဂလာပါ။ Hello."
            await edge_tts.Communicate(sample_text, code).save(sample_file)
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

async def post_init(application: Application):
    await application.bot.set_my_commands([("start", "Restart"), ("voice", "Change Speaker"), ("settings", "Settings")])

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
