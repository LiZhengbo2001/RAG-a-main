import json
import time
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from db import get_db
from schemas.widget import WidgetChatRequest, FeedbackRequest
from services.rag_pipeline import run_stream
from core.logger import logger

router = APIRouter(prefix="/widget", tags=["widget"])


@router.post("/chat/stream")
async def widget_chat_stream(
    req: WidgetChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """匿名流式聊天，visitor_id 代替 user_id（免认证）"""
    t0 = time.time()

    async def generator():
        try:
            async for ev in run_stream(
                db, req.query, req.conversation_id,
                user_id=None,
                visitor_id=req.visitor_id,
            ):
                yield {"event": ev["event"], "data": ev["data"]}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
            logger.error("Widget 流式对话异常",
                         extra={"event": "widget_stream_error",
                                "visitor_id": req.visitor_id,
                                "query": req.query[:60], "error": str(e)})
        finally:
            elapsed = int((time.time() - t0) * 1000)
            logger.info("Widget 流式对话结束",
                        extra={"event": "widget_stream_done",
                               "visitor_id": req.visitor_id,
                               "query": req.query[:60], "elapsed_ms": elapsed})

    return EventSourceResponse(generator())


@router.get("/suggestions")
async def widget_suggestions():
    """返回推荐问题列表（后续从配置或数据库读取）"""
    return {"questions": [
        "我想了解产品价格",
        "如何申请退款？",
        "售后服务电话是多少？",
        "支持哪些支付方式？",
    ]}


@router.post("/feedback")
async def widget_feedback(req: FeedbackRequest, db: AsyncSession = Depends(get_db)):
    """用户对回答的反馈（后续存储到 message 表）"""
    logger.info("收到反馈",
                extra={"event": "feedback", "message_id": req.message_id,
                       "visitor_id": req.visitor_id, "rating": req.rating})
    return {"status": "ok"}