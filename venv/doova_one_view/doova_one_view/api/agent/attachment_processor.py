"""
Attachment Processor for AI Agent.

Handles:
1. Decoding user-uploaded base64 documents/images.
2. Enterprise-grade security validation:
   - 15 MB max file size limit per file (50 MB batch limit).
   - Strict extension whitelist.
   - Multi-dot / double extension prevention (e.g. file.pdf.php).
   - Magic bytes / binary header signature sniffing (PDF, PNG, JPEG, GIF, WebP, XLSX, DOCX).
   - Binary injection & null-byte blocking in text/CSV/JSON documents.
   - Filename sanitization & path traversal mitigation.
   - Non-executable disk permission hardening (0o640).
3. Persisting copies under `storage_uploads/ai_agent_user_input/`.
4. Converting files into Claude-native multimodal blocks (Images, Native PDFs)
   with Anthropic Prompt Caching (`cache_control: {"type": "ephemeral"}`).
5. Extracting text/tables from Excel (.xlsx), CSV, Word (.docx), and plain text.
"""

import os
import re
import io
import time
import uuid
import shutil
import base64
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from django.conf import settings
from .logger import logger

# Maximum file size: 15 MB per file
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024
MAX_BATCH_SIZE_BYTES = 50 * 1024 * 1024
MAX_FILES_COUNT = 10

# Strict whitelist of allowed extensions
ALLOWED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".pdf",
    ".xlsx", ".xls",
    ".csv",
    ".docx",
    ".txt", ".md", ".json"
}

# Dangerous / executable extensions to strictly ban even in multi-dot names
DANGEROUS_EXTENSIONS = {
    "php", "php3", "php4", "php5", "phtml", "phar",
    "exe", "dll", "so", "bin", "sh", "bash", "bat", "cmd", "ps1", "vbs",
    "js", "mjs", "cjs", "py", "pyc", "pyd", "pl", "cgi", "jar", "war",
    "jsp", "asp", "aspx", "shtml", "htaccess", "htpasswd", "config", "env",
    "svg", "html", "htm", "xhtml", "xml"
}

