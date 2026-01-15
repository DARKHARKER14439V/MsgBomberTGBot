import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

from config import Config


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


REGISTER_NAME, REGISTER_AGE, REGISTER_DONE = range(3)
FEEDBACK_TEXT, FEEDBACK_CONFIRM = range(3, 5)
BROADCAST_TEXT, BROADCAST_CONFIRM = range(5, 7)
UTILITY_MENU, UTILITY_WAIT_INPUT = range(7, 9)


@dataclass
class UserProfile:
    user_id: int
    name: Optional[str] = None
    age: Optional[int] = None
    created_at: float = field(default_factory=time.time)


@dataclass
class FeedbackEntry:
    user_id: int
    username: Optional[str]
    text: str
    created_at: float = field(default_factory=time.time)


class InMemoryStore:
    def __init__(self) -> None:
        self.profiles: Dict[int, UserProfile] = {}
        self.feedback: List[FeedbackEntry] = []
        self.blocked_users: Set[int] = set()

    def get_or_create_profile(self, user_id: int) -> UserProfile:
        if user_id not in self.profiles:
            self.profiles[user_id] = UserProfile(user_id=user_id)
        return self.profiles[user_id]

    def update_profile_name(self, user_id: int, name: str) -> None:
        profile = self.get_or_create_profile(user_id)
        profile.name = name

    def update_profile_age(self, user_id: int, age: int) -> None:
        profile = self.get_or_create_profile(user_id)
        profile.age = age

    def add_feedback(self, entry: FeedbackEntry) -> None:
        self.feedback.append(entry)

    def get_recent_feedback(self, limit: int = 10) -> List[FeedbackEntry]:
        return list(self.feedback[-limit:])

    def block_user(self, user_id: int) -> None:
        self.blocked_users.add(user_id)

    def unblock_user(self, user_id: int) -> None:
        self.blocked_users.discard(user_id)

    def is_blocked(self, user_id: int) -> bool:
        return user_id in self.blocked_users


store = InMemoryStore()


def is_authorized(user_id: Optional[int]) -> bool:
    if user_id is None:
        return False
    try:
        return int(user_id) in Config.AUTH_USERS
    except Exception:
        return False


def format_profile(profile: UserProfile) -> str:
    parts: List[str] = []
    parts.append(f"ID: {profile.user_id}")
    if profile.name:
        parts.append(f"Name: {profile.name}")
    if profile.age is not None:
        parts.append(f"Age: {profile.age}")
    created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(profile.created_at))
    parts.append(f"Registered: {created}")
    return "\n".join(parts)


def build_main_menu_keyboard(is_admin: bool) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("Profile", callback_data="menu_profile"),
            InlineKeyboardButton("Utilities", callback_data="menu_utilities"),
        ],
        [InlineKeyboardButton("Feedback", callback_data="menu_feedback")],
    ]
    if is_admin:
        buttons.append(
            [
                InlineKeyboardButton("Admin: Broadcast", callback_data="menu_admin_broadcast"),
            ]
        )
    return InlineKeyboardMarkup(buttons)


