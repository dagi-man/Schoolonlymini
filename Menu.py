#!/usr/bin/env python3
"""
Felege Neway Academy — Telegram Bot
Menu: School App | School Group | Help
Deploy independently (Render, Railway, VPS, etc.)
"""

import os
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
SCHOOL_APP_URL = "https://schoolonlymini-3.onrender.com"
SCHOOL_GROUP_URL = "https://t.me/felegenewayacademy"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# KEYBOARD
# ──────────────────────────────────────────────
def main_menu():
    keyboard = [
        [KeyboardButton("📱 School App"), KeyboardButton("👥 School Group")],
        [KeyboardButton("ℹ️ Help")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ──────────────────────────────────────────────
# HANDLERS
# ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name or "there"

    text = (
        f"Welcome, {name} 👋\n\n"
        "This is the official <b>Felege Neway Academy</b> School Management Bot.\n\n"
        "Use the menu below to access the school application, "
        "join the official school group, or view help information."
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>Felege Neway Academy — School Management Bot</b>\n\n"
        "This is the official digital assistant of <b>Felege Neway Academy</b>.\n\n"
        "Through this bot you can:\n"
        "• Open the School Academic Management Mini App\n"
        "• Join the official school Telegram group\n"
        "• Receive important announcements and support\n\n"
        "The School App allows students, teachers, and administrators "
        "to manage classes, assessments, results, and academic records "
        "in a secure and organized manner.\n\n"
        "If you require further assistance, please contact the school administration."
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu())


async def school_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Open School App", url=SCHOOL_APP_URL)]
    ])
    await update.message.reply_text(
        "<b>School Academic Management App</b>\n\n"
        "Tap the button below to open the official school management system.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def school_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Join School Group", url=SCHOOL_GROUP_URL)]
    ])
    await update.message.reply_text(
        "<b>Official School Group</b>\n\n"
        "Tap the button below to join the Felege Neway Academy community group.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle menu button presses."""
    text = (update.message.text or "").strip()

    if text == "📱 School App":
        await school_app(update, context)
    elif text == "👥 School Group":
        await school_group(update, context)
    elif text == "ℹ️ Help":
        await help_command(update, context)
    else:
        await update.message.reply_text(
            "Please use the menu buttons below.",
            reply_markup=main_menu(),
        )


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "ERROR: BOT_TOKEN is not set.\n"
            "Add it as an environment variable before starting the bot."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("Felege Neway Academy Bot is starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