# Magic byte signatures for file verification
MAGIC_SIGNATURES = {
    "pdf": [b"%PDF-"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpeg": [b"\xff\xd8\xff"],
    "gif": [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],  # also check WEBP at offset 8
    "zip_office": [b"PK\x03\x04"]  # .xlsx, .docx
}


def sanitize_filename(name: str) -> str:
    """Cleans a filename to prevent path traversal, null bytes, and dangerous characters."""
    if not name:
        return "attachment"
    
    # Strip path traversal components
    clean_name = os.path.basename(name)
    clean_name = clean_name.replace("\x00", "").replace("/", "").replace("\\", "").strip()
    
    # Remove leading dots to prevent hidden files
    clean_name = clean_name.lstrip(".")
    
    # Sanitize characters to safe alphanumeric, underscores, hyphens, and single dot for extension
    safe_chars = re.sub(r"[^\w.\- ]", "_", clean_name, flags=re.UNICODE)
    return safe_chars or "attachment"


def validate_file_security(filename: str, data_bytes: bytes) -> Tuple[bool, str, str]:
    """
    Validates file against:
    1. Size limit (<= 15MB)
    2. Multi-extension / dangerous extension detection
    3. Whitelist check
    4. Magic byte signature verification
    
    Returns:
        (is_valid, sanitized_filename, error_reason)
    """
    # 1. Size check
    file_size = len(data_bytes)
    if file_size == 0:
        return False, filename, "Empty file (0 bytes)."
    if file_size > MAX_FILE_SIZE_BYTES:
        return False, filename, f"File exceeds maximum allowed size of 15MB ({file_size / (1024*1024):.1f}MB)."

    # 2. Filename and Extension Validation
    safe_name = sanitize_filename(filename)
    lower_name = safe_name.lower()
    
    # Check for dangerous extensions in multi-dot filenames (e.g. invoice.pdf.php, test.jpg.exe)
    parts = lower_name.split(".")
    if len(parts) > 1:
        # Check all suffixes after the first part
        for ext_part in parts[1:]:
            if ext_part in DANGEROUS_EXTENSIONS:
                logger.warning(f"[Security] Rejected dangerous extension '{ext_part}' in filename: {filename}")
                return False, safe_name, f"Security rejection: Dangerous file extension (.{ext_part}) is prohibited."

    # Extract final extension
    _, ext = os.path.splitext(lower_name)
    if ext not in ALLOWED_EXTENSIONS:
        logger.warning(f"[Security] Rejected disallowed extension '{ext}' in filename: {filename}")
        return False, safe_name, f"Disallowed file format '{ext}'. Allowed formats: Images, PDF, Excel, CSV, Word, Text."

    # 3. Magic Byte & Binary Header Verification
    header = data_bytes[:16]

    # PDF validation
    if ext == ".pdf":
        if not any(header.startswith(sig) for sig in MAGIC_SIGNATURES["pdf"]):
            logger.warning(f"[Security] Fake PDF detected for {filename} (magic bytes mismatch)")
            return False, safe_name, "Invalid PDF file: corrupted or invalid file header signature."

    # Image validation
    elif ext == ".png":
        if not header.startswith(MAGIC_SIGNATURES["png"][0]):
            logger.warning(f"[Security] Fake PNG detected for {filename}")
            return False, safe_name, "Invalid PNG file: corrupted or invalid file header signature."

    elif ext in (".jpg", ".jpeg"):
        if not header.startswith(MAGIC_SIGNATURES["jpeg"][0]):
            logger.warning(f"[Security] Fake JPEG detected for {filename}")
            return False, safe_name, "Invalid JPEG file: corrupted or invalid file header signature."

    elif ext == ".gif":
        if not (header.startswith(MAGIC_SIGNATURES["gif"][0]) or header.startswith(MAGIC_SIGNATURES["gif"][1])):
            logger.warning(f"[Security] Fake GIF detected for {filename}")
            return False, safe_name, "Invalid GIF file: corrupted or invalid file header signature."

    elif ext == ".webp":
        if not (header.startswith(b"RIFF") and len(data_bytes) >= 12 and data_bytes[8:12] == b"WEBP"):
            logger.warning(f"[Security] Fake WebP detected for {filename}")
            return False, safe_name, "Invalid WebP file: corrupted or invalid file header signature."

    # Office OpenXML (.xlsx, .docx) validation
    elif ext in (".xlsx", ".docx"):
        if not header.startswith(MAGIC_SIGNATURES["zip_office"][0]):
            logger.warning(f"[Security] Fake Office OpenXML detected for {filename}")
            return False, safe_name, f"Invalid {ext.upper()} document: corrupted or invalid file header signature."

    # Text / CSV / JSON / Markdown validation (Must not contain executable binaries or null bytes)
    elif ext in (".txt", ".md", ".json", ".csv"):
        # Check for null bytes (used in binary / executable exploits)
        if b"\x00" in data_bytes[:1024]:
            logger.warning(f"[Security] Binary null bytes detected in text document {filename}")
            return False, safe_name, "Invalid text file: binary data or null bytes detected."
        # Disallow ELF / PE executable headers
        if header.startswith(b"\x7fELF") or header.startswith(b"MZ"):
            logger.warning(f"[Security] Executable binary masquerading as text {filename}")
            return False, safe_name, "Security rejection: Binary executable detected."

    return True, safe_name, ""


def get_ai_user_input_storage_dir(tenant_id: Optional[str] = None, session_id: Optional[str] = None) -> Path:
    """Returns directory path: storage_uploads/ai_agent_user_input/[tenant_id]/[session_id]/"""
    base_dir = Path(getattr(settings, "BASE_DIR", Path.cwd()))
    storage_root = base_dir / "storage_uploads" / "ai_agent_user_input"
    
    tenant_part = re.sub(r"[^\w\-]", "_", str(tenant_id or "shared"))
    session_part = re.sub(r"[^\w\-]", "_", str(session_id or "general"))
    
    target_dir = storage_root / tenant_part / session_part
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def save_attachment_to_disk(
    filename: str,
    data_bytes: bytes,
    tenant_id: Optional[str] = None,
    session_id: Optional[str] = None
) -> Path:
    """Saves attachment bytes with non-executable permissions (0o640) under storage_uploads/ai_agent_user_input/."""
    folder = get_ai_user_input_storage_dir(tenant_id, session_id)
    safe_name = sanitize_filename(filename)
    unique_prefix = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    dest_path = folder / f"{unique_prefix}_{safe_name}"
    
    # Write file securely
    with open(dest_path, "wb") as f:
        f.write(data_bytes)
        
    # Enforce non-executable permissions (read/write by owner, read by group, none by others)
    try:
        os.chmod(dest_path, 0o640)
    except Exception as e:
        logger.debug(f"[Attachments] Could not set 0o640 permission: {e}")
        
    logger.info(f"[Attachments] Saved secure user attachment to: {dest_path} ({len(data_bytes)} bytes)")
    return dest_path


def save_attachment_to_db(
    filename: str,
    stored_filename: str,
    storage_path: str,
    file_size: int,
    content_type: str,
    tenant_id: Optional[str] = None,
    company_id: Optional[int] = None,
    session_id: Optional[str] = None
) -> Optional[int]:
    """Persists uploaded attachment metadata into the `stored_files` database table."""
    try:
        from django.db import connection
        from django.utils import timezone
        
        uploaded_at = timezone.now()
        description = f"AI Agent User Input | Session: {session_id or 'general'}"
        
        # Verify if tenant exists in odoo_app_tenant to avoid foreign key errors
        db_tenant_id = None
        if tenant_id and str(tenant_id).lower() not in ("shared", "default", "none", "all"):
            try:
                with connection.cursor() as cur:
                    cur.execute("SELECT id FROM odoo_app_tenant WHERE id = %s LIMIT 1", [tenant_id])
                    if cur.fetchone():
                        db_tenant_id = tenant_id
            except Exception:
                db_tenant_id = None
                
        # Verify if company exists in odoo_app_company
        db_company_id = None
        if company_id:
            try:
                with connection.cursor() as cur:
                    cur.execute("SELECT id FROM odoo_app_company WHERE id = %s LIMIT 1", [company_id])
                    if cur.fetchone():
                        db_company_id = company_id
            except Exception:
                db_company_id = None

        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                cursor.execute(
                    """
                    INSERT INTO stored_files
                        (tenant_id, company_id, file_name, stored_filename, file_size,
                         content_type, storage_path, description, uploaded_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    [
                        db_tenant_id,
                        db_company_id,
                        filename,
                        stored_filename,
                        file_size,
                        content_type or "application/octet-stream",
                        str(storage_path),
                        description,
                        uploaded_at,
                    ]
                )
                row = cursor.fetchone()
                file_id = row[0] if row else None
            else:
                cursor.execute(
                    """
                    INSERT INTO stored_files
                        (tenant_id, company_id, file_name, stored_filename, file_size,
                         content_type, storage_path, description, uploaded_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        db_tenant_id,
                        db_company_id,
                        filename,
                        stored_filename,
                        file_size,
                        content_type or "application/octet-stream",
                        str(storage_path),
                        description,
                        uploaded_at,
                    ]
                )
                file_id = getattr(cursor, "lastrowid", None)
                
        logger.info(f"[Attachments] Persisted file record in DB `stored_files` (id={file_id}, file={filename})")
        return file_id
    except Exception as e:
        logger.warning(f"[Attachments] Could not save attachment record to DB `stored_files`: {e}")
        return None


def parse_excel_to_markdown(data_bytes: bytes, filename: str) -> str:
    """Extracts tables from Excel workbook (.xlsx) and returns clean Markdown."""
    try:
        import openpyxl
        
        wb = openpyxl.load_workbook(io.BytesIO(data_bytes), data_only=True, read_only=True)
        sheets_output = []
        
        for sheetname in wb.sheetnames[:5]:  # limit to first 5 sheets
            ws = wb[sheetname]
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue
            
            # Filter empty rows
            non_empty_rows = [r for r in rows if any(cell is not None and str(cell).strip() != "" for cell in r)]
            if not non_empty_rows:
                continue
                
            # Limit rows per sheet to 100 to prevent context explosion
            preview_rows = non_empty_rows[:100]
            
            # Determine max cols
            max_cols = max(len(r) for r in preview_rows)
            normalized = [[str(cell if cell is not None else "").strip().replace("|", "\\|") for cell in r] + [""] * (max_cols - len(r)) for r in preview_rows]
            
            headers = normalized[0]
            data_rows = normalized[1:]
            
            md_table = []
            md_table.append(f"### Sheet: {sheetname}")
            md_table.append("| " + " | ".join(headers) + " |")
            md_table.append("| " + " | ".join(["---"] * max_cols) + " |")
            for r in data_rows:
                md_table.append("| " + " | ".join(r) + " |")
                
            if len(non_empty_rows) > 100:
                md_table.append(f"*(Showing 100 of {len(non_empty_rows)} rows)*")
                
            sheets_output.append("\n".join(md_table))
            
        return f"\n\n--- Spreadsheet Content: {filename} ---\n" + "\n\n".join(sheets_output) + "\n--- End Spreadsheet ---\n"
    except Exception as e:
        logger.warning(f"[Attachments] Failed to parse Excel with openpyxl ({e}), falling back to text")
        return f"\n\n[Attached Spreadsheet: {filename} (Error parsing workbook: {str(e)})]\n"


def parse_csv_to_markdown(data_bytes: bytes, filename: str) -> str:
    """Extracts CSV data to clean Markdown."""
    try:
        import csv
        
        text = data_bytes.decode("utf-8", errors="replace")
        reader = list(csv.reader(io.StringIO(text)))
        if not reader:
            return f"\n\n[Empty CSV: {filename}]\n"
            
        preview_rows = reader[:100]
        max_cols = max(len(r) for r in preview_rows)
        normalized = [[cell.strip().replace("|", "\\|") for cell in r] + [""] * (max_cols - len(r)) for r in preview_rows]
        
        headers = normalized[0]
        data_rows = normalized[1:]
        
        md_table = []
        md_table.append(f"### CSV Data: {filename}")
        md_table.append("| " + " | ".join(headers) + " |")
        md_table.append("| " + " | ".join(["---"] * max_cols) + " |")
        for r in data_rows:
            md_table.append("| " + " | ".join(r) + " |")
            
        if len(reader) > 100:
            md_table.append(f"*(Showing 100 of {len(reader)} rows)*")
            
        return f"\n\n--- CSV Document: {filename} ---\n" + "\n".join(md_table) + "\n--- End CSV ---\n"
    except Exception as e:
        logger.warning(f"[Attachments] Failed to parse CSV ({e})")
        return f"\n\n[Attached CSV: {filename} (Error parsing: {str(e)})]\n"


def process_attachments(
    attachments: List[Dict[str, Any]],
    tenant_id: Optional[str] = None,
    company_id: Optional[int] = None,
    session_id: Optional[str] = None,
    persist: bool = True
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Processes a list of frontend attachments with strict security validation into:
    1. Claude content blocks (image and document blocks with cache_control).
    2. Extracted text context for spreadsheets / text docs.
    3. Saves sanitized copies on disk under storage_uploads/ai_agent_user_input/ (when persist=True).
    4. Saves file metadata record in database `stored_files` table (when persist=True).
    
    Returns:
        (claude_content_blocks, extracted_text_context)
    """
    if not attachments:
        return [], ""
        
    claude_blocks = []
    text_contexts = []
    total_batch_bytes = 0
    
    for att in attachments[:MAX_FILES_COUNT]:
        name = att.get("name", "attachment")
        media_type = att.get("media_type") or att.get("type") or ""
        raw_data = att.get("data") or ""
        
        if not raw_data:
            continue
            
        # Strip data URL prefix if present (e.g. data:image/png;base64,....)
        if "," in raw_data and raw_data.startswith("data:"):
            header, base64_str = raw_data.split(",", 1)
            if not media_type and ";" in header:
                media_type = header.split(";")[0].replace("data:", "").strip()
        else:
            base64_str = raw_data
            
        try:
            data_bytes = base64.b64decode(base64_str)
        except Exception as e:
            logger.error(f"[Attachments] Base64 decode failed for {name}: {e}")
            continue
            
        # Check batch size limit
        total_batch_bytes += len(data_bytes)
        if total_batch_bytes > MAX_BATCH_SIZE_BYTES:
            logger.warning(f"[Security] Batch size exceeded 50MB on file: {name}. Skipping remaining files.")
            break
            
        # Security validation (size, extension, double extension, magic bytes)
        is_valid, safe_name, err_reason = validate_file_security(name, data_bytes)
        if not is_valid:
            logger.warning(f"[Security] File {name} rejected: {err_reason}")
            text_contexts.append(f"\n\n⚠️ **Attachment '{name}' was rejected for security reasons: {err_reason}**\n")
            continue
            
        # 1. Save validated copy to disk (only for active turn, not history rehydration)
        if persist:
            dest_path = None
            try:
                dest_path = save_attachment_to_disk(safe_name, data_bytes, tenant_id=tenant_id or "default", session_id=session_id)
            except Exception as e:
                logger.warning(f"[Attachments] Could not save attachment to disk: {e}")

            # 2. Save metadata record to database `stored_files` table
            if dest_path:
                try:
                    save_attachment_to_db(
                        filename=name,
                        stored_filename=dest_path.name,
                        storage_path=str(dest_path),
                        file_size=len(data_bytes),
                        content_type=media_type,
                        tenant_id=tenant_id or "default",
                        company_id=company_id,
                        session_id=session_id
                    )
                except Exception as e:
                    logger.warning(f"[Attachments] Could not save attachment record to DB: {e}")
            
        lower_name = safe_name.lower()
        lower_media = media_type.lower()
        
        # 1. Native Images (JPEG, PNG, GIF, WebP) -> Claude 'image' block
        if (
            "image/jpeg" in lower_media or "image/png" in lower_media or
            "image/webp" in lower_media or "image/gif" in lower_media or
            lower_name.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))
        ):
            if lower_name.endswith(".png") or "png" in lower_media:
                mtype = "image/png"
            elif lower_name.endswith(".webp") or "webp" in lower_media:
                mtype = "image/webp"
            elif lower_name.endswith(".gif") or "gif" in lower_media:
                mtype = "image/gif"
            else:
                mtype = "image/jpeg"
                
            claude_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mtype,
                    "data": base64_str.strip()
                },
                "cache_control": {"type": "ephemeral"}  # Anthropic Prompt Caching
            })
            continue

        # 2. Native PDF Document -> Claude 'document' block
        if "pdf" in lower_media or lower_name.endswith(".pdf"):
            claude_blocks.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64_str.strip()
                },
                "cache_control": {"type": "ephemeral"}  # Anthropic Prompt Caching
            })
            continue

        # 3. Excel Spreadsheets (.xlsx, .xls) -> Markdown Tables
        if lower_name.endswith((".xlsx", ".xls")) or "spreadsheet" in lower_media or "excel" in lower_media:
            extracted_table = parse_excel_to_markdown(data_bytes, safe_name)
            text_contexts.append(extracted_table)
            continue

        # 4. CSV Spreadsheets (.csv) -> Markdown Tables
        if lower_name.endswith(".csv") or "csv" in lower_media:
            extracted_csv = parse_csv_to_markdown(data_bytes, safe_name)
            text_contexts.append(extracted_csv)
            continue

        # 5. Plain Text, Markdown, JSON, Code -> Text blocks
        try:
            decoded_text = data_bytes.decode("utf-8", errors="replace")
            text_contexts.append(f"\n\n--- Document Attachment: {safe_name} ---\n{decoded_text}\n--- End Document ---\n")
        except Exception:
            text_contexts.append(f"\n\n[Attached File: {safe_name}]\n")

    combined_text = "\n".join(text_contexts)
    return claude_blocks, combined_text


def cleanup_session_attachments(session_id: str):
    """
    Deletes all physical disk files and database `stored_files` metadata records
    associated with a deleted chat session.
    """
    if not session_id:
        return
        
    session_clean = re.sub(r"[^\w\-]", "_", str(session_id))
    
    # 1. Delete physical directory on disk
    base_dir = Path(getattr(settings, "BASE_DIR", Path.cwd()))
    storage_root = base_dir / "storage_uploads" / "ai_agent_user_input"
    
    if storage_root.exists():
        for tenant_dir in storage_root.iterdir():
            if tenant_dir.is_dir():
                target_session_dir = tenant_dir / session_clean
                if target_session_dir.exists() and target_session_dir.is_dir():
                    try:
                        shutil.rmtree(target_session_dir)
                        logger.info(f"[Attachments] Deleted session disk storage: {target_session_dir}")
                    except Exception as e:
                        logger.warning(f"[Attachments] Could not delete directory {target_session_dir}: {e}")
                        
    # 2. Delete database records in `stored_files`
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM stored_files WHERE description LIKE %s",
                [f"%Session: {session_id}%"]
            )
            logger.info(f"[Attachments] Cleaned up `stored_files` records for session {session_id}")
    except Exception as e:
        logger.warning(f"[Attachments] Error removing stored_files records: {e}")
