import os
import json
import random
import logging
from typing import Union

import firebase_admin
from firebase_admin import credentials, db

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
# 1. FIREBASE INITIALIZATION (Crash-Proof Version)
# ---------------------------------------------------------
FIREBASE_JSON_PATH = os.environ.get("FIREBASE_JSON_PATH", "firebase_credentials.json")
DATABASE_URL = os.environ.get("FIREBASE_DB_URL", "https://your-firebase-db-url.firebaseio.com/")

if not firebase_admin._apps:
    if os.path.exists(FIREBASE_JSON_PATH):
        cred = credentials.Certificate(FIREBASE_JSON_PATH)
    else:
        fb_config_str = os.environ.get("FIREBASE_CONFIG_JSON")
        if fb_config_str:
            fb_config = json.loads(fb_config_str)
            cred = credentials.Certificate(fb_config)
        else:
            raise ValueError(
                "❌ Firebase Credentials nahi mile! Ya toh 'firebase_credentials.json' file "
                "GitHub par upload karein ya Render me 'FIREBASE_CONFIG_JSON' environment variable set karein."
            )
        
    firebase_admin.initialize_app(cred, {
        'databaseURL': DATABASE_URL
    })


# Config Configs
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789")) # Apni Admin Telegram ID yahan rakhein
UPI_ID = os.environ.get("UPI_ID", "yourupi@upi")

# Firebase DB References
users_ref = db.reference('users')
deposits_ref = db.reference('deposits')
withdraws_ref = db.reference('withdraws')

# ---------------------------------------------------------
# 2. HELPER DATABASE FUNCTIONS
# ---------------------------------------------------------
def get_user_data(user_id: int, name: str = "User"):
    u_ref = users_ref.child(str(user_id))
    data = u_ref.get()
    if not data:
        data = {
            "name": name,
            "balance": 500,  # Starting Signup bonus
            "total_bet": 0,
            "wins": 0,
            "losses": 0
        }
        u_ref.set(data)
    return data

def update_balance(user_id: int, amount: float):
    u_ref = users_ref.child(str(user_id))
    curr = u_ref.child('balance').get() or 0
    new_bal = curr + amount
    u_ref.update({'balance': new_bal})
    return new_bal

# ---------------------------------------------------------
# 3. CUSTOM UI KEYBOARDS (Inline Emoji & Custom Syntax)
# ---------------------------------------------------------
# Custom Keyboard helper simulating telegram emoji custom formatting
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

