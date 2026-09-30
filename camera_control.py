#!/usr/bin/env python3
"""Compatibility wrapper for the legacy command syntax.

  python3 camera_control.py                 -> web interface
  python3 camera_control.py --cmd left      -> single step
  python3 camera_control.py --cmd preset1_get
  python3 camera_control.py --snapshot x.jpg

The new syntax is `python3 -m pipc_011 ...` (see README).
"""

import argparse
import re
import sys

from pipc_011.__main__ import main

LEGACY_COMMANDS = {
    "center": ["ptz", "center"], "stop": ["stop"],
    "patrol_h_start": ["patrol", "h", "start"], "patrol_h_stop": ["patrol", "h", "stop"],
    "patrol_v_start": ["patrol", "v", "start"], "patrol_v_stop": ["patrol", "v", "stop"],
    "stop_patrol": ["patrol", "all", "stop"], "patrol_h": ["patrol", "h", "start"],
    "patrol_v": ["patrol", "v", "start"],
    "relay_on": ["relay", "on"], "relay_off": ["relay", "off"],
    "ir_on": ["relay", "on"], "ir_off": ["relay", "off"],
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cmd")
    parser.add_argument("--snapshot")
    parser.add_argument("--server", action="store_true")
    args, rest = parser.parse_known_args()
    if args.cmd:
        match = re.fullmatch(r"preset(\d+)(?:_(get|set))?", args.cmd)
        if match:
            argv = ["preset", "set" if match.group(2) == "set" else "goto", match.group(1)]
        else:
            argv = LEGACY_COMMANDS.get(args.cmd, ["ptz", args.cmd])
    elif args.snapshot:
        argv = ["snapshot", args.snapshot]
    else:
        argv = ["web"]
    sys.exit(main(rest + argv))
