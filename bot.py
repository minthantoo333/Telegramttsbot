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

# --- STATE DEFINITIONS ---
# We use a single state for simplicity, but handle menus globally
COLLECTING = 1

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
def preprocess_text_for_pauses(text):
    """Adds slight pauses to make speech less robotic."""
    text = text.replace("။", "။\n") 
    text = text.replace("、", "、 ") 
    text = text.replace(".", ".\n") 
    return text

def get_control_keyboard(total_chars):
    """The main control panel for the user."""
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Hard Reset: Clears everything and starts fresh."""
    context.user_data.clear() # WIPE MEMORY
    
    # Re-initialize defaults
    context.user_data["text_buffer"] = []
    context.user_data["voice"] = DEFAULT_VOICE
    context.user_data["voice_name"] = "Burmese (Thiha)"
    context.user_data["rate"] = 0
    context.user_data["pitch"] = 0

    await update.message.reply_text(
        "🔄 **Bot Restarted!**\n\n"
        "Send me any text to begin.\n"
        "I have cleared your previous text and settings.",
        parse_mode=ParseMode.MARKDOWN
    )
    return COLLECTING

async def collect_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Collects text messages."""
    text = update.message.text
    
    # Safety init
    if "text_buffer" not in context.user_data:
        context.user_data["text_buffer"] = []
        context.user_data.setdefault("voice", DEFAULT_VOICE)

    context.user_data["text_buffer"].append(text)
    total_len = sum(len(t) for t in context.user_data["text_buffer"])
    
    await update.message.reply_text(
        f"📥 **Added.** (Total: {total_len} chars)",
        reply_markup=get_control_keyboard(total_len),
        parse_mode=ParseMode.MARKDOWN
    )
    return COLLECTING

async def generate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the Generate and Clear buttons."""
    query = update.callback_query
    await query.answer()

    if query.data == "clear_buffer":
        context.user_data["text_buffer"] = []
        await query.edit_message_text("🗑 **Memory Cleared.** Send new text.")
        return COLLECTING

    if query.data == "generate":
        if not context.user_data.get("text_buffer"):
            await query.edit_message_text("⚠️ No text found. Send text first.")
            return COLLECTING

        await query.edit_message_text("⏳ **Generating...**")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VOICE)

        try:
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
            context.user_data["text_buffer"] = [] # Auto-clear
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="✅ Done! Send new text to start again."
            )

        except Exception as e:
            logging.error(f"TTS Error: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Error generating audio.")

    return COLLECTING

# --- GLOBAL MENU HANDLER (Fixes Unresponsive Buttons) ---
# This function handles Menus INDEPENDENT of the conversation state
async def global_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Vital to stop button loading animation
    data = query.data

    # 1. OPEN MENUS
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

    # 2. NAVIGATE VOICE MENUS
    if data.startswith("menu_"):
        region = data.replace("menu_", "")
        keyboard = [[InlineKeyboardButton(n, callback_data=f"set_{c}|{n}")] for n, c in VOICES[region].items()]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="open_voice_menu")]) # Points back to main voice menu
        await query.edit_message_text(f"📂 **{region}**", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # 3. SELECT VOICE
    if data.startswith("set_"):
        code, name = data.replace("set_", "").split("|")
        context.user_data["voice"] = code
        context.user_data["voice_name"] = name
        
        # Confirmation + Control Panel
        total = sum(len(t) for t in context.user_data.get("text_buffer", []))
        await query.edit_message_text(
            f"✅ Voice set to: **{name}**\n\nReady to generate.", 
            reply_markup=get_control_keyboard(total),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # 4. SETTINGS LOGIC
    if data == "close_settings":
        total = sum(len(t) for t in context.user_data.get("text_buffer", []))
        await query.edit_message_text(f"📥 **Ready.** (Total: {total} chars)", reply_markup=get_control_keyboard(total), parse_mode=ParseMode.MARKDOWN)
        return

    if "rate_" in data or "pitch_" in data:
        key, val = data.split("_")
        val = int(val)
        current = context.user_data.get(key, 0)
        context.user_data[key] = max(-100, min(100, current + val))
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

# --- MAIN SETUP ---
def main():
    if not TOKEN:
        print("❌ Error: TELEGRAM_TOKEN missing")
        return

    application = Application.builder().token(TOKEN).build()

    # 1. The Conversation Handler (For Flow)
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, collect_text)
        ],
        states={
            COLLECTING: [
                # Text Handler
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_text),
                # Generate/Clear Buttons
                CallbackQueryHandler(generate_handler, pattern="^(generate|clear_buffer)$"),
                # Menu Buttons (Pass to global handler)
                CallbackQueryHandler(global_menu_handler, pattern="^(open_|menu_|set_|rate_|pitch_|preset_|close_|back_)")
            ]
        },
        fallbacks=[CommandHandler("start", start)], # Handles restart mid-conversation
    )

    application.add_handler(conv_handler)
    
    # 2. Global Fallback (Fixes "Buttons not working" if bot restarted)
    # If the user clicks a button but the bot forgot the state, this catches it.
    application.add_handler(CallbackQueryHandler(global_menu_handler))

    print("🤖 Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    main()