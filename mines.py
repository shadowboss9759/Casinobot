import random
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# Helper: Mines Grid Keyboard Builder
def build_mines_keyboard(grid, revealed, game_over=False, current_win=0):
    keyboard = []
    for row in range(5):
        row_buttons = []
        for col in range(5):
            idx = row * 5 + col
            if idx in revealed:
                # Agar clicked hai
                tile_text = "💣" if grid[idx] == "MINE" else "💎"
            elif game_over:
                # Game over ke baad saare reveal kar do
                tile_text = "💣" if grid[idx] == "MINE" else "🟦"
            else:
                tile_text = "🟦"
            
            row_buttons.append(InlineKeyboardButton(tile_text, callback_data=f"mn_click_{idx}"))
        keyboard.append(row_buttons)

    # Cashout Button
    if not game_over and len(revealed) > 0:
        keyboard.append([InlineKeyboardButton(f"💰 CASHOUT ({current_win:.1f} Coins)", callback_data="mn_cashout")])

    return InlineKeyboardMarkup(keyboard)

# Mines Callback Handler
async def handle_mines_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    mines_data = context.user_data.get('mines_game')
    if not mines_data:
        await query.answer("❌ Game expired or not active!", show_alert=True)
        return

    # 1. CASHOUT ACTION
    if data == "mn_cashout":
        win_amt = mines_data['current_win']
        new_bal = update_balance(user_id, win_amt - mines_data['bet'])
        update_stats(user_id, is_win=True)

        reply_markup = build_mines_keyboard(mines_data['grid'], mines_data['revealed'], game_over=True)
        await query.edit_message_text(
            f"🎉 *CASHOUT SUCCESSFUL!*\n\n"
            f"💵 *Won:* `{format_bal(win_amt)}`\n"
            f"💰 *New Balance:* `{format_bal(new_bal)}`",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        context.user_data.pop('mines_game', None)
        return

    # 2. TILE CLICK ACTION
    if data.startswith("mn_click_"):
        idx = int(data.split("_")[2])
        if idx in mines_data['revealed']:
            await query.answer("⚠️ Already clicked!", show_alert=False)
            return

        # Mine hit ho gaya! 💥
        if mines_data['grid'][idx] == "MINE":
            new_bal = update_balance(user_id, -mines_data['bet'])
            update_stats(user_id, is_win=False)

            all_revealed = list(range(25))
            reply_markup = build_mines_keyboard(mines_data['grid'], all_revealed, game_over=True)
            await query.edit_message_text(
                f"💥 *BOOM! YOU HIT A MINE!*\n\n"
                f"💔 *Lost:* `{format_bal(mines_data['bet'])}`\n"
                f"💰 *New Balance:* `{format_bal(new_bal)}`",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
            context.user_data.pop('mines_game', None)
            return

        # Safe Tile! 💎
        mines_data['revealed'].append(idx)
        safe_clicked = len(mines_data['revealed'])
        
        # Multiplier Increase Logic
        multiplier = 1.0 + (safe_clicked * 0.25)
        mines_data['current_win'] = mines_data['bet'] * multiplier

        reply_markup = build_mines_keyboard(mines_data['grid'], mines_data['revealed'], False, mines_data['current_win'])
        await query.edit_message_text(
            f"💎 *SAFE TILE!* (Multiplier: `{multiplier:.2f}x`)\n"
            f"💰 *Current Cashout Value:* `{format_bal(mines_data['current_win'])}`\n\n"
            f"👉 Agey click karo ya Cashout dabo!",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
