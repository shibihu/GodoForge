from __future__ import annotations

import re
from .models import GodotError


class GodotErrorParser:
    # Pattern to extract res:// path, line, and optional column numbers
    # e.g., res://player.gd:42:10 or res://player.gd:42
    _LOCATION_PATTERN = re.compile(
        r"(res://[^\s:]+\.(?:gd|tscn|tres)):(\d+)(?::(\d+))?"
    )

    # Patterns for error prefixes/headers
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

            # Extract location if present
            file_path = None
            line_num = None
            col_num = None

            loc_match = cls._LOCATION_PATTERN.search(line_str)
            if loc_match:
                file_path = loc_match.group(1)
                line_num = int(loc_match.group(2))
                if loc_match.group(3):
                    col_num = int(loc_match.group(3))

            errors.append(
                GodotError(
                    message=line_str,
                    file=file_path,
                    line=line_num,
                    column=col_num,
                    severity="warning" if is_warning else "error",
                    raw_output=line_str,
                )
            )

        return errors
