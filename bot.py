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
CHUNK_SIZE = 2500  # Split text every 2500 chars

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

def preprocess_text_for_pauses(text):
    """
    TUNED FOR 200-300ms PAUSE (Narrator Style)
    1. Removes all newlines (\n) -> Prevents the long 800ms pause.
    2. Uses "။ " -> Triggers the natural sentence break (approx 300ms).
    """
    if not text: return ""
    
    # 1. Remove Newlines (The "Long Pause" killer)
    text = text.replace("\n", " ")
    
    # 2. Normalize Punctuation (The "Medium Pause" creator)
    # Adding a space after '။' ensures the engine sees it as a sentence end.
    text = text.replace("။", "။ ") 
    text = text.replace("、", "、 ") 
    text = text.replace(".", ". ") 
    
    # 3. Clean up accidental double spaces
    text = " ".join(text.split())
    
    return text

def split_text_smart(text, chunk_size):
    """
    Splits text into chunks respecting Burmese punctuation to avoid breaking 
    combined characters (like ရွှေ -> ရ + ွှ).
    """
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    while text:
        if len(text) <= chunk_size:
            chunks.append(text)
            break
        
        # Take a safe slice to analyze
        slice_candidate = text[:chunk_size]
        
        # PRIORITY 1: Split at Sentence Endings (Strongest Pause)
        prio1_indices = [
            slice_candidate.rfind("။") + len("။"),  # Burmese Full Stop
            slice_candidate.rfind(".") + 1,  # English Period
            slice_candidate.rfind("\n") + 1, # Newline
            slice_candidate.rfind("?") + 1,
            slice_candidate.rfind("!") + 1
        ]
        
        # Filter out 0 (not found) and get the one closest to the end
        valid_prio1 = [i for i in prio1_indices if i > 0]
        
        if valid_prio1:
            split_at = max(valid_prio1)
        else:
            # PRIORITY 2: Split at Commas or Spaces (Mid-sentence)
            prio2_indices = [
                slice_candidate.rfind("၊") + len("၊"), # Burmese Comma
                slice_candidate.rfind(",") + 1,
                slice_candidate.rfind(" ") + 1
            ]
            valid_prio2 = [i for i in prio2_indices if i > 0]
            
            if valid_prio2:
                split_at = max(valid_prio2)
            else:
                # Fallback: Force split if absolutely no punctuation found
                split_at = chunk_size
        
        current_chunk = text[:split_at].strip()
        if current_chunk:
            chunks.append(current_chunk)
        
        text = text[split_at:]
    
    return chunks

async def generate_long_audio(text, voice, rate_str, pitch_str, final_filename):
    """Generates audio in chunks and merges them."""
    chunks = split_text_smart(text, CHUNK_SIZE)
    merged_audio = b""
    
    for i, chunk in enumerate(chunks):
        if not chunk.strip(): continue
        
        temp_file = f"temp_chunk_{i}_{final_filename}"
        try:
            communicate = edge_tts.Communicate(chunk, voice, rate=rate_str, pitch=pitch_str)
            await communicate.save(temp_file)
            
            # Read binary and append
            with open(temp_file, "rb") as f:
                merged_audio += f.read()
            
            os.remove(temp_file)
        except Exception as e:
            logging.error(f"Chunk error: {e}")
            if os.path.exists(temp_file): os.remove(temp_file)
            return False

    # Save merged file
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🐢 Slower", callback_data="rate_-10"),
         InlineKeyboardButton(f"🚀 Faster ({speed}%)", callback_data="rate_+10")],
        [InlineKeyboardButton(f"🔉 Lower", callback_data="pitch_-5"),
         InlineKeyboardButton(f"🔊 Higher ({pitch}Hz)", callback_data="pitch_+5")],
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
    markup = get_settings_markup(context.user_data)
    text = "⚙️ **Audio Settings:**"
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

# --- TXT FILE HANDLER ---
async def handle_txt_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    
    if update.message.document.file_size > 5 * 1024 * 1024:
        await update.message.reply_text("⚠️ File too large. Limit: 5MB.")
        return

    file_bytes = await file.download_as_bytearray()
    
    try:
        text_content = file_bytes.decode('utf-8')
    except UnicodeDecodeError:
        try:
            text_content = file_bytes.decode('cp1252')
        except:
            await update.message.reply_text("⚠️ Encoding Error. Use UTF-8.")
            return

    if not text_content.strip():
        await update.message.reply_text("⚠️ Empty file.")
        return

    if "text_buffer" not in context.user_data:
        context.user_data["text_buffer"] = []
        context.user_data.setdefault("voice", DEFAULT_VOICE)
        context.user_data.setdefault("voice_name", "Burmese (Thiha)")

    context.user_data["text_buffer"].append(text_content)
    total_len = sum(len(t) for t in context.user_data["text_buffer"])

    await update.message.reply_text(
        f"📄 **File Read!** Added {len(text_content)} chars.\n📥 **Total:** {total_len} chars",
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

    if data == "generate":
        if not context.user_data.get("text_buffer"):
            await query.edit_message_text("⚠️ No text found.")
            return

        await query.edit_message_text("⏳ **Generating...**")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VOICE)

        try:
            # JOIN BUFFER
            raw_text = "".join(context.user_data["text_buffer"]) 
            voice = context.user_data.get("voice", DEFAULT_VOICE)
            output_file = f"tts_{query.from_user.id}.mp3"
            
            # SSML Check
            if raw_text.strip().startswith("<speak>"):
                await edge_tts.Communicate(raw_text, voice).save(output_file)
                caption = f"🗣 {context.user_data.get('voice_name')}\n(SSML)"
            else:
                # 1. CLEAN PAUSES (200-300ms logic applied here)
                final_text = preprocess_text_for_pauses(raw_text)
                
                rate, pitch = context.user_data.get("rate", 0), context.user_data.get("pitch", 0)
                rate_str = f"+{rate}%" if rate >= 0 else f"{rate}%"
                pitch_str = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"
                
                # 2. GENERATE (Using Safe Splitter)
                success = await generate_long_audio(final_text, voice, rate_str, pitch_str, output_file)
                if not success: raise Exception("Chunk generation failed")
                caption = f"🗣 {context.user_data.get('voice_name')}\n⚡ {rate_str} | 🎵 {pitch_str}"

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

    # VOICE NAVIGATION & SELECTION
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
            sample_text = "မင်္ဂလာပါ။ (Mingalabar)"
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

    # SETTINGS
    if data == "close_settings":
        total = sum(len(t) for t in context.user_data.get("text_buffer", []))
        if total > 0: await query.edit_message_text(f"📥 **Ready.** (Total: {total} chars)", reply_markup=get_control_keyboard(total), parse_mode=ParseMode.MARKDOWN)
        else: await query.delete_message(); await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Settings closed.")
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
