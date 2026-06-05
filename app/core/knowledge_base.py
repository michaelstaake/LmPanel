import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.knowledge_base import KnowledgeBaseDocument

MAX_DOCUMENT_BYTES = 10 * 1024  # 10 KB
MAX_RETRIEVAL_DOCS = 3
MAX_RETRIEVAL_CONTEXT_CHARS = 4000  # cap total context to preserve model context window


@dataclass
class DocumentScore:
    doc: KnowledgeBaseDocument
    score: float


def _tokenize(text: str) -> list[str]:
    """Simple word tokenizer for BM25."""
    return re.findall(r"[a-zA-Z0-9_]+", text.lower())


def _bm25_score(query_tokens: list[str], doc_text: str, k1: float = 1.5, b: float = 0.75) -> float:
    """Compute BM25 score for a single document against query tokens."""
    doc_tokens = _tokenize(doc_text)
    if not doc_tokens:
        return 0.0

    doc_len = len(doc_tokens)
    # We don't have corpus stats, so use a simple IDF approximation
    # and document length normalization
    score = 0.0
    for qtok in query_tokens:
        # Count occurrences in document
        freq = doc_tokens.count(qtok)
        if freq == 0:
            continue
        # Simple IDF approximation (log-based)
        idf = max(0.1, (1.0 + 0.1) / (1.0 + freq))
        # BM25 term frequency
        tf = (freq * (k1 + 1.0)) / (freq + k1 * (1.0 - b + b * (doc_len / 500.0)))
        score += idf * tf
    return score


def retrieve_relevant_documents(db: Session, user_id: int, query: str, max_docs: int = MAX_RETRIEVAL_DOCS, category_id: int | None = None) -> list[KnowledgeBaseDocument]:
    """Retrieve relevant documents for a query using BM25 keyword search."""
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    # Fetch user documents (for small KBs this is fine; for larger ones, add SQL FTS)
    query = (
        db.query(KnowledgeBaseDocument)
        .filter(KnowledgeBaseDocument.user_id == user_id)
        .order_by(KnowledgeBaseDocument.updated_at.desc())
    )

    if category_id is not None:
        query = query.filter(KnowledgeBaseDocument.category_id == category_id)

    docs = query.all()

    if not docs:
        return []

    # Score each document
    scored: list[DocumentScore] = []
    for doc in docs:
        text = f"{doc.title} {doc.content}"
        score = _bm25_score(query_tokens, text)
        if score > 0:
            scored.append(DocumentScore(doc=doc, score=score))

    # Sort by score descending, take top N
    scored.sort(key=lambda x: x.score, reverse=True)
    return [s.doc for s in scored[:max_docs]]


def build_rag_context(documents: list[KnowledgeBaseDocument], query: str) -> str:
    """Format retrieved documents as a context block to prepend to the system prompt."""
    if not documents:
        return ""

    parts: list[str] = [f"# Knowledge Base Context (query: \"{query}\")"]
    total_chars = 0

    for i, doc in enumerate(documents, 1):
        # Truncate content to stay within context budget
        remaining = MAX_RETRIEVAL_CONTEXT_CHARS - total_chars
        if remaining <= 0:
            break

        content = doc.content[:remaining] if remaining < len(doc.content) else doc.content
        category_prefix = f"[{doc.category.name}] " if doc.category and doc.category.name else ""
        parts.append(f"\n## {i}. {category_prefix}{doc.title}")
        parts.append(f"```markdown\n{content}\n```")
        total_chars += len(content) + 50  # approximate overhead

    return "\n".join(parts)


def truncate_content(content: str) -> str:
    """Truncate content to MAX_DOCUMENT_BYTES if needed."""
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_DOCUMENT_BYTES:
        # Truncate at byte boundary
        truncated = encoded[:MAX_DOCUMENT_BYTES].decode("utf-8", errors="ignore")
        return truncated + "\n\n[Content truncated]"
    return content
