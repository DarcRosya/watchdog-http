"""
Telegram bot for user verification and sending monitoring notifications.

Usage:
    python -m src.telegram.bot
"""

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select, update

from src.config.settings import settings
from src.core.database import async_session_factory
from src.models.user import User


router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Handle /start command."""
    await message.answer(
        "👋 Привет! Я бот для уведомлений Watchdog HTTP.\n\n"
        "Чтобы привязать свой аккаунт и получать уведомления о проблемах "
        "с вашими мониторами, отправьте мне ваш username (логин) из системы.\n\n"
        "Пример: просто напишите ваш username"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Handle /help command."""
    await message.answer(
        "📖 Справка по боту:\n\n"
        "1️⃣ Отправьте ваш username из системы Watchdog HTTP\n"
        "2️⃣ Если username найден, ваш Telegram будет привязан к аккаунту\n"
        "3️⃣ После привязки вы будете получать уведомления о проблемах с мониторами\n\n"
        "Команды:\n"
        "/start — Начать работу\n"
        "/help — Показать справку\n"
        "/status — Проверить статус привязки"
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """Check if user's Telegram is linked to an account."""
    telegram_id = message.from_user.id

    async with async_session_factory() as session:
        query = select(User).where(User.telegram_chat_id == telegram_id)
        result = await session.execute(query)
        user = result.scalars().first()

        if user:
            await message.answer(
                f"✅ Ваш Telegram привязан к аккаунту: {user.username}\n"
                "Вы будете получать уведомления о проблемах с мониторами."
            )
        else:
            await message.answer(
                "❌ Ваш Telegram не привязан ни к одному аккаунту.\n"
                "Отправьте ваш username для привязки."
            )


@router.message(F.text)
async def verify_username(message: Message) -> None:
    """
    Verify username and link Telegram account.
    User sends their username, bot checks DB and links telegram_chat_id.
    """
    username = message.text.strip()
    telegram_id = message.from_user.id

    if username.startswith("/"):
        await message.answer("❓ Неизвестная команда. Используйте /help для справки.")
        return

    async with async_session_factory() as session:
        existing_link_query = select(User).where(User.telegram_chat_id == telegram_id)
        existing_result = await session.execute(existing_link_query)
        existing_user = existing_result.scalars().first()

        if existing_user:
            if existing_user.username.lower() == username.lower():
                await message.answer(
                    f"ℹ️ Ваш Telegram уже привязан к аккаунту {existing_user.username}."
                )
            else:
                await message.answer(
                    f"⚠️ Ваш Telegram уже привязан к другому аккаунту: {existing_user.username}\n"
                    "Если хотите сменить привязку, сначала отвяжите текущий аккаунт через настройки."
                )
            return

        query = select(User).where(User.username.ilike(username))
        result = await session.execute(query)
        user = result.scalars().first()

        if not user:
            await message.answer(
                f"❌ Пользователь с username '{username}' не найден.\n"
                "Проверьте правильность написания и попробуйте снова."
            )
            return

        if user.telegram_chat_id and user.telegram_chat_id != telegram_id:
            await message.answer(
                "⚠️ К этому аккаунту уже привязан другой Telegram.\n"
                "Если это ваш аккаунт, отвяжите предыдущий Telegram через настройки."
            )
            return

        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(telegram_chat_id=telegram_id)
        )
        await session.commit()

        await message.answer(
            f"✅ Отлично! Ваш Telegram успешно привязан к аккаунту {user.username}!\n\n"
            "Теперь вы будете получать уведомления о проблемах с вашими мониторами:\n"
            "• Ошибки HTTP (4xx, 5xx)\n"
            "• Таймауты\n"
            "• Ошибки подключения\n"
            "• Другие проблемы"
        )


async def main() -> None:
    """Start the Telegram bot."""
    bot = Bot(token=settings.telegram.token)
    dp = Dispatcher()
    dp.include_router(router)

    print("=" * 60)
    print("🤖 TELEGRAM BOT STARTING")
    print("=" * 60)

    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