def build_yes_no_keyboard(prefix: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("Yes", callback_data=f"{prefix}:yes"),
            InlineKeyboardButton("No", callback_data=f"{prefix}:no"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)


def build_utility_menu_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("Echo", callback_data="util_echo"),
            InlineKeyboardButton("Roll Dice", callback_data="util_dice"),
        ],
        [
            InlineKeyboardButton("Random Number", callback_data="util_random"),
            InlineKeyboardButton("Back", callback_data="util_back"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    profile = store.get_or_create_profile(user.id)
    if profile.name is None and user.full_name:
        store.update_profile_name(user.id, user.full_name)
    is_admin = is_authorized(user.id)
    keyboard = build_main_menu_keyboard(is_admin=is_admin)
    text = (
        "Welcome to the utility bot.\n"
        "Use the buttons below or commands:\n"
        "/register, /profile, /feedback, /help"
    )
    await update.message.reply_text(text, reply_markup=keyboard)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines: List[str] = []
    lines.append("Available commands:")
    lines.append("/start - Show main menu")
    lines.append("/register - Create or update your profile")
    lines.append("/profile - Show your profile information")
    lines.append("/feedback - Send feedback to the admins")
    lines.append("/echo <text> - Echo back text")
    if is_authorized(update.effective_user.id if update.effective_user else None):
        lines.append("/broadcast - Send a message to all known users")
        lines.append("/admin_feedback - Show recent feedback entries")
    await update.message.reply_text("\n".join(lines))


async def echo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        await update.message.reply_text(" ".join(context.args))
    else:
        await update.message.reply_text("Send text after /echo to repeat it.")


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    profile = store.get_or_create_profile(user.id)
    text = format_profile(profile)
    await update.message.reply_text(text)


async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user is None:
        return ConversationHandler.END
    profile = store.get_or_create_profile(user.id)
    if profile.name:
        await update.message.reply_text(
            f"Your current name is: {profile.name}\nSend a new name or /cancel."
        )
    else:
        await update.message.reply_text("Send your name.")
    return REGISTER_NAME


async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user is None or update.message is None:
        return ConversationHandler.END
    name_text = update.message.text.strip()
    if not name_text:
        await update.message.reply_text("Name cannot be empty. Send your name.")
        return REGISTER_NAME
    store.update_profile_name(user.id, name_text)
    await update.message.reply_text("Now send your age as a number.")
    return REGISTER_AGE


async def register_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user is None or update.message is None:
        return ConversationHandler.END
    text = update.message.text.strip()
    try:
        age_val = int(text)
    except ValueError:
        await update.message.reply_text("Age must be a number. Send it again.")
        return REGISTER_AGE
    if age_val <= 0 or age_val > 120:
        await update.message.reply_text("Age seems invalid. Send a realistic age.")
        return REGISTER_AGE
    store.update_profile_age(user.id, age_val)
    profile = store.get_or_create_profile(user.id)
    summary = format_profile(profile)
    await update.message.reply_text(f"Registration completed:\n\n{summary}")
    return ConversationHandler.END


async def register_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Registration cancelled.")
    return ConversationHandler.END


async def feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Send your feedback text or /cancel.")
    return FEEDBACK_TEXT


async def feedback_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return ConversationHandler.END
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("Feedback cannot be empty. Send your text.")
        return FEEDBACK_TEXT
    context.user_data["pending_feedback"] = text
    keyboard = build_yes_no_keyboard("feedback_confirm")
    await update.message.reply_text(
        "Do you want to send this feedback?", reply_markup=keyboard
    )
    return FEEDBACK_CONFIRM


async def feedback_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    text = context.user_data.get("pending_feedback")
    if text is None:
        await query.edit_message_text("No feedback to send.")
        return ConversationHandler.END
    if data.endswith("yes"):
        user = query.from_user
        entry = FeedbackEntry(
            user_id=user.id,
            username=user.username,
            text=text,
        )
        store.add_feedback(entry)
        for admin_id in Config.AUTH_USERS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"New feedback from {user.id} (@{user.username}):\n{text}",
                )
            except Exception as exc:
                logger.warning("Failed to send feedback to admin %s: %s", admin_id, exc)
        await query.edit_message_text("Feedback sent. Thank you.")
    else:
        await query.edit_message_text("Feedback discarded.")
    context.user_data.pop("pending_feedback", None)
    return ConversationHandler.END


async def feedback_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Feedback cancelled.")
    context.user_data.pop("pending_feedback", None)
    return ConversationHandler.END


async def admin_show_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_authorized(user.id if user else None):
        await update.message.reply_text("You are not authorized to use this command.")
        return
    entries = store.get_recent_feedback(limit=10)
    if not entries:
        await update.message.reply_text("No feedback yet.")
        return
    lines: List[str] = []
    for entry in entries:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.created_at))
        lines.append(
            f"[{ts}] from {entry.user_id} (@{entry.username}):\n{entry.text}\n"
        )
    await update.message.reply_text("\n".join(lines))


async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_authorized(user.id if user else None):
        await update.message.reply_text("You are not authorized to broadcast.")
        return ConversationHandler.END
    await update.message.reply_text("Send the broadcast message text or /cancel.")
    return BROADCAST_TEXT


async def broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("Broadcast text cannot be empty.")
        return BROADCAST_TEXT
    context.user_data["pending_broadcast"] = text
    keyboard = build_yes_no_keyboard("broadcast_confirm")
    await update.message.reply_text(
        "Send this message to all known users?", reply_markup=keyboard
    )
    return BROADCAST_CONFIRM


