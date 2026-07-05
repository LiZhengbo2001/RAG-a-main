from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from db import get_db
from schemas import DocumentOut
from models.conversation import Document, User
from services.document_service import process_and_index, delete_document
from api.deps import get_current_user

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Document)
        .where(Document.user_id == current_user.id)
        .order_by(desc(Document.created_at))
        .limit(100)
    )
    return [d.to_dict() for d in result.scalars().all()]


@router.post("/upload", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not file.filename:
        raise HTTPException(400, "文件名为空")
    content = await file.read()
    if not content:
        raise HTTPException(400, "文件内容为空")
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(400, "文件过大，最大支持 20MB")

    try:
        await process_and_index(db, file.filename, content, current_user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"处理失败: {str(e)}")

    await db.commit()
    result = await db.execute(
        select(Document)
        .where(Document.user_id == current_user.id)
        .order_by(desc(Document.created_at))
        .limit(1)
    )
    return result.scalar_one().to_dict()


@router.delete("/{document_id}", status_code=204)
async def remove_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = (
        await db.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "文档不存在")
    if doc.user_id and doc.user_id != current_user.id:
        raise HTTPException(403, "无权删除此文档")

    try:
        await delete_document(db, document_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
