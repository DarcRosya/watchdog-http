from fastapi import FastAPI
from src.config.settings import settings

app = FastAPI(
    title="Watchdog Service",
    version="0.4.0",
    debug=settings.debug_mode
)

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "watchdog-api"}