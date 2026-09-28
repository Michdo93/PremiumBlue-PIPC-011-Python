"""Befehlstabellen der WC0030A (Apexis APM-H803-MPC, WebUI 17.14.5.45).

Alle Werte stammen aus der Weboberfläche der Kamera (live.htm, mobile.htm,
osdset.htm, setmenu/*.htm), nicht aus dem Foscam-SDK.

PTZ: /cgi-bin/decoder_control.cgi?type=<T>&cmd=<C>
    type 0 = Bewegung   (cmd siehe PTZ_*)
    type 1 = Preset speichern (cmd 0..8)
    type 2 = Preset anfahren  (cmd 0..8)
    type 3 = Schaltausgang    (cmd 1 = an, 0 = aus)

Bild: /cgi-bin/set_camera_vars.cgi?type=<T>&value=<V>   (siehe SCAM_*)
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
PTZ_FOCUS_ADD = 4      # nicht bei APM-H803-MPC (kein Fokus)
PTZ_FOCUS_DEL = 5
PTZ_ZOOM_ADD = 6       # nicht bei APM-H803-MPC (kein Zoom)
PTZ_ZOOM_DEL = 7
PTZ_IRIS_OPEN = 8      # nicht bei APM-H803-MPC (keine Iris)
PTZ_IRIS_CLOSE = 9
PTZ_STOP = 10
PTZ_AUTO_ON = 11       # Mittelknopf der Weboberfläche -> Kamera fährt in die Mitte
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

# Bei Überkopfmontage bzw. gespiegeltem Bild sind die Achsen vertauscht.
INVERT_V = {"up": "down", "down": "up", "up_left": "down_left", "up_right": "down_right",
            "down_left": "up_left", "down_right": "up_right"}
INVERT_H = {"left": "right", "right": "left", "up_left": "up_right", "up_right": "up_left",
            "down_left": "down_right", "down_right": "down_left"}

STEP_SECONDS = 0.5     # mobile.htm: Bewegung, 500 ms warten, Stopp
STEP_PAUSE = 0.2       # Pause zwischen zwei Einzelschritten (ptz --count)
STEP_MAX_COUNT = 50    # Obergrenze für Wiederholungen (CLI, MQTT, Web)
CRUISE_COUNT = 10      # get_list_cruise.cgi: Kurse 0..9, Stopp mit index=100
PRESET_COUNT = 9       # live.htm: set_preset(0..8), use_preset(0..8)

# ------------------------------------------------------------ set_camera_vars
# type -> (Name in get_camera_vars.cgi, min, max)
SCAM = {
    1: ("OSDTimer", 0, 12),     # OSD-Farbe: 0 aus, 1 schwarz … 12 hellblau
    2: ("brightness", 0, 255),
    3: ("contrast", 0, 255),
    4: ("hue", -128, 127),
    5: ("saturation", 0, 200),
    6: ("ptzspeed", 1, 100),
    7: ("mirror", 0, 1),
    8: ("flip", 0, 1),
    9: ("aec_value", 1, 3),     # Netzfrequenz: 1 = 50 Hz, 2 = 60 Hz, 3 = Außenbereich
}
SCAM_BY_NAME = {name: (t, lo, hi) for t, (name, lo, hi) in SCAM.items()}
SCAM_ALIASES = {"osd": "OSDTimer", "osd_color": "OSDTimer", "hz": "aec_value",
                "frequency": "aec_value", "speed": "ptzspeed", "bright": "brightness",
                "satura": "saturation"}

OSD_COLORS = ["aus", "schwarz", "rot", "grün", "blau", "lila", "grau", "silber",
              "gelb", "oliv", "türkis", "weiß", "hellblau"]

# ------------------------------------------------------------ set_lamp (Status-LED)
LAMP_MODES = {
    0: "blinkt bei Netzverbindung, aus ohne",
    1: "blinkt bei Netzverbindung, langsam ohne",
    2: "immer aus",
    3: "immer an",
}

# ------------------------------------------------------------ get_params?type=N
PARAM_TYPES = {
    1: "Benutzer", 2: "Bewegungs-/Alarmmelder", 3: "Audio", 4: "Geräteinfo",
    5: "FTP", 6: "Multi-Gerät", 7: "Netzwerk/UPnP/DDNS", 8: "WLAN", 9: "Datum/Zeit",
    10: "PTZ", 11: "E-Mail", 12: "Video", 13: "Netzwerk/DDNS (2)", 14: "SD-Karte",
}
# Diese Typen enthalten Passwörter -> werden in Berichten geschwärzt
SECRET_PARAM_TYPES = {1, 5, 6, 7, 8, 11, 13}

MOTION_LEVELS = {1: "niedrig", 2: "mittel", 3: "hoch", 4: "höher", 5: "am höchsten"}
MOTION_TIMEOUTS = {0: "dauerhaft", 1: "5 s", 2: "10 s", 3: "15 s", 4: "30 s", 5: "60 s"}

# ------------------------------------------------------------ Streams
RTSP_PATH = "/live/av0"   # vlc_video.htm: rtsp://host:port/live/av0?user=..&passwd=..

# Nur lesende CGIs ohne Pflichtparameter – für status --all und probe.
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

# Diese CGIs führt das Programm nie ohne --force/_force aus.
DANGEROUS_CGIS = {
    "reboot.cgi", "restore_factory.cgi", "format_sdc.cgi", "upgrade_firmware.cgi",
    "upgrade_webui.cgi", "set_mac.cgi", "set_users.cgi", "set_wifi.cgi",
    "set_static_ip.cgi", "set_dhcp_ip.cgi", "set_pppoe.cgi", "backup_params.cgi",
    "clear_log.cgi", "delete_sdcard_file.cgi",
}
