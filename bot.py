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
    expired = [uid for uid, e in otp_store
