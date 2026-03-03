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

# ================== CONFIG (Railway Variables) ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Admin (tu Telegram user id). Obligatorio para whitelist/admin.
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "180"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
GEN_RATE_LIMIT_SECONDS = int(os.getenv("GEN_RATE_LIMIT_SECONDS", "30"))

# Modo demo vs seguro
SHOW_OTP_IN_CHAT = os.getenv("SHOW_OTP_IN_CHAT", "false").lower() in ("1", "true", "yes", "y")

# Whitelist: "true" recomendado en producción
WHITELIST_ENABLED = os.getenv("WHITELIST_ENABLED", "true").lower() in ("1", "true", "yes", "y")

BRAND = "𝗜𝗟 𝗠𝗔𝗥𝗥𝗢𝗖𝗖𝗛𝗜𝗡𝗢 │ 𝗢𝗧𝗣 𝗦𝗘𝗖𝗨𝗥𝗜𝗧𝗬"

START_TEXT = (
    f"{BRAND}\n\n"
    "🔐 Infraestructura OTP operativa.\n"
    "Selecciona una acción:"
)

HELP_TEXT = (
    f"{BRAND}\n\n"
    "Comandos:\n"
    "/start — menú\n"
    "/status — estado\n"
    "/help — ayuda\n\n"
    "Admin:\n"
    "/admin — panel\n"
    "/allow <user_id> — autorizar\n"
    "/deny <user_id> — revocar\n"
    "/stats — métricas\n"
)

# ================== STATE (memoria; reinicia al redeploy) ==================
@dataclass
class OTPEntry:
    code: str
    expires_at: float
    attempts_left: int

otp_store: Dict[int, OTPEntry] = {}
awaiting_code: Dict[int, bool] = {}
last_gen_at: Dict[int, float] = {}
allowed_users: Set[int] = set()  # whitelist in-memory

# Metrics
metrics = {
    "otp_generated": 0,
    "otp_verified": 0,
    "otp_failed": 0,
    "blocked_by_rl": 0,
    "denied_by_whitelist": 0,
}

# ================== Helpers ==================
def now() -> float:
    return time.time()

def cleanup_expired() -> None:
    t = now()
    expired = [uid for uid, e in otp_store.items() if e.expires_at <= t]
    for uid in expired:
        otp_store.pop(uid, None)
        awaiting_code.pop(uid, None)

def gen_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"

def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID

def is_allowed(user_id: int) -> bool:
    if not WHITELIST_ENABLED:
        return True
    if is_admin(user_id):
        return True
    return user_id in allowed_users

def require_allowed(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else 0
        if not is_allowed(user_id):
            metrics["denied_by_whitelist"] += 1
            # Mensaje discreto
            if update.message:
                await update.message.reply_text("🚫 Acceso no autorizado.")
            elif update.callback_query:
                await update.callback_query.answer("Acceso no autorizado.", show_alert=True)
            return
        return await func(update, context)
    return wrapper

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

# ================== User Commands ==================
@require_allowed
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cleanup_expired()
    awaiting_code[update.effective_user.id] = False
    await update.message.reply_text(START_TEXT, reply_markup=main_menu())

@require_allowed
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, reply_markup=main_menu())

@require_allowed
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

