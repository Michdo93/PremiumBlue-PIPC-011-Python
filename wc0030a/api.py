"""HTTP-Client für die LogiLink WC0030A / Apexis APM-H803-MPC."""

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

# Snapshot-Endpunkte: snapshot.htm nutzt video_snapshot.cgi, mobile.htm mobile_snapshot.cgi.
SNAPSHOT_CANDIDATES = [
    "/cgi-bin/video_snapshot.cgi",
    "/cgi-bin/mobile_snapshot.cgi",
]


class CameraError(RuntimeError):
    pass


class Camera:
    """Kapselt alle bekannten CGI-Aufrufe der Kamera.

    Authentifizierung: wie die Original-Weboberfläche per Query-Parameter
    ``user`` und ``pwd`` (siehe main.htm: write_log.cgi?type=..&user=..&pwd=..).
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

    # ------------------------------------------------------------------ Basis
    @property
    def auth(self) -> dict[str, str]:
        return {"user": self.user, "pwd": self.password}

    def url(self, path: str, **params: Any) -> str:
        """Vollständige URL inkl. Zugangsdaten (z. B. für openHAB/VLC)."""
        req = requests.Request("GET", self._abs(path), params={**params, **self.auth}).prepare()
        return req.url

    def _abs(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/cgi-bin/" + path
        return self.base_url + path

    def _get(self, path: str, params: dict[str, Any] | None = None,
             stream: bool = False, timeout: float | None = None) -> requests.Response:
        p = dict(params or {})
        p.update(self.auth)
        attempts = 1 + self.retries
        for attempt in range(1, attempts + 1):
            try:
                if stream:  # eigene Verbindung, damit der Stream keine Befehle blockiert
                    r = requests.get(self._abs(path), params=p, stream=True,
                                     timeout=timeout or self.timeout)
                else:
                    with self._lock:
                        r = self._session.get(self._abs(path), params=p,
                                              timeout=timeout or self.timeout)
                break
            except (requests.ConnectionError, requests.Timeout) as exc:
                # Die Kamera beantwortet die erste Anfrage nach einer Pause oft zu spät
                # bzw. schließt Keep-Alive-Verbindungen still -> einmal neu versuchen.
                if attempt >= attempts:
                    raise CameraError(f"{path}: {exc}" + (f" (nach {attempts} Versuchen)"
                                                          if attempts > 1 else "")) from exc
                log.debug("%s: %s – Versuch %d/%d", path, exc, attempt + 1, attempts)
                if not stream:
                    self._session.close()  # evtl. tote Keep-Alive-Verbindung verwerfen
            except requests.RequestException as exc:
                raise CameraError(f"{path}: {exc}") from exc
        if r.status_code == 401:
            raise CameraError(f"{path}: Benutzername oder Passwort falsch (401)")
        if r.status_code != 200:
            raise CameraError(f"{path}: HTTP {r.status_code}")
        return r

    def raw(self, cgi: str, **params: Any) -> str:
        """Beliebigen CGI-Aufruf absetzen und den Text zurückgeben."""
        name = cgi.rsplit("/", 1)[-1]
        if name in C.DANGEROUS_CGIS and not params.pop("_force", False):
            raise CameraError(f"{name} ist als gefährlich markiert – nur mit --force bzw. _force=True")
        text = self._get(cgi, params).text
        if text.strip().startswith("params error"):
            raise CameraError(f"{cgi}: Kamera meldet 'params error' (Parameter falsch/fehlend)")
        return text

    def get_vars(self, cgi: str, strip_prefix: bool = True, **params: Any) -> dict[str, Any]:
        """get_*.cgi abfragen und als dict zurückgeben."""
        return parse_js_vars(self.raw(cgi, **params), strip_prefix=strip_prefix)

    # ------------------------------------------------------------ Statusdaten
    def status(self) -> dict[str, Any]:
        return self.get_vars("get_status.cgi")

    def real_status(self) -> dict[str, Any]:
        """Laufzeitstatus: Bewegung, Alarm, Eingänge, Auflösung, Framerate …"""
        return self.get_vars("get_real_status.cgi")

    def sd_status(self) -> dict[str, Any]:
        return self.get_vars("get_sdc_status.cgi")

    def preset_status(self) -> dict[str, Any]:
        return self.get_vars("get_preset_status.cgi")

    def camera_vars(self) -> dict[str, Any]:
        """Bildparameter (Helligkeit, Kontrast …). Braucht Login."""
        return self.get_vars("get_camera_vars.cgi")

    def params(self, type_: int) -> dict[str, Any]:
        """Einstellungsgruppe lesen (Typen siehe commands.PARAM_TYPES)."""
        if type_ not in C.PARAM_TYPES:
            raise ValueError(f"get_params type {type_} unbekannt (1..14)")
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
        """Kamera-Log (LogInfo.htm: get_log_page ?line, get_log_info ?page&line)."""
        info = self.get_vars("get_log_page.cgi", line=lines)
        info.update(self.get_vars("get_log_info.cgi", page=page, line=lines))
        return info

    _LOG_KEY = re.compile(r"loginfo_(user|ip|time|type)_(\d+)")

    def log_entries(self, page: int = 1, lines: int = 20) -> dict[str, Any]:
        """Kamera-Log als Liste von Einträgen statt flacher loginfo_*_N-Variablen."""
        raw = self.log(page, lines)
        rows: dict[int, dict[str, Any]] = {}
        rest: dict[str, Any] = {}
        for key, value in raw.items():
            m = self._LOG_KEY.fullmatch(key)
            if not m:
                rest[key] = value
                continue
            if isinstance(value, str):
                value = value.strip() or None
            rows.setdefault(int(m.group(2)), {})[m.group(1)] = value
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
                n = int(self.preset_status().get("presetsta_num", 0))
            except (CameraError, ValueError):
                n = 0
            self._preset_count = n if 0 < n <= 16 else C.PRESET_COUNT
        return self._preset_count

    # --------------------------------------------------------------- PTZ
    def decoder(self, type_: int, cmd: int) -> None:
        """decoder_control.cgi?type=..&cmd=.. (wie live.htm: all_ptz_control)."""
        self.raw("decoder_control.cgi", type=type_, cmd=cmd)
        log.debug("decoder_control type=%s cmd=%s", type_, cmd)

    def ptz(self, cmd: int) -> None:
        self.decoder(C.TYPE_PTZ, cmd)

    def _map_dir(self, direction: str) -> str:
        d = direction.lower().replace("-", "_")
        if d not in C.MOVE:
            raise ValueError(f"Unbekannte Richtung '{direction}'. Erlaubt: {', '.join(C.MOVE)}")
        if self.invert_v:
            d = C.INVERT_V.get(d, d)
        if self.invert_h:
            d = C.INVERT_H.get(d, d)
        return d

    def move(self, direction: str) -> None:
        """Dauerbewegung starten (läuft bis stop() oder Endanschlag)."""
        self.ptz(C.MOVE[self._map_dir(direction)])

    def stop(self, direction: str | None = None) -> None:
        """Bewegung anhalten (ein gemeinsamer Stopp-Code für alle Richtungen)."""
        self.ptz(C.PTZ_STOP)

    def step(self, direction: str, count: int = 1) -> None:
        """Wie mobile.htm: fahren, step_seconds warten, anhalten – ``count``-mal hintereinander.

        Zwischen den Schritten liegt eine kurze Pause (commands.STEP_PAUSE), damit die
        Kamera den Stopp verarbeitet. Auch bei Fehler/Strg+C wird immer gestoppt.
        """
        count = int(count)
        if not 1 <= count <= C.STEP_MAX_COUNT:
            raise ValueError(f"count {count} außerhalb 1..{C.STEP_MAX_COUNT}")
        d = self._map_dir(direction)  # Richtung vor der ersten Bewegung prüfen
        for i in range(count):
            if i:
                time.sleep(C.STEP_PAUSE)
            self.ptz(C.MOVE[d])
            try:
                time.sleep(self.step_seconds)
            finally:
                self.stop()

    def center(self) -> None:
        """Mittelknopf der Weboberfläche (PTZ_CMD_AUTOON)."""
        self.ptz(C.PTZ_AUTO_ON)

    def patrol(self, axis: str, start: bool = True) -> None:
        axis = axis.lower()[:1]
        if axis == "h":
            self.ptz(C.PTZ_PATROL_H if start else C.PTZ_PATROL_H_STOP)
        elif axis == "v":
            self.ptz(C.PTZ_PATROL_V if start else C.PTZ_PATROL_V_STOP)
        else:
            raise ValueError("axis muss 'h' oder 'v' sein")

    def patrol_stop(self) -> None:
        self.ptz(C.PTZ_PATROL_H_STOP)
        self.ptz(C.PTZ_PATROL_V_STOP)

    def preset_goto(self, n: int) -> None:
        """Preset n (1-basiert) anfahren; die Kamera zählt ab 0."""
        self._check_preset(n)
        self.decoder(C.TYPE_PRESET_CALL, n - 1)

    def preset_set(self, n: int) -> None:
        """Aktuelle Position als Preset n (1-basiert) speichern."""
        self._check_preset(n)
        self.decoder(C.TYPE_PRESET_SET, n - 1)

    def _check_preset(self, n: int) -> None:
        if not 1 <= n <= self.preset_count():
            raise ValueError(f"Preset {n} außerhalb 1..{self.preset_count()}")

    def io_output(self, on: bool) -> None:
        """Schaltausgang (Weboberfläche: 'Relay an/aus')."""
        self.decoder(C.TYPE_SWITCH, 1 if on else 0)

    # ----------------------------------------------------- Bild/Einstellungen
    IMAGE_VARS = tuple(C.SCAM_BY_NAME)

    @staticmethod
    def _scam_name(name: str) -> str:
        name = C.SCAM_ALIASES.get(name, name)
        if name not in C.SCAM_BY_NAME:
            raise ValueError(f"Bildparameter '{name}' unbekannt. Erlaubt: {', '.join(C.SCAM_BY_NAME)}")
        return name

    def set_camera_var(self, name: str, value: int) -> None:
        """Einen Bildparameter setzen: set_camera_vars.cgi?type=..&value=.."""
        name = self._scam_name(name)
        t, lo, hi = C.SCAM_BY_NAME[name]
        value = int(value)
        if not lo <= value <= hi:
            raise ValueError(f"{name}: {value} außerhalb {lo}..{hi}")
        self.raw("set_camera_vars.cgi", type=t, value=value)

    def set_camera_vars(self, **values: Any) -> None:
        """Mehrere Bildparameter nacheinander setzen (die Kamera kennt nur Einzelwerte)."""
        for name, value in values.items():
            self.set_camera_var(name, value)

    def set_lamp(self, mode: int) -> None:
        """Status-LED (setmenu/Light.htm), Modi siehe commands.LAMP_MODES."""
        if mode not in C.LAMP_MODES:
            raise ValueError(f"LED-Modus {mode} unbekannt (0..3)")
        self.raw("set_lamp.cgi", type=mode, next_url="setmenu/Light.htm")

    # ------------------------------------------------------ Bewegungsmelder
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
        p = self.params(2)
        return {new: p[old] for old, new in self.MOTION_KEYS.items() if old in p}

    def set_motion(self, **changes: Any) -> dict[str, Any]:
        """Bewegungsmelder ändern (lesen, ändern, komplett zurückschreiben).

        Schlüssel: motion_enable 0/1, motion_level 1..5, mtimeout 0..5,
        msdrec_enable, mmail_enable, mftp_enable, malarmout_enable (0/1).
        """
        cur = self.motion_settings()
        missing = [k for k in self.MOTION_KEYS.values() if k not in cur]
        if missing:
            raise CameraError(f"get_params type=2 liefert {missing} nicht – bitte probe ausführen")
        unknown = set(changes) - set(cur)
        if unknown:
            raise ValueError(f"unbekannte Schlüssel: {', '.join(sorted(unknown))}")
        cur.update({k: int(v) for k, v in changes.items()})
        # wie MotionAlarm.htm: Erkennungsbereich immer ganzes Bild
        self.raw("set_motion_alarm.cgi", next_url="setmenu/MotionAlarm.htm",
                 start_x=0, start_y=0, end_x=320, end_y=240, **cur)
        return cur

    # ------------------------------------------------------------- Kurse
    def cruise_start(self, index: int) -> None:
        """Gespeicherten Kurs (Preset-Tour) starten (cruise_set.htm). index=100 stoppt."""
        if not (0 <= index < C.CRUISE_COUNT or index == 100):
            raise ValueError(f"Kursindex {index} außerhalb 0..{C.CRUISE_COUNT - 1}")
        self.raw("control_cruise.cgi", index=index)

    def cruise_stop(self) -> None:
        self.raw("control_cruise.cgi", index=100)

    def reboot(self) -> None:
        self.raw("reboot.cgi", _force=True)

    # --------------------------------------------------------------- Bilder
    def snapshot(self) -> bytes:
        """Ein JPEG holen. Der funktionierende Endpunkt wird gemerkt."""
        paths = [self._snapshot_path] if self._snapshot_path else SNAPSHOT_CANDIDATES
        errors = []
        for path in paths:
            try:
                r = self._get(path, timeout=max(self.timeout, 8))
            except CameraError as exc:
                errors.append(str(exc))
                continue
            data = r.content
            if data.startswith(JPEG_SOI):
                self._snapshot_path = path
                return data
            # Manche Firmwares liefern eine HTML-Seite mit <img src=...>
            errors.append(f"{path}: kein JPEG ({r.headers.get('Content-Type')}, {len(data)} Bytes)")
        self._snapshot_path = None
        raise CameraError("Snapshot fehlgeschlagen: " + " | ".join(errors))

    def mjpeg_url(self, **params: Any) -> str:
        return self.url("/cgi-bin/videostream.cgi", **params)

    def mjpeg_frames(self, **params: Any) -> Iterator[bytes]:
        """Liefert einzelne JPEG-Frames aus dem MJPEG-Stream."""
        r = self._get("/cgi-bin/videostream.cgi", params, stream=True, timeout=10)
        buf = b""
        try:
            for chunk in r.iter_content(chunk_size=8192):
                buf += chunk
                while True:
                    a = buf.find(JPEG_SOI)
                    if a < 0:
                        buf = buf[-1:]
                        break
                    b = buf.find(JPEG_EOI, a + 2)
                    if b < 0:
                        buf = buf[a:]
                        break
                    yield buf[a:b + 2]
                    buf = buf[b + 2:]
                if len(buf) > 4_000_000:  # Schutz gegen kaputten Stream
                    buf = b""
        finally:
            r.close()

    def rtsp_url(self, path: str = C.RTSP_PATH) -> str:
        """RTSP-URL wie vlc_video.htm: /live/av0?user=..&passwd=.. (Parameter heißt passwd!)."""
        try:
            port = int(self.status().get("rtsp_port", 554))
        except CameraError:
            port = 554
        q = requests.Request("GET", "http://x/", params={"user": self.user, "passwd": self.password}).prepare().url
        return f"rtsp://{self.host}:{port}{path}?{q.split('?', 1)[1]}"
