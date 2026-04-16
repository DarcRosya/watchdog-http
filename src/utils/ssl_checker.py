import ssl
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse


async def get_ssl_days_remaining(url: str) -> int | None:
    """Returns the number of days until the SSL certificate expires. None if there is an error or it is not HTTPS."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return None

    host = parsed.hostname
    port = parsed.port or 443

    ssl_context = ssl.create_default_context()

    try:
        # Open a raw TCP connection with SSL “wrapper”
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl_context), timeout=5.0
        )

        cert = writer.get_extra_info("peercert")
        writer.close()
        await writer.wait_closed()

        if not cert or "notAfter" not in cert:
            return None

        expire_str = cert["notAfter"]
        expire_date = datetime.strptime(expire_str, "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
        now = datetime.now(timezone.utc)

        return (expire_date - now).days

    except Exception:
        return None
