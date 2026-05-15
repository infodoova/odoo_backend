"""
Files API service.

Stores uploaded files on local disk and keeps lightweight metadata in the
`stored_files` table managed by Django migrations.
"""

import os
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from django.conf import settings
from django.db import connection
from django.utils import timezone
from fastapi import HTTPException

MAX_FILE_BYTES = 10 * 1024 * 1024
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")
_SAFE_TENANT_RE = re.compile(r"[^a-zA-Z0-9_\-]")


def _storage_root() -> Path:
    return Path(getattr(settings, "BASE_DIR", Path.cwd())) / "storage_uploads"


def _safe_tenant(tenant_id: str) -> str:
    return _SAFE_TENANT_RE.sub("_", tenant_id) or "default"


def _sanitize_filename(original: str) -> str:
    base = Path(original or "upload").name
    safe = re.sub(r"[^\w.\-]", "_", base, flags=re.UNICODE).strip("._")
    return safe or "file"


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def _dict_row(cursor, row) -> dict[str, Any]:
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


def _ensure_table() -> None:
    return


def _row_to_wire(row: dict[str, Any], base_url: str) -> dict[str, Any]:
    public_base = (PUBLIC_BASE_URL or base_url).rstrip("/")
    tenant_id = row.get("tenant_id")
    company_id = row.get("company_id")
    file_id = row.get("id")
    
    # URL structure depends on whether we want to include company_id in the URL
    # Following the "same algo" request, we should probably include it.
    url = f"{public_base}/api/v1/files/{tenant_id}/{company_id}/{file_id}/content"
    
    return {
        "id": file_id,
        "tenant_id": tenant_id,
        "company_id": company_id,
        "file_name": row["file_name"],
        "file_size": row["file_size"],
        "content_type": row.get("content_type") or "",
        "url": url,
        "description": row.get("description") or "",
        "uploaded_at": _iso(row.get("uploaded_at")),
    }


class FilesService:
    @staticmethod
    def list_files(tenant_id: str, company_id: int, base_url: str) -> list[dict[str, Any]]:
        _ensure_table()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, tenant_id, company_id, file_name, stored_filename,
                       file_size, content_type, storage_path,
                       description, uploaded_at
                FROM stored_files
                WHERE tenant_id = %s AND company_id = %s
                ORDER BY uploaded_at DESC, id DESC
                """,
                [tenant_id, company_id],
            )
            rows = [_dict_row(cursor, row) for row in cursor.fetchall()]
        return [_row_to_wire(row, base_url) for row in rows]

    @staticmethod
    def save_file(
        tenant_id: str,
        company_id: int,
        original_filename: str,
        content_type: Optional[str],
        data: bytes,
        description: Optional[str],
        base_url: str,
    ) -> dict[str, Any]:
        _ensure_table()

        file_size = len(data)
        if file_size > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File size exceeds 10 MB limit ({file_size:,} bytes received).",
            )

        safe_name = _sanitize_filename(original_filename)
        ext = Path(safe_name).suffix or ""
        stored_name = f"{uuid.uuid4().hex}{ext}"
        # Store in a path that includes company_id for extra organization
        tenant_dir = _storage_root() / _safe_tenant(tenant_id) / str(company_id)
        tenant_dir.mkdir(parents=True, exist_ok=True)
        storage_path = tenant_dir / stored_name
        uploaded_at = timezone.now()

        try:
            storage_path.write_bytes(data)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Could not save file: {exc.strerror}")

        try:
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
                            tenant_id,
                            company_id,
                            safe_name,
                            stored_name,
                            file_size,
                            content_type or "application/octet-stream",
                            str(storage_path),
                            description or "",
                            uploaded_at,
                        ],
                    )
                    file_id = cursor.fetchone()[0]
                else:
                    cursor.execute(
                        """
                        INSERT INTO stored_files
                            (tenant_id, company_id, file_name, stored_filename, file_size,
                             content_type, storage_path, description, uploaded_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            tenant_id,
                            company_id,
                            safe_name,
                            stored_name,
                            file_size,
                            content_type or "application/octet-stream",
                            str(storage_path),
                            description or "",
                            uploaded_at,
                        ],
                    )
                    file_id = cursor.lastrowid

                cursor.execute(
                    """
                    SELECT id, tenant_id, company_id, file_name, stored_filename,
                           file_size, content_type, storage_path,
                           description, uploaded_at
                    FROM stored_files
                    WHERE id = %s AND tenant_id = %s AND company_id = %s
                    LIMIT 1
                    """,
                    [file_id, tenant_id, company_id],
                )
                row = _dict_row(cursor, cursor.fetchone())
        except Exception:
            storage_path.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail="Failed to save file metadata")

        return _row_to_wire(row, base_url)

    @staticmethod
    def delete_file(tenant_id: str, company_id: int, file_id: int) -> None:
        _ensure_table()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, storage_path FROM stored_files WHERE id = %s AND tenant_id = %s AND company_id = %s LIMIT 1",
                [file_id, tenant_id, company_id],
            )
            raw = cursor.fetchone()
            if not raw:
                raise HTTPException(status_code=404, detail=f"File {file_id} not found.")
            row = _dict_row(cursor, raw)

            storage_path = row.get("storage_path") or ""
            if storage_path:
                try:
                    Path(storage_path).unlink(missing_ok=True)
                except OSError:
                    pass

            cursor.execute(
                "DELETE FROM stored_files WHERE id = %s AND tenant_id = %s AND company_id = %s",
                [file_id, tenant_id, company_id],
            )

    @staticmethod
    def get_file_path(tenant_id: str, company_id: int, file_id: int) -> tuple[str, str]:
        _ensure_table()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT storage_path, file_name
                FROM stored_files
                WHERE id = %s AND tenant_id = %s AND company_id = %s
                LIMIT 1
                """,
                [file_id, tenant_id, company_id],
            )
            raw = cursor.fetchone()
            if not raw:
                raise HTTPException(status_code=404, detail=f"File {file_id} not found.")
            row = _dict_row(cursor, raw)

        storage_path = row.get("storage_path") or ""
        file_name = row.get("file_name") or "download"
        if not storage_path or not Path(storage_path).is_file():
            raise HTTPException(
                status_code=404,
                detail="File record exists but physical file is missing.",
            )
        return storage_path, file_name
