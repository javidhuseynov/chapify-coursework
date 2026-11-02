"""Validation of uploaded documents (FR-02) and server-side page counting (FR-04).

Only PDF files are accepted. A file is accepted only if it:
1. has the .pdf extension and is at most 5 MB,
2. really is a PDF (starts with the "%PDF-" signature, not just a renamed file),
3. can be opened by the PDF parser and is not protected by an opening password,
4. has between 1 and MAX_DOCUMENT_PAGES pages.

The page count read here is used for the price, so the user cannot under-declare
the number of pages.
"""

import os

from pypdf import PdfReader

ALLOWED_DOCUMENT_EXTENSIONS = [".pdf"]
MAX_DOCUMENT_SIZE = 5 * 1024 * 1024
MAX_DOCUMENT_PAGES = 500
PDF_SIGNATURE = b"%PDF-"


class DocumentValidationError(Exception):
    """The uploaded file cannot be accepted. The message is user-facing."""


def _read_header(uploaded_file, size=1024):
    uploaded_file.seek(0)
    header = uploaded_file.read(size)
    uploaded_file.seek(0)
    return header


def count_pdf_pages(uploaded_file):
    """Return the number of pages, or raise DocumentValidationError."""
    try:
        reader = PdfReader(uploaded_file, strict=False)

        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentValidationError(
                "Password-protected PDF files cannot be printed. Remove the password and upload again."
            )

        page_count = len(reader.pages)
    except DocumentValidationError:
        raise
    except Exception as exc:  # pypdf raises many different errors for damaged files
        raise DocumentValidationError(
            "The PDF file could not be read. It may be damaged or encrypted."
        ) from exc
    finally:
        uploaded_file.seek(0)

    if page_count < 1:
        raise DocumentValidationError("The PDF file has no pages.")

    if page_count > MAX_DOCUMENT_PAGES:
        raise DocumentValidationError(
            f"The PDF file has {page_count} pages. The maximum is {MAX_DOCUMENT_PAGES}."
        )

    return page_count


def inspect_uploaded_document(uploaded_file):
    """Validate an upload and return its page count."""
    if not uploaded_file:
        raise DocumentValidationError("Document file is required.")

    extension = os.path.splitext(uploaded_file.name.lower())[1]

    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise DocumentValidationError("Only PDF files are allowed.")

    if uploaded_file.size > MAX_DOCUMENT_SIZE:
        raise DocumentValidationError("File size must not exceed 5 MB.")

    if PDF_SIGNATURE not in _read_header(uploaded_file):
        raise DocumentValidationError("The file is not a valid PDF document.")

    return count_pdf_pages(uploaded_file)
