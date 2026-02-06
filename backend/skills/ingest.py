"""Document ingestion — reads local files and converts them into skills."""

import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger("nexus.ingest")

# Supported file types
SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".markdown",
    ".pdf",
    ".docx",
    ".csv",
    ".json",
    ".html", ".htm",
    ".py", ".js", ".ts", ".sh", ".yaml", ".yml", ".toml", ".ini", ".cfg",
}

# Max file size: 10MB
MAX_FILE_SIZE = 10 * 1024 * 1024


def _read_text_file(path):
    """Read a plain text file."""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _read_pdf(path):
    """Read a PDF file. Requires PyPDF2."""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(path)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)
    except ImportError:
        logger.warning("PyPDF2 not installed. Run: pip3 install PyPDF2")
        return "[PDF reading requires PyPDF2: pip3 install PyPDF2]"
    except Exception as e:
        logger.error(f"Error reading PDF {path}: {e}")
        return f"[Error reading PDF: {e}]"


def _read_docx(path):
    """Read a Word document. Requires python-docx."""
    try:
        from docx import Document
        doc = Document(path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    except ImportError:
        logger.warning("python-docx not installed. Run: pip3 install python-docx")
        return "[DOCX reading requires python-docx: pip3 install python-docx]"
    except Exception as e:
        logger.error(f"Error reading DOCX {path}: {e}")
        return f"[Error reading DOCX: {e}]"


def read_file(path):
    """Read a file and return its text content."""
    ext = Path(path).suffix.lower()

    if os.path.getsize(path) > MAX_FILE_SIZE:
        return f"[File too large: {os.path.getsize(path) / 1024 / 1024:.1f}MB, max {MAX_FILE_SIZE / 1024 / 1024:.0f}MB]"

    if ext == ".pdf":
        return _read_pdf(path)
    elif ext == ".docx":
        return _read_docx(path)
    else:
        return _read_text_file(path)


def file_hash(path):
    """Generate a hash of a file for change detection."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def scan_directory(docs_dir):
    """Scan a directory for supported files. Returns list of file info dicts."""
    files = []
    if not os.path.isdir(docs_dir):
        logger.warning(f"Documents directory not found: {docs_dir}")
        return files

    for root, dirs, filenames in os.walk(docs_dir):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith(".")]

        for fname in filenames:
            if fname.startswith("."):
                continue
            ext = Path(fname).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, docs_dir)
            size = os.path.getsize(full_path)

            files.append({
                "path": full_path,
                "relative_path": rel_path,
                "name": fname,
                "extension": ext,
                "size": size,
                "hash": file_hash(full_path),
            })

    return files


def get_ingest_prompt(filename, content):
    """Generate a prompt to distill a document into a skill."""
    # Truncate very long documents
    if len(content) > 30000:
        content = content[:15000] + "\n\n[...middle section truncated...]\n\n" + content[-15000:]

    return f"""You are a knowledge analyst. You have been given a document to analyse and distil into a structured knowledge skill.

Document filename: {filename}

Document content:
---
{content}
---

Please analyse this document and create a structured skill from it. Respond in the following exact format:

<overview>
A 2-3 paragraph overview of what this document covers. What is the core topic? What are the key takeaways?
</overview>

<concepts>
The key concepts from this document, each as a bullet point with a brief explanation. Extract the most important 5-15 ideas.
</concepts>

<decision_guide>
Practical guidance derived from this document: "If the user asks about X, the document says Y." or "When Z situation arises, the recommended approach is..." Make this actionable and specific to the document's content.
</decision_guide>

<quick_reference>
A quick-reference summary: the most important facts, figures, processes, or takeaways someone would need at a glance.
</quick_reference>

<sources>
Source: {filename}
Note any caveats about the document's content, date, or applicability.
</sources>

<metadata>
name: (short descriptive name based on the document content)
domain: (one or two word category)
description: (one sentence description of what knowledge this skill provides)
keywords: (comma-separated list of 5-10 keywords from the document)
</metadata>

Be thorough and extract maximum value from the document. This skill will be used to help answer future questions."""
