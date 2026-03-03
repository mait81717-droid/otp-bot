import os
import time
import secrets
from dataclasses import dataclass
from typing import Dict, Optional, Set

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

OTP_TTL_SECONDS = 180
OTP_MAX_ATTEMPTS = 5
GEN_RATE_LIMIT_SECONDS = 30

SHOW_OTP_IN_CHAT = False
WHITELIST_ENABLED = True

BRAND = "𝗜𝗟 𝗠𝗔𝗥𝗥𝗢𝗖𝗖𝗛𝗜𝗡𝗢 │ 𝗢𝗧𝗣 𝗦𝗘𝗖𝗨𝗥𝗜𝗧𝗬"

# ================= STATE =================
@dataclass
class OTPEntry:
    code: str
    expires_at: float
    attempts_left: int

otp_store: Dict[int, OTPEntry] = {}
awaiting_code: Dict[int, bool] = {}
last_gen_at: Dict[int, float] = {}
allowed_users: Set[int] = set()

# ================= HELPERS =================
def now():
    return time.time()

def gen_code():
    return f"{secrets.randbelow(1_000_000):06d}"

def is_admin(user_id: int):
    return user_id == ADMIN_ID

def is_allowed(user_id: int):
    if is_admin(user_id):
        return True
    return user_id in allowed_users

async def send_access_request(context, user):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Autorizar", callback_data=f"approve_{user.id}"),
            InlineKeyboardButton("❌ Denegar", callback_data=f"deny_{user.id}")
        ]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"🚨 Solicitud de acceso\n\n"
            f"Usuario: {user.full_name}\n"
            f"Username: @{user.username}\n"
            f"ID: {user.id}"
        ),
        reply_markup=keyboard
    )

# ================= COMMANDS =================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not is_allowed(user.id):
        await update.message.reply_text("🔒 Acceso restringido. Solicitud enviada al administrador.")
        await send_access_request(context, user)
        return

    await update.message.reply_text(
        f"{BRAND}\n\nSistema OTP operativo.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Generar OTP", callback_data="gen")],
            [InlineKeyboardButton("✅ Verificar OTP", callback_data="verify")]
        ])
    )

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id

    # Admin approvals
    if q.data.startswith("approve_"):
        if not is_admin(user_id):
            return
        uid = int(q.data.split("_")[1])
        allowed_users.add(uid)
        await q.edit_message_text(f"✅ Usuario autorizado: {uid}")
        return

    if q.data.startswith("deny_"):
        if not is_admin(user_id):
            return
        uid = int(q.data.split("_")[1])
        await q.edit_message_text(f"❌ Usuario denegado: {uid}")
        return

    # OTP actions
    if not is_allowed(user_id):
        return

    if q.data == "gen":
        code = gen_code()
        otp_store[user_id] = OTPEntry(code, now() + OTP_TTL_SECONDS, OTP_MAX_ATTEMPTS)

        if SHOW_OTP_IN_CHAT:
            await q.edit_message_text(f"OTP generado: `{code}`", parse_mode="Markdown")
        else:
            await q.edit_message_text("OTP generado. Proceda a verificar.")

    elif q.data == "verify":
        awaiting_code[user_id] = True
        await q.edit_message_text("Envíe el código OTP.")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if not is_allowed(user_id):
        return

    if not awaiting_code.get(user_id):
        return

    entry = otp_store.get(user_id)
    if not entry:
        await update.message.reply_text("OTP no activo.")
        return

    if text == entry.code:
        await update.message.reply_text("✅ OTP correcto.")
        otp_store.pop(user_id, None)
        awaiting_code[user_id] = False
    else:
        await update.message.reply_text("❌ OTP incorrecto.")

# ================= MAIN =================
def main():
    if not BOT_TOKEN:
        raise SystemExit("Falta BOT_TOKEN")
    if not ADMIN_ID:
        raise SystemExit("Falta ADMIN_ID")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling()

if __name__ == "__main__":
    main()