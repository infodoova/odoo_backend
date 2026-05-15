# api/agent/utils.py

import os
import re
from pathlib import Path

def get_public_base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

def make_report_url(report_path_or_filename: str | None) -> str | None:
    if not report_path_or_filename: return None
    filename = Path(report_path_or_filename).name
    public_base_url = get_public_base_url()
    return f"{public_base_url}/api/v1/reports/{filename}" if public_base_url else f"/api/v1/reports/{filename}"

def normalize_graph_for_frontend(graph_data):
    if not graph_data: return None
    if isinstance(graph_data, list):
        normalized = []
        for item in graph_data:
            if not isinstance(item, dict): continue
            if "name" in item and "value" in item: normalized.append(item)
            elif "x" in item and "y" in item: normalized.append({"name": str(item.get("x")), "value": float(item.get("y") or 0)})
        return normalized if normalized else None
    if isinstance(graph_data, dict):
        if isinstance(graph_data.get("x"), list) and isinstance(graph_data.get("y"), list):
            return [{"name": str(xv), "value": float(graph_data["y"][i] or 0)} for i, xv in enumerate(graph_data["x"])]
    return None
