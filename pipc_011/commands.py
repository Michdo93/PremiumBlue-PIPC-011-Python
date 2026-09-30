"""Command tables of the PIPC-011 (Apexis APM-H803-MPC, WebUI 17.14.5.45).

All values were taken from the camera's own web interface (live.htm, mobile.htm,
osdset.htm, setmenu/*.htm), not from the Foscam SDK.

PTZ: /cgi-bin/decoder_control.cgi?type=<T>&cmd=<C>
    type 0 = movement      (cmd see PTZ_*)
    type 1 = save preset   (cmd 0..8)
    type 2 = goto preset   (cmd 0..8)
    type 3 = relay output  (cmd 1 = on, 0 = off)

Image: /cgi-bin/set_camera_vars.cgi?type=<T>&value=<V>   (see SCAM_*)
"""

from __future__ import annotations

# ------------------------------------------------------------ decoder_control
TYPE_PTZ = 0
TYPE_PRESET_SET = 1
TYPE_PRESET_CALL = 2
TYPE_SWITCH = 3

PTZ_UP = 0
PTZ_DOWN = 1
PTZ_LEFT = 2
PTZ_RIGHT = 3
PTZ_FOCUS_ADD = 4      # not supported by APM-H803-MPC (no focus)
PTZ_FOCUS_DEL = 5
PTZ_ZOOM_ADD = 6       # not supported by APM-H803-MPC (no zoom)
PTZ_ZOOM_DEL = 7
PTZ_IRIS_OPEN = 8      # not supported by APM-H803-MPC (no iris)
PTZ_IRIS_CLOSE = 9
PTZ_STOP = 10
PTZ_AUTO_ON = 11       # center button of the web interface -> camera moves to center
PTZ_AUTO_OFF = 12
PTZ_LEFT_UP = 13
PTZ_LEFT_DOWN = 14
PTZ_RIGHT_UP = 15
PTZ_RIGHT_DOWN = 16
PTZ_PATROL_H = 17
PTZ_PATROL_V = 18
PTZ_PATROL_H_STOP = 19
PTZ_PATROL_V_STOP = 20

MOVE = {
    "up": PTZ_UP,
    "down": PTZ_DOWN,
    "left": PTZ_LEFT,
    "right": PTZ_RIGHT,
    "up_left": PTZ_LEFT_UP,
    "up_right": PTZ_RIGHT_UP,
    "down_left": PTZ_LEFT_DOWN,
    "down_right": PTZ_RIGHT_DOWN,
}

# For ceiling mounts or mirrored images the axes are swapped.
INVERT_V = {"up": "down", "down": "up", "up_left": "down_left", "up_right": "down_right",
            "down_left": "up_left", "down_right": "up_right"}
INVERT_H = {"left": "right", "right": "left", "up_left": "up_right", "up_right": "up_left",
            "down_left": "down_right", "down_right": "down_left"}

STEP_SECONDS = 0.5     # mobile.htm: move, wait 500 ms, stop
STEP_PAUSE = 0.2       # pause between two single steps (ptz --count)
STEP_MAX_COUNT = 50    # upper limit for repetitions (CLI, MQTT, web)
CRUISE_COUNT = 10      # get_list_cruise.cgi: cruises 0..9, stop with index=100
PRESET_COUNT = 9       # live.htm: set_preset(0..8), use_preset(0..8)

# ------------------------------------------------------------ set_camera_vars
# type -> (name in get_camera_vars.cgi, min, max)
SCAM = {
    1: ("OSDTimer", 0, 12),     # OSD color: 0 off, 1 black … 12 light blue
    2: ("brightness", 0, 255),
    3: ("contrast", 0, 255),
    4: ("hue", -128, 127),
    5: ("saturation", 0, 200),
    6: ("ptzspeed", 1, 100),
    7: ("mirror", 0, 1),
    8: ("flip", 0, 1),
    9: ("aec_value", 1, 3),     # mains frequency: 1 = 50 Hz, 2 = 60 Hz, 3 = outdoor
}
SCAM_BY_NAME = {name: (t, lo, hi) for t, (name, lo, hi) in SCAM.items()}
SCAM_ALIASES = {"osd": "OSDTimer", "osd_color": "OSDTimer", "hz": "aec_value",
                "frequency": "aec_value", "speed": "ptzspeed", "bright": "brightness",
                "satura": "saturation"}

OSD_COLORS = ["off", "black", "red", "green", "blue", "purple", "grey", "silver",
              "yellow", "olive", "teal", "white", "light blue"]

# ------------------------------------------------------------ set_lamp (status LED)
LAMP_MODES = {
    0: "blinks when network connected, off otherwise",
    1: "blinks when network connected, slow otherwise",
    2: "always off",
    3: "always on",
}

# ------------------------------------------------------------ get_params?type=N
PARAM_TYPES = {
    1: "Users", 2: "Motion/alarm detector", 3: "Audio", 4: "Device info",
    5: "FTP", 6: "Multi-device", 7: "Network/UPnP/DDNS", 8: "WiFi", 9: "Date/time",
    10: "PTZ", 11: "E-mail", 12: "Video", 13: "Network/DDNS (2)", 14: "SD card",
}
# These types contain passwords -> redacted in reports
SECRET_PARAM_TYPES = {1, 5, 6, 7, 8, 11, 13}

MOTION_LEVELS = {1: "low", 2: "medium", 3: "high", 4: "higher", 5: "highest"}
MOTION_TIMEOUTS = {0: "permanent", 1: "5 s", 2: "10 s", 3: "15 s", 4: "30 s", 5: "60 s"}

# ------------------------------------------------------------ Streams
RTSP_PATH = "/live/av0"   # vlc_video.htm: rtsp://host:port/live/av0?user=..&passwd=..

# Read-only CGIs without mandatory parameters – used by status --all and probe.
READ_CGIS = [
    "get_status.cgi",
    "get_real_status.cgi",
    "get_camera_vars.cgi",
    "get_preset_status.cgi",
    "get_sdc_status.cgi",
    "get_list_cruise.cgi",
    "get_motion_schedule.cgi",
    "get_alarm_schedule.cgi",
    "get_extra_server.cgi",
    "get_wifi_scan_result.cgi",
    "check_user.cgi",
]

# These CGIs are never executed without --force/_force.
DANGEROUS_CGIS = {
    "reboot.cgi", "restore_factory.cgi", "format_sdc.cgi", "upgrade_firmware.cgi",
    "upgrade_webui.cgi", "set_mac.cgi", "set_users.cgi", "set_wifi.cgi",
    "set_static_ip.cgi", "set_dhcp_ip.cgi", "set_pppoe.cgi", "backup_params.cgi",
    "clear_log.cgi", "delete_sdcard_file.cgi",
}
