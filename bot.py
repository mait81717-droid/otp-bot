import os
import time
import secrets
from dataclasses import dataclass
from typing import Dict, Set, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

ALLOWED_USER_IDS_RAW = os.getenv("ALLOWED_USER_IDS", "").strip()

OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "180"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
GEN_RATE_LIMIT_SECONDS = int(os.getenv("GEN_RATE_LIMIT_SECONDS", "30"))
SHOW_OTP_IN_CHAT = os.getenv("SHOW_OTP_IN_CHAT", "false").lower() in ("1", "true", "yes", "y")

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

metrics = {
    "otp_generated": 0,
    "otp_verified": 0,
    "otp_failed": 0,
    "blocked_by_rl": 0,
    "denied_by_whitelist": 0,
    "access_requests": 0,
}

# ================= HELPERS =================
def now() -> float:
    return time.time()

def load_allowed_users() -> Set[int]:
    ids: Set[int] = set()
    if not ALLOWED_USER_IDS_RAW:
        return ids
    for part in ALLOWED_USER_IDS_RAW.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            pass
    return ids

allowed_users: Set[int] = load_allowed_users()

def is_admin(user_id: int) -> bool:
    return ADMIN_ID != 0 and user_id == ADMIN_ID

def is_allowed(user_id: int) -> bool:
    return is_admin(user_id) or (user_id in allowed_users)

def gen_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"

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
        [InlineKeyboardButton("🆔 Mi ID", callback_data="whoami")],
        [InlineKeyboardButton("ℹ Ayuda", callback_data="help")],
    ]
    return InlineKeyboardMarkup(kb)

def help_text() -> str:
    return (
        f"{BRAND}\n\n"
        "Comandos:\n"
        "/start — menú\n"
        "/whoami — ver tu user_id\n"
        "/status — estado del OTP\n\n"
        "Admin:\n"
        "/admin — panel\n"
        "/stats — métricas\n\n"
        "Whitelist permanente:\n"
        "Railway → Variables → ALLOWED_USER_IDS\n"
        "Ej: 636...,123...,999..."
    )

async def notify_admin_access_request(context: ContextTypes.DEFAULT_TYPE, user) -> None:
    if not ADMIN_ID:
        return

    metrics["access_requests"] += 1
    uname = f"@{user.username}" if user.username else "(sin username)"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Autorizar (temporal)", callback_data=f"approve_{user.id}"),
            InlineKeyboardButton("❌ Denegar", callback_data=f"deny_{user.id}")
        ]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            "🚨 Solicitud de acceso\n\n"
            f"Usuario: {user.full_name}\n"
            f"Username: {uname}\n"
            f"ID: {user.id}\n\n"
            "📌 Para dejarlo PERMANENTE:\n"
            f"Añade {user.id} a Railway → ALLOWED_USER_IDS"
        ),
        reply_markup=kb
    )

async def send_copy_paste_line(context: ContextTypes.DEFAULT_TYPE, uid: int) -> None:
    # No podemos editar Railway desde el bot, pero sí darte el texto listo.
    current = ALLOWED_USER_IDS_RAW.strip()
    if current:
        line = f"ALLOWED_USER_IDS={current},{uid}"
    else:
        line = f"ALLOWED_USER_IDS={uid}"
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"✅ Copia y pega en Railway → Variables:\n`{line}`",
        parse_mode="Markdown"
    )

# ================= COMMANDS =================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cleanup_expired()
    user = update.effective_user

    if not is_allowed(user.id):
        metrics["denied_by_whitelist"] += 1
        await update.message.reply_text("🔒 Acceso restringido. Solicitud enviada al administrador.")
        await notify_admin_access_request(context, user)
        return

    awaiting_code[user.id] = False
    await update.message.reply_text(f"{BRAND}\n\nSistema OTP operativo.", reply_markup=main_menu())

