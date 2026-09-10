from __future__ import annotations

import re
from .models import GodotError


class GodotErrorParser:
    _LOCATION_PATTERN = re.compile(
        r"(res://[^\s:]+\.(?:gd|tscn|tres)):(\d+)(?::(\d+))?"
    )

    _ERROR_TYPE_PATTERNS = [
        ("parser_error", re.compile(r"parser\s+error|parse\s+error", re.IGNORECASE)),
        ("script_error", re.compile(r"script\s+error", re.IGNORECASE)),
        ("null_instance", re.compile(r"null\s+instance|invalid\s+get\s+index|invalid\s+set\s+index|cannot\s+call\s+method|on\s+a\s+null\s+instance", re.IGNORECASE)),
        ("invalid_call", re.compile(r"invalid\s+call|invalid\s+type|invalid\s+argument", re.IGNORECASE)),
        ("node_not_found", re.compile(r"node\s+not\s+found|node\s+path", re.IGNORECASE)),
        ("missing_resource", re.compile(r"failed\s+to\s+load|cannot\s+open\s+file|resource\s+not\s+found", re.IGNORECASE)),
    ]

    _ERROR_HEADERS = (
        "ERROR:",
        "SCRIPT ERROR:",
        "Parser Error:",
        "Parse error:",
        "Invalid call:",
        "Invalid get index:",
        "Invalid set index:",
        "Cannot call method:",
        "Node not found:",
        "Failed to load script:",
        "Condition",
    )

    @classmethod
    def parse(cls, stdout: str, stderr: str) -> list[GodotError]:
        errors: list[GodotError] = []
        seen_keys = set()

        combined_lines = []
        if stdout:
            combined_lines.extend(stdout.splitlines())
        if stderr:
            combined_lines.extend(stderr.splitlines())

        for line in combined_lines:
            line_str = line.strip()
            if not line_str:
                continue

            is_warning = "warning" in line_str.lower()
            is_error = any(hdr.lower() in line_str.lower() for hdr in cls._ERROR_HEADERS) or ("error" in line_str.lower() and not is_warning)

            if not is_error and not is_warning:
                continue

            file_path = None
            line_num = None
            col_num = None

            loc_match = cls._LOCATION_PATTERN.search(line_str)
            if loc_match:
                file_path = loc_match.group(1)
                line_num = int(loc_match.group(2))
                if loc_match.group(3):
                    col_num = int(loc_match.group(3))

            error_type = "general"
            for etype, pat in cls._ERROR_TYPE_PATTERNS:
                if pat.search(line_str):
                    error_type = etype
                    break

            severity = "warning" if is_warning else "error"
            dedup_key = (line_str, file_path, line_num, severity)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            errors.append(
                GodotError(
                    message=line_str,
                    file=file_path,
                    line=line_num,
                    column=col_num,
                    severity=severity,
                    error_type=error_type,
                    raw_output=line_str,
                )
            )

        return errors
