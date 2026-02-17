from enum import Enum

import httpx

from src.config.settings import settings
from src.core.logging import get_logger

logger = get_logger("telegram")


class AlertType(Enum):
    """Types of alerts that can be sent."""

    HTTP_ERROR = "http_error"  # 4xx, 5xx responses
    TIMEOUT = "timeout"  # Request timeout
    CONNECTION_ERROR = "connection"  # Cannot connect to host
    REQUEST_ERROR = "request"  # Other request failures
    RECOVERY = "recovery"  # Site is back online


# HTTP status code error descriptions
HTTP_STATUS_ERRORS = {
    # Client errors (4xx)
    400: "Bad Request",
    401: "Unauthorized",
    402: "Payment Required",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    406: "Not Acceptable",
    407: "Proxy Authentication Required",
    408: "Request Timeout",
    409: "Conflict",
    410: "Gone",
    411: "Length Required",
    412: "Precondition Failed",
    413: "Payload Too Large",
    414: "URI Too Long",
    415: "Unsupported Media Type",
    416: "Range Not Satisfiable",
    417: "Expectation Failed",
    418: "I'm a teapot",
    421: "Misdirected Request",
    422: "Unprocessable Entity",
    423: "Locked",
    424: "Failed Dependency",
    425: "Too Early",
    426: "Upgrade Required",
    428: "Precondition Required",
    429: "Too Many Requests",
    431: "Request Header Fields Too Large",
    451: "Unavailable For Legal Reasons",
    # Server errors (5xx)
    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
    505: "HTTP Version Not Supported",
    506: "Variant Also Negotiates",
    507: "Insufficient Storage",
    508: "Loop Detected",
    510: "Not Extended",
    511: "Network Authentication Required",
}


def get_http_error_description(status_code: int) -> str:
    return HTTP_STATUS_ERRORS.get(
        status_code, f"HTTP Error {status_code}" if status_code else "Unknown Error"
    )


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

    async def send_message(
        self, chat_id: int, text: str, parse_mode: str = "HTML"
    ) -> bool:
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
                logger.warning(
                    "telegram_api_error",
                    status_code=response.status_code,
                    response=response.text,
                    chat_id=chat_id,
                )
                return False

        except Exception as e:
            logger.error("telegram_send_failed", error=str(e), chat_id=chat_id)
            return False

    async def send_alert(self, chat_id: int, text: str) -> bool:
        return await self.send_message(chat_id, text)


PREDEFINED_MESSAGES = {
    AlertType.HTTP_ERROR: (
        "🔴 <b>HTTP Error</b>\n\n"
        "📍 {monitor_name}\n"
        "🔗 {url}\n\n"
        "Status Code: {status_code}\n"
        "Reason: {error}"
        "{duration_part}"
    ),
    AlertType.TIMEOUT: (
        "⏱️ <b>Timeout</b>\n\n"
        "📍 {monitor_name}\n"
        "🔗 {url}\n\n"
        "The site did not respond within the expected time."
    ),
    AlertType.CONNECTION_ERROR: (
        "🔌 <b>Connection Error</b>\n\n"
        "📍 {monitor_name}\n"
        "🔗 {url}\n\n"
        "Failed to establish connection to the server.\n"
        "Possible causes: server unavailable, DNS issues, network problems."
    ),
    AlertType.REQUEST_ERROR: (
        "❌ <b>Request Error</b>\n\n"
        "📍 {monitor_name}\n"
        "🔗 {url}\n\n"
        "An error occurred while executing the request:\n"
        "{error}"
    ),
    AlertType.RECOVERY: (
        "✅ <b>Recovered</b>\n\n"
        "📍 {monitor_name}\n"
        "🔗 {url}\n\n"
        "The service is back online and responding normally."
    ),
}


def get_predefined_message(
    alert_type: AlertType,
    monitor_name: str,
    url: str,
    error: str | None = None,
    status_code: int | None = None,
    duration_ms: int | None = None,
) -> str:
    """Get a pre-formatted message for quick notifications."""
    template = PREDEFINED_MESSAGES.get(alert_type, "⚠️ Monitoring issue {url}")

    # Format duration nicely if provided
    duration_part = f"\n⏱ Response time: {duration_ms}ms" if duration_ms else ""

    # Get detailed error description for HTTP errors
    if alert_type == AlertType.HTTP_ERROR and status_code:
        error = get_http_error_description(status_code)

    return template.format(
        monitor_name=monitor_name or "Noname",
        url=url,
        status_code=status_code or "?",
        duration_part=duration_part,
        error=error or "Unknown Error",
    )
