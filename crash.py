import asyncio
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# Helper: Rigged Crash Multiplier Generator (House Win Rate ~75-80%)
def generate_crash_point():
    rand = random.random()
    if rand < 0.65:
        # 65% Chance: Super early crash (Instant Loss Trap)
        return round(random.uniform(1.01, 1.25), 2)
    elif rand < 0.90:
        # 25% Chance: Medium crash
        return round(random.uniform(1.26, 1.80), 2)
    else:
        # 10% Chance: Moonshot (For hype/player attraction)
        return round(random.uniform(2.00, 4.00), 2)

# Game Start Function
async def start_crash_game(update: Update, context: ContextTypes.DEFAULT_TYPE, bet_amt: float, update_balance_func, update_stats_func, format_bal_func):
    user_id = update.effective_user.id
    crash_point = generate_crash_point()
    
    # Game State Store
    context.user_data['crash_game'] = {
        'bet': bet_amt,
        'crash_point': crash_point,
        'current_mult': 1.00,
        'active': True,
        'cashed_out': False
    }

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 CASHOUT (1.00x)", callback_data="crash_cashout")]
    ])

    msg = await update.message.reply_text(
        f"🚀 *CRASH GAME (AVIATOR)*\n\n"
        f"💵 *Bet Amount:* `{format_bal_func(bet_amt)}`\n"
        f"📈 *Multiplier:* `1.00x`\n\n"
        f"🚀 Rocket udne wala hai... Crash hone se pehle CASHOUT dabaayein!",
        parse_mode="Markdown",
        reply_markup=kb
    )

    current_mult = 1.00
    
    # Flight Animation Loop
    while current_mult < crash_point:
        await asyncio.sleep(1.3)  # Telegram Rate Limit Safety Delay
        
        c_data = context.user_data.get('crash_game')
        if not c_data or not c_data.get('active', False) or c_data.get('cashed_out', False):
            return

        # Increase Multiplier
        step = round(random.uniform(0.10, 0.25), 2)
        current_mult = round(current_mult + step, 2)

        if current_mult >= crash_point:
            break

        c_data['current_mult'] = current_mult
        current_win = bet_amt * current_mult

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💰 CASHOUT ({format_bal_func(current_win)})", callback_data="crash_cashout")]
        ])

        try:
            await msg.edit_text(
                f"🚀 *ROCKET IS FLYING...*\n\n"
                f"💵 *Bet:* `{format_bal_func(bet_amt)}`\n"
                f"📈 *Multiplier:* `{current_mult:.2f}x`\n"
                f"💸 *Current Value:* `{format_bal_func(current_win)}`\n\n"
                f"👉 Jaldi Cashout karo pehle ki crash ho jaye!",
                parse_mode="Markdown",
                reply_markup=kb
            )
        except Exception:
            pass

    # ==================== CRASHED! 💥 ====================
    c_data = context.user_data.get('crash_game')
    if c_data and c_data.get('active') and not c_data.get('cashed_out'):
        c_data['active'] = False
        
        # Balance Deduct & Stats Update
        new_bal = update_balance_func(user_id, -bet_amt)
        update_stats_func(user_id, is_win=False)

        try:
            await msg.edit_text(
                f"💥 *BOOM! ROCKET CRASHED AT `{crash_point:.2f}x`!*\n\n"
                f"💔 Aapne time par Cashout nahi kiya!\n"
                f"📉 *Lost:* `{format_bal_func(bet_amt)}`\n"
                f"💰 *New Balance:* `{format_bal_func(new_bal)}`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
            
        context.user_data.pop('crash_game', None)

# Crash Cashout Callback Handler
async def handle_crash_cashout(update: Update, context: ContextTypes.DEFAULT_TYPE, update_balance_func, update_stats_func, format_bal_func):
    query = update.callback_query
    user_id = query.from_user.id

    c_data = context.user_data.get('crash_game')
    if not c_data or not c_data.get('active') or c_data.get('cashed_out'):
        await query.answer("❌ Game over or already cashed out!", show_alert=True)
        return

    c_data['cashed_out'] = True
    c_data['active'] = False

    mult = c_data['current_mult']
    bet_amt = c_data['bet']
    win_amt = bet_amt * mult

    new_bal = update_balance_func(user_id, win_amt - bet_amt)
    update_stats_func(user_id, is_win=True)

    await query.edit_message_text(
        f"🎉 *CASHOUT SUCCESSFUL!*\n\n"
        f"🎯 *Cashed Out At:* `{mult:.2f}x`\n"
        f"💵 *Won:* `{format_bal_func(win_amt)}`\n"
        f"💰 *New Balance:* `{format_bal_func(new_bal)}`",
        parse_mode="Markdown"
    )
    context.user_data.pop('crash_game', None)
