from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.attachment_parser import extract_attachment_text
from app.core.db import get_db
from app.core.token_usage import record_token_usage
from app.models.chat import Chat, ChatMessage
from app.models.user import User
from app.utils.schemas import AttachmentExtractionResponse, ChatCreateRequest, ChatMessageAppendRequest, ChatRenameRequest, normalize_message_content

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("")
def list_chats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = (
        db.query(Chat)
        .filter(Chat.user_id == current_user.id)
        .order_by(Chat.id.desc())
        .all()
    )
    return [_serialize_chat(c) for c in rows]


@router.post("")
def create_chat(
    payload: ChatCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    chat = Chat(user_id=current_user.id, title=payload.title or "New Chat")
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return {"status": "ok", "chat": _serialize_chat(chat)}


@router.post("/attachments/extract", response_model=AttachmentExtractionResponse)
async def extract_attachments(
    files: list[UploadFile] = File(...),
    _: User = Depends(get_current_user),
) -> dict:
    attachments: list[dict] = []

    for upload in files:
        filename = upload.filename or "attachment"
        payload = await upload.read()
        attachments.append(
            extract_attachment_text(
                filename=filename,
                content_type=upload.content_type,
                payload=payload,
            )
        )
        await upload.close()

    return {"attachments": attachments}


@router.get("/{chat_id}")
def get_chat(
    chat_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    chat = _load_chat(db, chat_id, current_user)
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.chat_id == chat.id)
        .order_by(ChatMessage.id.asc())
        .all()
    )
    return {
        "chat": _serialize_chat(chat),
        "messages": [_serialize_message(m) for m in messages],
    }


@router.post("/{chat_id}/messages")
def append_message(
    chat_id: int,
    payload: ChatMessageAppendRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    chat = _load_chat(db, chat_id, current_user)
    message = ChatMessage(
        chat_id=chat.id,
        role=payload.role,
        content=normalize_message_content(payload.content),
        model_name=payload.model_name or (payload.stats.model if payload.stats else None),
        prompt_tokens=payload.stats.prompt_tokens if payload.stats else None,
        completion_tokens=payload.stats.completion_tokens if payload.stats else None,
        total_tokens=payload.stats.total_tokens if payload.stats else None,
        elapsed_seconds=payload.stats.elapsed_seconds if payload.stats else None,
        tokens_per_second=payload.stats.tokens_per_second if payload.stats else None,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    if payload.role == "assistant" and payload.stats is not None:
        record_token_usage(
            db,
            user_id=current_user.id,
            total_tokens=payload.stats.total_tokens,
            input_tokens=payload.stats.prompt_tokens,
            output_tokens=payload.stats.completion_tokens,
        )
    return {"status": "ok", "message": _serialize_message(message)}


@router.patch("/{chat_id}")
def rename_chat(
    chat_id: int,
    payload: ChatRenameRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    chat = _load_chat(db, chat_id, current_user)
    chat.title = payload.title.strip() or chat.title
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return {"status": "ok", "chat": _serialize_chat(chat)}


@router.delete("/{chat_id}")
def delete_chat(
    chat_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    chat = _load_chat(db, chat_id, current_user)
    db.delete(chat)
    db.commit()
    return {"status": "ok"}


def _load_chat(db: Session, chat_id: int, current_user: User) -> Chat:
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    if chat.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Chat does not belong to the current user")
    return chat


def _serialize_chat(chat: Chat) -> dict:
    return {
        "id": chat.id,
        "title": chat.title,
        "user_id": chat.user_id,
        "created_at": chat.created_at.isoformat() if chat.created_at else None,
    }


def _serialize_message(message: ChatMessage) -> dict:
    return {
        "id": message.id,
        "chat_id": message.chat_id,
        "role": message.role,
        "content": message.content,
        "modelName": message.model_name,
        "stats": {
            "model": message.model_name,
            "elapsedSeconds": message.elapsed_seconds,
            "promptTokens": message.prompt_tokens,
            "completionTokens": message.completion_tokens,
            "totalTokens": message.total_tokens,
            "tokensPerSecond": message.tokens_per_second,
        }
        if message.model_name is not None or message.elapsed_seconds is not None or message.prompt_tokens is not None or message.completion_tokens is not None or message.total_tokens is not None or message.tokens_per_second is not None
        else None,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }
