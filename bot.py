import logging
import asyncio
import sqlite3
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes, ConversationHandler)

# ========== CONFIG ==========
API_ID = 40814156
API_HASH = "b014c2955f956a9a0d58e96cc7c7ae96"
BOT_TOKEN = "7732247081:AAGdZ5Td3dsxBIZYuUP2IlADtgf0KBrX8Qs"

# ========== DB SETUP ==========
conn = sqlite3.connect("user_sessions.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS sessions (
    user_id INTEGER,
    phone TEXT,
    session_string TEXT,
    PRIMARY KEY(user_id, phone)
)
""")
conn.commit()

# ========== LOGGING ==========
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== STATES ==========
WAIT_PHONE, WAIT_CODE = range(2)
user_states = {}
temp_data = {}

# ========== COMMANDS ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = """
<b>✨ Welcome to Legend Vote Bot ✨</b>

🤖 Developed by @Aloneboy_dev

🔹 /connect – Link your Telegram account
🔹 /list – View your linked accounts
🔹 /unlink – Unlink one or all accounts
🔹 /vote – Auto-vote using your accounts
🔹 /history – See vote history

<b>Let's Rule The Polls! 🔥</b>
    """
    await update.message.reply_text(welcome, parse_mode="HTML")


async def connect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📱 Please send your phone number (with country code):\nExample: <code>+923001234567</code>", parse_mode="HTML")
    user_states[update.message.from_user.id] = WAIT_PHONE
    return WAIT_PHONE


async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    phone = update.message.text.strip()
    temp_data[user_id] = {"phone": phone}

    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        sent = await client.send_code_request(phone)
        temp_data[user_id]["client"] = client
        await update.message.reply_text("📩 Code sent! Now please enter the OTP code:")
        user_states[user_id] = WAIT_CODE
        return WAIT_CODE
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to send code: {str(e)}")
        return ConversationHandler.END


async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    code = update.message.text.strip()
    data = temp_data.get(user_id)

    if not data:
        await update.message.reply_text("❌ No session found. Please /connect again.")
        return ConversationHandler.END

    client = data["client"]
    phone = data["phone"]
    try:
        await client.sign_in(phone=phone, code=code)
        string = client.session.save()
        cursor.execute("REPLACE INTO sessions (user_id, phone, session_string) VALUES (?, ?, ?)", (user_id, phone, string))
        conn.commit()
        await update.message.reply_text("✅ Account linked successfully!")
        await client.disconnect()
        return ConversationHandler.END
    except SessionPasswordNeededError:
        await update.message.reply_text("🔐 2FA enabled. Not supported yet.")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {str(e)}")
    return ConversationHandler.END


async def list_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cursor.execute("SELECT phone FROM sessions WHERE user_id = ?", (user_id,))
    accounts = cursor.fetchall()
    if accounts:
        reply = "📄 Linked Accounts:\n" + "\n".join([f"🔹 {a[0]}" for a in accounts])
    else:
        reply = "⚠️ You have 0 linked accounts. Use /connect"
    await update.message.reply_text(reply)


async def unlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cursor.execute("SELECT phone FROM sessions WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("⚠️ No linked accounts to unlink.")
        return

    buttons = [[InlineKeyboardButton(f"❌ {row[0]}", callback_data=f"UNLINK_{row[0]}") for row in rows]]
    buttons.append([InlineKeyboardButton("🔥 Unlink All", callback_data="UNLINK_ALL")])
    await update.message.reply_text("Select account(s) to unlink:", reply_markup=InlineKeyboardMarkup(buttons))


async def handle_unlink_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "UNLINK_ALL":
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
        await query.edit_message_text("✅ All accounts unlinked.")
    elif query.data.startswith("UNLINK_"):
        phone = query.data.split("_", 1)[1]
        cursor.execute("DELETE FROM sessions WHERE user_id = ? AND phone = ?", (user_id, phone))
        conn.commit()
        await query.edit_message_text(f"✅ Unlinked {phone}.")


async def vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        if len(args) != 2:
            await update.message.reply_text("⚠️ Usage: /vote <poll_link> <option>\nExample: /vote https://t.me/funtoken_officialchat/1878701 A")
            return
        link, option = args
        user_id = update.message.from_user.id

        cursor.execute("SELECT session_string FROM sessions WHERE user_id = ?", (user_id,))
        rows = cursor.fetchall()
        if not rows:
            await update.message.reply_text("⚠️ No accounts linked. Use /connect")
            return

        option_map = {'A': 0, 'B': 1, 'C': 2, 'D': 3, 'E': 4}
        if option.upper() not in option_map:
            await update.message.reply_text("❌ Invalid option. Use A, B, C, D or E.")
            return

        message_id = int(link.split("/")[-1])
        for session_str in rows:
            try:
                client = TelegramClient(StringSession(session_str[0]), API_ID, API_HASH)
                await client.connect()
                await client(telethon.tl.functions.messages.GetMessagesRequest(id=[message_id]))
                await client(telethon.tl.functions.messages.GetPollVotesRequest(
                    peer='@FUNToken_OfficialChat',
                    id=message_id,
                    option=option_map[option.upper()]
                ))
                await client.disconnect()
            except FloodWaitError as e:
                await update.message.reply_text(f"⏳ Flood wait. Try again after {e.seconds} seconds.")
            except Exception as e:
                await update.message.reply_text(f"❌ Error while voting: {str(e)}")

        await update.message.reply_text("✅ Vote sent from all linked accounts!")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ========== MAIN ==========

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("connect", connect)],
        states={
            WAIT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)],
            WAIT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code)]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("list", list_accounts))
    app.add_handler(CommandHandler("vote", vote))
    app.add_handler(CommandHandler("unlink", unlink))
    app.add_handler(CallbackQueryHandler(handle_unlink_callback))

    app.run_polling()

if __name__ == '__main__':
    main()
