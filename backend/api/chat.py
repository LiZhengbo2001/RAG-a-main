import json
import time
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from db import get_db
from schemas import ChatRequest, ChatResponse
from models.conversation import User
from services.rag_pipeline import run, run_stream
from api.deps import get_current_user
from core.logger import logger

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat_non_stream(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    t0 = time.time()
    try:
        result = await run(db, req.query, req.conversation_id, current_user.id, req.image)
        elapsed = int((time.time() - t0) * 1000)
        logger.info("对话完成",
                    extra={"event": "chat_done", "user_id": current_user.id,
                           "conversation_id": result["conversation_id"],
                           "query": req.query[:60], "elapsed_ms": elapsed, "status": 200})
        return ChatResponse(**result)
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        logger.error("对话失败",
                     extra={"event": "chat_error", "user_id": current_user.id,
                            "query": req.query[:60], "elapsed_ms": elapsed, "error": str(e)})
        raise


@router.post("/stream")
async def chat_stream_endpoint(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    t0 = time.time()

    async def generator():
        try:
            async for ev in run_stream(db, req.query, req.conversation_id, current_user.id, req.image):
                yield {"event": ev["event"], "data": ev["data"]}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
            logger.error("流式对话异常",
                         extra={"event": "stream_error", "user_id": current_user.id,
                                "query": req.query[:60], "error": str(e)})
        finally:
            elapsed = int((time.time() - t0) * 1000)
            logger.info("流式对话结束",
                        extra={"event": "stream_done", "user_id": current_user.id,
                               "query": req.query[:60], "elapsed_ms": elapsed, "status": 200})

    return EventSourceResponse(generator())