def get_admin_keyboard(req_id: str, req_type: str):
    # Success & Primary action buttons for admin review
    keyboard = [
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"adm_app_{req_type}_{req_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"adm_rej_{req_type}_{req_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------------------------------------------------------
# 4. BOT COMMAND HANDLERS
# ---------------------------------------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user_data(user.id, user.first_name)
    
    welcome_text = (
        f"👑 *Welcome to Casino Royals, {user.first_name}!*\n\n"
        f"💰 *Welcome Bonus:* `500 Coins` added to your wallet!\n\n"
        f"Choose an option below to start playing in PM or Group:"
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

    all_users = users_ref.get() or {}
    total_users = len(all_users)
    total_vault = sum([u.get('balance', 0) for u in all_users.values()])

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
# 5. RIGGED DICE GAME LOGIC (20% WIN / 80% LOSS)
# ---------------------------------------------------------
def calculate_rigged_dice(bet_type: str, selected_val: Union[str, int]) -> int:
    """
    Forces 80% loss probability and 20% win probability
    """
    win_roll = False
    # 20% Chance to win
    if random.random() < 0.20:
        win_roll = True

    if bet_type == "BIG":
        # Big = 4, 5, 6
        winning_outcomes = [4, 5, 6]
        losing_outcomes = [1, 2, 3]
    elif bet_type == "SMALL":
        # Small = 1, 2, 3
        winning_outcomes = [1, 2, 3]
        losing_outcomes = [4, 5, 6]
    else: # Exact Number (1 to 6)
        target = int(selected_val)
        winning_outcomes = [target]
        losing_outcomes = [i for i in range(1, 7) if i != target]

    if win_roll:
        return random.choice(winning_outcomes)
    else:
        return random.choice(losing_outcomes)

# ---------------------------------------------------------
# 6. CALLBACK QUERY HANDLERS (Inline Buttons)
# ---------------------------------------------------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_id = user.id
    data = query.data
    
    u_data = get_user_data(user_id, user.first_name)
    bal = u_data.get('balance', 0)

    # Balance Check
    if data == "action_balance":
        await query.edit_message_text(
            f"💰 *Wallet Balance:* `{bal} Coins`",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard()
        )
        return

    # Profile Stats
    if data == "action_stats":
        text = (
            f"👤 *Player Profile:* {user.first_name}\n"
            f"🆔 *ID:* `{user_id}`\n"
            f"💰 *Balance:* `{bal} Coins`\n"
            f"🟢 *Wins:* `{u_data.get('wins', 0)}` | 🔴 *Losses:* `{u_data.get('losses', 0)}`"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
        return

    # Deposit Workflow
    if data == "action_deposit":
        context.user_data['state'] = 'AWAITING_DEPOSIT'
        text = (
            f"💳 *DEPOSIT MONEY*\n\n"
            f"Send money to UPI ID: `{UPI_ID}`\n\n"
            f"📸 *Step 2:* Send payment screenshot in this chat. Admin will approve it instantly."
        )
        await query.edit_message_text(text, parse_mode="Markdown")
        return

    # Withdraw Workflow
    if data == "action_withdraw":
        if bal < 100:
            await query.edit_message_text("❌ Minimum withdrawal amount is 100 Coins!", reply_markup=get_main_menu_keyboard())
            return
        context.user_data['state'] = 'AWAITING_WITHDRAW_DETAILS'
        await query.edit_message_text("🏧 *ENTER WITHDRAWAL DETAILS*\n\nReply with your `UPI_ID Amount` (e.g., `user@upi 200`)", parse_mode="Markdown")
        return

    # Game Menus
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

        # Rigged Calculation
        outcome_dice = calculate_rigged_dice(bet_type, target_val)

        # Send Separate Animated Dice Message
        dice_msg = await context.bot.send_dice(chat_id=query.message.chat_id, emoji="🎲")
        
        # Determine Win / Loss
        is_win = False
        if bet_type == "BIG" and outcome_dice in [4, 5, 6]:
            is_win = True
        elif bet_type == "SMALL" and outcome_dice in [1, 2, 3]:
            is_win = True
        elif bet_type == "EXACT" and outcome_dice == int(target_val):
            is_win = True

        # Force actual dice value override logically in response display
        u_ref = users_ref.child(str(user_id))
        if is_win:
            win_amt = BET_AMOUNT * 2
            update_balance(user_id, win_amt - BET_AMOUNT)
            u_ref.child('wins').set((u_data.get('wins', 0)) + 1)
            result_txt = f"🎉 *YOU WON!* (+{win_amt} Coins)\nDice Outcome matched your bet!"
        else:
            update_balance(user_id, -BET_AMOUNT)
            u_ref.child('losses').set((u_data.get('losses', 0)) + 1)
            result_txt = f"💔 *YOU LOST!* (-{BET_AMOUNT} Coins)\nDice rolled *{outcome_dice}*. Better luck next time! 🤣"

        # Edit text after dice roll finishes
        await query.message.reply_text(
            f"🎲 *Dice Rolled Value:* `{outcome_dice}`\n{result_txt}\n\n💰 Updated Balance: `{users_ref.child(str(user_id)).child('balance').get()} Coins`",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard()
        )

    # Admin Request Handling
    if data.startswith("adm_"):
        if user_id != ADMIN_ID:
            return
        _, action, rtype, req_id = data.split("_")
        
        if rtype == "dep":
            req_data = deposits_ref.child(req_id).get()
            if not req_data:
                await query.edit_message_caption("❌ Request already processed.")
                return
            target_u = req_data['user_id']
            if action == "app":
                update_balance(target_u, 500) # Default deposit credit 500
                deposits_ref.child(req_id).delete()
                await context.bot.send_message(target_u, "✅ Your Deposit of 500 Coins has been Approved!")
                await query.edit_message_caption("✅ Approved and Balance Credited!")
            else:
                deposits_ref.child(req_id).delete()
                await context.bot.send_message(target_u, "❌ Your Deposit request was Rejected.")
                await query.edit_message_caption("❌ Rejected!")

        elif rtype == "wd":
            req_data = withdraws_ref.child(req_id).get()
            if not req_data:
                await query.edit_message_text("❌ Request already processed.")
                return
            target_u = req_data['user_id']
            amt = req_data['amount']
            if action == "app":
                withdraws_ref.child(req_id).delete()
                await context.bot.send_message(target_u, f"✅ Your Withdrawal of {amt} Coins has been Processed!")
                await query.edit_message_text(f"✅ Approved Withdrawal for `{target_u}`")
            else:
                update_balance(target_u, amt) # Refund balance on reject
                withdraws_ref.child(req_id).delete()
                await context.bot.send_message(target_u, f"❌ Your Withdrawal request was Rejected. Balance Refunded!")
                await query.edit_message_text(f"❌ Rejected Withdrawal for `{target_u}`")

# ---------------------------------------------------------
# 7. MEDIA & TEXT MESSAGES (Deposit Screenshot & Withdraw Input)
# ---------------------------------------------------------
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    state = context.user_data.get('state')

    # Deposit Screenshot Handler
    if state == 'AWAITING_DEPOSIT' and update.message.photo:
        photo_id = update.message.photo[-1].file_id
        req_ref = deposits_ref.push({
            "user_id": user.id,
            "username": user.username,
            "status": "pending"
        })
        req_id = req_ref.key
        
        # Send photo to admin
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_id,
            caption=f"💳 *NEW DEPOSIT REQUEST*\nUser: {user.first_name} (`{user.id}`)\nUsername: @{user.username}",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard(req_id, "dep")
        )
        context.user_data['state'] = None
        await update.message.reply_text("✅ Screenshot sent to Admin for approval!", reply_markup=get_main_menu_keyboard())
        return

    # Withdraw Text Details Handler
    if state == 'AWAITING_WITHDRAW_DETAILS' and update.message.text:
        try:
            upi_details, amt_str = update.message.text.split()
            amount = float(amt_str)
            bal = get_user_data(user.id).get('balance', 0)

            if amount > bal or amount < 100:
                await update.message.reply_text("❌ Invalid Amount or Insufficient Balance!")
                return

            # Deduct balance temporarily
            update_balance(user.id, -amount)

            req_ref = withdraws_ref.push({
                "user_id": user.id,
                "amount": amount,
                "upi": upi_details,
                "status": "pending"
            })
            req_id = req_ref.key

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🏧 *NEW WITHDRAWAL REQUEST*\nUser: `{user.id}`\nAmount: `{amount} Coins`\nUPI: `{upi_details}`",
                parse_mode="Markdown",
                reply_markup=get_admin_keyboard(req_id, "wd")
            )
            context.user_data['state'] = None
            await update.message.reply_text("✅ Withdrawal Request Sent to Admin!", reply_markup=get_main_menu_keyboard())
        except Exception:
            await update.message.reply_text("❌ Invalid Format! Send like this: `yourupi@upi 200`", parse_mode="Markdown")

# ---------------------------------------------------------
# 8. APPLICATION ENTRYPOINT
# ---------------------------------------------------------
if __name__ == '__main__':
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable not set!")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("admin", admin_panel_cmd))
    app.add_handler(CommandHandler("addcoins", add_coins_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, handle_messages))

    print("⚡ Casino Royalty Rigged Bot Started Successfully...")
    app.run_polling()
