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
    """Adds slight pauses to make speech less robotic."""
    if not text: return ""
    text = text.replace("။", "။\n") 
    text = text.replace("、", "、 ") 
    text = text.replace(".", ".\n") 
    return text

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

# --- COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resets the bot memory and shows welcome message."""
    context.user_data.clear()
    
    # Initialize Defaults
    context.user_data["text_buffer"] = []
    context.user_data["voice"] = DEFAULT_VOICE
    context.user_data["voice_name"] = "Burmese (Thiha)"
    context.user_data["rate"] = 0
    context.user_data["pitch"] = 0

    await update.message.reply_text(
        "👋 **Bot Restarted!**\n\n"
        "Send me text to begin.\n"
        "I have cleared your previous memory.",
        parse_mode=ParseMode.MARKDOWN
    )

async def collect_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Captures user text input."""
    text = update.message.text
    
    # Init if missing
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

# --- UNIVERSAL BUTTON HANDLER ---
# This handles ALL buttons (Voice, Settings, Generate) regardless of state.
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Crucial: stops the loading animation
    data = query.data

    # --- 1. GENERATE & CLEAR ---
    if data == "clear_buffer":
        context.user_data["text_buffer"] = []
        await query.edit_message_text("🗑 **Memory Cleared.** Send new text.")
        return

    if data == "generate":
        if not context.user_data.get("text_buffer"):
            await query.edit_message_text("⚠️ No text found. Send text first.")
            return

        await query.edit_message_text("⏳ **Generating...**")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VOICE)

        try:
            raw_text = "\n".join(context.user_data["text_buffer"])
            final_text = preprocess_text_for_pauses(raw_text)
            
            # Fetch settings
            voice = context.user_data.get("voice", DEFAULT_VOICE)
            rate = context.user_data.get("rate", 0)
            pitch = context.user_data.get("pitch", 0)
            
            rate_str = f"+{rate}%" if rate >= 0 else f"{rate}%"
            pitch_str = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"

            output_file = f"tts_{query.from_user.id}.mp3"
            
            # Create Audio
            communicate = edge_tts.Communicate(final_text, voice, rate=rate_str, pitch=pitch_str)
            await communicate.save(output_file)

            # Send Audio
            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=open(output_file, "rb"),
                caption=f"🗣 {context.user_data.get('voice_name', 'Unknown')}\n⚡ {rate_str} | 🎵 {pitch_str}",
                title="TTS Audio"
            )
            
            # Cleanup
            os.remove(output_file)
            context.user_data["text_buffer"] = [] # Clear buffer
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="✅ Done! Send new text to start again."
            )

        except Exception as e:
            logging.error(f"TTS Error: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Error generating audio.")
        return

    # --- 2. MENUS (OPENING) ---
    if data == "open_voice_menu":
        keyboard = [[InlineKeyboardButton(r, callback_data=f"menu_{r}")] for r in VOICES.keys()]
        keyboard.append([InlineKeyboardButton("❌ Close", callback_data="close_settings")])
        await query.edit_message_text("🗣 **Select Voice Category:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        return

    if data == "open_settings":
        context.user_data.setdefault("rate", 0)
        context.user_data.setdefault("pitch", 0)
        await query.edit_message_text("⚙️ **Audio Settings:**", reply_markup=get_settings_markup(context.user_data), parse_mode=ParseMode.MARKDOWN)
        return

    # --- 3. VOICE NAVIGATION ---
    if data.startswith("menu_"):
        region = data.replace("menu_", "")
        keyboard = [[InlineKeyboardButton(n, callback_data=f"set_{c}|{n}")] for n, c in VOICES[region].items()]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="open_voice_menu")])
        await query.edit_message_text(f"📂 **{region}**", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # --- 4. VOICE SELECTION + SAMPLE ---
    if data.startswith("set_"):
        code, name = data.replace("set_", "").split("|")
        context.user_data["voice"] = code
        context.user_data["voice_name"] = name
        
        # Send a sample
        await query.edit_message_text(f"⏳ Loading sample for **{name}**...", parse_mode=ParseMode.MARKDOWN)
        sample_file = f"sample_{query.from_user.id}.mp3"
        try:
            # Use English for sample text as it works on all multilingual/English voices. 
            # For pure Burmese voices, they might sound funny reading English, but it confirms they work.
            sample_text = "Hello, this is my voice." 
            await edge_tts.Communicate(sample_text, code).save(sample_file)
            await context.bot.send_voice(chat_id=update.effective_chat.id, voice=open(sample_file, "rb"))
            os.remove(sample_file)
        except Exception:
            pass # Skip sample if fail

        # Return to control panel
        total = sum(len(t) for t in context.user_data.get("text_buffer", []))
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Voice set to: **{name}**",
            reply_markup=get_control_keyboard(total)
        )
        return

    # --- 5. SETTINGS ADJUSTMENT ---
    if data == "close_settings":
        total = sum(len(t) for t in context.user_data.get("text_buffer", []))
        if total > 0:
            await query.edit_message_text(f"📥 **Ready.** (Total: {total} chars)", reply_markup=get_control_keyboard(total), parse_mode=ParseMode.MARKDOWN)
        else:
            await query.delete_message()
            await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Settings closed. Send text.")
        return

    if "rate_" in data or "pitch_" in data:
        key, val = data.split("_")
        val = int(val)
        current = context.user_data.get(key, 0)
        # Limits
        context.user_data[key] = max(-100, min(100, current + val))
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))
        return

    if data == "preset_crisp":
        context.user_data.update({"rate": 10, "pitch": 5})
        await query.answer("✨ Crisp Mode ON")
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))
        return

    if data == "preset_reset":
        context.user_data.update({"rate": 0, "pitch": 0})
        await query.answer("🔄 Reset")
        await query.edit_message_reply_markup(get_settings_markup(context.user_data))
        return

# --- INIT ---
async def post_init(application: Application):
    """Sets the menu commands automatically."""
    commands = [
        ("start", "Restart Bot & Clear Memory"),
        ("voice", "Change Speaker"),
        ("settings", "Speed & Pitch"),
    ]
    await application.bot.set_my_commands(commands)

def main():
    if not TOKEN:
        print("❌ TELEGRAM_TOKEN missing")
        return

    # We removed ConversationHandler because it was causing 'stuck' buttons.
    # We now use simple logic: Text messages -> collect_text, Button clicks -> button_handler
    application = Application.builder().token(TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("voice", lambda u, c: button_handler(u, c, manual_trigger="open_voice_menu"))) # Hacky shim not needed, just text hint
    # Actually, let's map /voice and /settings to trigger the menu by sending a message with a button
    
    async def command_menu_shim(update, context):
        """Helper to show menus via commands"""
        if update.message.text == "/voice":
            await button_handler(update, context) # Complex to shim, easier to just send a new menu
            keyboard = [[InlineKeyboardButton(r, callback_data=f"menu_{r}")] for r in VOICES.keys()]
            await update.message.reply_text("🗣 **Select Voice:**", reply_markup=InlineKeyboardMarkup(keyboard))
        elif update.message.text == "/settings":
             context.user_data.setdefault("rate", 0)
             context.user_data.setdefault("pitch", 0)
             await update.message.reply_text("⚙️ **Settings:**", reply_markup=get_settings_markup(context.user_data))

    application.add_handler(CommandHandler(["voice", "settings"], command_menu_shim))
    
    # MAIN HANDLERS
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_text))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    main()