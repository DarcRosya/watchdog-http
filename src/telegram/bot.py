import json
from typing import Any

import redis.asyncio as aioredis
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select, update

from src.core.database import async_session_factory
from src.core.logging import configure_logging, get_logger
from src.core.redis import create_redis_client
from src.core.settings import settings
from src.models.monitor import Monitor
from src.models.user import User

configure_logging(
    service="telegram",
    json_logs=not settings.debug_mode,
    log_level="DEBUG" if settings.debug_mode else "INFO",
    enable_file_logging=settings.enable_file_logging,
)
logger = get_logger("telegram")
router = Router()


async def refresh_user_monitor_cache(
    user_id: int,
    telegram_chat_id: int | None,
    redis_client: aioredis.Redis | None,
) -> None:
    """Update Redis cache for all monitors of a user after Telegram linking."""

    if redis_client is None:
        logger.debug("cache_refresh_skipped_no_redis", user_id=user_id)
        return

    async with async_session_factory() as session:
        query = select(Monitor.id).where(
            Monitor.user_id == user_id,
            Monitor.is_active == True,  # noqa: E712
        )
        result = await session.execute(query)
        monitor_ids = result.scalars().all()

    if not monitor_ids:
        logger.debug("cache_refresh_no_monitors", user_id=user_id)
        return

    async with redis_client.pipeline() as pipe:
        for monitor_id in monitor_ids:
            config_key = f"monitor:{monitor_id}:config"
            pipe.get(config_key)
            pipe.ttl(config_key)

        # [config1, ttl1, config2, ttl2, ...]
        # [index0, index1, index2, index3, ...]
        read_results: list[Any] = await pipe.execute()

    updated = 0

    async with redis_client.pipeline() as pipe:
        for i, monitor_id in enumerate(monitor_ids):
            config_raw = read_results[i * 2]  # Even indexes are configs
            ttl = read_results[i * 2 + 1]  # Odd indexes are TTL

            if config_raw:
                config: dict[str, Any] = json.loads(config_raw)
                config["telegram_chat_id"] = telegram_chat_id

                if ttl < 0:
                    ttl = 86400

                config_key = f"monitor:{monitor_id}:config"
                pipe.setex(config_key, ttl, json.dumps(config))
                updated += 1

        if updated > 0:
            await pipe.execute()

    logger.info(
        "monitor_cache_refreshed",
        user_id=user_id,
        telegram_chat_id=telegram_chat_id,
        monitors_found=len(monitor_ids),
        configs_updated=updated,
    )


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

        # Refresh Redis cache so workers pick up the new telegram_chat_id
        try:
            await refresh_user_monitor_cache(user.id, telegram_id, _bot_redis)
        except Exception as e:
            logger.error(
                "cache_refresh_failed",
                user_id=user.id,
                error=str(e),
            )

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


_bot_redis: aioredis.Redis | None = None


async def main() -> None:
    global _bot_redis

    configure_logging(
        service="telegram",
        json_logs=not settings.debug_mode,
        log_level="DEBUG" if settings.debug_mode else "INFO",
    )

    _bot_redis = create_redis_client(
        host=settings.redis.R_HOST,
        port=settings.redis.R_PORT,
    )

    bot = Bot(token=settings.telegram.token)
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("startup", bot_username="watchdog_bot")

    try:
        await dp.start_polling(bot)  # type: ignore
    finally:
        await _bot_redis.aclose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
