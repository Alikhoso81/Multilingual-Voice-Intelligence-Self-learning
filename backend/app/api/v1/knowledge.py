import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, require_roles
from app.models.knowledge import (
    DocumentStatus,
    DocumentType,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.models.user import User, UserRole
from app.schemas.knowledge import DocumentOut, RetrievalQuery, RetrievedChunkOut
from app.services.rag.chunking import chunk_text
from app.services.rag.embeddings import embed_passages_batch
from app.services.rag.parsing import extract_text
from app.services.rag.retrieval import retrieve_relevant_chunks

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

DOCUMENT_STORAGE_DIR = Path("/code/storage/documents")
DOCUMENT_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

EXTENSION_TO_TYPE = {
    ".pdf": DocumentType.pdf,
    ".docx": DocumentType.docx,
    ".txt": DocumentType.txt,
    ".csv": DocumentType.csv,
}


@router.post("/documents", response_model=DocumentOut, status_code=201)
def upload_document(
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin)),
) -> KnowledgeDocument:
    """
    Admin-only: upload a knowledge document. Processing (parse -> chunk ->
    embed -> store) happens synchronously in this request for Phase 3 —
    Phase 8+ moves this to a Celery background job so large documents don't
    block the request. For typical FAQ/policy-doc sizes this is fine for now.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    suffix = Path(file.filename).suffix.lower()
    document_type = EXTENSION_TO_TYPE.get(suffix)
    if document_type is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Supported: pdf, docx, txt, csv",
        )

    saved_filename = f"{uuid.uuid4()}{suffix}"
    saved_path = DOCUMENT_STORAGE_DIR / saved_filename
    with saved_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    document = KnowledgeDocument(
        organization_id=current_user.organization_id,
        uploaded_by=current_user.id,
        filename=file.filename,
        file_path=str(saved_path),
        document_type=document_type,
        status=DocumentStatus.processing,
    )
    db.add(document)
    db.flush()

    try:
        raw_text = extract_text(str(saved_path), document_type.value)
        if not raw_text.strip():
            raise ValueError("No extractable text found in document")

        chunks = chunk_text(raw_text)
        if not chunks:
            raise ValueError("Document produced no chunks after splitting")

        vectors = embed_passages_batch(chunks)

        for idx, (chunk_content, vector) in enumerate(zip(chunks, vectors)):
            db.add(
                KnowledgeChunk(
                    document_id=document.id,
                    organization_id=current_user.organization_id,
                    chunk_index=idx,
                    text=chunk_content,
                    embedding=vector,
                    chunk_metadata={"source_filename": file.filename},
                )
            )

        document.status = DocumentStatus.ready
        db.commit()
        db.refresh(document)

    except Exception as exc:
        db.rollback()
        document.status = DocumentStatus.failed
        document.error_message = str(exc)
        db.add(document)
        db.commit()
        db.refresh(document)

    return _to_document_out(db, document)


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DocumentOut]:
    documents = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.organization_id == current_user.organization_id)
        .order_by(KnowledgeDocument.created_at.desc())
        .all()
    )
    return [_to_document_out(db, d) for d in documents]


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.admin)),
) -> None:
    document = (
        db.query(KnowledgeDocument)
        .filter(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.organization_id == current_user.organization_id,
        )
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(document)  # cascades to chunks
    db.commit()


@router.post("/search", response_model=list[RetrievedChunkOut])
def search_knowledge(
    payload: RetrievalQuery,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RetrievedChunkOut]:
    """
    Test endpoint for Phase 3: run retrieval directly without going through
    the full conversation/LLM pipeline (that wiring is Phase 4). Useful for
    verifying your uploaded documents are actually retrievable before we plug
    in the LLM.
    """
    results = retrieve_relevant_chunks(
        db, current_user.organization_id, payload.query, top_k=payload.top_k
    )
    return [
        RetrievedChunkOut(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            text=r.text,
            similarity=r.similarity,
        )
        for r in results
    ]


def _to_document_out(db: Session, document: KnowledgeDocument) -> DocumentOut:
    chunk_count = (
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).count()
    )
    out = DocumentOut.model_validate(document)
    out.chunk_count = chunk_count
    return out
