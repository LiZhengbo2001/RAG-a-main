from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from db import get_db
from schemas import ConversationCreate, ConversationOut
from models.conversation import Conversation, User
from api.deps import get_current_user

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(desc(Conversation.updated_at))
        .limit(50)
    )
    return [c.to_dict() for c in result.scalars().all()]


@router.post("", response_model=ConversationOut, status_code=201)
async def create_conversation(
    body: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conv = Conversation(title=body.title, user_id=current_user.id)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv.to_dict()


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conv = (
        await db.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.messages))
        )
    ).scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "对话不存在")
    if conv.user_id and conv.user_id != current_user.id:
        raise HTTPException(403, "无权访问此对话")

    return {
        "id": conv.id,
        "title": conv.title,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "thinking": m.thinking,
                "sources": m.sources,
                "trace": m.trace,
                "timestamp": m.created_at.strftime("%H:%M"),
            }
            for m in conv.messages
        ],
    }


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conv = (
        await db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
    ).scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "对话不存在")
    if conv.user_id and conv.user_id != current_user.id:
        raise HTTPException(403, "无权删除此对话")
    await db.delete(conv)
    await db.commit()