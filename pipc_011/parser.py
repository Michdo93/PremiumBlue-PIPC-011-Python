"""Parser for the JavaScript responses of the Apexis firmware.

The get_*.cgi endpoints do not return JSON but JavaScript, e.g.::

    var ret_alias_name='IP CAMERA';
    var ret_mvideo_w=1280;
    var ret_presetsta_enable=new Array();
    ret_presetsta_enable[0]=1;

This is converted into a dict. Arrays become lists, numbers become int.
"""

from __future__ import annotations

import re
from typing import Any

_VAR_RE = re.compile(r"^\s*(?:var\s+)?([A-Za-z_]\w*)\s*=\s*(.*?)\s*$", re.S)
_IDX_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*=\s*(.*?)\s*$", re.S)


def _value(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith("new Array"):
        inner = raw[raw.find("(") + 1: raw.rfind(")")].strip()
        return [_value(x) for x in _split_args(inner)] if inner else []
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _split(text: str, sep: str) -> list[str]:
    """Split at `sep`, ignoring separators inside string literals."""
    parts, current, quote = [], "", None
    for ch in text:
        if quote:
            current += ch
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            current += ch
        elif ch == sep:
            parts.append(current)
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current)
    return parts


def _split_args(s: str) -> list[str]:
    return _split(s, ",")


def parse_js_vars(text: str, strip_prefix: bool = False) -> dict[str, Any]:
    """Convert a `var x=...;` response into a dict.

    strip_prefix=True removes the ``ret_`` prefix from the keys.
    """
    result: dict[str, Any] = {}
    for stmt in _split(text.replace("\r", ""), ";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        m = _IDX_RE.match(stmt)
        if m:
            name, idx, val = m.group(1), int(m.group(2)), _value(m.group(3))
            lst = result.get(name)
            if not isinstance(lst, list):
                lst = result[name] = []
            while len(lst) <= idx:
                lst.append(None)
            lst[idx] = val
            continue
        m = _VAR_RE.match(stmt)
        if m:
            result[m.group(1)] = _value(m.group(2))
    if strip_prefix:
        result = {k[4:] if k.startswith("ret_") else k: v for k, v in result.items()}
    return result
