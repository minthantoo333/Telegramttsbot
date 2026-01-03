import os
import re
import logging
import threading
import asyncio
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- LIBRARIES ---
import edge_tts
from pydub import AudioSegment
from pydub.effects import speedup
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
        "Vietnamese (HoaiMy - F)": "vi-VN-HoaiMyNeural",
        "Japanese (Nanami - F)": "ja-JP-NanamiNeural",
        "Korean (SunHi - F)": "ko-KR-SunHiNeural",
        "Chinese (Xiaoxiao - F)": "zh-CN-XiaoxiaoNeural",
    },
    "🇪🇺 Europe": {
        "British (Sonia - F)": "en-GB-SoniaNeural",
        "British (Ryan - M)": "en-GB-RyanNeural",
        "French (Denise - F)": "fr-FR-DeniseNeural",
        "Spanish (Paloma - F)": "es-US-PalomaNeural",
        "Russian (Svetlana - F)": "ru-RU-SvetlanaNeural",
    }
}

# --- LOGGING ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# --- DUMMY SERVER ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.wfile.write(b"Bot Active")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), SimpleHandler).serve_forever()

# --- SRT & AUDIO PROCESSING ---

def parse_srt_content(content):
    """Parses SRT string into list of dicts: {'start_ms': int, 'end_ms': int, 'text': str}"""
    pattern = re.compile(r'(\d+)\n(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})\n(.*?)(?=\n\n|\n$|\Z)', re.DOTALL)
    segments = []
    
    for match in pattern.finditer(content.replace('\r\n', '\n')):
        # Parse Start Time
        sh, sm, ss, sms = map(int, match.group(2, 3, 4, 5))
        start_ms = (sh * 3600 + sm * 60 + ss) * 1000 + sms
        
        # Parse End Time
        eh, em, es, ems = map(int, match.group(6, 7, 8, 9))
        end_ms = (eh * 3600 + em * 60 + es) * 1000 + ems
        
        text = match.group(10).replace('\n', ' ').strip()
        segments.append({'start_ms': start_ms, 'end_ms': end_ms, 'duration': end_ms - start_ms, 'text': text})
        
    return segments

def speed_change(sound, speed=1.0):
    """Changes speed of audio without changing pitch (using pydub/ffmpeg)"""
    if speed == 1.0: return sound
    # Using pydub's speedup (Note: speedup works best between 0.5 and 2.0)
    # For higher speeds, we might need a more aggressive chunk size
    return speedup(sound, playback_speed=speed, chunk_size=150, crossfade=25)

async def generate_srt_audio(srt_content, voice, base_rate, base_pitch):
    """Generates a synchronous audio file for the SRT."""
    segments = parse_srt_content(srt_content)
    final_audio = AudioSegment.empty()
    current_timeline_ms = 0
    
    # Create a temporary directory for segment files
    with tempfile.TemporaryDirectory() as temp_dir:
        for i, seg in enumerate(segments):
            text = seg['text']
            target_duration = seg['duration']
            start_time = seg['start_ms']

            # 1. Fill silence gap between previous end and current start
            gap = start_time - current_timeline_ms
            if gap > 0:
                final_audio += AudioSegment.silent(duration=gap)
            
            # Update timeline to current segment start
            current_timeline_ms = start_time

            # 2. Generate Audio for this segment
            temp_file = os.path.join(temp_dir, f"seg_{i}.mp3")
            
            # Use EdgeTTS
            rate_str = f"+{base_rate}%" if base_rate >= 0 else f"{base_rate}%"
            pitch_str = f"+{base_pitch}Hz" if base_pitch >= 0 else f"{base_pitch}Hz"
            
            communicate = edge_tts.Communicate(text, voice, rate=rate_str, pitch=pitch_str)
            await communicate.save(temp_file)
            
            # Load into Pydub
            segment_audio = AudioSegment.from_mp3(temp_file)
            original_duration = len(segment_audio)
            
            # 3. Process Duration (Dubbing Logic)
            if original_duration > target_duration:
                # AUDIO TOO LONG: Speed up to fit
                # Calculate required speed ratio (add 5% buffer to be safe)
                ratio = original_duration / target_duration
                # Cap max speed to avoid incomprehensible audio (e.g., max 2.5x)
                if ratio > 3.0: ratio = 3.0 
                
                segment_audio = speed_change(segment_audio, speed=ratio)
                
                # If still slightly too long after speedup due to artifacts, crop it
                if len(segment_audio) > target_duration:
                     segment_audio = segment_audio[:target_duration]
            
            # If Audio is shorter than target, we just use it as is. 
            # The loop logic handles the silence for the NEXT segment automatically.

            final_audio += segment_audio
            current_timeline_ms += len(segment_audio)

    return final_audio

# --- KEYBOARD HELPERS ---
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
        [InlineKeyboardButton("🔄 Reset", callback_data="preset_reset"),
         InlineKeyboardButton("✅ Back", callback_data="close_settings")]
    ])

# --- MENUS ---
async def show_voice_menu(update, context, is_new=False):
    keyboard = [[InlineKeyboardButton(r, callback_data=f"menu_{r}")] for r in VOICES.keys()]
    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="close_settings")])
    markup = InlineKeyboardMarkup(keyboard)
    text = "🗣 **Select Voice Category:**"
    if is_new: await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    else: await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)

