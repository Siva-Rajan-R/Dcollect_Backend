from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.mongodb import connect_to_mongo, close_mongo_connection
from app.core.redis import connect_to_redis, close_redis_connection
from app.core.minio import connect_to_minio
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await connect_to_mongo()
    await connect_to_redis()
    connect_to_minio()
    yield
    # Shutdown
    await close_mongo_connection()
    await close_redis_connection()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Set all CORS enabled origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.v1.api import api_router

app.include_router(api_router, prefix=settings.API_V1_STR)

from app.api.v1.qrcodes import redirect_qr
app.add_api_route("/qrcodes/r/{short_id}", redirect_qr, methods=["GET"])

from app.api.v1.cards import redirect_card
app.add_api_route("/cards/r/{short_id}", redirect_card, methods=["GET"])

@app.get("/health")
async def health_check():
    return {"status": "ok"}
