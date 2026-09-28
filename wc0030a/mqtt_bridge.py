"""MQTT-Brücke: Kamera-Status publizieren, Befehle entgegennehmen.

Topic-Schema (base = mqtt.base_topic, Default "wc0030a"):

  base/status                  online | offline               (retained, LWT)
  base/state/<key>             einzelne Zustände              (retained)
  base/state/json/<cgi>        komplette Antwort als JSON     (retained)
  base/snapshot                JPEG-Bytes                     (retained)

  base/cmd/ptz                 UP DOWN LEFT RIGHT UP_LEFT UP_RIGHT DOWN_LEFT
                               DOWN_RIGHT CENTER STOP  -> Einzelschritt,
                               "LEFT:3" -> drei Einzelschritte
  base/cmd/ptz/move            Richtung -> Dauerbewegung, STOP beendet
  base/cmd/preset              1..9 -> Preset anfahren
  base/cmd/preset/set          1..9 -> aktuelle Position speichern
  base/cmd/patrol              HORIZONTAL | VERTICAL | STOP
  base/cmd/relay               ON | OFF
  base/cmd/snapshot            beliebig -> neues Bild auf base/snapshot
  base/cmd/refresh             beliebig -> alle Zustände neu lesen
  base/cmd/camera_vars         JSON {"name": wert, ...} -> set_camera_vars.cgi
  base/cmd/camera/<name>       Einzelwert, z. B. camera/brightness = 140, camera/flip = ON
                               (brightness contrast hue saturation ptzspeed mirror flip
                                OSDTimer aec_value; Aliase: osd, hz, speed)
  base/cmd/lamp                0..3 Status-LED
  base/cmd/motion/enable       ON | OFF  Bewegungserkennung der Kamera
  base/cmd/motion/level        1..5      Empfindlichkeit
  base/cmd/motion/timeout      0..5      Alarmdauer (0 dauerhaft, 1=5 s … 5=60 s)
  base/cmd/cruise              Index -> Kurs starten, STOP
  base/cmd/reboot              REBOOT
  base/cmd/raw                 JSON {"cgi": "...", "params": {...}} (nur allow_raw)
"""

from __future__ import annotations

import json
import logging
import queue
import signal
import threading
import time
from typing import Any, Callable

import paho.mqtt.client as mqtt

from .api import Camera, CameraError
from . import commands as C

log = logging.getLogger(__name__)

ONOFF = {0: "OFF", 1: "ON"}


def _onoff(v: Any) -> str:
    try:
        return "ON" if int(v) else "OFF"
    except (TypeError, ValueError):
        return "OFF"


