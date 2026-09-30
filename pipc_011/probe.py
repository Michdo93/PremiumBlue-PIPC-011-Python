"""Exploration of the real camera (read-only).

The saved dump does not contain the pages with the actual control logic
(ffserver.htm, mobile.htm, settings pages), and get_camera_vars /
get_params came back empty because they were fetched without login.

`pipc_011 probe` fetches this with login:
  1. all read-only get_*.cgi  -> JSON
  2. crawls all .htm/.js pages starting from main.htm/login.htm
  3. extracts every CGI call with its parameter names and every
     decoder_control number from the JavaScript
  4. checks RTSP paths via DESCRIBE (404 = does not exist, 401/200 = exists)
Result: folder + ZIP + report.md. No set_*.cgi is ever called.
"""

from __future__ import annotations

import json
import re
import socket
import zipfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from . import commands as C
from .api import Camera, CameraError

START_PAGES = [
    "index.htm", "index.html", "main.htm", "login.htm", "ffserver.htm", "activex.htm",
    "mobile.htm", "ptz.htm", "video.htm", "media.htm", "setting.htm", "left.htm",
    "right.htm", "top.htm", "quick_install.htm", "vlc_install.htm",
    "language/german.js", "language/english.js", "language/lang.js",
]

REF_RE = re.compile(r"""["'(=\s]([\w./-]+\.(?:htm|html|js))(?:[?#"'\s)])""", re.I)
CGI_RE = re.compile(r"(\w+\.cgi)([^\n]{0,500})", re.I)
PARAM_RE = re.compile(r"[?&](\w+)=")
DECODER_RE = re.compile(r"decoder_control\.cgi\?command=['\"]?\s*\+?\s*(\w+)", re.I)
CALL_NUM_RE = re.compile(r"""on(?:mousedown|mouseup|click|touchstart|touchend)\s*=\s*["']([^"']*?\(\s*\d+[^"']*)["']""", re.I)

RTSP_PATHS = ["/live/av0", "/live/av1"]  # av0 from vlc_video.htm, av1 presumably substream


def _fetch(camera: Camera, page: str) -> requests.Response | None:
    url = camera.base_url + "/" + page.lstrip("/")
    try:
        response = requests.get(url, params=camera.auth, timeout=camera.timeout)
    except requests.RequestException:
        return None
    return response if response.status_code == 200 else None


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", "replace")


def crawl(camera: Camera, out: Path, limit: int = 200) -> dict[str, str]:
    pages: dict[str, str] = {}
    queue = list(START_PAGES)
    seen: set[str] = set()
    while queue and len(seen) < limit:
        page = queue.pop(0).lstrip("/")
        if page in seen:
            continue
        seen.add(page)
        response = _fetch(camera, page)
        if response is None:
            continue
        text = _decode(response.content)
        pages[page] = text
        dest = out / "web" / page
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(response.content)
        base = "http://x/" + page
        for ref in REF_RE.findall(" " + text):
            ref_path = urlparse(urljoin(base, ref)).path.lstrip("/")
            if ref_path and ref_path not in seen and ".cgi" not in ref_path:
                queue.append(ref_path)
    return pages


def analyse(pages: dict[str, str]) -> dict:
    cgi_params: dict[str, set[str]] = defaultdict(set)
    cgi_where: dict[str, set[str]] = defaultdict(set)
    decoder: dict[str, set[str]] = defaultdict(set)
    handlers: list[str] = []
    for page, text in pages.items():
        for name, rest in CGI_RE.findall(text):
            cgi_where[name].add(page)
            # parameters up to the next CGI name in the same line
            rest = re.split(r"\w+\.cgi", rest, maxsplit=1)[0]
            for param in PARAM_RE.findall(rest):
                if param not in ("user", "pwd", "next_url"):
                    cgi_params[name].add(param)
        for ref in DECODER_RE.findall(text):
            decoder[page].add(ref)
        for handler in CALL_NUM_RE.findall(text):
            handlers.append(f"{page}: {handler.strip()}")
    return {
        "cgi_params": {k: sorted(v) for k, v in sorted(cgi_params.items())},
        "cgi_where": {k: sorted(v) for k, v in sorted(cgi_where.items())},
        "decoder_refs": {k: sorted(v) for k, v in decoder.items()},
        "handlers": sorted(set(handlers)),
    }


