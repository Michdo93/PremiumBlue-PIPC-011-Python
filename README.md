# PremiumBlue-PIPC-011-Python

Control the **PremiumBlue PIPC-011** Pan/Tilt IP Camera using Python – available as a library, command-line interface (CLI), web interface, and MQTT bridge for openHAB or Home Assistant.

The PremiumBlue PIPC-011 is an OEM camera based on the Apexis platform. In `get_status.cgi`, the device identifies itself as **APM-H803-MPC** (Firmware `83.2.5.69c3`, WebUI `17.14.5.45`, Sensor OV9710, 1280×720). Note that the CGI API is **not** standard Foscam-compatible; all commands documented here have been extracted directly from the camera's native web interface – see the [CGI Reference](#cgi-reference) below.

---

## Installation

### Linux / macOS

```bash
git clone [https://github.com/Michdo93/PremiumBlue-PIPC-011-Python.git](https://github.com/Michdo93/PremiumBlue-PIPC-011-Python.git)
cd PremiumBlue-PIPC-011-Python
python3 -m venv . && source ./bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml   # Set your camera's IP and password
```

### Windows (PowerShell)

```powershell
git clone [https://github.com/Michdo93/PremiumBlue-PIPC-011-Python.git](https://github.com/Michdo93/PremiumBlue-PIPC-011-Python.git)
cd PremiumBlue-PIPC-011-Python
python -m venv .; .\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config.example.yaml config.yaml   # Set your camera's IP and password
```

> **Configuration Priority:**
> Hardcoded Defaults < `config.yaml` < Environment Variables (`PIPC011_HOST`, `PIPC011_PASSWORD`, `MQTT_HOST`, etc.) < CLI Options (`--host`, `--password`).

---

## Command Line Interface (CLI)

```bash
python -m pipc_011 status                # Device and runtime status as JSON
python -m pipc_011 status --all          # Read all status CGIs
python -m pipc_011 ptz left              # Drive 0.5s, then stop (mobile.htm behavior)
python -m pipc_011 ptz left --count 3    # Perform 3 short incremental steps (-n 3)
python -m pipc_011 ptz up --continuous   # Drive until "stop" command is sent
python -m pipc_011 stop
python -m pipc_011 ptz center
python -m pipc_011 preset goto 3         # Go to Preset 1–9
python -m pipc_011 preset set 3          # Save current position to Preset 3
python -m pipc_011 patrol h start        # Patrol horizontal (h) or vertical (v)
python -m pipc_011 patrol h stop
python -m pipc_011 patrol all stop       # Stop both horizontal and vertical patrol
python -m pipc_011 relay on              # Switch alarm output relay on
python -m pipc_011 snapshot image.jpg    # Capture and save a snapshot
python -m pipc_011 image                 # Display image parameters
python -m pipc_011 image brightness=140 flip=1 hz=1 osd=0
python -m pipc_011 motion                # Display motion detector configuration
python -m pipc_011 motion motion_enable=1 motion_level=3
python -m pipc_011 lamp 2                # Status LED: 0/1 blink, 2 off, 3 on
python -m pipc_011 cruise list           # List cruises 0–9 with status
python -m pipc_011 cruise start 0        # Start cruise 0 (warns if cruise is unconfigured)
python -m pipc_011 cruise stop
python -m pipc_011 params 2              # Read parameter group (1–14)
python -m pipc_011 log                   # Fetch logs as list (--raw for flat camera variables)
python -m pipc_011 urls                  # Print Snapshot, MJPEG, and RTSP stream URLs
python -m pipc_011 raw get_camera_vars.cgi
python -m pipc_011 probe                 # Deep-probe camera features and endpoints
python -m pipc_011 web                   # Start web interface on port 5000
python -m pipc_011 mqtt                  # Start MQTT bridge

```

Legacy argument syntax is supported: `python3 camera_control.py --cmd preset1_get`, `--snapshot image.jpg`. Running without arguments defaults to launching the web interface.

---

## Web Interface

Launch using:

```bash
python -m pipc_011 web
```

Then navigate to `http://<ip-or-localhost>:5000`.

