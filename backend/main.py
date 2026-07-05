import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import init_db
from core.vectordb import init_collection
from core.logger import logger
from config import UPLOAD_DIR
from api.chat import router as chat_router
from api.conversations import router as conversations_router
from api.documents import router as documents_router
from api.auth import router as auth_router
from api.widget_chat import router as widget_chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    await init_db()
    init_collection()
    logger.info("服务启动",
                extra={"event": "startup", "db": "ok", "milvus": "ok"})
    print("[启动] 数据库表已创建，Milvus 集合已就绪")
    yield


app = FastAPI(title="RAG Agent API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(widget_chat_router, prefix="/api")

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "rag-agent"}