async def broadcast_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    text = context.user_data.get("pending_broadcast")
    if text is None:
        await query.edit_message_text("No broadcast pending.")
        return ConversationHandler.END
    if not is_authorized(query.from_user.id if query.from_user else None):
        await query.edit_message_text("Not authorized.")
        return ConversationHandler.END
    if data.endswith("yes"):
        targets = list(store.profiles.keys())
        sent = 0
        failed = 0
        for user_id in targets:
            try:
                if store.is_blocked(user_id):
                    continue
                await context.bot.send_message(chat_id=user_id, text=text)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception as exc:
                logger.warning("Failed to send broadcast to %s: %s", user_id, exc)
                failed += 1
        await query.edit_message_text(
            f"Broadcast finished. Sent: {sent}, failed: {failed}."
        )
    else:
        await query.edit_message_text("Broadcast cancelled.")
    context.user_data.pop("pending_broadcast", None)
    return ConversationHandler.END


async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Broadcast cancelled.")
    context.user_data.pop("pending_broadcast", None)
    return ConversationHandler.END


async def button_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data or ""
    if data == "menu_profile":
        profile = store.get_or_create_profile(user.id)
        text = format_profile(profile)
        await query.edit_message_text(text)
    elif data == "menu_utilities":
        keyboard = build_utility_menu_keyboard()
        await query.edit_message_text("Choose a utility:", reply_markup=keyboard)
        context.user_data["utility_mode"] = None
    elif data == "menu_feedback":
        await query.edit_message_text(
            "Use /feedback to send feedback message to admins."
        )
    elif data == "menu_admin_broadcast":
        if not is_authorized(user.id if user else None):
            await query.edit_message_text("You are not authorized for admin actions.")
        else:
            await query.edit_message_text(
                "Use /broadcast to send message to all known users."
            )


async def utility_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "util_back":
        user = query.from_user
        keyboard = build_main_menu_keyboard(is_authorized(user.id if user else None))
        await query.edit_message_text("Main menu:", reply_markup=keyboard)
        context.user_data["utility_mode"] = None
        return
    if data == "util_echo":
        context.user_data["utility_mode"] = "echo"
        await query.edit_message_text("Send text and I will echo it.")
    elif data == "util_dice":
        value = random.randint(1, 6)
        await query.edit_message_text(f"Dice rolled: {value}")
        context.user_data["utility_mode"] = None
    elif data == "util_random":
        value = random.randint(0, 100)
        await query.edit_message_text(f"Random number: {value}")
        context.user_data["utility_mode"] = None


async def utility_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mode = context.user_data.get("utility_mode")
    if mode == "echo" and update.message is not None:
        await update.message.reply_text(update.message.text)
    else:
        if update.message is not None:
            await update.message.reply_text(
                "I do not understand. Use /help or /start."
            )


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Unknown command. Use /help.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling update %s", update, exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="An error occurred while processing your request.",
            )
    except Exception as exc:
        logger.error("Failed to send error message: %s", exc)


def build_application() -> Application:
    app = Application.builder().token(Config.BOT_TOKEN).build()
    register_conv = ConversationHandler(
        entry_points=[CommandHandler("register", register_start)],
        states={
            REGISTER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)
            ],
            REGISTER_AGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_age)
            ],
        },
        fallbacks=[CommandHandler("cancel", register_cancel)],
    )
    feedback_conv = ConversationHandler(
        entry_points=[CommandHandler("feedback", feedback_start)],
        states={
            FEEDBACK_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_text)
            ],
            FEEDBACK_CONFIRM: [
                CallbackQueryHandler(
                    feedback_decision, pattern=r"^feedback_confirm:(yes|no)$"
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", feedback_cancel)],
    )
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={
            BROADCAST_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_text)
            ],
            BROADCAST_CONFIRM: [
                CallbackQueryHandler(
                    broadcast_decision, pattern=r"^broadcast_confirm:(yes|no)$"
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", broadcast_cancel)],
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("echo", echo_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("admin_feedback", admin_show_feedback))
    app.add_handler(register_conv)
    app.add_handler(feedback_conv)
    app.add_handler(broadcast_conv)
    app.add_handler(
        CallbackQueryHandler(
            button_main_menu,
            pattern=r"^(menu_profile|menu_utilities|menu_feedback|menu_admin_broadcast)$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            utility_menu_handler, pattern=r"^util_(echo|dice|random|back)$"
        )
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            utility_text_handler,
        )
    )
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    app.add_error_handler(error_handler)
    return app


async def main() -> None:
    app = build_application()
    logger.info("Bot is starting with long polling.")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    asyncio.run(main())
