#!/usr/bin/env python3
"""Minimal camera simulator for development/testing without hardware.

Serves the get_*.cgi responses stored in the dump, logs decoder_control
commands, generates a test JPEG and an MJPEG stream.
Motion can be simulated via /sim/motion?on=1.

  python tools/fake_camera.py --port 8080
  PIPC011_HOST=127.0.0.1 PIPC011_PORT=8080 PIPC011_PASSWORD=test python -m pipc_011 status
"""

import argparse
import io
import re
import time
from pathlib import Path

from flask import Flask, Response, request

RESPONSES_DIR = Path(__file__).parent / "fake_responses"
USER, PWD = "admin", "test"
app = Flask(__name__)
state = {
    "motion": 0, "log": [],
    # values as read from the real camera
    "vars": {"OSDTimer": 7, "brightness": 123, "contrast": 147, "hue": 1, "saturation": 110,
             "ptzspeed": 50, "mirror": 0, "flip": 0, "aec_value": 1},
    "motion_cfg": {"motion_Enable": 0, "byMotionSensitive": 3, "mtimeout": 1, "msdrec_enable": 0,
                   "mmail_enable": 0, "mftp_enable": 0, "malarmout_enable": 0},
}


def jpeg(text: str) -> bytes:
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (640, 360), (30, 40, 55))
        ImageDraw.Draw(img).text((20, 20), text, fill=(230, 230, 230))
        buffer = io.BytesIO()
        img.save(buffer, "JPEG")
        return buffer.getvalue()
    except ImportError:
        return b"\xff\xd8\xff\xe0" + text.encode() + b"\xff\xd9"


def authed() -> bool:
    return request.args.get("user") == USER and request.args.get("pwd") == PWD


@app.route("/cgi-bin/<name>")
def cgi(name):
    if name in ("get_status.cgi", "get_real_status.cgi"):  # readable without login, like the original
        pass
    elif not authed():
        return "var ret_check_user=3;\nvar ret_user_right=-1;\n" if name == "check_user.cgi" else "params error.\r\n"
    if name == "decoder_control.cgi":
        # like the real PIPC-011: type + cmd are mandatory
        if "type" not in request.args or "cmd" not in request.args:
            return "params error.\r\n"
        entry = (int(request.args["type"]), int(request.args["cmd"]))
        state["log"].append((time.time(), entry))
        print("decoder_control type=%d cmd=%d" % entry)
        return "ok.\r\n"
    if name in ("video_snapshot.cgi", "mobile_snapshot.cgi"):
        return Response(jpeg(time.strftime("%H:%M:%S")), mimetype="image/jpeg")
    if name == "videostream.cgi":
        def gen():
            for _ in range(10000):
                frame = jpeg("LIVE " + time.strftime("%H:%M:%S"))
                yield b"--ipcamera\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(frame) + frame + b"\r\n"
                time.sleep(0.2)
        return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=ipcamera")
    if name == "get_camera_vars.cgi":
        values = state["vars"]
        return "".join(f"var {key}={values[key]};\n" for key in values)
    if name == "set_camera_vars.cgi":
        names = {1: "OSDTimer", 2: "brightness", 3: "contrast", 4: "hue", 5: "saturation",
                 6: "ptzspeed", 7: "mirror", 8: "flip", 9: "aec_value"}
        try:
            state["vars"][names[int(request.args["type"])]] = int(request.args["value"])
        except (KeyError, ValueError):
            return "params error.\r\n"
        return "ok.\r\n"
    if name == "get_params.cgi":
        if request.args.get("type") != "2":
            return ""  # other groups are not simulated
        return "".join(f"var {k}={v};\n" for k, v in state["motion_cfg"].items())
    if name == "set_motion_alarm.cgi":
        keys = {"motion_enable": "motion_Enable", "motion_level": "byMotionSensitive",
                "mtimeout": "mtimeout", "msdrec_enable": "msdrec_enable", "mmail_enable": "mmail_enable",
                "mftp_enable": "mftp_enable", "malarmout_enable": "malarmout_enable"}
        if any(k not in request.args for k in keys):
            return "params error.\r\n"
        for k, old in keys.items():
            state["motion_cfg"][old] = int(request.args[k])
        return "ok.\r\n"
    if name in ("set_lamp.cgi", "control_cruise.cgi"):
        key = "type" if name == "set_lamp.cgi" else "index"
        if key not in request.args:
            return "params error.\r\n"
        state["log"].append((time.time(), (name, int(request.args[key]))))
        return "ok.\r\n"
    if name == "get_preset_status.cgi":
        return "var ret_presetsta_result=1;\nvar ret_presetsta_num=9;\nvar ret_presetsta_enable=new Array();\n" + \
               "".join(f"ret_presetsta_enable[{i}]={1 if i < 3 else 0};\n" for i in range(9))
    response_file = RESPONSES_DIR / name
    if response_file.exists():
        text = response_file.read_text(encoding="utf-8", errors="replace")
        if name == "get_real_status.cgi":
            text = re.sub(r"realstatus_motion=\d", f"realstatus_motion={state['motion']}", text)
        return Response(text, mimetype="text/plain")
    return "params error.\r\n"


@app.route("/live.htm")
def live():
    # excerpt from the real live.htm
    return ('<script>function all_ptz_control(type,value){action_zone.location="/cgi-bin/decoder_control.cgi?type="+type+"&cmd="+value+"&user="+top.user+"&pwd="+top.pwd;}'
            'function live_setcam_control(command,value){action_zone.location="/cgi-bin/set_camera_vars.cgi?type="+command+"&value="+value+"&user="+top.user+"&pwd="+top.pwd;}</script>')


@app.route("/sim/motion")
def sim_motion():
    state["motion"] = int(request.args.get("on", 1))
    return str(state["motion"])


@app.route("/sim/log")
def sim_log():
    return {"log": state["log"][-50:]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    app.run(port=parser.parse_args().port, threaded=True)
