"""HTTP client for the PremiumBlue PIPC-011 / Apexis APM-H803-MPC."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Iterator

import requests

from . import commands as C
from .parser import parse_js_vars

log = logging.getLogger(__name__)

JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"

# Snapshot endpoints: snapshot.htm uses video_snapshot.cgi, mobile.htm uses mobile_snapshot.cgi.
SNAPSHOT_CANDIDATES = [
    "/cgi-bin/video_snapshot.cgi",
    "/cgi-bin/mobile_snapshot.cgi",
]


class CameraError(RuntimeError):
    pass


class Camera:
    """Wraps all known CGI calls of the camera.

    Authentication: like the original web interface, via the query parameters
    ``user`` and ``pwd`` (see main.htm: write_log.cgi?type=..&user=..&pwd=..).
    """

    def __init__(self, host: str, user: str = "admin", password: str = "",
                 port: int = 80, timeout: float = 5.0, retries: int = 1,
                 invert_v: bool = False, invert_h: bool = False,
                 step_seconds: float = C.STEP_SECONDS):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.timeout = timeout
        self.retries = max(0, int(retries))
        self.invert_v = invert_v
        self.invert_h = invert_h
        self.step_seconds = step_seconds
        self.base_url = f"http://{host}" + (f":{port}" if port != 80 else "")
        self._session = requests.Session()
        self._lock = threading.Lock()
        self._snapshot_path: str | None = None
        self._preset_count: int | None = None

    # ------------------------------------------------------------------ Basics
    @property
    def auth(self) -> dict[str, str]:
        return {"user": self.user, "pwd": self.password}

    def url(self, path: str, **params: Any) -> str:
        """Full URL including credentials (e.g. for openHAB/VLC)."""
        request = requests.Request("GET", self._abs(path), params={**params, **self.auth}).prepare()
        return request.url

    def _abs(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/cgi-bin/" + path
        return self.base_url + path

    def _get(self, path: str, params: dict[str, Any] | None = None,
             stream: bool = False, timeout: float | None = None) -> requests.Response:
        query = dict(params or {})
        query.update(self.auth)
        attempts = 1 + self.retries
        for attempt in range(1, attempts + 1):
            try:
                if stream:  # separate connection so the stream does not block commands
                    response = requests.get(self._abs(path), params=query, stream=True,
                                     timeout=timeout or self.timeout)
                else:
                    with self._lock:
                        response = self._session.get(self._abs(path), params=query,
                                              timeout=timeout or self.timeout)
                break
            except (requests.ConnectionError, requests.Timeout) as exc:
                # The camera often answers the first request after an idle period too late
                # or silently closes keep-alive connections -> retry once.
                if attempt >= attempts:
                    raise CameraError(f"{path}: {exc}" + (f" (after {attempts} attempts)"
                                                          if attempts > 1 else "")) from exc
                log.debug("%s: %s – attempt %d/%d", path, exc, attempt + 1, attempts)
                if not stream:
                    self._session.close()  # discard a possibly dead keep-alive connection
            except requests.RequestException as exc:
                raise CameraError(f"{path}: {exc}") from exc
        if response.status_code == 401:
            raise CameraError(f"{path}: wrong username or password (401)")
        if response.status_code != 200:
            raise CameraError(f"{path}: HTTP {response.status_code}")
        return response

    def raw(self, cgi: str, **params: Any) -> str:
        """Send an arbitrary CGI request and return the response text."""
        name = cgi.rsplit("/", 1)[-1]
        if name in C.DANGEROUS_CGIS and not params.pop("_force", False):
            raise CameraError(f"{name} is marked as dangerous – only allowed with --force or _force=True")
        text = self._get(cgi, params).text
        if text.strip().startswith("params error"):
            raise CameraError(f"{cgi}: camera reports 'params error' (wrong/missing parameters)")
        return text

    def get_vars(self, cgi: str, strip_prefix: bool = True, **params: Any) -> dict[str, Any]:
        """Query a get_*.cgi endpoint and return the result as dict."""
        return parse_js_vars(self.raw(cgi, **params), strip_prefix=strip_prefix)

    # ------------------------------------------------------------ Status data
    def status(self) -> dict[str, Any]:
        return self.get_vars("get_status.cgi")

    def real_status(self) -> dict[str, Any]:
        """Runtime status: motion, alarm, inputs, resolution, frame rate …"""
        return self.get_vars("get_real_status.cgi")

    def sd_status(self) -> dict[str, Any]:
        return self.get_vars("get_sdc_status.cgi")

    def preset_status(self) -> dict[str, Any]:
        return self.get_vars("get_preset_status.cgi")

    def camera_vars(self) -> dict[str, Any]:
        """Image parameters (brightness, contrast …). Requires login."""
        return self.get_vars("get_camera_vars.cgi")

    def params(self, type_: int) -> dict[str, Any]:
        """Read a settings group (types see commands.PARAM_TYPES)."""
        if type_ not in C.PARAM_TYPES:
            raise ValueError(f"get_params type {type_} unknown (1..14)")
        return self.get_vars("get_params.cgi", type=type_)

    def check_user(self) -> dict[str, Any]:
        return self.get_vars("check_user.cgi")

    def cruise_list(self) -> dict[str, Any]:
        return self.get_vars("get_list_cruise.cgi")

    def cruise(self, index: int) -> dict[str, Any]:
        return self.get_vars("get_cruise.cgi", index=index)

    def motion_schedule(self) -> dict[str, Any]:
        return self.get_vars("get_motion_schedule.cgi")

    def alarm_schedule(self) -> dict[str, Any]:
        return self.get_vars("get_alarm_schedule.cgi")

    def log(self, page: int = 1, lines: int = 20) -> dict[str, Any]:
        """Camera log (LogInfo.htm: get_log_page ?line, get_log_info ?page&line)."""
        info = self.get_vars("get_log_page.cgi", line=lines)
        info.update(self.get_vars("get_log_info.cgi", page=page, line=lines))
        return info

    _LOG_KEY = re.compile(r"loginfo_(user|ip|time|type)_(\d+)")

    def log_entries(self, page: int = 1, lines: int = 20) -> dict[str, Any]:
        """Camera log as a list of entries instead of flat loginfo_*_N variables."""
        raw = self.log(page, lines)
        rows: dict[int, dict[str, Any]] = {}
        rest: dict[str, Any] = {}
        for key, value in raw.items():
            match = self._LOG_KEY.fullmatch(key)
            if not match:
                rest[key] = value
                continue
            if isinstance(value, str):
                value = value.strip() or None
            rows.setdefault(int(match.group(2)), {})[match.group(1)] = value
        rest["page"] = page
        rest["entries"] = [rows[i] for i in sorted(rows)]
        return rest

    def all_status(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for cgi in C.READ_CGIS:
            try:
                out[cgi] = self.get_vars(cgi)
            except CameraError as exc:
                out[cgi] = {"error": str(exc)}
        return out

    def preset_count(self) -> int:
        if self._preset_count is None:
            try:
                count = int(self.preset_status().get("presetsta_num", 0))
            except (CameraError, ValueError):
                count = 0
            self._preset_count = count if 0 < count <= 16 else C.PRESET_COUNT
        return self._preset_count

    # --------------------------------------------------------------- PTZ
    def decoder(self, type_: int, cmd: int) -> None:
        """decoder_control.cgi?type=..&cmd=.. (like live.htm: all_ptz_control)."""
        self.raw("decoder_control.cgi", type=type_, cmd=cmd)
        log.debug("decoder_control type=%s cmd=%s", type_, cmd)

    def ptz(self, cmd: int) -> None:
        self.decoder(C.TYPE_PTZ, cmd)

    def _map_direction(self, direction: str) -> str:
        mapped = direction.lower().replace("-", "_")
        if mapped not in C.MOVE:
            raise ValueError(f"Unknown direction '{direction}'. Allowed: {', '.join(C.MOVE)}")
        if self.invert_v:
            mapped = C.INVERT_V.get(mapped, mapped)
        if self.invert_h:
            mapped = C.INVERT_H.get(mapped, mapped)
        return mapped

    def move(self, direction: str) -> None:
        """Start continuous movement (runs until stop() or end stop is reached)."""
        self.ptz(C.MOVE[self._map_direction(direction)])

    def stop(self, direction: str | None = None) -> None:
        """Stop movement (a single stop code for all directions)."""
        self.ptz(C.PTZ_STOP)

    def step(self, direction: str, count: int = 1) -> None:
        """Like mobile.htm: move, wait step_seconds, stop – ``count`` times in a row.

        A short pause (commands.STEP_PAUSE) between the steps gives the camera time
        to process the stop. The camera is always stopped, even on error/Ctrl+C.
        """
        count = int(count)
        if not 1 <= count <= C.STEP_MAX_COUNT:
            raise ValueError(f"count {count} outside 1..{C.STEP_MAX_COUNT}")
        mapped = self._map_direction(direction)  # validate direction before the first movement
        for i in range(count):
            if i:
                time.sleep(C.STEP_PAUSE)
            self.ptz(C.MOVE[mapped])
            try:
                time.sleep(self.step_seconds)
            finally:
                self.stop()

    def center(self) -> None:
        """Center button of the web interface (PTZ_CMD_AUTOON)."""
        self.ptz(C.PTZ_AUTO_ON)

    def patrol(self, axis: str, start: bool = True) -> None:
        axis = axis.lower()[:1]
        if axis == "h":
            self.ptz(C.PTZ_PATROL_H if start else C.PTZ_PATROL_H_STOP)
        elif axis == "v":
            self.ptz(C.PTZ_PATROL_V if start else C.PTZ_PATROL_V_STOP)
        else:
            raise ValueError("axis must be 'h' or 'v'")

    def patrol_stop(self) -> None:
        self.ptz(C.PTZ_PATROL_H_STOP)
        self.ptz(C.PTZ_PATROL_V_STOP)

    def preset_goto(self, number: int) -> None:
        """Go to preset ``number`` (1-based); the camera counts from 0."""
        self._check_preset(number)
        self.decoder(C.TYPE_PRESET_CALL, number - 1)

    def preset_set(self, number: int) -> None:
        """Save the current position as preset ``number`` (1-based)."""
        self._check_preset(number)
        self.decoder(C.TYPE_PRESET_SET, number - 1)

    def _check_preset(self, number: int) -> None:
        if not 1 <= number <= self.preset_count():
            raise ValueError(f"Preset {number} outside 1..{self.preset_count()}")

    def io_output(self, on: bool) -> None:
        """Relay output (web interface: 'Relay on/off')."""
        self.decoder(C.TYPE_SWITCH, 1 if on else 0)

    # ----------------------------------------------------- Image/settings
    IMAGE_VARS = tuple(C.SCAM_BY_NAME)

    @staticmethod
    def _scam_name(name: str) -> str:
        name = C.SCAM_ALIASES.get(name, name)
        if name not in C.SCAM_BY_NAME:
            raise ValueError(f"Image parameter '{name}' unknown. Allowed: {', '.join(C.SCAM_BY_NAME)}")
        return name

    def set_camera_var(self, name: str, value: int) -> None:
        """Set a single image parameter: set_camera_vars.cgi?type=..&value=.."""
        name = self._scam_name(name)
        type_, low, high = C.SCAM_BY_NAME[name]
        value = int(value)
        if not low <= value <= high:
            raise ValueError(f"{name}: {value} outside {low}..{high}")
        self.raw("set_camera_vars.cgi", type=type_, value=value)

    def set_camera_vars(self, **values: Any) -> None:
        """Set several image parameters one after another (the camera only accepts single values)."""
        for name, value in values.items():
            self.set_camera_var(name, value)

    def set_lamp(self, mode: int) -> None:
        """Status LED (setmenu/Light.htm), modes see commands.LAMP_MODES."""
        if mode not in C.LAMP_MODES:
            raise ValueError(f"LED mode {mode} unknown (0..3)")
        self.raw("set_lamp.cgi", type=mode, next_url="setmenu/Light.htm")

    # ------------------------------------------------------ Motion detector
    MOTION_KEYS = {  # get_params type=2 -> set_motion_alarm.cgi
        "motion_Enable": "motion_enable",
        "byMotionSensitive": "motion_level",
        "mtimeout": "mtimeout",
        "msdrec_enable": "msdrec_enable",
        "mmail_enable": "mmail_enable",
        "mftp_enable": "mftp_enable",
        "malarmout_enable": "malarmout_enable",
    }

    def motion_settings(self) -> dict[str, Any]:
        params = self.params(2)
        return {new: params[old] for old, new in self.MOTION_KEYS.items() if old in params}

    def set_motion(self, **changes: Any) -> dict[str, Any]:
        """Change motion detector settings (read, modify, write back completely).

        Keys: motion_enable 0/1, motion_level 1..5, mtimeout 0..5,
        msdrec_enable, mmail_enable, mftp_enable, malarmout_enable (0/1).
        """
        current = self.motion_settings()
        missing = [k for k in self.MOTION_KEYS.values() if k not in current]
        if missing:
            raise CameraError(f"get_params type=2 does not return {missing} – please run probe")
        unknown = set(changes) - set(current)
        if unknown:
            raise ValueError(f"unknown keys: {', '.join(sorted(unknown))}")
        current.update({k: int(v) for k, v in changes.items()})
        # like MotionAlarm.htm: detection area is always the full image
        self.raw("set_motion_alarm.cgi", next_url="setmenu/MotionAlarm.htm",
                 start_x=0, start_y=0, end_x=320, end_y=240, **current)
        return current

    # ------------------------------------------------------------- Cruises
    def cruise_start(self, index: int) -> None:
        """Start a stored cruise (preset tour) (cruise_set.htm). index=100 stops."""
        if not (0 <= index < C.CRUISE_COUNT or index == 100):
            raise ValueError(f"Cruise index {index} outside 0..{C.CRUISE_COUNT - 1}")
        self.raw("control_cruise.cgi", index=index)

    def cruise_stop(self) -> None:
        self.raw("control_cruise.cgi", index=100)

    def reboot(self) -> None:
        self.raw("reboot.cgi", _force=True)

    # --------------------------------------------------------------- Images
    def snapshot(self) -> bytes:
        """Fetch a JPEG. The working endpoint is remembered."""
        paths = [self._snapshot_path] if self._snapshot_path else SNAPSHOT_CANDIDATES
        errors = []
        for path in paths:
            try:
                response = self._get(path, timeout=max(self.timeout, 8))
            except CameraError as exc:
                errors.append(str(exc))
                continue
            data = response.content
            if data.startswith(JPEG_SOI):
                self._snapshot_path = path
                return data
            # Some firmwares return an HTML page with <img src=...>
            errors.append(f"{path}: not a JPEG ({response.headers.get('Content-Type')}, {len(data)} bytes)")
        self._snapshot_path = None
        raise CameraError("Snapshot failed: " + " | ".join(errors))

    def mjpeg_url(self, **params: Any) -> str:
        return self.url("/cgi-bin/videostream.cgi", **params)

    def mjpeg_frames(self, **params: Any) -> Iterator[bytes]:
        """Yield individual JPEG frames from the MJPEG stream."""
        response = self._get("/cgi-bin/videostream.cgi", params, stream=True, timeout=10)
        buffer = b""
        try:
            for chunk in response.iter_content(chunk_size=8192):
                buffer += chunk
                while True:
                    start = buffer.find(JPEG_SOI)
                    if start < 0:
                        buffer = buffer[-1:]
                        break
                    end = buffer.find(JPEG_EOI, start + 2)
                    if end < 0:
                        buffer = buffer[start:]
                        break
                    yield buffer[start:end + 2]
                    buffer = buffer[end + 2:]
                if len(buffer) > 4_000_000:  # protection against a broken stream
                    buffer = b""
        finally:
            response.close()

    def rtsp_url(self, path: str = C.RTSP_PATH) -> str:
        """RTSP URL like vlc_video.htm: /live/av0?user=..&passwd=.. (parameter is called passwd!)."""
        try:
            port = int(self.status().get("rtsp_port", 554))
        except CameraError:
            port = 554
        query = requests.Request("GET", "http://x/", params={"user": self.user, "passwd": self.password}).prepare().url
        return f"rtsp://{self.host}:{port}{path}?{query.split('?', 1)[1]}"
