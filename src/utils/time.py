from datetime import datetime, timedelta, timezone


def get_next_aligned_time(interval_seconds: int = 60) -> datetime:
    """
    Calculate next aligned time based on interval.

    Example:
        >>> # Current time: 14:23:47.123456
        >>> get_next_aligned_time(60)
        # Returns: 14:24:00.000000 (aligned to next minute)
    """
    now = datetime.now(timezone.utc)
    aligned_now = now.replace(second=0, microsecond=0)

    return aligned_now + timedelta(seconds=interval_seconds)
