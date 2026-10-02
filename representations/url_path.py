"""URL-path semantic view, never hostname, query parameters, or fragment."""

import re
from urllib.parse import unquote, urlsplit

VERSION = "url-path-v1"


def normalize_path(href):
    result = {"version": VERSION, "raw_path": "", "segments": [], "text": "",
              "status": "unavailable", "reason": None, "flags": []}
    try:
        if not isinstance(href, str) or re.search(r"[\x00-\x20\x7f]", href):
            raise ValueError("invalid_url")
        parts = urlsplit(href)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ValueError("unsupported_url")
        _ = parts.port  # Validate malformed ports too.
        result["raw_path"] = parts.path
        for segment in parts.path.split("/"):
            if re.search(r"%(?![a-fA-F0-9]{2})", segment):
                raise ValueError("invalid_percent_escape")
            decoded = unquote(segment, encoding="utf-8", errors="strict")
            if re.search(r"[\x00-\x1f\x7f]", decoded):
                raise ValueError("control_character_in_path")
            if re.search(r"%2f", segment, re.I):
                result["flags"].append("encoded_slash_in_segment")
            text = " ".join(re.sub(r"[-_]", " ", decoded).split())
            if text:
                result["segments"].append(text)
                if text.isnumeric():
                    result["flags"].append("numeric_segment")
                if len(text) >= 24 and " " not in text:
                    result["flags"].append("possibly_opaque_segment")
        result["text"] = " / ".join(result["segments"])
        result["status"] = "ready" if result["text"] else "unavailable"
        result["reason"] = None if result["text"] else "root_only_path"
    except (ValueError, UnicodeError):
        result.update(status="unavailable", reason="invalid_or_unsupported_url_path", text="", segments=[])
    return result