# ================== Buttons ==================
@require_allowed
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
            metrics["blocked_by_rl"] += 1
            await q.edit_message_text(
                f"{BRAND}\n\n🚫 Límite de generación.\nEspera {int(wait)}s.",
                reply_markup=main_menu()
            )
            return

        code = gen_code()
        otp_store[user_id] = OTPEntry(code=code, expires_at=now() + OTP_TTL_SECONDS, attempts_left=OTP_MAX_ATTEMPTS)
        last_gen_at[user_id] = now()
        awaiting_code[user_id] = False
        metrics["otp_generated"] += 1

        if SHOW_OTP_IN_CHAT:
            await q.edit_message_text(
                f"{BRAND}\n\n🔑 OTP generado:\n`{code}`\n\n"
                f"⏳ Válido: {OTP_TTL_SECONDS//60} min\n"
                f"🔁 Intentos: {OTP_MAX_ATTEMPTS}",
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
        else:
            await q.edit_message_text(
                f"{BRAND}\n\n✅ OTP generado.\n"
                f"⏳ Válido: {OTP_TTL_SECONDS//60} min\n"
                "Pulsa ✅ Verificar OTP y envía el código.",
                reply_markup=main_menu()
            )

    elif q.data == "verify":
        awaiting_code[user_id] = True
        await q.edit_message_text(
            f"{BRAND}\n\n✅ Envía el OTP (6 dígitos) para verificarlo.",
            reply_markup=main_menu()
        )

    elif q.data == "status":
        entry = get_active_entry(user_id)
        if not entry:
            await q.edit_message_text(f"{BRAND}\n\n📊 No hay OTP activo.", reply_markup=main_menu())
            return
        remaining = int(entry.expires_at - now())
        await q.edit_message_text(
            f"{BRAND}\n\n📊 OTP activo.\n⏳ Expira en: {remaining}s\n🔁 Intentos: {entry.attempts_left}",
            reply_markup=main_menu()
        )

    elif q.data == "help":
        await q.edit_message_text(HELP_TEXT, reply_markup=main_menu())

# ================== OTP text input ==================
@require_allowed
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    if not awaiting_code.get(user_id, False):
        return

    entry = get_active_entry(user_id)
    if not entry:
        awaiting_code[user_id] = False
        await update.message.reply_text("❌ No hay OTP activo o ya caducó. Genera uno nuevo.", reply_markup=main_menu())
        return

    if not (text.isdigit() and len(text) == 6):
        await update.message.reply_text("⚠️ Formato inválido. Envía 6 dígitos.", reply_markup=main_menu())
        return

    if entry.attempts_left <= 0:
        otp_store.pop(user_id, None)
        awaiting_code[user_id] = False
        await update.message.reply_text("🚫 OTP bloqueado por demasiados intentos. Genera uno nuevo.", reply_markup=main_menu())
        return

    if secrets.compare_digest(text, entry.code):
        otp_store.pop(user_id, None)
        awaiting_code[user_id] = False
        metrics["otp_verified"] += 1
        await update.message.reply_text("✅ OTP verificado correctamente.", reply_markup=main_menu())
    else:
        entry.attempts_left -= 1
        otp_store[user_id] = entry
        metrics["otp_failed"] += 1
        await update.message.reply_text(f"❌ OTP incorrecto. Intentos restantes: {entry.attempts_left}", reply_markup=main_menu())

# ================== Admin Commands ==================
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("🚫 Acceso no autorizado.")
        return

    await update.message.reply_text(
        f"{BRAND}\n\n👑 Panel Admin\n"
        f"- Whitelist: {'ON' if WHITELIST_ENABLED else 'OFF'}\n"
        f"- Usuarios autorizados: {len(allowed_users)}\n\n"
        "Comandos:\n"
        "/allow <user_id>\n"
        "/deny <user_id>\n"
        "/stats",
        reply_markup=main_menu()
    )

async def cmd_allow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Acceso no autorizado.")
        return

    if not context.args:
        await update.message.reply_text("Uso: /allow <user_id>")
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID inválido.")
        return

    allowed_users.add(uid)
    await update.message.reply_text(f"✅ Usuario autorizado: {uid}")

async def cmd_deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Acceso no autorizado.")
        return

    if not context.args:
        await update.message.reply_text("Uso: /deny <user_id>")
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID inválido.")
        return

    allowed_users.discard(uid)
    otp_store.pop(uid, None)
    awaiting_code.pop(uid, None)
    await update.message.reply_text(f"✅ Acceso revocado: {uid}")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Acceso no autorizado.")
        return

    cleanup_expired()
    await update.message.reply_text(
        f"{BRAND}\n\n📈 Stats\n"
        f"- OTP generados: {metrics['otp_generated']}\n"
        f"- OTP verificados: {metrics['otp_verified']}\n"
        f"- OTP fallidos: {metrics['otp_failed']}\n"
        f"- Rate-limit bloqueos: {metrics['blocked_by_rl']}\n"
        f"- Denegados por whitelist: {metrics['denied_by_whitelist']}\n"
        f"- OTP activos: {len(otp_store)}\n"
        f"- Usuarios autorizados: {len(allowed_users)}\n"
    )

# ================== Main ==================
def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Falta BOT_TOKEN en variables de entorno.")
    if ADMIN_ID == 0:
        raise SystemExit("Falta ADMIN_ID en variables de entorno (tu Telegram user id).")

    app = Application.builder().token(BOT_TOKEN).build()

    # User
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))

    # Admin
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("allow", cmd_allow))
    app.add_handler(CommandHandler("deny", cmd_deny))
    app.add_handler(CommandHandler("stats", cmd_stats))

    # Buttons + text
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling()

if __name__ == "__main__":
    main() 
