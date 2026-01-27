from fastapi import FastAPI

from src.config.settings import settings
from src.routes import users, monitors


app = FastAPI(
    title="Watchdog HTTP Monitoring Service",
    version="0.8.2",
    description="""
    Watchdog is an autonomous, asynchronous web monitoring system. 
    It performs background health checks on target APIs and websites, 
    records performance metrics (latency, status codes) into TimescaleDB, 
    and instantly alerts owners via Telegram.
    """,
    debug=settings.debug_mode,
)

app.include_router(users.router, prefix="/api/v1")
app.include_router(monitors.router, prefix="/api/v1")


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "watchdog-api"}


@app.on_event("startup")
async def startup_event():
    print("🚀 Watchdog API starting up...")
    print(f"📊 Debug mode: {settings.debug_mode}")
    print(f"🗄️ Database: {settings.db.HOST}:{settings.db.PORT}/{settings.db.NAME}")
    print(f"📮 Redis: {settings.redis.R_HOST}:{settings.redis.R_PORT}")


@app.on_event("shutdown")
async def shutdown_event():
    print("🛑 Watchdog API shutting down...")