"""
doova_one_view/api/agent/data_sanitizer.py

Resilient Prompt-Injection Defense: XML Boundary Isolation.
Replaces fragile keyword denylists with structural XML isolation (<untrusted_source_record>)
and CDATA encapsulation so that database free-text is strictly treated as passive data.
"""

import re
import html
from typing import Any, Dict, List, Optional, Union


class DataSanitizer:
    """
    Sanitizes untrusted database text and wraps free-form fields in explicit XML boundaries.
    """

    @staticmethod
    def clean_raw_string(text: Optional[str]) -> str:
        """
        Cleans control characters and sanitizes CDATA break sequences without mangling unicode or punctuation.
        """
        if text is None:
            return ""
        
        # Convert to string if not already
        s = str(text)

        # Remove null bytes and non-printable control chars (except tab, newline, carriage return)
        s = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', s)

        # Escape CDATA termination tokens to prevent boundary breakouts
        s = s.replace("]]>", "]]&gt;")
        return s.strip()

    @classmethod
    def wrap_field_xml(
        cls, 
        field_name: str, 
        content: Any, 
        entity: str = "record", 
        record_id: Optional[Union[str, int]] = None
    ) -> str:
        """
        Wraps an untrusted text field in a secure XML boundary.
        """
        clean_content = cls.clean_raw_string(content)
        rec_attr = f' id="{html.escape(str(record_id))}"' if record_id is not None else ""
        return (
            f'<untrusted_source_record source="odoo_database" entity="{html.escape(entity)}"{rec_attr}>\n'
            f'  <{html.escape(field_name)}><![CDATA[{clean_content}]]></{html.escape(field_name)}>\n'
            f'</untrusted_source_record>'
        )

    @classmethod
    def sanitize_dict_fields(
        cls, 
        data: Dict[str, Any], 
        text_fields: Optional[List[str]] = None,
        entity: str = "record",
        record_id_key: str = "id"
    ) -> Dict[str, Any]:
        """
        Recursively sanitizes and encapsulates untrusted string fields within a dictionary.
        """
        sanitized = {}
        rec_id = data.get(record_id_key) or data.get("odoo_id") or data.get("name")
        
        for k, v in data.items():
            if isinstance(v, str):
                if text_fields is None or k in text_fields:
                    sanitized[k] = cls.clean_raw_string(v)
                else:
                    sanitized[k] = v
            elif isinstance(v, dict):
                sanitized[k] = cls.sanitize_dict_fields(v, text_fields=text_fields, entity=k)
            elif isinstance(v, list):
                sanitized[k] = [
                    cls.sanitize_dict_fields(item, text_fields=text_fields, entity=k) if isinstance(item, dict)
                    else (cls.clean_raw_string(item) if isinstance(item, str) else item)
                    for item in v
                ]
            else:
                sanitized[k] = v
        return sanitized
