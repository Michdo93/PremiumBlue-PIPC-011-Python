"""Konfiguration: Defaults < config.yaml < Umgebungsvariablen < CLI."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "camera": {
        "host": "192.168.0.35",
        "port": 80,
        "user": "admin",
        "password": "",
        "timeout": 5,
        "retries": 1,          # Wiederholungen bei Timeout/Verbindungsfehler
        "invert_v": False,     # Überkopfmontage: oben/unten tauschen
        "invert_h": False,
        "step_seconds": 0.5,   # Dauer einer Einzelschritt-Bewegung (wie mobile.htm)
    },
    "mqtt": {
        "host": "localhost",
        "port": 1883,
        "user": "",
        "password": "",
        "client_id": "wc0030a-bridge",
        "base_topic": "wc0030a",
        "poll_fast": 2,        # s – Bewegung/Alarm (get_real_status)
        "poll_slow": 60,       # s – Geräteinfo, SD-Karte
        "snapshot_interval": 0,  # s – 0 = nur auf Befehl bzw. bei Bewegung
        "snapshot_on_motion": True,
        "allow_raw": False,    # cmd/raw erlaubt beliebige (nicht gefährliche) CGIs
    },
    "web": {
        "host": "0.0.0.0",
        "port": 5000,
    },
}

ENV = {
    "WC0030A_HOST": ("camera", "host"),
    "WC0030A_PORT": ("camera", "port"),
    "WC0030A_USER": ("camera", "user"),
    "WC0030A_PASSWORD": ("camera", "password"),
    "WC0030A_TIMEOUT": ("camera", "timeout"),
    "WC0030A_RETRIES": ("camera", "retries"),
    "MQTT_HOST": ("mqtt", "host"),
    "MQTT_PORT": ("mqtt", "port"),
    "MQTT_USER": ("mqtt", "user"),
    "MQTT_PASSWORD": ("mqtt", "password"),
    "MQTT_BASE_TOPIC": ("mqtt", "base_topic"),
}


def _merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v


def _cast(old: Any, new: str) -> Any:
    if isinstance(old, bool):
        return new.lower() in ("1", "true", "yes", "on")
    if isinstance(old, int):
        return int(new)
    if isinstance(old, float):
        return float(new)
    return new


def load(path: str | None = None) -> dict[str, Any]:
    cfg = copy.deepcopy(DEFAULTS)
    candidates = [path] if path else ["config.yaml", str(Path.home() / ".config/wc0030a/config.yaml"),
                                      "/etc/wc0030a/config.yaml"]
    for p in candidates:
        if p and Path(p).is_file():
            import yaml  # nur nötig, wenn eine Datei existiert
            with open(p, encoding="utf-8") as fh:
                _merge(cfg, yaml.safe_load(fh) or {})
            cfg["_file"] = p
            break
    else:
        if path:
            raise FileNotFoundError(path)
    for var, (sec, key) in ENV.items():
        if var in os.environ:
            cfg[sec][key] = _cast(cfg[sec][key], os.environ[var])
    return cfg


def camera_from(cfg: dict[str, Any]):
    from .api import Camera
    c = cfg["camera"]
    return Camera(c["host"], c["user"], c["password"], port=int(c["port"]),
                  timeout=float(c["timeout"]), retries=int(c.get("retries", 1)),
                  invert_v=bool(c["invert_v"]),
                  invert_h=bool(c["invert_h"]), step_seconds=float(c["step_seconds"]))
