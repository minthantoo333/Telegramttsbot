import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import edge_tts
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ✅ GOOD (Do this):
TOKEN = os.environ.get("TELEGRAM_TOKEN")

if not TOKEN:
    raise ValueError("No TELEGRAM_TOKEN found in environment variables!")

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
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# --- STATES ---
COLLECTING, CONFIRMING = range(2)

# --- DUMMY SERVER ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Active")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), SimpleHandler).serve_forever()

# --- HELPERS ---
def get_settings_markup(data):
    """Generates the buttons for Speed/Pitch adjustment."""
    speed = data.get("rate", 0)
    pitch = data.get("pitch", 0)
    
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🐢 Slower", callback_data="rate_-10"),
            InlineKeyboardButton(f"🚀 Faster ({speed}%)", callback_data="rate_+10"),
        ],
        [
            InlineKeyboardButton(f"🔉 Lower", callback_data="pitch_-5"),
            InlineKeyboardButton(f"🔊 Higher ({pitch}Hz)", callback_data="pitch_+5"),
        ],
        [InlineKeyboardButton("✨ Make it Crisp & Clear", callback_data="preset_crisp")],
        [InlineKeyboardButton("🔄 Reset Normal", callback_data="preset_reset")],
        [InlineKeyboardButton("✅ Done / Close", callback_data="close_settings")]
    ])