Features include live video feed, 8-directional D-pad (**hold to move**, release to stop), Presets 1–9 (go/save), patrol control, relay toggling, and live motion alarm status. The MJPEG stream is proxied internally via `/video_feed`, keeping camera credentials hidden from client browsers.

---

## Python Library Usage

```python
from pipc_011 import Camera

cam = Camera("192.168.0.35", "admin", "secret_password")

# PTZ Movement
cam.step("right")             # Short step and stop
cam.step("right", count=3)    # 3 short steps
cam.move("up"); cam.stop()    # Continuous movement
cam.preset_goto(2)            # Go to preset 2

# Status & Snapshots
print(cam.real_status()["realstatus_motion"])
with open("snapshot.jpg", "wb") as f:
    f.write(cam.snapshot())

# Stream frames (e.g., for OpenCV or AI processing)
for frame in cam.mjpeg_frames():
    process_frame(frame)

```

---

## openHAB Integration

The service runs via `python -m pipc_011 mqtt`, bridging HTTP requests to the camera and publishing to an MQTT broker.

Example configuration files (Things, Items, Sitemap, MAP transformations, JS rules) are located in the `openhab/` directory.

### MQTT Topics

| Topic | Direction | Content / Description |
| --- | --- | --- |
| `pipc011/status` | → openHAB | `online` / `offline` (LWT, retained) |
| `pipc011/state/motion` | → | `ON` / `OFF` (Polled every 2s) |
| `pipc011/state/alarm`, `input1`, `input2`, `sd_alarm` | → | `ON` / `OFF` |
| `pipc011/state/resolution`, `framerate`, `ip` | → | Runtime state |
| `pipc011/state/model`, `firmware`, `webui`, `alias`, `lamp` | → | Device Info (Polled every 60s) |
| `pipc011/state/sd_ok`, `sd_free_mb`, `sd_total_mb` | → | SD Card metrics |
| `pipc011/state/presets` | → | Available presets count (9) |
| `pipc011/state/relay`, `patrol` | → | Last sent state (Camera does not return status) |
| `pipc011/state/camera/<name>` | → | Camera image attributes from `get_camera_vars.cgi` |
| `pipc011/state/json/<cgi>` | → | Complete JSON payload response |
| `pipc011/state/last_error` | → | Last reported error string |
| `pipc011/snapshot` | → | Raw JPEG bytes (Image channel), updated on demand or motion |
| `pipc011/cmd/ptz` | ← | `UP` `DOWN` `LEFT` `RIGHT` `UP_LEFT` `UP_RIGHT` `DOWN_LEFT` `DOWN_RIGHT` `CENTER` `STOP` – Single step (`LEFT:3` = 3 steps) |
| `pipc011/cmd/ptz/move` | ← | Direction → Start continuous drive (`STOP` halts) |
| `pipc011/cmd/preset` | ← | Jump to Preset `1`–`9` |
| `pipc011/cmd/preset/set` | ← | Save Preset `1`–`9` |
| `pipc011/cmd/patrol` | ← | `HORIZONTAL` / `VERTICAL` / `STOP` |
| `pipc011/cmd/relay` | ← | `ON` / `OFF` |
| `pipc011/cmd/snapshot` | ← | Any payload triggers a new snapshot |
| `pipc011/cmd/refresh` | ← | Force state refresh |
| `pipc011/cmd/camera_vars` | ← | JSON payload, e.g., `{"brightness": 140, "flip": 1}` |
| `pipc011/cmd/motion/enable` | ← | `ON` / `OFF` motion detection |
| `pipc011/cmd/motion/level` | ← | Sensitivity `1`–`5` |
| `pipc011/cmd/lamp` | ← | `0`–`3` Status LED state |
| `pipc011/cmd/reboot` | ← | `REBOOT` |

### Video Streaming in openHAB

1. **Proxied via Python App:** Run `web` service, add to Sitemap:
`Video url="http://<server-ip>:5000/video_feed" encoding="mjpeg"`
2. **IpCamera Binding:** Use `ipcamera:httponly` with stream URLs provided by `python -m pipc_011 urls`.

### Systemd Services Installation

```bash
sudo cp -r . /opt/PremiumBlue-PIPC-011-Python
sudo cp systemd/pipc011-mqtt.service systemd/pipc011-web.service /etc/systemd/system/
sudo systemctl enable --now pipc011-mqtt pipc011-web
```

---

## CGI Reference

Extracted from native firmware interfaces (`live.htm`, `mobile.htm`, `osdset.htm`, `setmenu/*.htm`). All requests require authentication: `user=…&pwd=…`.

### PTZ Control: `decoder_control.cgi?type=T&cmd=C`

| type | Function | cmd values |
| --- | --- | --- |
| 0 | Movement | 0 Up, 1 Down, 2 Left, 3 Right, 13 Up-Left, 14 Down-Left, 15 Up-Right, 16 Down-Right, **10 Stop**, 11 Center, 12 Auto Off, 17/18 Patrol H/V, 19/20 Stop Patrol |
| 1 | Save Preset | 0–8 (Presets 1–9) |
| 2 | Goto Preset | 0–8 (Presets 1–9) |
| 3 | Relay Output | 1 On, 0 Off |

> Movements continue until a stop command (`type=0&cmd=10`) is explicitly sent. Commands 4–9 (Focus/Zoom/Iris) exist in protocol logic but are unsupported by camera hardware.

### Image Controls: `set_camera_vars.cgi?type=T&value=V`

Query settings via `get_camera_vars.cgi`.

| type | Variable | Valid Range / Description |
| --- | --- | --- |
| 1 | `OSDTimer` | OSD Color: 0 Off, 1 Black, 2 Red, 3 Green, 4 Blue, 5 Purple, 6 Grey, 7 Silver, 8 Yellow, 9 Olive, 10 Teal, 11 White, 12 Light Blue |
| 2 | `brightness` | 0–255 |
| 3 | `contrast` | 0–255 |
| 4 | `hue` | −128 to 127 |
| 5 | `saturation` | 0–200 |
| 6 | `ptzspeed` | 1–100 |
| 7 | `mirror` | 0/1 |
| 8 | `flip` | 0/1 |
| 9 | `aec_value` | 1 = 50Hz, 2 = 60Hz, 3 = Outdoor |

### Additional Endpoints

| Feature | Query Endpoint |
| --- | --- |
| Snapshot | `video_snapshot.cgi` (Desktop), `mobile_snapshot.cgi` (Mobile) |
| MJPEG Stream | `videostream.cgi` |
| RTSP Stream (H.264) | `rtsp://<ip>:554/live/av0?user=…&passwd=…` *(Note: Uses `passwd` parameter instead of `pwd`)* |
| Status LED | `set_lamp.cgi?type=0…3` |
| Motion Settings | Read: `get_params.cgi?type=2` / Write: `set_motion_alarm.cgi` |
| Cruise Controls | `control_cruise.cgi?index=N` (Stop with `index=100`) |
| System Logs | `get_log_page.cgi?line=20` |

---

## Offline Development / Mocking

`tools/fake_camera.py` simulates the camera responses using pre-recorded dumps, logging PTZ actions, and serving test MJPEG streams.

```bash
python tools/fake_camera.py --port 8080 &
PIPC011_HOST=127.0.0.1 PIPC011_PORT=8080 PIPC011_PASSWORD=test python -m pipc_011 web
```

PowerShell:

```powershell
Start-Process python "tools/fake_camera.py --port 8080"
$env:PIPC011_HOST="127.0.0.1"; $env:PIPC011_PORT="8080"; $env:PIPC011_PASSWORD="test"
python -m pipc_011 web
```

---

## Security Advice

Legacy Apexis firmware variants harbor unpatched security vulnerabilities (e.g., CVE-2017-17101: Unauthenticated stream and settings exposure). `get_status.cgi` and `get_real_status.cgi` respond without requiring login credentials.

**Security Recommendations:**

* Isolate the camera within a dedicated IoT VLAN with **no external Internet access**.
* Do **not** port-forward HTTP or RTSP endpoints to the public internet.
* Disable UPnP, DDNS (`oipcam.com`), and P2P options within the camera config.
* Access streams externally **only** via protected proxies (such as openHAB, Home Assistant, or WireGuard VPN).

```
