import os
import time
import secrets
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = "8648361748:AAFbDnWn0AA27PJ1HZy7zX5Txe451pxCo2M"

OTP_STORE = {}
OTP_TTL = 180  # 3 minutos

BRAND = "𝗜𝗟 𝗠𝗔𝗥𝗥𝗢𝗖𝗖𝗛𝗜𝗡𝗢 │ 𝗢𝗧𝗣 𝗦𝗘𝗖𝗨𝗥𝗜𝗧𝗬"

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
        code = f"{secrets.randbelow(1000000):06d}"
        OTP_STORE[user_id] = (code, time.time() + OTP_TTL)
        await query.edit_message_text(
            f"{BRAND}\n\n🔑 OTP generado:\n`{code}`\n\n⏳ Válido por 3 minutos.",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    elif query.data == "verify":
        await query.edit_message_text(
            f"{BRAND}\n\nEnvía el código OTP de 6 dígitos.",
            reply_markup=main_menu()
        )

    elif query.data == "status":
        entry = OTP_STORE.get(user_id)
        if not entry or entry[1] < time.time():
            await query.edit_message_text(
                f"{BRAND}\n\n📊 No hay OTP activo.",
                reply_markup=main_menu()
            )
        else:
            remaining = int(entry[1] - time.time())
            await query.edit_message_text(
                f"{BRAND}\n\n📊 OTP activo.\nExpira en {remaining} segundos.",
                reply_markup=main_menu()
            )

async def check_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    entry = OTP_STORE.get(user_id)
    if not entry:
        return

    if entry[1] < time.time():
        OTP_STORE.pop(user_id)
        await update.message.reply_text("❌ OTP expirado.")
        return

    if text == entry[0]: