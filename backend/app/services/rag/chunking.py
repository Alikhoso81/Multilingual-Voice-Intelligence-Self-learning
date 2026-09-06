"""
Splits extracted document text into overlapping chunks suitable for embedding
and retrieval.

Approach: split on paragraph boundaries first (keeps semantically related
sentences together), then greedily pack paragraphs into chunks up to
`max_chars`, carrying a small overlap forward so a fact split across a chunk
boundary isn't lost from retrieval entirely.

This is a character-count-based chunker rather than token-based for Phase 3
simplicity — good enough at this scale. Swap for a token-aware chunker
(matched to the embedding model's tokenizer) later if you see truncation
issues with very long paragraphs.
"""
import re


def chunk_text(text: str, max_chars: int = 1200, overlap_chars: int = 150) -> list[str]:
    text = text.strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        # A single paragraph longer than max_chars gets hard-split on its own.
        if len(para) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(para), max_chars - overlap_chars):
                chunks.append(para[i : i + max_chars])
            continue

        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            # carry a small tail of the previous chunk forward for continuity
            tail = current[-overlap_chars:] if len(current) > overlap_chars else current
            current = f"{tail}\n\n{para}"

    if current:
        chunks.append(current)

    return chunks
