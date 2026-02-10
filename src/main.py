from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config.settings import settings
from src.core.logging import configure_logging, get_logger
from src.routes import users, monitors

# from src.utils.version import __version__

configure_logging(
    service="api",
    json_logs=not settings.debug_mode,
    log_level="DEBUG" if settings.debug_mode else "INFO",
    enable_file_logging=settings.enable_file_logging,
)
logger = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(
        "startup",
        debug_mode=settings.debug_mode,
        database_host=settings.db.HOST,
        database_port=settings.db.PORT,
        database_name=settings.db.NAME,
        redis_host=settings.redis.R_HOST,
        redis_port=settings.redis.R_PORT,
    )

    yield  # App is running

    logger.info("shutdown")


app = FastAPI(
    title="Watchdog HTTP Monitoring Service",
    version="1.7.7",
    description="""
    Watchdog is an autonomous, asynchronous web monitoring system. 
    It performs background health checks on target APIs and websites, 
    records performance metrics (latency, status codes) into TimescaleDB, 
    and instantly alerts owners via Telegram.
    """,
    debug=settings.debug_mode,
    lifespan=lifespan,
)

app.include_router(users.router, prefix="/api/v1")
app.include_router(monitors.router, prefix="/api/v1")


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "watchdog-api"}