SECRET_RE = re.compile(r"((?:var\s+)?\w*(?:pwd|pass|psk|key|guid)\w*\s*=\s*)(['\"])[^'\"]*\2", re.I)


def redact(text: str) -> str:
    """Remove passwords/keys from JS responses (so the report can be shared)."""
    return SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}***{m.group(2)}", text)


def _redact_obj(obj):
    if isinstance(obj, dict):
        return {k: ("***" if re.search(r"pwd|pass|psk|key|guid", k, re.I) and v not in ("", None)
                    else _redact_obj(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_obj(v) for v in obj]
    return obj


def rtsp_probe(host: str, port: int) -> dict[str, str]:
    """DESCRIBE without login: 401 means 'path exists, login required'."""
    results = {}
    for path in RTSP_PATHS:
        url = f"rtsp://{host}:{port}{path}"
        req = (f"DESCRIBE {url} RTSP/1.0\r\nCSeq: 2\r\nAccept: application/sdp\r\n"
               f"User-Agent: pipc011-probe\r\n\r\n").encode()
        try:
            with socket.create_connection((host, port), timeout=3) as sock:
                sock.sendall(req)
                line = sock.recv(256).split(b"\r\n", 1)[0].decode(errors="replace")
        except OSError as exc:
            line = f"Error: {exc}"
        results[path] = line
    return results


def run(camera: Camera, out_dir: str = "probe_out") -> Path:
    out = Path(out_dir)
    (out / "cgi").mkdir(parents=True, exist_ok=True)

    status = {}
    for cgi in C.READ_CGIS:
        try:
            text = camera.raw(cgi)
            (out / "cgi" / cgi).write_text(redact(text), encoding="utf-8")
            status[cgi] = camera.get_vars(cgi) if text.strip() else {}
        except CameraError as exc:
            status[cgi] = {"error": str(exc)}
    status = _redact_obj(status)
    (out / "status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")

    pages = crawl(camera, out)
    info = analyse(pages)
    (out / "analysis.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        rtsp_port = int(status.get("get_status.cgi", {}).get("rtsp_port", 554))
    except (TypeError, ValueError):
        rtsp_port = 554
    rtsp = rtsp_probe(camera.host, rtsp_port)

    # settings groups (get_params requires ?type=1..14)
    for param_type in C.PARAM_TYPES:
        key = f"get_params.cgi?type={param_type}"
        try:
            text = camera.raw("get_params.cgi", type=param_type)
            (out / "cgi" / f"get_params_type{param_type}.cgi").write_text(redact(text), encoding="utf-8")
            status[key] = _redact_obj(camera.get_vars("get_params.cgi", type=param_type))
        except CameraError as exc:
            status[key] = {"error": str(exc)}
    (out / "status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = ["# Probe Report PIPC-011", ""]
    device = status.get("get_status.cgi", {})
    lines += [f"- Model: {device.get('prot_mode')}  Firmware: {device.get('server_version')}  WebUI: {device.get('client_version')}",
              f"- Pages found: {len(pages)}", "", "## CGI calls from the web interface", ""]
    for name, params in info["cgi_params"].items():
        lines.append(f"- `{name}`: {', '.join(params) or '–'}  _(in {', '.join(info['cgi_where'][name])})_")
    lines += ["", "## decoder_control references", ""]
    for page, refs in info["decoder_refs"].items():
        lines.append(f"- {page}: {', '.join(refs)}")
    lines += ["", "## Event handlers with numbers (PTZ buttons)", ""]
    lines += [f"- `{handler}`" for handler in info["handlers"][:300]]
    lines += ["", "## RTSP DESCRIBE", ""]
    lines += [f"- `{path}` → {result}" for path, result in rtsp.items()]
    lines += ["", "## Status (logged in)", "", "```json", json.dumps(status, indent=2, ensure_ascii=False), "```"]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")

    zip_path = out.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in out.rglob("*"):
            if file.is_file():
                archive.write(file, file.relative_to(out.parent))
    return zip_path
