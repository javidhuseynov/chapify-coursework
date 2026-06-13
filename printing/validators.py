import os


ALLOWED_DOCUMENT_EXTENSIONS = [".pdf", ".docx", ".txt"]
MAX_DOCUMENT_SIZE = 5 * 1024 * 1024


def validate_uploaded_document(uploaded_file):
    if not uploaded_file:
        return "Document file is required."

    file_name = uploaded_file.name.lower()
    extension = os.path.splitext(file_name)[1]

    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        return "Only PDF, DOCX, and TXT files are allowed."

    if uploaded_file.size > MAX_DOCUMENT_SIZE:
        return "File size must not exceed 5 MB."

    return None