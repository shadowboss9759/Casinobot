import sqlite3
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

DB_FILE = "casino_bot.db"
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))  # Apni Admin Telegram ID yahan daalein

# ---------------------------------------------------------
# DATABASE INITIALIZATION FOR ADMIN & SYSTEM SETTINGS
# ---------------------------------------------------------
def init_admin_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Settings Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # Banned Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY
        )
    ''')

    # Default Settings Insert
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('bot_status', 'ON')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('force_channel', '')")
    
    conn.commit()
    conn.close()

init_admin_db()

# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------
def get_setting(key: str) -> str:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""

def set_setting(key: str, value: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def is_user_banned(user_id: int) -> bool:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM banned_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def coins_to_inr(coins: float) -> float:
    return round(coins / 100.0, 2)  # 100 Coins = 1 INR

# ---------------------------------------------------------
# FORCE JOIN CHECKER (Aapke har user handler me call hoga)
# ---------------------------------------------------------
async def check_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    
    # Admin bypasses force join
    if user_id == ADMIN_ID:
        return True

    # Check Bot On/Off
    if get_setting("bot_status") == "OFF":
        await context.bot.send_message(chat_id=user_id, text="⚠️ Bot abhi Maintenance/OFF mode par hai. Baad me try karein!")
        return False

    # Check Ban
    if is_user_banned(user_id):
        await context.bot.send_message(chat_id=user_id, text="🚫 Aapko is bot se Ban kar diya gaya hai.")
        return False

    channel = get_setting("force_channel")
    if not channel:
        return True  # Force channel set nahi hai toh allow karein

    try:
        member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in ['creator', 'administrator', 'member']:
            return True
        else:
            raise Exception("Not Joined")
    except Exception:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(text="📢 Join Channel", url=f"https://t.me/{channel.replace('@', '')}")],
            [InlineKeyboardButton(text="✅ Joined / Refresh", callback_data="check_join_refresh")]
        ])
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ *Access Denied!*\n\nBot ko use karne ke liye pehle hamara Official Channel join karein:\n👉 {channel}",
            parse_mode="Markdown",
            reply_markup=kb
        )
        return False

# ---------------------------------------------------------
# ADMIN MAIN COMMAND HANDLER (/admin)
# ---------------------------------------------------------
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Authorized Admin Access Only!")
        return

    bot_status = get_setting("bot_status")
    channel = get_setting("force_channel") or "Not Set"

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # User Stats
    cursor.execute("SELECT COUNT(*), SUM(balance), SUM(wins), SUM(losses) FROM users")
    u_stats = cursor.fetchone()
    total_users = u_stats[0] or 0
    total_coins = u_stats[1] or 0.0
    total_wins = u_stats[2] or 0
    total_losses = u_stats[3] or 0

    cursor.execute("SELECT COUNT(*) FROM banned_users")
    banned_count = cursor.fetchone()[0] or 0

    # Financial Stats (Requests Table)
    cursor.execute("SELECT SUM(amount) FROM requests WHERE type='dep' AND status='approved'")
    tot_dep = cursor.fetchone()[0] or 0.0

    cursor.execute("SELECT SUM(amount) FROM requests WHERE type='dep' AND status='pending'")
    pend_dep = cursor.fetchone()[0] or 0.0

    cursor.execute("SELECT SUM(amount) FROM requests WHERE type='wd' AND status='approved'")
    tot_wd = cursor.fetchone()[0] or 0.0

    cursor.execute("SELECT SUM(amount) FROM requests WHERE type='wd' AND status='pending'")
    pend_wd = cursor.fetchone()[0] or 0.0

    conn.close()

    admin_text = (
        f"⚙️ *ADMIN CONTROL PANEL*\n\n"
        f"🤖 *Bot Status:* `{bot_status}`\n"
        f"📢 *Force Channel:* `{channel}`\n\n"
        f"👥 *USERS STATS*\n"
        f"• Total Users: `{total_users}`\n"
        f"• Banned Users: `{banned_count}`\n"
        f"• Total User Balance: `{total_coins} Coins` (₹{coins_to_inr(total_coins)})\n\n"
        f"🎮 *GAME STATS*\n"
        f"• Total Wins: `{total_wins}` | Total Losses: `{total_losses}`\n\n"
        f"💳 *FINANCE STATS*\n"
        f"• Total Deposits: `{tot_dep} Coins` (₹{coins_to_inr(tot_dep)})\n"
        f"• Pending Deposits: `{pend_dep} Coins` (₹{coins_to_inr(pend_dep)})\n"
        f"• Total Withdrawals: `{tot_wd} Coins` (₹{coins_to_inr(tot_wd)})\n"
        f"• Pending Withdrawals: `{pend_wd} Coins` (₹{coins_to_inr(pend_wd)})\n\n"
        f"📌 *COMMANDS LIST:*\n"
        f"`/addcoins <id> <coins>` - Add Balance\n"
        f"`/cutcoins <id> <coins>` - Cut Balance\n"
        f"`/ban <id>` - Ban User\n"
        f"`/unban <id>` - Unban User\n"
        f"`/user <id>` - Get Full User Details\n"
        f"`/setchannel <@username>` - Set Force Channel\n"
        f"`/boton` - Turn Bot ON\n"
        f"`/botoff` - Turn Bot OFF"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(text=f"🟢 Turn OFF Bot" if bot_status == "ON" else "🔴 Turn ON Bot", callback_data="toggle_bot_status")],
        [InlineKeyboardButton(text="🔄 Refresh Dashboard", callback_data="admin_refresh")]
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(admin_text, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(admin_text, parse_mode="Markdown", reply_markup=kb)

# ---------------------------------------------------------
# ADMIN COMMAND IMPLEMENTATIONS
# ---------------------------------------------------------
# Helper: User ko formatted balance dikhane ke liye
def format_bal(coins: float) -> str:
    inr = round(coins / 100.0, 2)
    return f"{int(coins)} Coins ({inr}₹)"

# Add Coins Command (Updated)
async def add_coins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: 
        return
    try:
        t_id, amt = int(context.args[0]), float(context.args[1])
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, t_id))
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (t_id,))
        row = cursor.fetchone()
        conn.commit()
        conn.close()

        if row:
            new_bal = row[0]
            # Admin ko confirmation message
            await update.message.reply_text(f"✅ Added `{amt} Coins` to `{t_id}`.\nNew Balance: `{format_bal(new_bal)}`", parse_mode="Markdown")
            
            # USER KO NOTIFICATION MESSAGE
            try:
                await context.bot.send_message(
                    chat_id=t_id,
                    text=f"💳 *BALANCE CREDITED!*\n\n`+{amt} Coins` added by Admin.\n💰 Updated Balance: `{format_bal(new_bal)}`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass  # Agar user ne bot block kiya hoga toh ignore karega
        else:
            await update.message.reply_text("❌ User ID not found in database!")
    except Exception:
        await update.message.reply_text("Usage: `/addcoins <user_id> <coins>`", parse_mode="Markdown")

# Cut Coins Command (Updated)
async def cut_coins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: 
        return
    try:
        t_id, amt = int(context.args[0]), float(context.args[1])
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = MAX(0, balance - ?) WHERE user_id = ?", (amt, t_id))
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (t_id,))
        row = cursor.fetchone()
        conn.commit()
        conn.close()

        if row:
            new_bal = row[0]
            # Admin ko confirmation message
            await update.message.reply_text(f"✂️ Deducted `{amt} Coins` from `{t_id}`.\nNew Balance: `{format_bal(new_bal)}`", parse_mode="Markdown")
            
            # USER KO NOTIFICATION MESSAGE
            try:
                await context.bot.send_message(
                    chat_id=t_id,
                    text=f"⚠️ *BALANCE DEDUCTED!*\n\n`-{amt} Coins` deducted by Admin.\n💰 Updated Balance: `{format_bal(new_bal)}`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        else:
            await update.message.reply_text("❌ User ID not found in database!")
    except Exception:
        await update.message.reply_text("Usage: `/cutcoins <user_id> <coins>`", parse_mode="Markdown")

async def ban_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        t_id = int(context.args[0])
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (t_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🚫 User `{t_id}` Banned successfully!", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("Usage: `/ban <user_id>`", parse_mode="Markdown")

async def unban_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        t_id = int(context.args[0])
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (t_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ User `{t_id}` Unbanned successfully!", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("Usage: `/unban <user_id>`", parse_mode="Markdown")

async def user_details_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        t_id = int(context.args[0])
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, name, balance, wins, losses FROM users WHERE user_id = ?", (t_id,))
        u = cursor.fetchone()
        
        if not u:
            await update.message.reply_text("❌ User Not Found!")
            conn.close()
            return

        cursor.execute("SELECT SUM(amount) FROM requests WHERE user_id = ? AND type='dep' AND status='approved'", (t_id,))
        dep = cursor.fetchone()[0] or 0.0
        cursor.execute("SELECT SUM(amount) FROM requests WHERE user_id = ? AND type='wd' AND status='approved'", (t_id,))
        wd = cursor.fetchone()[0] or 0.0
        conn.close()

        banned = is_user_banned(t_id)

        msg = (
            f"👤 *USER DETAILS:*\n\n"
            f"• ID: `{u[0]}`\n"
            f"• Name: `{u[1]}`\n"
            f"• Status: `{'🚫 BANNED' if banned else '🟢 ACTIVE'}`\n"
            f"• Balance: `{u[2]} Coins` (₹{coins_to_inr(u[2])})\n"
            f"• Total Wins: `{u[3]}` | Losses: `{u[4]}`\n"
            f"• Approved Deposits: `{dep} Coins` (₹{coins_to_inr(dep)})\n"
            f"• Approved Withdrawals: `{wd} Coins` (₹{coins_to_inr(wd)})"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("Usage: `/user <user_id>`", parse_mode="Markdown")

async def set_channel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        ch = context.args[0]
        if not ch.startswith("@"):
            ch = "@" + ch
        set_setting("force_channel", ch)
        await update.message.reply_text(f"📢 Force Channel set to: `{ch}`\nMake sure bot is ADMIN in this channel!", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("Usage: `/setchannel @channel_username`", parse_mode="Markdown")

async def bot_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    set_setting("bot_status", "ON")
    await update.message.reply_text("🟢 Bot is now **ON**!", parse_mode="Markdown")

async def bot_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    set_setting("bot_status", "OFF")
    await update.message.reply_text("🔴 Bot is now **OFF** (Maintenance Mode)!", parse_mode="Markdown")

# ---------------------------------------------------------
# CALLBACK QUERY HANDLER FOR ADMIN BUTTONS
# ---------------------------------------------------------
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    if data == "toggle_bot_status":
        curr = get_setting("bot_status")
        new_status = "OFF" if curr == "ON" else "ON"
        set_setting("bot_status", new_status)
        await query.answer(f"Bot Status changed to {new_status}")
        await admin_command(update, context)

    elif data == "admin_refresh":
        await query.answer("Refreshed!")
        await admin_command(update, context)

    elif data == "check_join_refresh":
        if await check_force_join(update, context):
            await query.edit_message_text("✅ Thank you for joining! Type /start to open menu.")
        else:
            await query.answer("❌ You have not joined the channel yet!", show_alert=True)

# ---------------------------------------------------------
# REGISTER HANDLERS FUNCTION (Main bot.py me import karne ke liye)
# ---------------------------------------------------------
def register_admin_handlers(app):
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("addcoins", add_coins_cmd))
    app.add_handler(CommandHandler("cutcoins", cut_coins_cmd))
    app.add_handler(CommandHandler("ban", ban_user_cmd))
    app.add_handler(CommandHandler("unban", unban_user_cmd))
    app.add_handler(CommandHandler("user", user_details_cmd))
    app.add_handler(CommandHandler("setchannel", set_channel_cmd))
    app.add_handler(CommandHandler("boton", bot_on_cmd))
    app.add_handler(CommandHandler("botoff", bot_off_cmd))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^(toggle_bot_status|admin_refresh|check_join_refresh)$"))
