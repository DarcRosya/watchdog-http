from enum import Enum

import httpx

from src.config.settings import settings


class AlertType(Enum):
    """Types of alerts that can be sent."""
    HTTP_ERROR = "http_error"           # 4xx, 5xx responses
    TIMEOUT = "timeout"                  # Request timeout
    CONNECTION_ERROR = "connection"      # Cannot connect to host
    REQUEST_ERROR = "request"            # Other request failures
    RECOVERY = "recovery"                # Site is back online



class TelegramNotifier:
    """
    Sends notifications via Telegram Bot API.
    Uses httpx for async HTTP requests (reuses existing httpx client in worker).
    """

    TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self.token = settings.telegram.token
        self.api_url = self.TELEGRAM_API_URL.format(token=self.token)
        self._http_client = http_client
        self._own_client = False

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
            self._own_client = True
        return self._http_client

    async def close(self) -> None:
        """Close HTTP client if we created it."""
        if self._own_client and self._http_client:
            await self._http_client.aclose()

    async def send_message(self, chat_id: int, text: str, parse_mode: str = "HTML") -> bool:
        client = await self._get_client()

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            response = await client.post(self.api_url, json=payload)

            if response.status_code == 200:
                return True
            else:
                print(f"⚠️ Telegram API error: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            print(f"❌ Failed to send Telegram message: {e}")
            return False

    async def send_alert(self, chat_id: int, text: str) -> bool:
        return await self.send_message(chat_id, text)


# Pre-formatted messages for quick notifications
PREDEFINED_MESSAGES = {
    AlertType.HTTP_ERROR: (
        "🔴 <b>HTTP Ошибка</b>\n\n"
        "📍 {monitor_name}\n"
        "🔗 {url}\n\n"
        "Код ответа: {status_code}"
        "{duration_part}"
    ),
    AlertType.TIMEOUT: (
        "⏱️ <b>Таймаут</b>\n\n"
        "📍 {monitor_name}\n"
        "🔗 {url}\n\n"
        "Сайт не ответил в течение установленного времени ожидания."
    ),
    AlertType.CONNECTION_ERROR: (
        "🔌 <b>Ошибка подключения</b>\n\n"
        "📍 {monitor_name}\n"
        "🔗 {url}\n\n"
        "Не удалось установить соединение с сервером.\n"
        "Возможные причины: сервер недоступен, проблемы с DNS, сеть."
    ),
    AlertType.REQUEST_ERROR: (
        "❌ <b>Ошибка запроса</b>\n\n"
        "📍 {monitor_name}\n"
        "🔗 {url}\n\n"
        "Произошла ошибка при выполнении запроса:\n"
        "{error}"
    ),
}


def get_predefined_message(
    alert_type: AlertType,
    monitor_name: str,
    url: str,
    error: str | None = None,
    status_code: int | None = None,
    duration_ms: int | None = None
) -> str:
    """Get a pre-formatted message for quick notifications."""
    template = PREDEFINED_MESSAGES.get(alert_type, "⚠️ Проблема с мониторингом {url}")
    
    # Format duration nicely if provided
    duration_part = f"\n⏱ Время ответа: {duration_ms}ms" if duration_ms else ""
    
    return template.format(
        monitor_name=monitor_name or "Noname",
        url=url,
        status_code=status_code or "?",
        duration_part=duration_part,
        error=error or "Unknown Error"
    )
