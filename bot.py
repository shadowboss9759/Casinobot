import os
import random
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Temporary In-Memory Wallet (User ID: Balance)
user_wallets = {}

def get_balance(user_id):
    if user_id not in user_wallets:
        user_wallets[user_id] = 1000  # Har naye user ko 1000 free coins
    return user_wallets[user_id]

# Main Menu Keyboards
def main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🎲 Roll Dice", callback_data="play_dice"),
            InlineKeyboardButton("🎰 Slot Machine", callback_data="play_slot")
        ],
        [
            InlineKeyboardButton("💰 Balance", callback_data="check_balance"),
            InlineKeyboardButton("🎁 Daily Bonus", callback_data="daily_bonus")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# /start Command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_balance(user.id) # Initialize balance
    
    welcome_text = (
        f"👑 *Welcome to Casino Royals, {user.first_name}!*\n\n"
        f"Aapko welcome bonus me *1000 Coins* mile hain!\n"
        f"Khelne ke liye niche diye gaye buttons par click karein:"
    )
    await update.message.reply_text(
        welcome_text, 
        parse_mode="Markdown", 
        reply_markup=main_menu_keyboard()
    )

# Button Handlers
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    balance = get_balance(user_id)
    
    if query.data == "check_balance":
        await query.edit_message_text(
            f"💰 *Aapka Current Balance:* `{balance} Coins`\n\nKhelna jaari rakhein!",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
        
    elif query.data == "daily_bonus":
        bonus = 200
        user_wallets[user_id] += bonus
        await query.edit_message_text(
            f"🎁 Aapne `{bonus} Coins` ka Daily Bonus claim kar liya hai!\n"
            f"Naya Balance: `{user_wallets[user_id]} Coins`",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )

    elif query.data == "play_dice":
        bet = 100
        if balance < bet:
            await query.edit_message_text(
                "❌ Aapke paas kaafi coins nahi hain (Bet: 100 Coins)!",
                reply_markup=main_menu_keyboard()
            )
            return

        # Simple Dice logic (4-6 wins 2x bet)
        roll = random.randint(1, 6)
        if roll >= 4:
            user_wallets[user_id] += bet
            res = f"🎲 Aapka number aaya: *{roll}*\n🎉 *Aap Jeet Gaye!* (+{bet} Coins)"
        else:
            user_wallets[user_id] -= bet
            res = f"🎲 Aapka number aaya: *{roll}*\n💔 *Aap Haar Gaye!* (-{bet} Coins)"
            
        await query.edit_message_text(
            f"{res}\n\nNaya Balance: `{user_wallets[user_id]} Coins`",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )

    elif query.data == "play_slot":
        bet = 100
        if balance < bet:
            await query.edit_message_text(
                "❌ Aapke paas kaafi coins nahi hain (Bet: 100 Coins)!",
                reply_markup=main_menu_keyboard()
            )
            return

        symbols = ["🍋", "🍒", "💎", "7️⃣"]
        s1, s2, s3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)
        
        if s1 == s2 == s3:
            win = bet * 5
            user_wallets[user_id] += win
            res = f"🎰 [{s1} | {s2} | {s3}]\n🔥 *JACKPOT!* Aap `{win} Coins` jeet gaye!"
        else:
            user_wallets[user_id] -= bet
            res = f"🎰 [{s1} | {s2} | {s3}]\n❌ Koyi match nahi hua! (-{bet} Coins)"

        await query.edit_message_text(
            f"{res}\n\nNaya Balance: `{user_wallets[user_id]} Coins`",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )

if __name__ == '__main__':
    TOKEN = os.environ.get("BOT_TOKEN")
    
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable set nahi hai!")

    app = ApplicationBuilder().token(TOKEN).build()

    # Handlers Add Karein
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_click))

    print("⚡ Bot chal raha hai...")
    app.run_polling()
