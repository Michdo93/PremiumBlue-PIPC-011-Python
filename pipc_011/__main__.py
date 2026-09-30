"""Command line: python -m pipc_011 <command> ...

Examples:
  python -m pipc_011 status
  python -m pipc_011 ptz left              # single step
  python -m pipc_011 ptz left --count 3    # three single steps
  python -m pipc_011 ptz up --continuous   # move until 'stop'
  python -m pipc_011 stop
  python -m pipc_011 preset goto 3
  python -m pipc_011 preset set 3
  python -m pipc_011 patrol h start
  python -m pipc_011 patrol all stop
  python -m pipc_011 cruise list
  python -m pipc_011 cruise start 0
  python -m pipc_011 cruise stop
  python -m pipc_011 relay on
  python -m pipc_011 snapshot image.jpg
  python -m pipc_011 image brightness=140 contrast=150
  python -m pipc_011 motion motion_enable=1 motion_level=3
  python -m pipc_011 lamp 2
  python -m pipc_011 raw get_camera_vars.cgi
  python -m pipc_011 probe
  python -m pipc_011 web
  python -m pipc_011 mqtt
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
        count = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not an integer") from None
    if not 1 <= count <= C.STEP_MAX_COUNT:
        raise argparse.ArgumentTypeError(f"{count} outside 1..{C.STEP_MAX_COUNT}")
    return count


def _pairs(items: list[str], as_int: bool = False) -> dict[str, object]:
    """Convert name=value arguments into a dict, with a clear error message."""
    result: dict[str, object] = {}
    for item in items:
        key, sep, value = item.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            raise ValueError(f"'{item}' is not of the form name=value")
        if as_int:
            try:
                result[key] = int(value)
            except ValueError:
                raise ValueError(f"{key}: '{value}' is not an integer") from None
        else:
            result[key] = value
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipc_011", description="PremiumBlue PIPC-011 / Apexis APM-H803-MPC",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("-c", "--config", help="YAML configuration (default: ./config.yaml)")
    parser.add_argument("--host", help="IP address of the camera")
    parser.add_argument("--user")
    parser.add_argument("--password")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="status as JSON")
    s.add_argument("--all", action="store_true", help="all read-only CGIs")

    s = sub.add_parser("ptz", help="pan/tilt")
    s.add_argument("direction", choices=list(C.MOVE) + ["center"])
    group = s.add_mutually_exclusive_group()
    group.add_argument("-n", "--count", type=_count, default=1, metavar="N",
                       help=f"repeat single step N times (1..{C.STEP_MAX_COUNT}, default 1)")
    group.add_argument("--continuous", action="store_true", help="do not stop automatically (until 'stop')")

    sub.add_parser("stop", help="stop movement")

    s = sub.add_parser("preset", help="go to/save preset")
    s.add_argument("action", choices=["goto", "set"])
    s.add_argument("number", type=int)

    s = sub.add_parser("patrol", help="patrol")
    s.add_argument("axis", choices=["h", "v", "all"])
    s.add_argument("action", choices=["start", "stop"])

    s = sub.add_parser("relay", help="relay output")
    s.add_argument("state", choices=["on", "off"])

    s = sub.add_parser("snapshot", help="save JPEG")
    s.add_argument("file")

    s = sub.add_parser("urls", help="print stream/snapshot URLs (e.g. for openHAB/VLC)")
    s.add_argument("--rtsp-path", default=C.RTSP_PATH)

    s = sub.add_parser("image", help="read/set image parameters, e.g. brightness=128 flip=1 osd=0 hz=1")
    s.add_argument("values", nargs="*", metavar="name=value")

    s = sub.add_parser("lamp", help="status LED: 0 blink/off, 1 blink/slow, 2 always off, 3 always on")
    s.add_argument("mode", type=int, choices=[0, 1, 2, 3])

    s = sub.add_parser("motion", help="read/set motion detector, e.g. motion_enable=1 motion_level=3")
    s.add_argument("values", nargs="*", metavar="name=value")

    s = sub.add_parser("cruise", help="start/stop/list cruise (preset tour)")
    s.add_argument("action", choices=["list", "start", "stop"])
    s.add_argument("index", type=int, nargs="?", default=0, choices=range(C.CRUISE_COUNT),
                   metavar="INDEX", help=f"cruise 0..{C.CRUISE_COUNT - 1} (start only)")

    s = sub.add_parser("params", help="read settings group (get_params.cgi?type=1..14)")
    s.add_argument("type", type=int, choices=range(1, 15), metavar="TYPE")

    s = sub.add_parser("log", help="read camera log")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--raw", action="store_true", help="flat loginfo_*_N variables as returned by the camera")

    s = sub.add_parser("raw", help="call an arbitrary CGI (testing)")
    s.add_argument("cgi")
    s.add_argument("params", nargs="*", metavar="key=value")
    s.add_argument("--force", action="store_true", help="also allow dangerous CGIs (reboot …)")

    s = sub.add_parser("probe", help="explore camera, create report + ZIP (read-only)")
    s.add_argument("--out", default="probe_out")

    s = sub.add_parser("web", help="start web interface")
    s.add_argument("--port", type=int)

    s = sub.add_parser("mqtt", help="start MQTT bridge for openHAB")
    s.add_argument("--broker", help="host[:port]")
    s.add_argument("--base-topic")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load(args.config)
    for key in ("host", "user", "password"):
        if getattr(args, key):
            cfg["camera"][key] = getattr(args, key)
    camera = camera_from(cfg)

    try:
        if args.cmd == "status":
            data = camera.all_status() if args.all else {"status": camera.status(), "real_status": camera.real_status()}
            print(json.dumps(data, indent=2, ensure_ascii=False))
        elif args.cmd == "ptz":
            if args.direction == "center":
                camera.center()
            elif args.continuous:
                camera.move(args.direction)
            else:
                camera.step(args.direction, args.count)
        elif args.cmd == "stop":
            camera.stop()
        elif args.cmd == "preset":
            (camera.preset_goto if args.action == "goto" else camera.preset_set)(args.number)
        elif args.cmd == "patrol":
            if args.action == "stop":
                camera.patrol_stop() if args.axis == "all" else camera.patrol(args.axis, False)
            elif args.axis == "all":
                raise ValueError("'all' is only valid with stop – start with h or v")
            else:
                camera.patrol(args.axis, True)
        elif args.cmd == "relay":
            camera.io_output(args.state == "on")
        elif args.cmd == "snapshot":
            with open(args.file, "wb") as fh:
                fh.write(camera.snapshot())
            print(f"Saved: {args.file}")
        elif args.cmd == "urls":
            print("Snapshot:", camera.url(camera._snapshot_path or "/cgi-bin/video_snapshot.cgi"))
            print("MJPEG:   ", camera.mjpeg_url())
            print("RTSP:    ", camera.rtsp_url(args.rtsp_path))
        elif args.cmd == "image":
            for name, value in _pairs(args.values, as_int=True).items():
                camera.set_camera_var(name, value)
            print(json.dumps(camera.camera_vars(), indent=2))
        elif args.cmd == "lamp":
            camera.set_lamp(args.mode)
            print("Status LED:", C.LAMP_MODES[args.mode])
        elif args.cmd == "motion":
            if args.values:
                camera.set_motion(**_pairs(args.values, as_int=True))
            print(json.dumps(camera.motion_settings(), indent=2))
        elif args.cmd == "cruise":
            if args.action == "list":
                print(json.dumps(camera.cruise_list(), indent=2, ensure_ascii=False))
            elif args.action == "start":
                enabled = camera.cruise_list().get("lcruise_enable") or []
                if args.index < len(enabled) and not enabled[args.index]:
                    print(f"Note: cruise {args.index} is not configured/enabled in the camera – "
                          "the camera will probably not move.", file=sys.stderr)
                camera.cruise_start(args.index)
            else:
                camera.cruise_stop()
        elif args.cmd == "params":
            from .probe import _redact_obj
            data = camera.params(args.type)
            print(json.dumps(_redact_obj(data) if args.type in C.SECRET_PARAM_TYPES else data,
                             indent=2, ensure_ascii=False))
        elif args.cmd == "log":
            data = camera.log(args.page) if args.raw else camera.log_entries(args.page)
            print(json.dumps(data, indent=2, ensure_ascii=False))
        elif args.cmd == "raw":
            params = _pairs(args.params)
            if args.force:
                params["_force"] = True
            print(camera.raw(args.cgi, **params))
        elif args.cmd == "probe":
            from .probe import run
            path = run(camera, args.out)
            print(f"Done: {path}  (report: {args.out}/report.md, passwords redacted)")
        elif args.cmd == "web":
            from .web import create_app
            port = args.port or int(cfg["web"]["port"])
            print(f"Web interface: http://{cfg['web']['host']}:{port}")
            create_app(camera).run(host=cfg["web"]["host"], port=port, threaded=True, debug=False)
        elif args.cmd == "mqtt":
            from .mqtt_bridge import Bridge
            mqtt_cfg = cfg["mqtt"]
            if args.broker:
                host, _, port = args.broker.partition(":")
                mqtt_cfg["host"] = host
                if port:
                    mqtt_cfg["port"] = int(port)
            if args.base_topic:
                mqtt_cfg["base_topic"] = args.base_topic
            Bridge(camera, mqtt_cfg).run()
    except (CameraError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Aborted.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
