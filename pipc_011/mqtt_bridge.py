"""MQTT bridge: publish camera state, receive commands.

Topic scheme (base = mqtt.base_topic, default "pipc011"):

  base/status                  online | offline               (retained, LWT)
  base/state/<key>             individual states              (retained)
  base/state/json/<cgi>        complete response as JSON      (retained)
  base/snapshot                JPEG bytes                     (retained)

  base/cmd/ptz                 UP DOWN LEFT RIGHT UP_LEFT UP_RIGHT DOWN_LEFT
                               DOWN_RIGHT CENTER STOP  -> single step,
                               "LEFT:3" -> three single steps
  base/cmd/ptz/move            direction -> continuous movement, STOP ends it
  base/cmd/preset              1..9 -> go to preset
  base/cmd/preset/set          1..9 -> save current position
  base/cmd/patrol              HORIZONTAL | VERTICAL | STOP
  base/cmd/relay               ON | OFF
  base/cmd/snapshot            any payload -> new image on base/snapshot
  base/cmd/refresh             any payload -> re-read all states
  base/cmd/camera_vars         JSON {"name": value, ...} -> set_camera_vars.cgi
  base/cmd/camera/<name>       single value, e.g. camera/brightness = 140, camera/flip = ON
                               (brightness contrast hue saturation ptzspeed mirror flip
                                OSDTimer aec_value; aliases: osd, hz, speed)
  base/cmd/lamp                0..3 status LED
  base/cmd/motion/enable       ON | OFF  camera motion detection
  base/cmd/motion/level        1..5      sensitivity
  base/cmd/motion/timeout      0..5      alarm duration (0 permanent, 1=5 s … 5=60 s)
  base/cmd/cruise              index -> start cruise, STOP
  base/cmd/reboot              REBOOT
  base/cmd/raw                 JSON {"cgi": "...", "params": {...}} (allow_raw only)
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


def _onoff(value: Any) -> str:
    try:
        return "ON" if int(value) else "OFF"
    except (TypeError, ValueError):
        return "OFF"


class Bridge:
    def __init__(self, camera: Camera, cfg: dict[str, Any]):
        self.camera = camera
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

    # ----------------------------------------------------------- Publishing
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

    # ------------------------------------------------------------- MQTT callbacks
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        log.info("MQTT connected (rc=%s)", rc)
        client.subscribe(f"{self.base}/cmd/#", qos=1)
        self._last.clear()
        self._online = None
        self.jobs.put(("refresh", self.refresh_all))

    def _on_message(self, client, userdata, msg):
        sub = msg.topic[len(self.base) + 5:]  # after "base/cmd/"
        payload = msg.payload.decode("utf-8", "replace").strip()
        log.info("Command %s = %s", sub, payload)
        try:
            job = self._dispatch(sub, payload)
        except (ValueError, KeyError) as exc:
            self.state("last_error", f"{sub}: {exc}", force=True)
            return
        if job:
            self.jobs.put((sub, job))

    def _dispatch(self, sub: str, payload: str) -> Callable[[], None] | None:
        camera, up = self.camera, payload.upper()
        if sub == "ptz":
            if up == "CENTER":
                return camera.center
            if up == "STOP":
                return camera.stop
            direction, _, number = up.lower().partition(":")   # "LEFT" or "LEFT:3"
            if direction not in C.MOVE:
                raise ValueError(f"Direction '{payload}' unknown")
            count = int(number) if number else 1
            if not 1 <= count <= C.STEP_MAX_COUNT:
                raise ValueError(f"Count {count} outside 1..{C.STEP_MAX_COUNT}")
            return lambda: camera.step(direction, count)
        if sub == "ptz/move":
            if up == "STOP":
                return camera.stop
            direction = up.lower()
            if direction not in C.MOVE:
                raise ValueError(f"Direction '{payload}' unknown")
            return lambda: camera.move(direction)
        if sub == "preset":
            number = int(float(payload))
            return lambda: camera.preset_goto(number)
        if sub == "preset/set":
            number = int(float(payload))
            return lambda: camera.preset_set(number)
        if sub == "patrol":
            def patrol():
                camera.patrol_stop()
                if up.startswith("H"):
                    camera.patrol("h", True)
                elif up.startswith("V"):
                    camera.patrol("v", True)
                self.state("patrol", {"H": "HORIZONTAL", "V": "VERTICAL"}.get(up[:1], "STOP"))
            return patrol
        if sub == "relay":
            on = up in ("ON", "1", "TRUE")

            def relay():
                camera.io_output(on)
                self.state("relay", "ON" if on else "OFF")
            return relay
        if sub == "snapshot":
            return self.publish_snapshot
        if sub == "refresh":
            return self.refresh_all
        if sub == "camera_vars":
            values = json.loads(payload)

            def set_vars():
                camera.set_camera_vars(**values)
                self.poll_camera_vars()
            return set_vars
        if sub.startswith("camera/"):
            name = Camera._scam_name(sub.split("/", 1)[1])
            value = int(up == "ON") if up in ("ON", "OFF") else int(float(payload))

            def set_single_var():
                camera.set_camera_var(name, value)
                self.poll_camera_vars()
            return set_single_var
        if sub == "lamp":
            mode = int(float(payload))

            def lamp():
                camera.set_lamp(mode)
                self.state("lamp", mode)
            return lamp
        if sub in ("motion/enable", "motion/level", "motion/timeout"):
            key = {"motion/enable": "motion_enable", "motion/level": "motion_level",
                   "motion/timeout": "mtimeout"}[sub]
            value = int(up == "ON") if up in ("ON", "OFF") else int(float(payload))

            def motion():
                camera.set_motion(**{key: value})
                self.poll_motion_settings()
            return motion
        if sub == "cruise":
            if up == "STOP":
                return camera.cruise_stop
            index = int(float(payload))
            return lambda: camera.cruise_start(index)
        if sub == "reboot":
            if up != "REBOOT":
                raise ValueError("Payload must be REBOOT")
            return camera.reboot
        if sub == "raw":
            if not self.cfg.get("allow_raw"):
                raise ValueError("cmd/raw is disabled (mqtt.allow_raw)")
            req = json.loads(payload)

            def raw():
                self.pub("raw/result", camera.raw(req["cgi"], **req.get("params", {})), retain=False, force=True)
            return raw
        raise ValueError(f"unknown command {sub}")

    # ------------------------------------------------------------- Polling
    def poll_fast(self) -> None:
        real_status = self.camera.real_status()
        self.set_online(True)
        motion = _onoff(real_status.get("realstatus_motion"))
        self.state("motion", motion)
        self.state("alarm", _onoff(real_status.get("realstatus_alstatus")))
        self.state("input1", _onoff(real_status.get("realstatus_inputal1")))
        self.state("input2", _onoff(real_status.get("realstatus_inputal2")))
        self.state("sd_alarm", _onoff(real_status.get("realstatus_sdalarm")))
        self.state("framerate", real_status.get("realstatus_mrate", ""))
        width, height = real_status.get("realstatus_videoW"), real_status.get("realstatus_videoH")
        if width and height:
            self.state("resolution", f"{width}x{height}")
        self.state("ip", real_status.get("realstatus_ipaddr", ""))
        self.state("json/real_status", real_status)
        is_motion = motion == "ON"
        if is_motion and not self._motion and self.cfg.get("snapshot_on_motion"):
            self.jobs.put(("snapshot", self.publish_snapshot))
        self._motion = is_motion

    def poll_slow(self) -> None:
        device = self.camera.status()
        self.state("model", device.get("prot_mode", ""))
        self.state("firmware", device.get("server_version", ""))
        self.state("webui", device.get("client_version", ""))
        self.state("alias", device.get("alias_name", ""))
        self.state("lamp", device.get("lamp_status", ""))
        self.state("json/status", device)
        try:
            sd = self.camera.sd_status()
            self.state("sd_ok", _onoff(sd.get("sdc_status_normal")))
            self.state("sd_total_mb", round(int(sd.get("sdc_status_allspace", 0)) / 1024))
            self.state("sd_free_mb", round(int(sd.get("sdc_status_freespace", 0)) / 1024))
        except (CameraError, ValueError) as exc:
            log.debug("SD status: %s", exc)
        self.state("presets", self.camera.preset_count())
        self.poll_camera_vars()
        self.poll_motion_settings()

    def poll_motion_settings(self) -> None:
        try:
            settings = self.camera.motion_settings()
        except CameraError as exc:
            log.debug("motion_settings: %s", exc)
            return
        if "motion_enable" in settings:
            self.state("motion/enable", _onoff(settings["motion_enable"]))
        if "motion_level" in settings:
            self.state("motion/level", settings["motion_level"])
        if "mtimeout" in settings:
            self.state("motion/timeout", settings["mtimeout"])

    def poll_camera_vars(self) -> None:
        try:
            camera_vars = self.camera.camera_vars()
        except CameraError as exc:
            log.debug("camera_vars: %s", exc)
            return
        self.state("json/camera_vars", camera_vars)
        for key, value in camera_vars.items():
            if not key.endswith("result"):
                self.state(f"camera/{key}", value)

    def refresh_all(self) -> None:
        self.poll_fast()
        self.poll_slow()

    def publish_snapshot(self) -> None:
        self.pub("snapshot", self.camera.snapshot(), retain=True)
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
            interval = float(self.cfg.get("snapshot_interval") or 0)
            if interval > 0 and now >= next_snap:
                self.jobs.put(("snapshot", self.publish_snapshot))
                next_snap = now + interval
            # do not let the queue fill up if the camera hangs
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
        for thread in threads:
            thread.start()

        def _stop(*_):
            self.stop_event.set()
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
        log.info("Bridge running: camera %s, broker %s:%s, base topic '%s'",
                 self.camera.host, self.cfg["host"], self.cfg["port"], self.base)
        while not self.stop_event.is_set():
            self.stop_event.wait(1)
        self.client.publish(f"{self.base}/status", "offline", qos=1, retain=True).wait_for_publish(2)
        self.client.loop_stop()
        self.client.disconnect()
