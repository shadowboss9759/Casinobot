import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# Helper: 3x3 Grid Create Karne Ke Liye (3 Mines, 6 Safe)
def create_mine_grid():
    grid = ["SAFE"] * 6 + ["MINE"] * 3
    random.shuffle(grid)
    return grid

# Multiplier Logic for 3x3 Grid (3 Mines)
MULTIPLIERS = {
    1: 1.30,  # 1st Safe
    2: 1.85,  # 2nd Safe
    3: 2.70,  # 3rd Safe
    4: 4.20,  # 4th Safe
    5: 7.00,  # 5th Safe
    6: 12.00 # 6th Safe (All Clear)
}

# Helper: Mines 3x3 Grid Keyboard Builder
def build_mines_keyboard(grid, revealed, game_over=False, current_win=0):
    keyboard = []
    for row in range(3):
        row_buttons = []
        for col in range(3):
            idx = row * 3 + col
            if idx in revealed:
                tile_text = "💣" if grid[idx] == "MINE" else "💎"
            elif game_over:
                tile_text = "💣" if grid[idx] == "MINE" else "🟦"
            else:
                tile_text = "🟦"
            
            row_buttons.append(InlineKeyboardButton(tile_text, callback_data=f"mn_click_{idx}"))
        keyboard.append(row_buttons)

    # Cashout Button
    if not game_over and len(revealed) > 0:
        keyboard.append([InlineKeyboardButton(f"💰 CASHOUT ({current_win:.1f} Coins)", callback_data="mn_cashout")])

    return InlineKeyboardMarkup(keyboard)

# Game Start Function
async def start_mines_game(update: Update, context: ContextTypes.DEFAULT_TYPE, bet_amt: float, format_bal_func):
    grid = create_mine_grid()
    
    context.user_data['mines_game'] = {
        'bet': bet_amt,
        'grid': grid,
        'revealed': [],
        'current_win': bet_amt
    }

    reply_markup = build_mines_keyboard(grid, [], game_over=False, current_win=bet_amt)
    await update.message.reply_text(
        f"💣 *MINES GAME (3x3)*\n\n"
        f"💵 *Bet Amount:* `{format_bal_func(bet_amt)}`\n"
        f"💣 *Total Mines:* `3` | 💎 *Safe Tiles:* `6`\n\n"
        f"👉 Diamond (💎) dhoondhne ke liye kisi bhi box (🟦) par click karein:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

# Mines Click & Cashout Callback Handler
async def handle_mines_click(update: Update, context: ContextTypes.DEFAULT_TYPE, update_balance_func, update_stats_func, format_bal_func):
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
        new_bal = update_balance_func(user_id, win_amt - mines_data['bet'])
        update_stats_func(user_id, is_win=True)

        reply_markup = build_mines_keyboard(mines_data['grid'], mines_data['revealed'], game_over=True)
        await query.edit_message_text(
            f"🎉 *CASHOUT SUCCESSFUL!*\n\n"
            f"💵 *Won:* `{format_bal_func(win_amt)}`\n"
            f"💰 *New Balance:* `{format_bal_func(new_bal)}`",
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

        # ==================== RIGGED TRAP LOGIC (House Win Rate ~20-25%) ====================
        # Agar user SAFE tile par click karta hai aur pehle se 1 safe khol chuka hai,
        # toh 65% Chance hai ki hum tile ko MINE se swap kar denge (Taki House ka loss na ho)
        if mines_data['grid'][idx] == "SAFE":
            safe_already = len(mines_data['revealed'])
            if safe_already >= 1 and random.random() < 0.65:
                # Find an unrevealed MINE tile and swap it
                unrevealed_mines = [i for i in range(9) if mines_data['grid'][i] == "MINE" and i not in mines_data['revealed']]
                if unrevealed_mines:
                    swap_idx = random.choice(unrevealed_mines)
                    mines_data['grid'][idx] = "MINE"
                    mines_data['grid'][swap_idx] = "SAFE"

        # Mine Hit Ho Gaya! 💥
        if mines_data['grid'][idx] == "MINE":
            new_bal = update_balance_func(user_id, -mines_data['bet'])
            update_stats_func(user_id, is_win=False)

            all_revealed = list(range(9))
            reply_markup = build_mines_keyboard(mines_data['grid'], all_revealed, game_over=True)
            await query.edit_message_text(
                f"💥 *BOOM! YOU HIT A MINE!*\n\n"
                f"💔 *Lost:* `{format_bal_func(mines_data['bet'])}`\n"
                f"💰 *New Balance:* `{format_bal_func(new_bal)}`",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
            context.user_data.pop('mines_game', None)
            return

        # Safe Tile Revealed! 💎
        mines_data['revealed'].append(idx)
        safe_clicked = len(mines_data['revealed'])
        
        # Multiplier update
        multiplier = MULTIPLIERS.get(safe_clicked, 1.0)
        mines_data['current_win'] = mines_data['bet'] * multiplier

        # Auto Cashout if all 6 safe tiles opened
        if safe_clicked == 6:
            win_amt = mines_data['current_win']
            new_bal = update_balance_func(user_id, win_amt - mines_data['bet'])
            update_stats_func(user_id, is_win=True)
            reply_markup = build_mines_keyboard(mines_data['grid'], mines_data['revealed'], game_over=True)
            await query.edit_message_text(
                f"🏆 *ALL SAFE TILES CLEARED! PERFECT WIN!*\n\n"
                f"💵 *Won:* `{format_bal_func(win_amt)}` (`{multiplier:.2f}x`)\n"
                f"💰 *New Balance:* `{format_bal_func(new_bal)}`",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
            context.user_data.pop('mines_game', None)
            return

        reply_markup = build_mines_keyboard(mines_data['grid'], mines_data['revealed'], False, mines_data['current_win'])
        await query.edit_message_text(
            f"💎 *SAFE TILE!* (Multiplier: `{multiplier:.2f}x`)\n"
            f"💰 *Current Value:* `{format_bal_func(mines_data['current_win'])}`\n\n"
            f"👉 Agla box kholein ya Cashout dabayein!",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
