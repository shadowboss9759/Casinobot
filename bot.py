import os
import random
import logging
import sqlite3
from typing import Union
from admin import register_admin_handlers, check_force_join

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Config Configs (Environment variables se ya Direct Value)
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))  # Yahan apni Admin Telegram ID daalein
UPI_ID = os.environ.get("UPI_ID", "kingdipak@fam")  # Yahan apna UPI ID daalein

# ---------------------------------------------------------
# 1. IN-BUILT SQLITE DATABASE SETUP
# ---------------------------------------------------------
DB_FILE = "casino_bot.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            balance REAL DEFAULT 500.0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0
        )
    ''')
    # Requests Table (Deposit / Withdraw)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            amount REAL,
            details TEXT,
            status TEXT DEFAULT 'pending'
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_user_data(user_id: int, name: str = "User"):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name, balance, wins, losses FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, name, balance, wins, losses) VALUES (?, ?, 500.0, 0, 0)", (user_id, name))
        conn.commit()
        data = {"user_id": user_id, "name": name, "balance": 500.0, "wins": 0, "losses": 0}
    else:
        data = {"user_id": row[0], "name": row[1], "balance": row[2], "wins": row[3], "losses": row[4]}
    conn.close()
    return data

def update_balance(user_id: int, amount: float):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    new_bal = cursor.fetchone()[0]
    conn.close()
    return new_bal

def update_stats(user_id: int, is_win: bool):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if is_win:
        cursor.execute("UPDATE users SET wins = wins + 1 WHERE user_id = ?", (user_id,))
    else:
        cursor.execute("UPDATE users SET losses = losses + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# ---------------------------------------------------------
# 2. KEYBOARDS
# ---------------------------------------------------------
def get_main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="🎲 Roll Dice (Big/Small)", callback_data="menu_dice_type"),
            InlineKeyboardButton(text="🎯 Roll Exact Number", callback_data="menu_dice_exact")
        ],
        [
            InlineKeyboardButton(text="💳 Deposit Cash", callback_data="action_deposit"),
            InlineKeyboardButton(text="🏧 Withdraw Cash", callback_data="action_withdraw")
        ],
        [
            InlineKeyboardButton(text="💰 My Balance", callback_data="action_balance"),
            InlineKeyboardButton(text="📊 Profile / Stats", callback_data="action_stats")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard(req_id: int, req_type: str):
    keyboard = [
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"adm_app_{req_type}_{req_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_rej_{req_type}_{req_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------------------------------------------------------
# 3. COMMAND HANDLERS
# ---------------------------------------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user_data(user.id, user.first_name)
    
    welcome_text = (
        f"👑 *Welcome to Casino Royals, {user.first_name}!*\n\n"
        f"💰 *Welcome Bonus:* `500 Coins` added to your wallet!\n\n"
        f"Choose an option below to start playing:"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard()
    )

async def admin_panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ You are not authorized to view the admin panel.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), SUM(balance) FROM users")
    row = cursor.fetchone()
    conn.close()

    total_users = row[0] or 0
    total_vault = row[1] or 0.0

    text = (
        f"🛠 *ADMIN PANEL MANAGER*\n\n"
        f"👥 *Total Registered Users:* `{total_users}`\n"
        f"💵 *Total User Balance Pool:* `{total_vault} Coins`\n\n"
        f"Commands:\n"
        f"`/addcoins <user_id> <amount>` - Add balance\n"
        f"`/cutcoins <user_id> <amount>` - Deduct balance"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def add_coins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        target_id = int(context.args[0])
        amount = float(context.args[1])
        new_bal = update_balance(target_id, amount)
        await update.message.reply_text(f"✅ Added {amount} coins to User `{target_id}`. New Balance: `{new_bal}`")
    except Exception:
        await update.message.reply_text("Usage: `/addcoins <user_id> <amount>`", parse_mode="Markdown")

# ---------------------------------------------------------
# 4. RIGGED GAME LOGIC (20% WIN / 80% LOSS)
# ---------------------------------------------------------
def calculate_rigged_dice(bet_type: str, selected_val: Union[str, int]) -> int:
    win_roll = random.random() < 0.20  # 20% Chance Win

    if bet_type == "BIG":
        winning_outcomes, losing_outcomes = [4, 5, 6], [1, 2, 3]
    elif bet_type == "SMALL":
        winning_outcomes, losing_outcomes = [1, 2, 3], [4, 5, 6]
    else:
        target = int(selected_val)
        winning_outcomes = [target]
        losing_outcomes = [i for i in range(1, 7) if i != target]

    return random.choice(winning_outcomes) if win_roll else random.choice(losing_outcomes)

# ---------------------------------------------------------
# 5. CALLBACK HANDLERS
# ---------------------------------------------------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_id = user.id
    data = query.data
    
    u_data = get_user_data(user_id, user.first_name)
    bal = u_data['balance']

    if data == "action_balance":
        await query.edit_message_text(
            f"💰 *Wallet Balance:* `{bal} Coins`",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard()
        )
        return

    if data == "action_stats":
        text = (
            f"👤 *Player Profile:* {user.first_name}\n"
            f"🆔 *ID:* `{user_id}`\n"
            f"💰 *Balance:* `{bal} Coins`\n"
            f"🟢 *Wins:* `{u_data['wins']}` | 🔴 *Losses:* `{u_data['losses']}`"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
        return

    if data == "action_deposit":
        context.user_data['state'] = 'AWAITING_DEPOSIT'
        text = (
            f"💳 *DEPOSIT MONEY*\n\n"
            f"Send money to UPI ID: `{UPI_ID}`\n\n"
            f"📸 *Step 2:* Send payment screenshot in this chat."
        )
        await query.edit_message_text(text, parse_mode="Markdown")
        return

    if data == "action_withdraw":
        if bal < 100:
            await query.edit_message_text("❌ Minimum withdrawal amount is 100 Coins!", reply_markup=get_main_menu_keyboard())
            return
        context.user_data['state'] = 'AWAITING_WITHDRAW_DETAILS'
        await query.edit_message_text("🏧 *ENTER WITHDRAWAL DETAILS*\n\nReply with your `UPI_ID Amount` (e.g. `user@upi 200`)", parse_mode="Markdown")
        return

    if data == "menu_dice_type":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(text="🔴 BIG (4, 5, 6)", callback_data="play_bet_BIG"),
             InlineKeyboardButton(text="🔵 SMALL (1, 2, 3)", callback_data="play_bet_SMALL")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="back_main")]
        ])
        await query.edit_message_text("🎲 Choose your Bet Option (Bet fixed at 100 Coins):", reply_markup=kb)
        return

    if data == "menu_dice_exact":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(text="1", callback_data="play_bet_EXACT_1"),
             InlineKeyboardButton(text="2", callback_data="play_bet_EXACT_2"),
             InlineKeyboardButton(text="3", callback_data="play_bet_EXACT_3")],
            [InlineKeyboardButton(text="4", callback_data="play_bet_EXACT_4"),
             InlineKeyboardButton(text="5", callback_data="play_bet_EXACT_5"),
             InlineKeyboardButton(text="6", callback_data="play_bet_EXACT_6")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="back_main")]
        ])
        await query.edit_message_text("🎯 Select Exact Target Number (Bet 100 Coins):", reply_markup=kb)
        return

    if data == "back_main":
        await query.edit_message_text("Main Menu:", reply_markup=get_main_menu_keyboard())
        return

    # Bet Execution
    if data.startswith("play_bet_"):
        BET_AMOUNT = 100
        if bal < BET_AMOUNT:
            await query.edit_message_text("❌ Insufficient Balance! Please Deposit.", reply_markup=get_main_menu_keyboard())
            return

        parts = data.split("_")
        bet_type = parts[2]
        target_val = parts[3] if len(parts) > 3 else None

        outcome_dice = calculate_rigged_dice(bet_type, target_val)

        # Animated Dice
        await context.bot.send_dice(chat_id=query.message.chat_id, emoji="🎲")

        is_win = False
        if bet_type == "BIG" and outcome_dice in [4, 5, 6]:
            is_win = True
        elif bet_type == "SMALL" and outcome_dice in [1, 2, 3]:
            is_win = True
        elif bet_type == "EXACT" and outcome_dice == int(target_val):
            is_win = True

        if is_win:
            win_amt = BET_AMOUNT * 2
            new_bal = update_balance(user_id, win_amt - BET_AMOUNT)
            update_stats(user_id, True)
            result_txt = f"🎉 *YOU WON!* (+{win_amt} Coins)"
        else:
            new_bal = update_balance(user_id, -BET_AMOUNT)
            update_stats(user_id, False)
            result_txt = f"💔 *YOU LOST!* (-{BET_AMOUNT} Coins) 🤣"

        await query.message.reply_text(
            f"🎲 *Dice Rolled Value:* `{outcome_dice}`\n{result_txt}\n\n💰 Updated Balance: `{new_bal} Coins`",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard()
        )

    # Admin Request Handling
    if data.startswith("adm_"):
        if user_id != ADMIN_ID:
            return
        _, action, rtype, req_id_str = data.split("_")
        req_id = int(req_id_str)

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, amount FROM requests WHERE id = ? AND status = 'pending'", (req_id,))
        req = cursor.fetchone()

        if not req:
            await query.edit_message_caption("❌ Request already processed.") if query.message.photo else await query.edit_message_text("❌ Request already processed.")
            conn.close()
            return

        target_u, amt = req[0], req[1]

        if action == "app":
            cursor.execute("UPDATE requests SET status = 'approved' WHERE id = ?", (req_id,))
            conn.commit()
            conn.close()
            
            if rtype == "dep":
                update_balance(target_u, 500)  # Default 500 credit
                await context.bot.send_message(target_u, "✅ Your Deposit of 500 Coins has been Approved!")
            else:
                await context.bot.send_message(target_u, f"✅ Your Withdrawal of {amt} Coins has been Processed!")

            if query.message.photo:
                await query.edit_message_caption("✅ Approved!")
            else:
                await query.edit_message_text("✅ Approved!")

        else:
            cursor.execute("UPDATE requests SET status = 'rejected' WHERE id = ?", (req_id,))
            conn.commit()
            conn.close()

            if rtype == "wd":
                update_balance(target_u, amt)  # Refund
                await context.bot.send_message(target_u, f"❌ Your Withdrawal request was Rejected. Balance Refunded!")
            else:
                await context.bot.send_message(target_u, "❌ Your Deposit request was Rejected.")

            if query.message.photo:
                await query.edit_message_caption("❌ Rejected!")
            else:
                await query.edit_message_text("❌ Rejected!")

# ---------------------------------------------------------
# 6. MESSAGE HANDLERS
# ---------------------------------------------------------
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    state = context.user_data.get('state')

    # Deposit Photo
    if state == 'AWAITING_DEPOSIT' and update.message.photo:
        photo_id = update.message.photo[-1].file_id

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO requests (user_id, type, amount, details) VALUES (?, 'dep', 500, 'screenshot')", (user.id,))
        req_id = cursor.lastrowid
        conn.commit()
        conn.close()

        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_id,
            caption=f"💳 *NEW DEPOSIT REQUEST*\nUser: {user.first_name} (`{user.id}`)",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard(req_id, "dep")
        )
        context.user_data['state'] = None
        await update.message.reply_text("✅ Screenshot sent to Admin for approval!", reply_markup=get_main_menu_keyboard())
        return

    # Withdraw Text
    if state == 'AWAITING_WITHDRAW_DETAILS' and update.message.text:
        try:
            upi_details, amt_str = update.message.text.split()
            amount = float(amt_str)
            bal = get_user_data(user.id)['balance']

            if amount > bal or amount < 100:
                await update.message.reply_text("❌ Invalid Amount or Insufficient Balance!")
                return

            update_balance(user.id, -amount)

            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO requests (user_id, type, amount, details) VALUES (?, 'wd', ?, ?)", (user.id, amount, upi_details))
            req_id = cursor.lastrowid
            conn.commit()
            conn.close()

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🏧 *NEW WITHDRAWAL REQUEST*\nUser: `{user.id}`\nAmount: `{amount} Coins`\nUPI: `{upi_details}`",
                parse_mode="Markdown",
                reply_markup=get_admin_keyboard(req_id, "wd")
            )
            context.user_data['state'] = None
            await update.message.reply_text("✅ Withdrawal Request Sent to Admin!", reply_markup=get_main_menu_keyboard())
        except Exception:
            await update.message.reply_text("❌ Send details like this: `yourupi@upi 200`", parse_mode="Markdown")

# ---------------------------------------------------------
# 7. MAIN ENTRYPOINT
# ---------------------------------------------------------
if __name__ == '__main__':
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set!")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("admin", admin_panel_cmd))
    app.add_handler(CommandHandler("addcoins", add_coins_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, handle_messages))

    print("⚡ Bot chal raha hai bina kisi Firebase ke...")
    app.run_polling()