async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    uname = f"@{user.username}" if user.username else "(sin username)"
    await update.message.reply_text(
        f"🆔 Tu ID: `{user.id}`\nUsuario: {user.full_name}\nUsername: {uname}",
        parse_mode="Markdown"
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cleanup_expired()
    user_id = update.effective_user.id

    if not is_allowed(user_id):
        metrics["denied_by_whitelist"] += 1
        await update.message.reply_text("🔒 Acceso restringido.")
        return

    entry = otp_store.get(user_id)
    if not entry:
        await update.message.reply_text("📊 No hay OTP activo.", reply_markup=main_menu())
        return

    remaining = max(0, int(entry.expires_at - now()))
    await update.message.reply_text(
        f"📊 OTP activo\n⏳ Expira en: {remaining}s\n🔁 Intentos: {entry.attempts_left}",
        reply_markup=main_menu()
    )

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Acceso no autorizado.")
        return

    await update.message.reply_text(
        f"{BRAND}\n\n👑 Admin Panel\n"
        f"- ALLOWED_USER_IDS cargados: {len(allowed_users)}\n"
        f"- OTP activos: {len(otp_store)}\n\n"
        "Usa /stats para métricas.",
        reply_markup=main_menu()
    )

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Acceso no autorizado.")
        return

    cleanup_expired()
    await update.message.reply_text(
        f"📈 Stats\n"
        f"- OTP generados: {metrics['otp_generated']}\n"
        f"- OTP verificados: {metrics['otp_verified']}\n"
        f"- OTP fallidos: {metrics['otp_failed']}\n"
        f"- Rate-limit bloqueos: {metrics['blocked_by_rl']}\n"
        f"- Denegados whitelist: {metrics['denied_by_whitelist']}\n"
        f"- Solicitudes acceso: {metrics['access_requests']}\n"
        f"- OTP activos: {len(otp_store)}\n"
        f"- Users permitidos (cargados): {len(allowed_users)}\n"
    )

# ================= CALLBACK BUTTONS =================
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    cleanup_expired()

    # Admin approve/deny
    if q.data.startswith("approve_"):
        if not is_admin(user_id):
            return
        uid = int(q.data.split("_", 1)[1])
        allowed_users.add(uid)  # temporal (hasta reinicio); permanente es Railway var
        await q.edit_message_text(f"✅ Autorizado (temporal): {uid}")
        await send_copy_paste_line(context, uid)
        return

    if q.data.startswith("deny_"):
        if not is_admin(user_id):
            return
        uid = int(q.data.split("_", 1)[1])
        await q.edit_message_text(f"❌ Denegado: {uid}")
        return

    # Si no está permitido, no seguimos
    if not is_allowed(user_id):
        metrics["denied_by_whitelist"] += 1
        return

    if q.data == "help":
        await q.edit_message_text(help_text(), reply_markup=main_menu())
        return

    if q.data == "whoami":
        uname = f"@{q.from_user.username}" if q.from_user.username else "(sin username)"
        await q.edit_message_text(
            f"🆔 Tu ID: `{q.from_user.id}`\nUsuario: {q.from_user.full_name}\nUsername: {uname}",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        return

    if q.data == "status":
        entry = otp_store.get(user_id)
        if not entry:
            await q.edit_message_text("📊 No hay OTP activo.", reply_markup=main_menu())
            return
        remaining = max(0, int(entry.expires_at - now()))
        await q.edit_message_text(
            f"📊 OTP activo\n⏳ Expira en: {remaining}s\n🔁 Intentos: {entry.attempts_left}",
            reply_markup=main_menu()
        )
        return

    if q.data == "gen":
        # rate limit
        last = last_gen_at.get(user_id, 0.0)
        wait = GEN_RATE_LIMIT_SECONDS - (now() - last)
        if wait > 0:
            metrics["blocked_by_rl"] += 1
            await q.edit_message_text(f"🚫 Límite. Espera {int(wait)}s.", reply_markup=main_menu())
            return

        code = gen_code()
        otp_store[user_id] = OTPEntry(code=code, expires_at=now() + OTP_TTL_SECONDS, attempts_left=OTP_MAX_ATTEMPTS)
        awaiting_code[user_id] = False
        last_gen_at[user_id] = now()
        metrics["otp_generated"] += 1

        if SHOW_OTP_IN_CHAT:
            await q.edit_message_text(f"🔐 OTP generado:\n`{code}`", parse_mode="Markdown", reply_markup=main_menu())
        else:
            await q.edit_message_text("🔐 OTP generado. Pulsa ✅ Verificar OTP y envía el código.", reply_markup=main_menu())
        return

    if q.data == "verify":
        awaiting_code[user_id] = True
        await q.edit_message_text("✅ Envía el OTP (6 dígitos).", reply_markup=main_menu())
        return

# ================= TEXT HANDLER =================
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cleanup_expired()
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    if not is_allowed(user_id):
        metrics["denied_by_whitelist"] += 1
        await update.message.reply_text("🔒 Acceso restringido. Solicitud enviada al administrador.")
        await notify_admin_access_request(context, update.effective_user)
        return

    if not awaiting_code.get(user_id, False):
        return

    entry: Optional[OTPEntry] = otp_store.get(user_id)
    if not entry:
        awaiting_code[user_id] = False
        await update.message.reply_text("❌ No hay OTP activo. Genera uno nuevo.", reply_markup=main_menu())
        return

    if not (text.isdigit() and len(text) == 6):
        await update.message.reply_text("⚠️ Formato inválido. Envía 6 dígitos.", reply_markup=main_menu())
        return

    if now() > entry.expires_at:
        otp_store.pop(user_id, None)
        awaiting_code[user_id] = False
        await update.message.reply_text("⏳ OTP expirado.", reply_markup=main_menu())
        return

    if entry.attempts_left <= 0:
        otp_store.pop(user_id, None)
        awaiting_code[user_id] = False
        await update.message.reply_text("🚫 OTP bloqueado. Genera uno nuevo.", reply_markup=main_menu())
        return

    if secrets.compare_digest(text, entry.code):
        otp_store.pop(user_id, None)
        awaiting_code[user_id] = False
        metrics["otp_verified"] += 1
        await update.message.reply_text("✅ OTP correcto.", reply_markup=main_menu())
    else:
        entry.attempts_left -= 1
        otp_store[user_id] = entry
        metrics["otp_failed"] += 1
        await update.message.reply_text(f"❌ OTP incorrecto. Intentos: {entry.attempts_left}", reply_markup=main_menu())

# ================= MAIN =================
def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Falta BOT_TOKEN en Railway")
    if not ADMIN_ID:
        raise SystemExit("Falta ADMIN_ID en Railway")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("status", cmd_status))

    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("stats", cmd_stats))

    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling()

if __name__ == "__main__":
    main()