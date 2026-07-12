import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import router
from app.database import init_database
from app.runtime import LocalRuntime

structlog.configure(processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()])
app = FastAPI(title="EGX Stock Intelligence", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://tauri.localhost", "https://tauri.localhost"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.on_event("startup")
async def startup() -> None:
    await init_database()
    await runtime.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await runtime.stop()
runtime = LocalRuntime()