class Bridge:
    def __init__(self, cam: Camera, cfg: dict[str, Any]):
        self.cam = cam
        self.cfg = cfg
        self.base = cfg["base_topic"].rstrip("/")
        self.jobs: "queue.Queue[tuple[str, Callable[[], None]]]" = queue.Queue()
        self.stop_event = threading.Event()
        self._last: dict[str, str] = {}
        self._motion = False
        self._online = None

        try:  # paho-mqtt >= 2.0
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg["client_id"])
        except AttributeError:  # paho-mqtt 1.x
            self.client = mqtt.Client(client_id=cfg["client_id"])
        if cfg.get("user"):
            self.client.username_pw_set(cfg["user"], cfg.get("password") or None)
        self.client.will_set(f"{self.base}/status", "offline", qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(1, 30)

    # ----------------------------------------------------------- publizieren
    def pub(self, key: str, value: Any, retain: bool = True, force: bool = False) -> None:
        topic = f"{self.base}/{key}"
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        if not isinstance(value, (bytes, bytearray)):
            value = str(value)
            if not force and self._last.get(topic) == value:
                return
            self._last[topic] = value
        self.client.publish(topic, value, qos=1, retain=retain)

    def state(self, key: str, value: Any, **kw) -> None:
        self.pub(f"state/{key}", value, **kw)

    def set_online(self, online: bool) -> None:
        if online != self._online:
            self._online = online
            self.pub("status", "online" if online else "offline", force=True)

    # ------------------------------------------------------------- MQTT-Callbacks
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        log.info("MQTT verbunden (rc=%s)", rc)
        client.subscribe(f"{self.base}/cmd/#", qos=1)
        self._last.clear()
        self._online = None
        self.jobs.put(("refresh", self.refresh_all))

    def _on_message(self, client, userdata, msg):
        sub = msg.topic[len(self.base) + 5:]  # nach "base/cmd/"
        payload = msg.payload.decode("utf-8", "replace").strip()
        log.info("Befehl %s = %s", sub, payload)
        try:
            job = self._dispatch(sub, payload)
        except (ValueError, KeyError) as exc:
            self.state("last_error", f"{sub}: {exc}", force=True)
            return
        if job:
            self.jobs.put((sub, job))

    def _dispatch(self, sub: str, payload: str) -> Callable[[], None] | None:
        cam, up = self.cam, payload.upper()
        if sub == "ptz":
            if up == "CENTER":
                return cam.center
            if up == "STOP":
                return cam.stop
            d, _, n = up.lower().partition(":")   # "LEFT" oder "LEFT:3"
            if d not in C.MOVE:
                raise ValueError(f"Richtung '{payload}' unbekannt")
            count = int(n) if n else 1
            if not 1 <= count <= C.STEP_MAX_COUNT:
                raise ValueError(f"Anzahl {count} außerhalb 1..{C.STEP_MAX_COUNT}")
            return lambda: cam.step(d, count)
        if sub == "ptz/move":
            if up == "STOP":
                return cam.stop
            d = up.lower()
            if d not in C.MOVE:
                raise ValueError(f"Richtung '{payload}' unbekannt")
            return lambda: cam.move(d)
        if sub == "preset":
            n = int(float(payload))
            return lambda: cam.preset_goto(n)
        if sub == "preset/set":
            n = int(float(payload))
            return lambda: cam.preset_set(n)
        if sub == "patrol":
            def patrol():
                cam.patrol_stop()
                if up.startswith("H"):
                    cam.patrol("h", True)
                elif up.startswith("V"):
                    cam.patrol("v", True)
                self.state("patrol", {"H": "HORIZONTAL", "V": "VERTICAL"}.get(up[:1], "STOP"))
            return patrol
        if sub == "relay":
            on = up in ("ON", "1", "TRUE")

            def relay():
                cam.io_output(on)
                self.state("relay", "ON" if on else "OFF")
            return relay
        if sub == "snapshot":
            return self.publish_snapshot
        if sub == "refresh":
            return self.refresh_all
        if sub == "camera_vars":
            values = json.loads(payload)

            def setvars():
                cam.set_camera_vars(**values)
                self.poll_camera_vars()
            return setvars
        if sub.startswith("camera/"):
            name = Camera._scam_name(sub.split("/", 1)[1])
            value = int(up == "ON") if up in ("ON", "OFF") else int(float(payload))

            def setone():
                cam.set_camera_var(name, value)
                self.poll_camera_vars()
            return setone
        if sub == "lamp":
            mode = int(float(payload))

            def lamp():
                cam.set_lamp(mode)
                self.state("lamp", mode)
            return lamp
        if sub in ("motion/enable", "motion/level", "motion/timeout"):
            key = {"motion/enable": "motion_enable", "motion/level": "motion_level",
                   "motion/timeout": "mtimeout"}[sub]
            value = int(up == "ON") if up in ("ON", "OFF") else int(float(payload))

            def motion():
                cam.set_motion(**{key: value})
                self.poll_motion_settings()
            return motion
        if sub == "cruise":
            if up == "STOP":
                return cam.cruise_stop
            idx = int(float(payload))
            return lambda: cam.cruise_start(idx)
        if sub == "reboot":
            if up != "REBOOT":
                raise ValueError("Payload muss REBOOT lauten")
            return cam.reboot
        if sub == "raw":
            if not self.cfg.get("allow_raw"):
                raise ValueError("cmd/raw ist deaktiviert (mqtt.allow_raw)")
            req = json.loads(payload)

            def raw():
                self.pub("raw/result", cam.raw(req["cgi"], **req.get("params", {})), retain=False, force=True)
            return raw
        raise ValueError(f"unbekannter Befehl {sub}")

    # ------------------------------------------------------------- Polling
    def poll_fast(self) -> None:
        rs = self.cam.real_status()
        self.set_online(True)
        motion = _onoff(rs.get("realstatus_motion"))
        self.state("motion", motion)
        self.state("alarm", _onoff(rs.get("realstatus_alstatus")))
        self.state("input1", _onoff(rs.get("realstatus_inputal1")))
        self.state("input2", _onoff(rs.get("realstatus_inputal2")))
        self.state("sd_alarm", _onoff(rs.get("realstatus_sdalarm")))
        self.state("framerate", rs.get("realstatus_mrate", ""))
        w, h = rs.get("realstatus_videoW"), rs.get("realstatus_videoH")
        if w and h:
            self.state("resolution", f"{w}x{h}")
        self.state("ip", rs.get("realstatus_ipaddr", ""))
        self.state("json/real_status", rs)
        is_motion = motion == "ON"
        if is_motion and not self._motion and self.cfg.get("snapshot_on_motion"):
            self.jobs.put(("snapshot", self.publish_snapshot))
        self._motion = is_motion

    def poll_slow(self) -> None:
        st = self.cam.status()
        self.state("model", st.get("prot_mode", ""))
        self.state("firmware", st.get("server_version", ""))
        self.state("webui", st.get("client_version", ""))
        self.state("alias", st.get("alias_name", ""))
        self.state("lamp", st.get("lamp_status", ""))
        self.state("json/status", st)
        try:
            sd = self.cam.sd_status()
            self.state("sd_ok", _onoff(sd.get("sdc_status_normal")))
            self.state("sd_total_mb", round(int(sd.get("sdc_status_allspace", 0)) / 1024))
            self.state("sd_free_mb", round(int(sd.get("sdc_status_freespace", 0)) / 1024))
        except (CameraError, ValueError) as exc:
            log.debug("SD-Status: %s", exc)
        self.state("presets", self.cam.preset_count())
        self.poll_camera_vars()
        self.poll_motion_settings()

    def poll_motion_settings(self) -> None:
        try:
            m = self.cam.motion_settings()
        except CameraError as exc:
            log.debug("motion_settings: %s", exc)
            return
        if "motion_enable" in m:
            self.state("motion/enable", _onoff(m["motion_enable"]))
        if "motion_level" in m:
            self.state("motion/level", m["motion_level"])
        if "mtimeout" in m:
            self.state("motion/timeout", m["mtimeout"])

    def poll_camera_vars(self) -> None:
        try:
            cv = self.cam.camera_vars()
        except CameraError as exc:
            log.debug("camera_vars: %s", exc)
            return
        self.state("json/camera_vars", cv)
        for k, v in cv.items():
            if not k.endswith("result"):
                self.state(f"camera/{k}", v)

    def refresh_all(self) -> None:
        self.poll_fast()
        self.poll_slow()

    def publish_snapshot(self) -> None:
        self.pub("snapshot", self.cam.snapshot(), retain=True)
        self.state("snapshot_time", time.strftime("%Y-%m-%dT%H:%M:%S"), force=True)

    # ------------------------------------------------------------- Threads
    def _worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                name, job = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                job()
            except (CameraError, ValueError) as exc:
                log.warning("%s: %s", name, exc)
                self.state("last_error", f"{name}: {exc}", force=True)
                if isinstance(exc, CameraError) and "HTTP" not in str(exc) and "params" not in str(exc):
                    self.set_online(False)

    def _poller(self) -> None:
        next_fast = next_slow = next_snap = 0.0
        while not self.stop_event.is_set():
            now = time.monotonic()
            if now >= next_fast:
                self.jobs.put(("poll_fast", self.poll_fast))
                next_fast = now + float(self.cfg["poll_fast"])
            if now >= next_slow:
                self.jobs.put(("poll_slow", self.poll_slow))
                next_slow = now + float(self.cfg["poll_slow"])
            iv = float(self.cfg.get("snapshot_interval") or 0)
            if iv > 0 and now >= next_snap:
                self.jobs.put(("snapshot", self.publish_snapshot))
                next_snap = now + iv
            # Warteschlange nicht volllaufen lassen, wenn die Kamera hängt
            while self.jobs.qsize() > 20:
                try:
                    self.jobs.get_nowait()
                except queue.Empty:
                    break
            self.stop_event.wait(0.2)

    def run(self) -> None:
        self.client.connect_async(self.cfg["host"], int(self.cfg["port"]), keepalive=30)
        self.client.loop_start()
        threads = [threading.Thread(target=self._worker, daemon=True, name="worker"),
                   threading.Thread(target=self._poller, daemon=True, name="poller")]
        for t in threads:
            t.start()

        def _stop(*_):
            self.stop_event.set()
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
        log.info("Bridge läuft: Kamera %s, Broker %s:%s, Basis-Topic '%s'",
                 self.cam.host, self.cfg["host"], self.cfg["port"], self.base)
        while not self.stop_event.is_set():
            self.stop_event.wait(1)
        self.client.publish(f"{self.base}/status", "offline", qos=1, retain=True).wait_for_publish(2)
        self.client.loop_stop()
        self.client.disconnect()
