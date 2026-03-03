import os
import time
import secrets
from dataclasses import dataclass
from typing import Dict, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ====== CONFIG (Railway Variables) ======
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "180"))           # 3 min
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))           # intentos
GEN_RATE_LIMIT_SECONDS = int(os.getenv("GEN_RATE_LIMIT_SECONDS", "30"))  # 30s
SHOW_OTP_IN_CHAT = os.getenv("SHOW_OTP_IN_CHAT", "false").lower() in ("1","true","yes","y")

BRAND = "𝗜𝗟 𝗠𝗔𝗥𝗥𝗢𝗖𝗖𝗛𝗜𝗡𝗢 │ 𝗢𝗧𝗣 𝗦𝗘𝗖𝗨𝗥𝗜𝗧𝗬"

START_TEXT = (
    f"{BRAND}\n\n"
    "🔐 Infraestructura OTP operativa.\n"
    "Selecciona una acción:"
)

HELP_TEXT = (
    f"{BRAND}\n\n"
    "Comandos:\n"
    "/start — menú principal\n"
    "/status — estado del OTP\n"
    "/help — ayuda\n\n"
    "Uso:\n"
    "1) Genera un OTP\n"
    "2) Verifica enviando el código (6 dígitos)\n"
)

# ====== STATE ======
@dataclass
class OTPEntry:
    code: str
    expires_at: float
    attempts_left: int

otp_store: Dict[int, OTPEntry] = {}         # user_id -> OTP
awaiting_code: Dict[int, bool] = {}         # user_id -> esperando OTP
last_gen_at: Dict[int, float] = {}          # user_id -> timestamp último generate


def now() -> float:
    return time.time()

def cleanup_expired() -> None:
    t = now()
    expired = [uid for uid, e in otp_store.items() if e.expires_at <= t]
    for uid in expired:
        otp_store.pop(uid, None)
        awaiting_code.pop(uid, None)

def main_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("🔑 Generar OTP", callback_data="gen")],
        [InlineKeyboardButton("✅ Verificar OTP", callback_data="verify")],
        [InlineKeyboardButton("📊 Estado", callback_data="status")],
        [InlineKeyboardButton("ℹ Ayuda", callback_data="help")],
    ]
    return InlineKeyboardMarkup(kb)

def get_active_entry(user_id: int) -> Optional[OTPEntry]:
    cleanup_expired()
    return otp_store.get(user_id)

def gen_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cleanup_expired()
    awaiting_code[update.effective_user.id] = False
    await update.message.reply_text(START_TEXT, reply_markup=main_menu())

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, reply_markup=main_menu())

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    entry = get_active_entry(user_id)
    if not entry:
        await update.message.reply_text(f"{BRAND}\n\n📊 No hay OTP activo.", reply_markup=main_menu())
        return
    remaining = int(entry.expires_at - now())
    await update.message.reply_text(
        f"{BRAND}\n\n📊 OTP activo.\n"
        f"⏳ Expira en: {remaining}s\n"
        f"🔁 Intentos restantes: {entry.attempts_left}",
        reply_markup=main_menu()
    )

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id

    cleanup_expired()

    if q.data == "gen":
        # Rate limit
        last = last_gen_at.get(user_id, 0.0)
        wait = GEN_RATE_LIMIT_SECONDS - (now() - last)
        if wait > 0:
            await q.edit_message_text(
                f"{BRAND}\n\n🚫 Límite de generación.\n"
                f"Es
