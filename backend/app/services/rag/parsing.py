"""
Extracts plain text from uploaded knowledge documents.

Kept deliberately simple for Phase 3: one function per format, all returning
plain text. Table/layout-aware extraction (needed for complex PDFs with tables)
is a later refinement — flag it if your policy documents are heavily tabular
and answers seem to be missing data, and we can swap in a more structured
extractor without changing anything else in the pipeline.
"""
import csv
import io

import pypdf
from docx import Document as DocxDocument


def extract_text(file_path: str, document_type: str) -> str:
    if document_type == "pdf":
        return _extract_pdf(file_path)
    if document_type == "docx":
        return _extract_docx(file_path)
    if document_type == "txt":
        return _extract_txt(file_path)
    if document_type == "csv":
        return _extract_csv(file_path)
    raise ValueError(f"Unsupported document type: {document_type}")


def _extract_pdf(file_path: str) -> str:
    reader = pypdf.PdfReader(file_path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def _extract_docx(file_path: str) -> str:
    doc = DocxDocument(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def _extract_txt(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _extract_csv(file_path: str) -> str:
    """
    Flattens CSV rows into readable text lines, e.g. "column1: value1 | column2: value2".
    This makes each row embeddable/retrievable like a mini-FAQ entry, which is
    usually what CSV knowledge sources are (e.g. a Q&A spreadsheet export).
    """
    lines: list[str] = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            line = " | ".join(f"{k}: {v}" for k, v in row.items() if v)
            if line:
                lines.append(line)
    return "\n".join(lines)
