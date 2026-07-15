import asyncio
from contextlib import asynccontextmanager
import time
import uuid
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import router
from app.database import init_database
from app.diagnostics import configure_diagnostics, logger, structlog_file_processor, app_errors_path
from app.config import get_settings
from app.content_updates import ContentUpdateError, ContentUpdateService
from app.runtime import LocalRuntime

structlog.configure(processors=[
    structlog_file_processor(app_errors_path()),
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.JSONRenderer(),
])
diagnostic_log = configure_diagnostics()
runtime = LocalRuntime()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_database()
    logger().info("local_engine_started")
    await runtime.start()
    asyncio.create_task(refresh_content_updates())
    yield
    logger().info("local_engine_stopped")
    await runtime.stop()


app = FastAPI(title="EGX Stock Intelligence", version="0.1.71", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://tauri.localhost", "https://tauri.localhost"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.middleware("http")
async def record_api_request(request, call_next):
    request_id = uuid.uuid4().hex[:12]
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as error:
        diagnostic_log.exception(
            "api_request_failed",
            extra={"request_id": request_id, "method": request.method, "path": request.url.path,
                   "error_type": type(error).__name__},
        )
        raise
    duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
    diagnostic_log.info(
        "api_response",
        extra={"request_id": request_id, "method": request.method, "path": request.url.path,
               "status_code": response.status_code, "duration_ms": duration_ms},
    )
    response.headers["X-EGX-Request-ID"] = request_id
    return response


async def refresh_content_updates() -> None:
    try:
        result = await ContentUpdateService(get_settings()).check_and_apply()
        logger().info("content_update_checked", **result)
    except ContentUpdateError as error:
        logger().warning("content_update_check_failed", error=str(error))
