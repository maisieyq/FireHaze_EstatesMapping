
import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from update_data import update_data

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
INTERVAL_SECONDS = 60 * 60

status = {
    "state": "idle",
    "last_success": None,
    "last_attempt": None,
    "last_error": None,
    "reason": None,
}

update_lock = asyncio.Lock()
update_task = None


def utc_now():
    return datetime.now(timezone.utc).isoformat()


async def run_update(reason, force=False):
    async with update_lock:
        status["state"] = "updating"
        status["reason"] = reason
        status["last_attempt"] = utc_now()
        status["last_error"] = None

        try:
            # Run blocking GIS/API work outside the event loop.
            result = await asyncio.to_thread(
                update_data,
                force
            )

            status["state"] = "success"
            status["last_success"] = result["updated_at"]

        except Exception as exc:
            status["state"] = "failed"
            status["last_error"] = (
                f"{type(exc).__name__}: {str(exc)}"
            )
            print("Update failed:", exc)

        finally:
            status["reason"] = reason


async def hourly_scheduler():
    # Try refreshing immediately when the server starts.
    await run_update("startup", force=False)

    while True:
        await asyncio.sleep(INTERVAL_SECONDS)

        if not update_lock.locked():
            await run_update("automatic", force=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = asyncio.create_task(hourly_scheduler())

    try:
        yield
    finally:
        scheduler.cancel()

        try:
            await scheduler
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)


@app.get("/api/status")
async def get_status():
    return status.copy()


@app.post("/api/refresh")
async def refresh(
    x_admin_token: str | None = Header(default=None)
):
    global update_task

    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_TOKEN is not configured"
        )

    if not x_admin_token or not secrets.compare_digest(
        x_admin_token, ADMIN_TOKEN
    ):
        raise HTTPException(
            status_code=403,
            detail="Unauthorized"
        )

    if update_lock.locked() or (
        update_task is not None and not update_task.done()
    ):
        return JSONResponse(
            status_code=409,
            content={"message": "Update already running"}
        )

    update_task = asyncio.create_task(
        run_update("manual", force=True)
    )

    status["state"] = "queued"

    return {
        "message": "Refresh started",
        "state": "queued"
    }


# Must be last: serve the existing HTML/CSS/JS and JSON.
app.mount(
    "/",
    StaticFiles(
        directory=str(ROOT / "web"),
        html=True
    ),
    name="web"
)
