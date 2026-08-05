import os
import random
import logging
import sqlite3
from typing import Union
from threading import Thread
from flask import Flask

from admin import register_admin_handlers, check_force_join, broadcast_cmd

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

# ---------------------------------------------------------
# KEEP ALIVE WEB SERVER (Render Sleep Fix For UptimeRobot)
# ---------------------------------------------------------
web_app = Flask('')

@web_app.route('/')
def home():
    return "Bot is alive and running 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

# Server start
keep_alive()
# ---------------------------------------------------------


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
DB_FILE = "/data/casino_bot.db"

# Ensure /data directory exists before creating DB
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

# Group / Channel ID jahan automatic screenshots jayenge (Apna Channel ID yahan daalein)
PROOF_CHANNEL_ID = int(os.environ.get("PROOF_CHANNEL_ID", "-1003580731079"))

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
            losses INTEGER DEFAULT 0,
            wager_required REAL DEFAULT 0.0,
            wager_done REAL DEFAULT 0.0
        )
    ''')
    
    # Check if columns exist for existing users (Data Safe keeping)
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN wager_required REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN wager_done REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass

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
    cursor.execute("SELECT user_id, name, balance, wins, losses, wager_required, wager_done FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        # NEW USER BONUS: 100 Coins Bonus & 500 Coins (5x) Wager
        initial_bal = 100.0
        initial_wager_req = 500.0  # 100 * 5
        cursor.execute(
            "INSERT INTO users (user_id, name, balance, wins, losses, wager_required, wager_done) VALUES (?, ?, ?, 0, 0, ?, 0.0)", 
            (user_id, name, initial_bal, initial_wager_req)
        )
        conn.commit()
        data = {
            "user_id": user_id, 
            "name": name, 
            "balance": initial_bal, 
            "wins": 0, 
            "losses": 0,
            "wager_required": initial_wager_req,
            "wager_done": 0.0
        }
    else:
        data = {
            "user_id": row[0], 
            "name": row[1], 
            "balance": row[2], 
            "wins": row[3], 
            "losses": row[4],
            "wager_required": row[5] if len(row) > 5 and row[5] is not None else 0.0,
            "wager_done": row[6] if len(row) > 6 and row[6] is not None else 0.0
        }
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

def update_wager_progress(user_id: int, bet_amount: float):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET wager_done = wager_done + ? WHERE user_id = ?", 
        (bet_amount, user_id)
    )
    conn.commit()
    conn.close()

def add_deposit_with_wager(user_id: int, deposit_amt: float):
    bonus_amt = deposit_amt * 0.10  # 10% Extra Bonus
    total_credit = deposit_amt + bonus_amt
    
    # Wager logic: Deposit ka 1x + Bonus ka 5x
    added_wager = (deposit_amt * 1.0) + (bonus_amt * 5.0)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET balance = balance + ?, wager_required = wager_required + ? WHERE user_id = ?",
        (total_credit, added_wager, user_id)
    )
    conn.commit()
    conn.close()
    return total_credit, bonus_amt, added_wager

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
            InlineKeyboardButton(text="🪙 Head & Tail", callback_data="menu_ht_type"),
            InlineKeyboardButton(text="🎰 Slot Machine", callback_data="menu_slot_type")
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
    win_roll = random.random() < 0.15  # 20% Chance Win

    if bet_type == "BIG":
        winning_outcomes, losing_outcomes = [4, 5, 6],[1,2,3]
    elif bet_type == "SMALL":
        winning_outcomes, losing_outcomes = [1, 2, 3],[4,5,6]
    else:
        target = int(selected_val)
        winning_outcomes = [target]
        losing_outcomes = [i for i in range(1, 7) if i != target]

    return random.choice(winning_outcomes) if win_roll else random.choice(losing_outcomes)

# Head/Tail Logic (20% Win)
def calculate_rigged_ht(user_choice: str) -> str:
    win_roll = random.random() < 0.20  # 20% Win Chance
    if win_roll:
        return user_choice
    return "TAIL" if user_choice == "HEAD" else "HEAD"

# Slot Machine Logic (20% Win)
# Telegram Slot values: 1, 22, 43, 64 correspond to Jackpot 777 wins
def calculate_rigged_slot() -> tuple[bool, int]:
    win_roll = random.random() < 0.20
    if win_roll:
        return True, random.choice([1, 22, 43, 64])  # Winning slot outcomes
    else:
        # Non-winning outcomes
        losing_vals = [i for i in range(1, 65) if i not in [1, 22, 43, 64]]
        return False, random.choice(losing_vals)

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
        # 1. SECURITY CHECK: Strictly check Admin ID
        if user_id != ADMIN_ID:
            await query.answer("❌ Unauthorized! Only Admin can approve/reject requests.", show_alert=True)
            return

        _, action, rtype, req_id_str = data.split("_")
        req_id = int(req_id_str)

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, amount FROM requests WHERE id = ? AND status = 'pending'", (req_id,))
        req = cursor.fetchone()
        conn.close()

        if not req:
            msg_text = "❌ Request already processed."
            if query.message.photo:
                await query.edit_message_caption(msg_text)
            else:
                await query.edit_message_text(msg_text)
            return

        target_u, amt = req[0], req[1]

        # ==================== APPROVE ACTION ====================
        if action == "app":
            # --- DEPOSIT APPROVAL ---
            if rtype == "dep":
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute("UPDATE requests SET status = 'approved' WHERE id = ?", (req_id,))
                conn.commit()
                conn.close()

                total_credited, bonus_given, added_wager = add_deposit_with_wager(target_u, amt)
                u_data = get_user_data(target_u)

                admin_txt = (
                    f"✅ *DEPOSIT APPROVED!*\n\n"
                    f"🆔 *User ID:* `{target_u}`\n"
                    f"💵 *Amount:* `{format_bal(amt)}`\n"
                    f"🎁 *10% Bonus:* `{format_bal(bonus_given)}`\n"
                    f"🎯 *Wager Added:* `{added_wager:.1f} Coins`\n"
                    f"💰 *New Balance:* `{format_bal(u_data['balance'])}`\n"
                    f"⚡ *Status:* Approved"
                )

                user_txt = (
                    f"🎉 *DEPOSIT APPROVED!*\n\n"
                    f"🆔 *User ID:* `{target_u}`\n"
                    f"💵 *Amount:* `{format_bal(amt)}`\n"
                    f"🎁 *Bonus:* `{format_bal(bonus_given)}` (10%)\n"
                    f"🎯 *Wager Added:* `{added_wager:.1f} Coins`\n"
                    f"💰 *New Balance:* `{format_bal(u_data['balance'])}`\n"
                    f"✅ *Status:* Successful!"
                )

                proof_txt = (
                    f"🟢 *DEPOSIT APPROVED PROOF* 🟢\n\n"
                    f"🆔 *User ID:* `{target_u}`\n"
                    f"💵 *Amount Deposited:* `{format_bal(amt)}`\n"
                    f"🎁 *Bonus Credited:* `{format_bal(bonus_given)}`\n"
                    f"💰 *User Balance:* `{format_bal(u_data['balance'])}`\n"
                    f"⚡ *Status:* Approved ✅"
                )

                # Send User Msg
                try:
                    await context.bot.send_message(chat_id=target_u, text=user_txt, parse_mode="Markdown")
                except Exception:
                    pass

                # Send Photo & Proof to Group
                if query.message.photo:
                    await query.edit_message_caption(admin_txt, parse_mode="Markdown")
                    try:
                        photo_id = query.message.photo[-1].file_id
                        await context.bot.send_photo(chat_id=PROOF_CHANNEL_ID, photo=photo_id, caption=proof_txt, parse_mode="Markdown")
                    except Exception as e:
                        print(f"Group Error: {e}")
                else:
                    await query.edit_message_text(admin_txt, parse_mode="Markdown")

            # --- WITHDRAW APPROVAL (Ask Admin Screenshot) ---
            elif rtype == "wd":
                context.user_data['admin_state'] = 'AWAITING_WD_PROOF'
                context.user_data['wd_req_id'] = req_id
                context.user_data['wd_target_u'] = target_u
                context.user_data['wd_amt'] = amt

                prompt_txt = (
                    f"📸 *PAYMENT PROOF REQUIRED*\n\n"
                    f"🆔 *User ID:* `{target_u}`\n"
                    f"💸 *Withdraw Amount:* `{format_bal(amt)}`\n\n"
                    f"👉 *Kripya Payment Screenshot (Photo) yahan bhejein:* User aur Group me bhejney ke liye."
                )

                if query.message.photo:
                    await query.edit_message_caption(prompt_txt, parse_mode="Markdown")
                else:
                    await query.edit_message_text(prompt_txt, parse_mode="Markdown")

        # ==================== REJECT ACTION ====================
        elif action == "rej":
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("UPDATE requests SET status = 'rejected' WHERE id = ?", (req_id,))
            conn.commit()
            conn.close()

            # --- WITHDRAW REJECT ---
            if rtype == "wd":
                update_balance(target_u, amt) # Refund Coins
                u_data = get_user_data(target_u)

                user_txt = (
                    f"❌ *WITHDRAWAL REJECTED*\n\n"
                    f"🆔 *User ID:* `{target_u}`\n"
                    f"💸 *Amount:* `{format_bal(amt)}`\n"
                    f"💰 *Refunded Balance:* `{format_bal(u_data['balance'])}`\n"
                    f"⚠️ *Status:* Rejected (Amount Credited back to balance)"
                )

                proof_txt = (
                    f"🔴 *WITHDRAWAL REJECTED PROOF* 🔴\n\n"
                    f"🆔 *User ID:* `{target_u}`\n"
                    f"💸 *Requested Amount:* `{format_bal(amt)}`\n"
                    f"⚡ *Status:* Rejected & Refunded ❌"
                )

            # --- DEPOSIT REJECT ---
            else:
                u_data = get_user_data(target_u)
                user_txt = (
                    f"❌ *DEPOSIT REJECTED*\n\n"
                    f"🆔 *User ID:* `{target_u}`\n"
                    f"💵 *Deposit Amount:* `{format_bal(amt)}`\n"
                    f"💰 *Balance:* `{format_bal(u_data['balance'])}`\n"
                    f"⚠️ *Reason:* Invalid Transaction or Payment Proof"
                )

                proof_txt = (
                    f"🔴 *DEPOSIT REJECTED PROOF* 🔴\n\n"
                    f"🆔 *User ID:* `{target_u}`\n"
                    f"💵 *Attempted Amount:* `{format_bal(amt)}`\n"
                    f"⚡ *Status:* Rejected / Invalid Payment ❌"
                )

            # Send Notification to User
            try:
                await context.bot.send_message(chat_id=target_u, text=user_txt, parse_mode="Markdown")
            except Exception:
                pass

            # Send Reject Proof to Group
            try:
                await context.bot.send_message(chat_id=PROOF_CHANNEL_ID, text=proof_txt, parse_mode="Markdown")
            except Exception as e:
                print(f"Group Reject Send Error: {e}")

            admin_rej_txt = f"❌ *REQUEST REJECTED*\n\n🆔 User ID: `{target_u}` | Amount: `{format_bal(amt)}`"
            if query.message.photo:
                await query.edit_message_caption(admin_rej_txt, parse_mode="Markdown")
            else:
                await query.edit_message_text(admin_rej_txt, parse_mode="Markdown")
        return



    # Head & Tail Menu
    if data == "menu_ht_type":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(text="🪙 HEAD", callback_data="play_bet_HEAD"),
             InlineKeyboardButton(text="🪙 TAIL", callback_data="play_bet_TAIL")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="back_main")]
        ])
        await query.edit_message_text("🪙 Choose HEAD or TAIL:", reply_markup=kb)
        return

    # Slot Machine Menu
    if data == "menu_slot_type":
        context.user_data['game_type'] = 'SLOT'
        context.user_data['state'] = 'AWAITING_BET_AMOUNT'
        await query.edit_message_text(
            f"🎰 *SLOT MACHINE BET*\n\n"
            f"• Min Bet: `100 Coins (1₹)`\n"
            f"• Max Bet: `1000 Coins (10₹)`\n"
            f"• Your Balance: `{format_bal(bal)}`",
            parse_mode="Markdown"
        )
        return

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
                await update.message.reply_text("❌ Minimum deposit amount `100 Coins (1₹)` hai!", parse_mode="Markdown")
                return

            context.user_data['dep_amount'] = amt
            context.user_data['state'] = 'AWAITING_DEP_SCREENSHOT'

            text = (
                f"💳 *DEPOSIT DETAILS*\n\n"
                f"• Amount: `{format_bal(amt)}`\n"
                f"• Send Money To UPI: `{UPI_ID}`\n\n"
                f"📸 *Step 2:* Payment karne ke baad screenshot (Photo) is chat me bhejein."
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
        
    # 3. Withdraw Step 1: Input Amount & Wager Check
    if state == 'AWAITING_WD_AMOUNT' and update.message.text:
        try:
            amt = float(update.message.text.strip())
            u_data = get_user_data(user.id)
            bal = u_data['balance']
            w_req = u_data['wager_required']
            w_done = u_data['wager_done']

            # Calculate Remaining Wager
            w_remaining = max(0.0, w_req - w_done)

            # Check Wager Status
            if w_remaining > 0:
                progress_pct = min(100.0, (w_done / w_req) * 100) if w_req > 0 else 100
                msg_txt = (
                    f"🚫 *WITHDRAWAL LOCKED!*\n\n"
                    f"Aapka Wager Requirement abhi baki hai.\n\n"
                    f"📊 *Wager Status:*\n"
                    f"• Target Wager: `{w_req:.1f} Coins`\n"
                    f"• Completed: `{w_done:.1f} Coins` ({progress_pct:.1f}%)\n"
                    f"• *Remaining Required:* `{w_remaining:.1f} Coins` ⚠️\n\n"
                    f"💡 *Note:* Withdraw karne ke liye aapko `{w_remaining:.1f} Coins` ki aur bets khelni hongi!"
                )
                await update.message.reply_text(msg_txt, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
                context.user_data.clear()
                return

            if amt < 100:
                await update.message.reply_text("❌ Minimum withdrawal amount `100 Coins (1₹)` hai!")
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
        amt = context.user_data.get('wd_amount', 100.0)
        u_data = get_user_data(user.id)
        bal = u_data['balance']

        if amt > bal:
            await update.message.reply_text("❌ Insufficient balance!")
            context.user_data.clear()
            return

        try:
            # Deduct balance temporarily
            update_balance(user.id, -amt)

            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            # Fail-safe: Missing columns check & add
            try:
                cursor.execute("ALTER TABLE requests ADD COLUMN details TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            try:
                cursor.execute("ALTER TABLE requests ADD COLUMN status TEXT DEFAULT 'pending'")
            except sqlite3.OperationalError:
                pass  # Column already exists

            cursor.execute(
                "INSERT INTO requests (user_id, type, amount, details, status) VALUES (?, 'wd', ?, ?, 'pending')",
                (user.id, amt, upi_details)
            )
            req_id = cursor.lastrowid
            conn.commit()
            conn.close()

            # Inline keyboard for Admin approval
            admin_kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_wd_{req_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_wd_{req_id}")
                ]
            ])

            # Send Notification to Admin
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🏧 *NEW WITHDRAWAL REQUEST*\n\n"
                    f"🆔 *User ID:* `{user.id}`\n"
                    f"💸 *Amount:* `{format_bal(amt)}`\n"
                    f"📲 *UPI ID:* `{upi_details}`"
                ),
                parse_mode="Markdown",
                reply_markup=admin_kb
            )

            context.user_data.clear()
            await update.message.reply_text("✅ *Withdrawal Request Sent to Admin!*", parse_mode="Markdown", reply_markup=get_main_menu_keyboard())

        except Exception as e:
            print(f"Withdrawal Error: {e}")
            await update.message.reply_text(f"⚠️ *Withdrawal Error:* `{str(e)}`", parse_mode="Markdown")
        return

    # 5. Dynamic Bet Processing Handler (Dice, Head/Tail, Slot)
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

            # Wager count update
            update_wager_progress(user.id, bet_amt)

            bet_type = context.user_data.get('game_type')
            target_val = context.user_data.get('game_target')

            is_win = False
            result_display = ""

            # ----------------- HEAD & TAIL -----------------
            if bet_type in ["HEAD", "TAIL"]:
                outcome_ht = calculate_rigged_ht(bet_type)
                if outcome_ht == bet_type:
                    is_win = True
                result_display = f"🪙 Coin Result: *{outcome_ht}*"

            # ----------------- SLOT MACHINE -----------------
            elif bet_type == "SLOT":
                is_win, slot_val = calculate_rigged_slot()
                # Slot Machine animation send karein
                await context.bot.send_dice(chat_id=update.effective_chat.id, emoji="🎰")
                result_display = "🎰 Slot Machine Rolled!"

            # ----------------- DICE GAME -----------------
            else:
                outcome_dice = calculate_rigged_dice(bet_type, target_val)
                result_display = f"🎲 Dice Rolled Value: `{outcome_dice}`"
                if bet_type == "BIG" and outcome_dice in [4, 5, 6]:
                    is_win = True
                elif bet_type == "SMALL" and outcome_dice in [1, 2, 3]:
                    is_win = True
                elif bet_type == "EXACT" and outcome_dice == int(target_val):
                    is_win = True

            # Process Win/Loss
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
                f"{result_display}\n{result_txt}\n\n💰 Updated Balance: `{format_bal(new_bal)}`",
                parse_mode="Markdown",
                reply_markup=get_main_menu_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ Valid number daalein (e.g. 100)!")
        return

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    state = context.user_data.get('state')
    admin_state = context.user_data.get('admin_state')

    # ==================== 1. USER DEPOSIT SCREENSHOT HANDLER ====================
    if state == 'AWAITING_DEP_SCREENSHOT':
        amt = context.user_data.get('dep_amount', 100.0)
        photo_id = update.message.photo[-1].file_id

        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            # Fail-safe missing columns check
            try:
                cursor.execute("ALTER TABLE requests ADD COLUMN details TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE requests ADD COLUMN status TEXT DEFAULT 'pending'")
            except sqlite3.OperationalError:
                pass

            cursor.execute(
                "INSERT INTO requests (user_id, type, amount, details, status) VALUES (?, 'dep', ?, 'screenshot', 'pending')",
                (user.id, amt)
            )
            req_id = cursor.lastrowid
            conn.commit()
            conn.close()

            # Admin Buttons for Deposit Request
            admin_kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_dep_{req_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_dep_{req_id}")
                ]
            ])

            # Send Deposit Screenshot & Details to Admin
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=photo_id,
                caption=(
                    f"💳 *NEW DEPOSIT REQUEST*\n\n"
                    f"🆔 *User ID:* `{user.id}` ({user.first_name})\n"
                    f"💵 *Amount:* `{format_bal(amt)}`\n"
                    f"📸 *Payment Screenshot Attached*"
                ),
                parse_mode="Markdown",
                reply_markup=admin_kb
            )

            context.user_data.clear()
            await update.message.reply_text(
                "✅ *Deposit Screenshot sent to Admin for approval!*",
                parse_mode="Markdown",
                reply_markup=get_main_menu_keyboard()
            )

        except Exception as e:
            print(f"Deposit Photo Error: {e}")
            await update.message.reply_text(f"⚠️ *Deposit Error:* `{str(e)}`", parse_mode="Markdown")
        return

    # ==================== 2. ADMIN WITHDRAWAL PROOF SCREENSHOT HANDLER ====================
    if user.id == ADMIN_ID and admin_state == 'AWAITING_WD_PROOF':
        req_id = context.user_data.get('wd_req_id')
        target_u = context.user_data.get('wd_target_u')
        amt = context.user_data.get('wd_amt')
        photo_file_id = update.message.photo[-1].file_id

        # Update DB Request Status
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE requests SET status = 'approved' WHERE id = ?", (req_id,))
        conn.commit()
        conn.close()

        u_data = get_user_data(target_u)

        # User Text
        user_txt = (
            f"🎉 *WITHDRAWAL SUCCESSFUL!*\n\n"
            f"🆔 *User ID:* `{target_u}`\n"
            f"💸 *Withdraw Amount:* `{format_bal(amt)}`\n"
            f"💰 *Remaining Balance:* `{format_bal(u_data['balance'])}`\n"
            f"✅ *Status:* Approved & Paid"
        )

        # Proof Group Text
        proof_txt = (
            f"🔴 *WITHDRAWAL SUCCESS PROOF* 🔴\n\n"
            f"🆔 *User ID:* `{target_u}`\n"
            f"💸 *Amount Paid:* `{format_bal(amt)}`\n"
            f"💰 *User Balance:* `{format_bal(u_data['balance'])}`\n"
            f"⚡ *Status:* Approved ✅"
        )

        # Send Photo to User
        try:
            await context.bot.send_photo(chat_id=target_u, photo=photo_file_id, caption=user_txt, parse_mode="Markdown")
        except Exception as e:
            print(f"Error sending photo to user: {e}")

        # Send Photo to Proof Channel
        try:
            await context.bot.send_photo(chat_id=PROOF_CHANNEL_ID, photo=photo_file_id, caption=proof_txt, parse_mode="Markdown")
        except Exception as e:
            print(f"Error sending photo to proof channel: {e}")

        await update.message.reply_text("✅ *Withdrawal Approved! Proof Screenshot sent to User and Group!*", parse_mode="Markdown")
        context.user_data.clear()
        return

# ---------------------------------------------------------
# 7. MAIN ENTRYPOINT
# ---------------------------------------------------------
if __name__ == '__main__':
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set!")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # 1. Base Commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    # 2. Callbacks
    app.add_handler(CallbackQueryHandler(callback_handler))

    # 3. Photo Handler (Withdrawal Proof Screenshot ke liye)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # 4. Text Handler (Game Bets & Normal Messages ke liye)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))

    # 5. Register Admin Handlers (Isse /admin Command aur Admin Panel chalega!)
    register_admin_handlers(app)

    print("⚡ Bot successfully started with all requested fixes...")
    app.run_polling()
