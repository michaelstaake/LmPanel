from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user, get_current_user
from app.core.db import get_db
from app.core.knowledge_base import build_rag_context, retrieve_relevant_documents, truncate_content
from app.models.knowledge_base import KnowledgeBaseCategory, KnowledgeBaseDocument
from app.models.user import User
from app.utils.schemas import (
    KnowledgeBaseCategoryCreateRequest,
    KnowledgeBaseCategoryResponse,
    KnowledgeBaseCategoryUpdateRequest,
    KnowledgeBaseDocumentCreateRequest,
    KnowledgeBaseDocumentResponse,
    KnowledgeBaseDocumentUpdateRequest,
    KnowledgeBaseRagContextResponse,
)

router = APIRouter(prefix="/api/knowledge-base", tags=["knowledge-base"])


# --- Category endpoints ---

@router.get("/categories", response_model=list[KnowledgeBaseCategoryResponse])
def list_categories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KnowledgeBaseCategoryResponse]:
    categories = (
        db.query(KnowledgeBaseCategory)
        .filter(KnowledgeBaseCategory.user_id == current_user.id)
        .order_by(KnowledgeBaseCategory.is_default.desc(), KnowledgeBaseCategory.name.asc())
        .all()
    )
    return [_serialize_category(cat) for cat in categories]


@router.post("/categories", response_model=KnowledgeBaseCategoryResponse)
def create_category(
    payload: KnowledgeBaseCategoryCreateRequest,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> KnowledgeBaseCategoryResponse:
    # Check for duplicate name (case-insensitive) among non-default categories
    existing = (
        db.query(KnowledgeBaseCategory)
        .filter(
            KnowledgeBaseCategory.user_id == current_user.id,
            KnowledgeBaseCategory.name.ilike(payload.name),
            KnowledgeBaseCategory.is_default == False,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="A category with this name already exists")

    cat = KnowledgeBaseCategory(
        user_id=current_user.id,
        name=payload.name.strip(),
        is_default=False,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return _serialize_category(cat)


@router.patch("/categories/{cat_id}", response_model=KnowledgeBaseCategoryResponse)
def update_category(
    cat_id: int,
    payload: KnowledgeBaseCategoryUpdateRequest,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> KnowledgeBaseCategoryResponse:
    cat = (
        db.query(KnowledgeBaseCategory)
        .filter(KnowledgeBaseCategory.id == cat_id, KnowledgeBaseCategory.user_id == current_user.id)
        .first()
    )
    if cat is None:
        raise HTTPException(status_code=404, detail="Category not found")

    if payload.name is not None:
        # Check for duplicate name (case-insensitive) among non-default categories
        existing = (
            db.query(KnowledgeBaseCategory)
            .filter(
                KnowledgeBaseCategory.user_id == current_user.id,
                KnowledgeBaseCategory.name.ilike(payload.name),
                KnowledgeBaseCategory.is_default == False,
                KnowledgeBaseCategory.id != cat_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=409, detail="A category with this name already exists")
        cat.name = payload.name.strip()

    db.add(cat)
    db.commit()
    db.refresh(cat)
    return _serialize_category(cat)


@router.delete("/categories/{cat_id}")
def delete_category(
    cat_id: int,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    cat = (
        db.query(KnowledgeBaseCategory)
        .filter(KnowledgeBaseCategory.id == cat_id, KnowledgeBaseCategory.user_id == current_user.id)
        .first()
    )
    if cat is None:
        raise HTTPException(status_code=404, detail="Category not found")

    if cat.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete the Default category")

    doc_count = (
        db.query(KnowledgeBaseDocument)
        .filter(KnowledgeBaseDocument.category_id == cat_id)
        .count()
    )
    if doc_count > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete category with {doc_count} document(s). Move or delete documents first.")

    db.delete(cat)
    db.commit()
    return {"status": "ok"}


# --- Document endpoints ---

@router.get("/documents", response_model=list[KnowledgeBaseDocumentResponse])
def list_documents(
    category_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KnowledgeBaseDocumentResponse]:
    query = (
        db.query(KnowledgeBaseDocument)
        .filter(KnowledgeBaseDocument.user_id == current_user.id)
        .order_by(KnowledgeBaseDocument.updated_at.desc())
    )

    if category_id is not None:
        query = query.filter(KnowledgeBaseDocument.category_id == category_id)

    docs = query.all()
    return [_serialize_document(doc) for doc in docs]


@router.post("/documents", response_model=KnowledgeBaseDocumentResponse)
def create_document(
    payload: KnowledgeBaseDocumentCreateRequest,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> KnowledgeBaseDocumentResponse:
    content = truncate_content(payload.content)
    doc = KnowledgeBaseDocument(
        user_id=current_user.id,
        category_id=payload.category_id,
        title=payload.title,
        content=content,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _serialize_document(doc)


@router.patch("/documents/{doc_id}", response_model=KnowledgeBaseDocumentResponse)
def update_document(
    doc_id: int,
    payload: KnowledgeBaseDocumentUpdateRequest,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> KnowledgeBaseDocumentResponse:
    doc = (
        db.query(KnowledgeBaseDocument)
        .filter(KnowledgeBaseDocument.id == doc_id, KnowledgeBaseDocument.user_id == current_user.id)
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    if payload.title is not None:
        doc.title = payload.title
    if payload.content is not None:
        doc.content = truncate_content(payload.content)
    if payload.category_id is not None:
        # Verify category belongs to user
        cat = (
            db.query(KnowledgeBaseCategory)
            .filter(KnowledgeBaseCategory.id == payload.category_id, KnowledgeBaseCategory.user_id == current_user.id)
            .first()
        )
        if cat is None:
            raise HTTPException(status_code=404, detail="Category not found")
        doc.category_id = payload.category_id

    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _serialize_document(doc)


@router.delete("/documents/{doc_id}")
def delete_document(
    doc_id: int,
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> dict:
    doc = (
        db.query(KnowledgeBaseDocument)
        .filter(KnowledgeBaseDocument.id == doc_id, KnowledgeBaseDocument.user_id == current_user.id)
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    db.delete(doc)
    db.commit()
    return {"status": "ok"}


@router.get("/rag-context", response_model=KnowledgeBaseRagContextResponse)
def get_rag_context(
    query: str,
    category_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeBaseRagContextResponse:
    docs = retrieve_relevant_documents(db, current_user.id, query, category_id=category_id)
    context = build_rag_context(docs, query)
    return KnowledgeBaseRagContextResponse(context=context, document_count=len(docs))


def _serialize_category(cat: KnowledgeBaseCategory) -> KnowledgeBaseCategoryResponse:
    return KnowledgeBaseCategoryResponse(
        id=cat.id,
        user_id=cat.user_id,
        name=cat.name,
        is_default=cat.is_default,
        created_at=cat.created_at.isoformat() if cat.created_at else None,
    )


def _serialize_document(doc: KnowledgeBaseDocument) -> KnowledgeBaseDocumentResponse:
    return KnowledgeBaseDocumentResponse(
        id=doc.id,
        user_id=doc.user_id,
        category_id=doc.category_id,
        title=doc.title,
        content=doc.content,
        created_at=doc.created_at.isoformat() if doc.created_at else None,
        updated_at=doc.updated_at.isoformat() if doc.updated_at else None,
    )