async def show_settings_menu(update, context, is_new=False):
    context.user_data.setdefault("rate", 0)
    context.user_data.setdefault("pitch", 0)
    markup = get_settings_markup(context.user_data)
    text = "⚙️ **Audio Settings:**\nNote: For SRT Dubbing, 'Faster' only affects base speed. The bot auto-accelerates further if lines are too long."
    if is_new: await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    else: await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["text_buffer"] = []
    context.user_data["voice"] = DEFAULT_VOICE
    context.user_data["voice_name"] = "Burmese (Thiha)"
    await update.message.reply_text(
        "👋 **TTS Dubbing Bot Ready!**\n\n"
        "1️⃣ **Simple Mode:** Send text messages to build a paragraph.\n"
        "2️⃣ **Dubbing Mode:** Upload an `.srt` file. I will generate audio synced to timestamps (speeding up if necessary).",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    file_name = doc.file_name.lower()
    
    # Download file
    new_file = await doc.get_file()
    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = os.path.join(temp_dir, doc.file_name)
        await new_file.download_to_drive(input_path)
        
        # Read content
        try:
            with open(input_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            # Fallback for old windows encodings
            with open(input_path, "r", encoding="cp1252") as f:
                content = f.read()

        # CASE 1: TXT File -> Append to buffer
        if file_name.endswith(".txt"):
            if "text_buffer" not in context.user_data: context.user_data["text_buffer"] = []
            context.user_data["text_buffer"].append(content)
            total = sum(len(t) for t in context.user_data["text_buffer"])
            await update.message.reply_text(f"📄 **Text file added.** (Buffer: {total} chars)", reply_markup=get_control_keyboard(total))
            return

        # CASE 2: SRT File -> Immediate Processing
        if file_name.endswith(".srt"):
            status_msg = await update.message.reply_text("🎬 **SRT Received.** Analyzing timestamps & Dubbing...")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VOICE)
            
            voice = context.user_data.get("voice", DEFAULT_VOICE)
            rate = context.user_data.get("rate", 0)
            pitch = context.user_data.get("pitch", 0)
            
            try:
                # Generate Synced Audio
                final_audio = await generate_srt_audio(content, voice, rate, pitch)
                
                # Export
                output_path = os.path.join(temp_dir, f"dubbing_{doc.file_name}.mp3")
                final_audio.export(output_path, format="mp3")
                
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=open(output_path, "rb"),
                    title=f"Dubbed: {doc.file_name}",
                    caption=f"✅ **Dubbing Complete**\n🎤 {context.user_data.get('voice_name')}\n⏱️ Synced to SRT timestamps."
                )
                await status_msg.delete()
            except Exception as e:
                logging.error(e)
                await status_msg.edit_text(f"⚠️ **Error processing SRT:**\n{str(e)[:100]}")
            return

    await update.message.reply_text("⚠️ Please send .txt or .srt files.")

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

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # --- MENU NAVIGATION ---
    if data == "open_voice_menu":
        await show_voice_menu(update, context)
        return
    if data == "open_settings":
        await show_settings_menu(update, context)
        return
    if data == "clear_buffer":
        context.user_data["text_buffer"] = []
        await query.edit_message_text("🗑 **Memory Cleared.**")
        return
    if data == "close_settings":
        total = sum(len(t) for t in context.user_data.get("text_buffer", []))
        if total > 0:
             await query.edit_message_text(f"📥 **Ready.** ({total} chars)", reply_markup=get_control_keyboard(total))
        else:
             await query.delete_message()
        return

    # --- GENERATE (Simple Mode) ---
    if data == "generate":
        if not context.user_data.get("text_buffer"):
            await query.edit_message_text("⚠️ Buffer empty.")
            return

        await query.edit_message_text("⏳ **Generating Normal Audio...**")
        raw_text = "\n".join(context.user_data["text_buffer"])
        
        voice = context.user_data.get("voice", DEFAULT_VOICE)
        rate = context.user_data.get("rate", 0)
        pitch = context.user_data.get("pitch", 0)
        rate_str = f"+{rate}%" if rate >= 0 else f"{rate}%"
        pitch_str = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"

        try:
            comm = edge_tts.Communicate(raw_text, voice, rate=rate_str, pitch=pitch_str)
            filename = f"tts_{query.from_user.id}.mp3"
            await comm.save(filename)
            await context.bot.send_audio(
                chat_id=update.effective_chat.id, 
                audio=open(filename, "rb"),
                caption=f"🗣 {context.user_data.get('voice_name')}",
                title="Simple TTS"
            )
            os.remove(filename)
            context.user_data["text_buffer"] = []
            await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Done.")
        except Exception as e:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Error: {e}")
        return

    # --- SETTINGS ADJUSTMENT ---
    if "rate_" in data or "pitch_" in data:
        key, val = data.split("_")
        context.user_data[key] = max(-100, min(100, context.user_data.get(key, 0) + int(val)))
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))
        return
    
    if data == "preset_reset":
        context.user_data.update({"rate": 0, "pitch": 0})
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))
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
        total = sum(len(t) for t in context.user_data.get("text_buffer", []))
        await query.edit_message_text(f"✅ Voice set to: **{name}**", reply_markup=get_control_keyboard(total))
        return

# --- MAIN ---
async def post_init(app: Application):
    await app.bot.set_my_commands([
        ("start", "Restart Bot"), 
        ("voice", "Change Speaker"), 
        ("settings", "Audio Settings")
    ])

def main():
    if not TOKEN:
        print("❌ ERROR: TELEGRAM_TOKEN missing.")
        return

    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("voice", lambda u, c: show_voice_menu(u, c, True)))
    app.add_handler(CommandHandler("settings", lambda u, c: show_settings_menu(u, c, True)))
    
    # Text & Document Handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 Bot Started...")
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    main()
