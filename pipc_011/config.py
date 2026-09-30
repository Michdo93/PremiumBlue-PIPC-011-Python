"""Configuration: defaults < config.yaml < environment variables < CLI."""

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
        "retries": 1,          # retries on timeout/connection error
        "invert_v": False,     # ceiling mount: swap up/down
        "invert_h": False,
        "step_seconds": 0.5,   # duration of a single-step movement (like mobile.htm)
    },
    "mqtt": {
        "host": "localhost",
        "port": 1883,
        "user": "",
        "password": "",
        "client_id": "pipc011-bridge",
        "base_topic": "pipc011",
        "poll_fast": 2,        # s – motion/alarm (get_real_status)
        "poll_slow": 60,       # s – device info, SD card
        "snapshot_interval": 0,  # s – 0 = only on command or on motion
        "snapshot_on_motion": True,
        "allow_raw": False,    # cmd/raw allows arbitrary (non-dangerous) CGIs
    },
    "web": {
        "host": "0.0.0.0",
        "port": 5000,
    },
}

ENV_VARS = {
    "PIPC011_HOST": ("camera", "host"),
    "PIPC011_PORT": ("camera", "port"),
    "PIPC011_USER": ("camera", "user"),
    "PIPC011_PASSWORD": ("camera", "password"),
    "PIPC011_TIMEOUT": ("camera", "timeout"),
    "PIPC011_RETRIES": ("camera", "retries"),
    "MQTT_HOST": ("mqtt", "host"),
    "MQTT_PORT": ("mqtt", "port"),
    "MQTT_USER": ("mqtt", "user"),
    "MQTT_PASSWORD": ("mqtt", "password"),
    "MQTT_BASE_TOPIC": ("mqtt", "base_topic"),
}


def _merge(dst: dict, src: dict) -> None:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _merge(dst[key], value)
        else:
            dst[key] = value


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
    candidates = [path] if path else ["config.yaml", str(Path.home() / ".config/pipc011/config.yaml"),
                                      "/etc/pipc011/config.yaml"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            import yaml  # only required if a config file exists
            with open(candidate, encoding="utf-8") as fh:
                _merge(cfg, yaml.safe_load(fh) or {})
            cfg["_file"] = candidate
            break
    else:
        if path:
            raise FileNotFoundError(path)
    for var, (section, key) in ENV_VARS.items():
        if var in os.environ:
            cfg[section][key] = _cast(cfg[section][key], os.environ[var])
    return cfg


def camera_from(cfg: dict[str, Any]):
    from .api import Camera
    c = cfg["camera"]
    return Camera(c["host"], c["user"], c["password"], port=int(c["port"]),
                  timeout=float(c["timeout"]), retries=int(c.get("retries", 1)),
                  invert_v=bool(c["invert_v"]),
                  invert_h=bool(c["invert_h"]), step_seconds=float(c["step_seconds"]))