# --- COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["text_buffer"] = []
    # Defaults
    if "voice" not in context.user_data:
        context.user_data["voice"] = DEFAULT_VOICE
        context.user_data["voice_name"] = "Burmese (Thiha)"
    if "rate" not in context.user_data: context.user_data["rate"] = 0
    if "pitch" not in context.user_data: context.user_data["pitch"] = 0

    await update.message.reply_text(
        "👋 **Burmese TTS Bot**\n\n"
        "1. Send text parts.\n"
        "2. Type /done to finish.\n"
        "3. Type /voice to change speaker.\n"
        "4. Type /settings to adjust Speed & Pitch.",
        parse_mode="Markdown"
    )
    return COLLECTING

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Opens the settings menu."""
    await update.message.reply_text(
        "⚙️ **Audio Settings**\nAdjust the speed and pitch below:",
        reply_markup=get_settings_markup(context.user_data)
    )

async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles clicks on the settings buttons."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_data = context.user_data

    if data == "close_settings":
        await query.delete_message()
        return

    # Adjust Rate (Speed)
    if data.startswith("rate_"):
        change = int(data.split("_")[1])
        user_data["rate"] = max(-50, min(100, user_data.get("rate", 0) + change))
    
    # Adjust Pitch
    elif data.startswith("pitch_"):
        change = int(data.split("_")[1])
        user_data["pitch"] = max(-50, min(50, user_data.get("pitch", 0) + change))
    
    # Preset: Crisp & Clear (High pitch, slightly fast)
    elif data == "preset_crisp":
        user_data["rate"] = 10
        user_data["pitch"] = 5
        await query.answer("✨ Crisp mode activated!", show_alert=True)

    # Preset: Reset
    elif data == "preset_reset":
        user_data["rate"] = 0
        user_data["pitch"] = 0

    # Refresh the menu with new values
    await query.edit_message_reply_markup(reply_markup=get_settings_markup(user_data))


# --- VOICE MENU HANDLERS (Same logic, updated dict) ---
async def voice_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(r, callback_data=f"menu_{r}")] for r in VOICES.keys()]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_voice")])
    await update.message.reply_text("🗣 **Select Voice Category:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def voice_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel_voice":
        await query.edit_message_text("✅ Cancelled.")
        return

    if data.startswith("menu_"):
        region = data.replace("menu_", "")
        keyboard = [[InlineKeyboardButton(n, callback_data=f"set_{c}|{n}")] for n, c in VOICES[region].items()]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_main")])
        await query.edit_message_text(f"📂 **{region}**", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "back_main":
        await voice_menu(update, context) # Re-use the menu function logic lightly modified or just recall command logic if split. 
        # For simplicity, we manually re-show main menu here:
        keyboard = [[InlineKeyboardButton(r, callback_data=f"menu_{r}")] for r in VOICES.keys()]
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_voice")])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))


    elif data.startswith("set_"):
        code, name = data.replace("set_", "").split("|")
        context.user_data["voice"] = code
        context.user_data["voice_name"] = name
        await query.edit_message_text(f"✅ Voice set to: **{name}**")

# --- GENERATION ---
async def collect_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.setdefault("text_buffer", []).append(update.message.text)
    await update.message.reply_text(f"📥 Received. (Total: {sum(len(t) for t in context.user_data['text_buffer'])})")
    return COLLECTING

async def done_collecting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not context.user_data.get("text_buffer"):
        await update.message.reply_text("⚠️ Send text first.")
        return COLLECTING
    
    full_text = "\n".join(context.user_data["text_buffer"])
    context.user_data["final_text"] = full_text
    
    # Show summary with current settings
    r = context.user_data.get("rate", 0)
    p = context.user_data.get("pitch", 0)
    rate_str = f"+{r}%" if r >= 0 else f"{r}%"
    pitch_str = f"+{p}Hz" if p >= 0 else f"{p}Hz"

    msg = (
        f"📝 **Ready** ({len(full_text)} chars)\n"
        f"🗣 **Voice:** {context.user_data.get('voice_name', 'Default')}\n"
        f"⚙️ **Settings:** Speed {rate_str} | Pitch {pitch_str}"
    )
    
    keyboard = [[InlineKeyboardButton("✅ Generate", callback_data="generate"),
                 InlineKeyboardButton("❌ Cancel", callback_data="cancel_gen")]]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CONFIRMING

async def generate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_gen":
        context.user_data["text_buffer"] = []
        await query.edit_message_text("❌ Cancelled.")
        return COLLECTING

    await query.edit_message_text("⏳ Generating...")
    
    # PREPARE ARGUMENTS
    text = context.user_data["final_text"]
    voice = context.user_data.get("voice", DEFAULT_VOICE)
    rate = context.user_data.get("rate", 0)
    pitch = context.user_data.get("pitch", 0)
    
    rate_str = f"+{rate}%" if rate >= 0 else f"{rate}%"
    pitch_str = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"

    output_file = f"tts_{query.from_user.id}.mp3"
    
    try:
        # COMMUNICATE WITH PITCH/RATE
        communicate = edge_tts.Communicate(text, voice, rate=rate_str, pitch=pitch_str)
        await communicate.save(output_file)
        
        await context.bot.send_audio(
            chat_id=update.effective_chat.id,
            audio=open(output_file, "rb"),
            caption=f"🗣 {context.user_data.get('voice_name')}\n⚡ {rate_str} | 🎵 {pitch_str}"
        )
        os.remove(output_file)
        context.user_data["text_buffer"] = []
    except Exception as e:
        logging.error(e)
        await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Error generating audio.")

    return COLLECTING

# --- MAIN ---
def main():
    if not TOKEN: return print("Missing Token")
    app = Application.builder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            COLLECTING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_text),
                CommandHandler("done", done_collecting),
                CommandHandler("voice", voice_menu),
                CommandHandler("settings", settings_menu)
            ],
            CONFIRMING: [CallbackQueryHandler(generate_handler)],
        },
        fallbacks=[CommandHandler("cancel", start)]
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("voice", voice_menu))
    app.add_handler(CommandHandler("settings", settings_menu))
    app.add_handler(CallbackQueryHandler(voice_button_handler, pattern="^(menu_|set_|back_main|cancel_voice)"))
    app.add_handler(CallbackQueryHandler(settings_handler, pattern="^(rate_|pitch_|preset_|close_settings)"))

    print("Bot Started...")
    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    main()
