import os
import time
import secrets
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OTP_TTL = int(os.getenv("OTP_TTL_SECONDS", "180"))

OTP_STORE = {}
BRAND = "IL MARROCHINO | OTP SECURITY"

def main_menu():
    keyboard = [
        [InlineKeyboardButton("🔑 Generar OTP", callback_data="gen")],
        [InlineKeyboardButton("✅ Verificar OTP", callback_data="verify")],
        [InlineKeyboardButton("📊 Estado", callback_data="status")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"{BRAND}\n\n🔐 Sistema OTP activo.\nSelecciona una opción:",
        reply_markup=main_menu()
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "gen":
        code = f"{secrets.randbelow(1_000_000):06d}"
        OTP_STORE[user_id] = (code, time.time() + OTP_TTL)

        await query.edit_message_text(
            f"{BRAND}\n\n🔑 OTP generado:\n`{code}`\n\n⏳ Válido por {OTP_TTL//60} min.",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    elif query.data == "verify":
        await query.edit_message_text(
            f"{BRAND}\n\n✅ Envíame el código OTP (6 dígitos).",
            reply_markup=main_menu()
        )

    elif query.data == "status":
        entry = OTP_STORE.get(user_id)
        if not entry:
            await query.edit_message_text(
                f"{BRAND}\n\n📊 No hay OTP activo.",
                reply_markup=main_menu()
            )
            return

        code, exp = entry
        if exp < time.time():
            OTP_STORE.pop(user_id, None)
            await query.edit_message_text(
                f"{BRAND}\n\n📊 OTP expirado.",
                reply_markup=main_menu()
            )
            return

        remaining = int(exp - time.time())
        await query.edit_message_text(
            f"{BRAND}\n\n📊 OTP activo.\nExpira en {remaining} segundos.",
            reply_markup=main_menu()
        )

async def check_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    entry = OTP_STORE.get(user_id)
    if not entry:
        return

    code, exp = entry
    if exp < time.time():
        OTP_STORE.pop(user_id, None)
        await update.message.reply_text("❌ OTP expirado.")
        return

    if text.isdigit() and len(text) == 6 and secrets.compare_digest(text, code):
        OTP_STORE.pop(user_id, None)
        await update.message.reply_text("✅ OTP verificado correctamente.", reply_markup=main_menu())
    else:
        await update.message.reply_text("❌ OTP incorrecto.")

def main():
    if not BOT_TOKEN:
        raise SystemExit("Falta BOT_TOKEN en variables de entorno (Railway).")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_otp))

    app.run_polling()

if __name__ == "__main__":
    main()
