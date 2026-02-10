from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select, update

from src.config.settings import settings
from src.core.database import async_session_factory
from src.core.logging import configure_logging, get_logger
from src.models.user import User

configure_logging(
    service="telegram",
    json_logs=not settings.debug_mode,
    log_level="DEBUG" if settings.debug_mode else "INFO",
    enable_file_logging=settings.enable_file_logging,
)
logger = get_logger("telegram")
router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Handle /start command."""
    if not message.from_user:
        return
    logger.info(
        "command_received",
        command="start",
        user_id=message.from_user.id,
        username=message.from_user.username,
    )
    await message.answer(
        "👋 Hello! I'm the Watchdog HTTP notification bot.\n\n"
        "To link your account and receive notifications about issues "
        "with your monitors, send me your username (login) from the system.\n\n"
        "Example: just type your username"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Handle /help command."""
    if not message.from_user:
        return
    logger.info(
        "command_received",
        command="help",
        user_id=message.from_user.id,
        username=message.from_user.username,
    )
    await message.answer(
        "📖 Bot Help:\n\n"
        "1️⃣ Send your username from the Watchdog HTTP system\n"
        "2️⃣ If username is found, your Telegram will be linked to the account\n"
        "3️⃣ After linking, you will receive notifications about monitor issues\n\n"
        "Commands:\n"
        "/start — Start the bot\n"
        "/help — Show help\n"
        "/status — Check linking status"
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """Check if user's Telegram is linked to an account."""
    if not message.from_user:
        return
    telegram_id = message.from_user.id
    logger.info(
        "command_received",
        command="status",
        user_id=telegram_id,
        username=message.from_user.username,
    )

    async with async_session_factory() as session:
        query = select(User).where(User.telegram_chat_id == telegram_id)
        result = await session.execute(query)
        user = result.scalars().first()

        if user:
            await message.answer(
                f"✅ Your Telegram is linked to account: {user.username}\n"
                "You will receive notifications about monitor issues."
            )
        else:
            await message.answer(
                "❌ Your Telegram is not linked to any account.\n"
                "Send your username to link."
            )


@router.message(F.text)
async def verify_username(message: Message) -> None:
    """
    Verify username and link Telegram account.
    User sends their username, bot checks DB and links telegram_chat_id.
    """
    if not message.text or not message.from_user:
        return
    username = message.text.strip()
    telegram_id = message.from_user.id

    if username.startswith("/"):
        logger.debug("unknown_command", text=username, user_id=telegram_id)
        await message.answer("❓ Unknown command. Use /help for help.")
        return

    logger.info(
        "username_verification_attempt",
        username=username,
        user_id=telegram_id,
        telegram_username=message.from_user.username,
    )

    async with async_session_factory() as session:
        existing_link_query = select(User).where(User.telegram_chat_id == telegram_id)
        existing_result = await session.execute(existing_link_query)
        existing_user = existing_result.scalars().first()

        if existing_user:
            if existing_user.username.lower() == username.lower():
                await message.answer(
                    f"ℹ️ Your Telegram is already linked to account {existing_user.username}."
                )
            else:
                await message.answer(
                    f"⚠️ Your Telegram is already linked to another account: {existing_user.username}\n"
                    "If you want to change the link, first unlink the current account via settings."
                )
            return

        query = select(User).where(User.username.ilike(username))
        result = await session.execute(query)
        user = result.scalars().first()

        if not user:
            await message.answer(
                f"❌ User with username '{username}' not found.\n"
                "Check the spelling and try again."
            )
            return

        if user.telegram_chat_id and user.telegram_chat_id != telegram_id:
            await message.answer(
                "⚠️ This account is already linked to another Telegram.\n"
                "If this is your account, unlink the previous Telegram via settings."
            )
            return

        await session.execute(
            update(User).where(User.id == user.id).values(telegram_chat_id=telegram_id)
        )
        await session.commit()

        logger.info(
            "telegram_linked",
            username=user.username,
            user_id=user.id,
            telegram_chat_id=telegram_id,
            telegram_username=message.from_user.username,
        )

        await message.answer(
            f"✅ Great! Your Telegram has been successfully linked to account {user.username}!\n\n"
            "Now you will receive notifications about issues with your monitors:\n"
            "• HTTP errors (4xx, 5xx)\n"
            "• Timeouts\n"
            "• Connection errors\n"
            "• Other issues"
        )


async def main() -> None:
    configure_logging(
        service="telegram",
        json_logs=not settings.debug_mode,
        log_level="DEBUG" if settings.debug_mode else "INFO",
    )

    bot = Bot(token=settings.telegram.token)
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("startup", bot_username="watchdog_bot")

    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
