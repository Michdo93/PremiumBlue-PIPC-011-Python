"""Kommandozeile: python -m wc0030a <befehl> ...

Beispiele:
  python -m wc0030a status
  python -m wc0030a ptz left              # Einzelschritt
  python -m wc0030a ptz left --count 3    # drei Einzelschritte
  python -m wc0030a ptz up --continuous   # fahren bis 'stop'
  python -m wc0030a stop
  python -m wc0030a preset goto 3
  python -m wc0030a preset set 3
  python -m wc0030a patrol h start
  python -m wc0030a patrol all stop
  python -m wc0030a cruise list
  python -m wc0030a cruise start 0
  python -m wc0030a cruise stop
  python -m wc0030a relay on
  python -m wc0030a snapshot bild.jpg
  python -m wc0030a image brightness=140 contrast=150
  python -m wc0030a motion motion_enable=1 motion_level=3
  python -m wc0030a lamp 2
  python -m wc0030a raw get_camera_vars.cgi
  python -m wc0030a probe
  python -m wc0030a web
  python -m wc0030a mqtt
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import commands as C
from .api import CameraError
from .config import camera_from, load


def _count(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' ist keine ganze Zahl") from None
    if not 1 <= n <= C.STEP_MAX_COUNT:
        raise argparse.ArgumentTypeError(f"{n} außerhalb 1..{C.STEP_MAX_COUNT}")
    return n


def _pairs(items: list[str], as_int: bool = False) -> dict[str, object]:
    """name=wert-Argumente in ein dict umwandeln, mit verständlicher Fehlermeldung."""
    out: dict[str, object] = {}
    for kv in items:
        key, sep, value = kv.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            raise ValueError(f"'{kv}' hat nicht die Form name=wert")
        if as_int:
            try:
                out[key] = int(value)
            except ValueError:
                raise ValueError(f"{key}: '{value}' ist keine ganze Zahl") from None
        else:
            out[key] = value
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wc0030a", description="LogiLink WC0030A / Apexis APM-H803-MPC",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("-c", "--config", help="YAML-Konfiguration (Default: ./config.yaml)")
    p.add_argument("--host", help="IP der Kamera")
    p.add_argument("--user")
    p.add_argument("--password")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="Status als JSON")
    s.add_argument("--all", action="store_true", help="alle lesenden CGIs")

    s = sub.add_parser("ptz", help="schwenken/neigen")
    s.add_argument("direction", choices=list(C.MOVE) + ["center"])
    g = s.add_mutually_exclusive_group()
    g.add_argument("-n", "--count", type=_count, default=1, metavar="N",
                   help=f"Einzelschritt N-mal wiederholen (1..{C.STEP_MAX_COUNT}, Default 1)")
    g.add_argument("--continuous", action="store_true", help="nicht automatisch stoppen (bis 'stop')")

    sub.add_parser("stop", help="Bewegung anhalten")

    s = sub.add_parser("preset", help="Preset anfahren/speichern")
    s.add_argument("action", choices=["goto", "set"])
    s.add_argument("number", type=int)

    s = sub.add_parser("patrol", help="Patrouille")
    s.add_argument("axis", choices=["h", "v", "all"])
    s.add_argument("action", choices=["start", "stop"])

    s = sub.add_parser("relay", help="Schaltausgang")
    s.add_argument("state", choices=["on", "off"])

    s = sub.add_parser("snapshot", help="JPEG speichern")
    s.add_argument("file")

    s = sub.add_parser("urls", help="Stream-/Snapshot-URLs ausgeben (z. B. für openHAB/VLC)")
    s.add_argument("--rtsp-path", default=C.RTSP_PATH)

    s = sub.add_parser("image", help="Bildparameter lesen/setzen, z. B. brightness=128 flip=1 osd=0 hz=1")
    s.add_argument("values", nargs="*", metavar="name=wert")

    s = sub.add_parser("lamp", help="Status-LED: 0 blinkt/aus, 1 blinkt/langsam, 2 immer aus, 3 immer an")
    s.add_argument("mode", type=int, choices=[0, 1, 2, 3])

    s = sub.add_parser("motion", help="Bewegungsmelder lesen/setzen, z. B. motion_enable=1 motion_level=3")
    s.add_argument("values", nargs="*", metavar="name=wert")

    s = sub.add_parser("cruise", help="Kurs (Preset-Tour) starten/stoppen/auflisten")
    s.add_argument("action", choices=["list", "start", "stop"])
    s.add_argument("index", type=int, nargs="?", default=0, choices=range(C.CRUISE_COUNT),
                   metavar="INDEX", help=f"Kurs 0..{C.CRUISE_COUNT - 1} (nur bei start)")

    s = sub.add_parser("params", help="Einstellungsgruppe lesen (get_params.cgi?type=1..14)")
    s.add_argument("type", type=int, choices=range(1, 15), metavar="TYPE")

    s = sub.add_parser("log", help="Kamera-Log lesen")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--raw", action="store_true", help="flache loginfo_*_N-Variablen wie von der Kamera")

    s = sub.add_parser("raw", help="beliebiges CGI aufrufen (Test)")
    s.add_argument("cgi")
    s.add_argument("params", nargs="*", metavar="key=value")
    s.add_argument("--force", action="store_true", help="auch gefährliche CGIs (reboot …)")

    s = sub.add_parser("probe", help="Kamera erkunden, Bericht + ZIP erzeugen (nur lesend)")
    s.add_argument("--out", default="probe_out")

    s = sub.add_parser("web", help="Weboberfläche starten")
    s.add_argument("--port", type=int)

    s = sub.add_parser("mqtt", help="MQTT-Brücke für openHAB starten")
    s.add_argument("--broker", help="host[:port]")
    s.add_argument("--base-topic")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load(args.config)
    for key in ("host", "user", "password"):
        if getattr(args, key):
            cfg["camera"][key] = getattr(args, key)
    cam = camera_from(cfg)

    try:
        if args.cmd == "status":
            data = cam.all_status() if args.all else {"status": cam.status(), "real_status": cam.real_status()}
            print(json.dumps(data, indent=2, ensure_ascii=False))
        elif args.cmd == "ptz":
            if args.direction == "center":
                cam.center()
            elif args.continuous:
                cam.move(args.direction)
            else:
                cam.step(args.direction, args.count)
        elif args.cmd == "stop":
            cam.stop()
        elif args.cmd == "preset":
            (cam.preset_goto if args.action == "goto" else cam.preset_set)(args.number)
        elif args.cmd == "patrol":
            if args.action == "stop":
                cam.patrol_stop() if args.axis == "all" else cam.patrol(args.axis, False)
            elif args.axis == "all":
                raise ValueError("'all' gibt es nur mit stop – starten mit h oder v")
            else:
                cam.patrol(args.axis, True)
        elif args.cmd == "relay":
            cam.io_output(args.state == "on")
        elif args.cmd == "snapshot":
            with open(args.file, "wb") as fh:
                fh.write(cam.snapshot())
            print(f"Gespeichert: {args.file}")
        elif args.cmd == "urls":
            print("Snapshot:", cam.url(cam._snapshot_path or "/cgi-bin/video_snapshot.cgi"))
            print("MJPEG:   ", cam.mjpeg_url())
            print("RTSP:    ", cam.rtsp_url(args.rtsp_path))
        elif args.cmd == "image":
            for k, v in _pairs(args.values, as_int=True).items():
                cam.set_camera_var(k, v)
            print(json.dumps(cam.camera_vars(), indent=2))
        elif args.cmd == "lamp":
            cam.set_lamp(args.mode)
            print("Status-LED:", C.LAMP_MODES[args.mode])
        elif args.cmd == "motion":
            if args.values:
                cam.set_motion(**_pairs(args.values, as_int=True))
            print(json.dumps(cam.motion_settings(), indent=2))
        elif args.cmd == "cruise":
            if args.action == "list":
                print(json.dumps(cam.cruise_list(), indent=2, ensure_ascii=False))
            elif args.action == "start":
                enabled = cam.cruise_list().get("lcruise_enable") or []
                if args.index < len(enabled) and not enabled[args.index]:
                    print(f"Hinweis: Kurs {args.index} ist in der Kamera nicht angelegt/aktiv – "
                          "die Kamera bewegt sich vermutlich nicht.", file=sys.stderr)
                cam.cruise_start(args.index)
            else:
                cam.cruise_stop()
        elif args.cmd == "params":
            from .probe import _redact_obj
            data = cam.params(args.type)
            print(json.dumps(_redact_obj(data) if args.type in C.SECRET_PARAM_TYPES else data,
                             indent=2, ensure_ascii=False))
        elif args.cmd == "log":
            data = cam.log(args.page) if args.raw else cam.log_entries(args.page)
            print(json.dumps(data, indent=2, ensure_ascii=False))
        elif args.cmd == "raw":
            params = _pairs(args.params)
            if args.force:
                params["_force"] = True
            print(cam.raw(args.cgi, **params))
        elif args.cmd == "probe":
            from .probe import run
            path = run(cam, args.out)
            print(f"Fertig: {path}  (Bericht: {args.out}/report.md, Passwörter geschwärzt)")
        elif args.cmd == "web":
            from .web import create_app
            port = args.port or int(cfg["web"]["port"])
            print(f"Weboberfläche: http://{cfg['web']['host']}:{port}")
            create_app(cam).run(host=cfg["web"]["host"], port=port, threaded=True, debug=False)
        elif args.cmd == "mqtt":
            from .mqtt_bridge import Bridge
            m = cfg["mqtt"]
            if args.broker:
                host, _, port = args.broker.partition(":")
                m["host"] = host
                if port:
                    m["port"] = int(port)
            if args.base_topic:
                m["base_topic"] = args.base_topic
            Bridge(cam, m).run()
    except (CameraError, ValueError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Abgebrochen.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
