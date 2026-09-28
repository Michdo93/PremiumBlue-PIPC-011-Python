# LogiLink-WC0030A-Python

Steuerung der Pan/Tilt-IP-Kamera **LogiLink WC0030A** per Python – als Bibliothek, Kommandozeile, Weboberfläche und MQTT-Brücke für openHAB.

Die WC0030A ist ein OEM-Gerät von Apexis. Die Kamera meldet sich in `get_status.cgi` als **APM-H803-MPC** (Firmware `83.2.5.69c3`, WebUI `17.14.5.45`, Sensor OV9710, 1280×720). Die CGI-Schnittstelle ist **nicht** Foscam-kompatibel; alle Befehle hier sind aus der Weboberfläche der Kamera selbst entnommen – siehe [CGI-Referenz](#cgi-referenz).

## Installation

```bash
git clone https://github.com/Michdo93/LogiLink-WC0030A-Python.git
cd LogiLink-WC0030A-Python
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml   # IP und Passwort eintragen
```

Windows (PowerShell):

```powershell
git clone https://github.com/Michdo93/LogiLink-WC0030A-Python.git
cd LogiLink-WC0030A-Python
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item config.example.yaml config.yaml   # IP und Passwort eintragen
```

Die Zugangsdaten stehen nicht mehr im Code. Reihenfolge: Defaults < `config.yaml` < Umgebungsvariablen (`WC0030A_HOST`, `WC0030A_PASSWORD`, `MQTT_HOST` …) < CLI-Optionen (`--host`, `--password`).

## Kommandozeile

```bash
python -m wc0030a status                 # Geräte- und Laufzeitstatus als JSON
python -m wc0030a status --all           # alle lesenden CGIs
python -m wc0030a ptz left               # 0,5 s fahren, anhalten (wie mobile.htm)
python -m wc0030a ptz left --count 3    # drei Einzelschritte (Kurzform: -n 3)
python -m wc0030a ptz up --continuous    # fahren bis „stop“
python -m wc0030a stop
python -m wc0030a ptz center
python -m wc0030a preset goto 3          # Presets 1–9
python -m wc0030a preset set 3
python -m wc0030a patrol h start         # Achse h oder v
python -m wc0030a patrol h stop
python -m wc0030a patrol all stop        # beide Patrouillen stoppen
python -m wc0030a relay on
python -m wc0030a snapshot bild.jpg
python -m wc0030a image                  # Bildparameter anzeigen
python -m wc0030a image brightness=140 flip=1 hz=1 osd=0
python -m wc0030a motion                 # Bewegungsmelder anzeigen
python -m wc0030a motion motion_enable=1 motion_level=3
python -m wc0030a lamp 2                 # Status-LED: 0/1 blinken, 2 aus, 3 an
python -m wc0030a cruise list            # Kurse 0–9 mit Status
python -m wc0030a cruise start 0         # warnt, wenn Kurs 0 nicht angelegt ist
python -m wc0030a cruise stop
python -m wc0030a params 2               # Einstellungsgruppe 1–14 lesen
python -m wc0030a log                    # Einträge als Liste; --raw = flache Kamera-Variablen
python -m wc0030a urls                   # Snapshot-/MJPEG-/RTSP-URL für VLC, openHAB …
python -m wc0030a raw get_camera_vars.cgi
python -m wc0030a probe                  # Kamera erkunden (siehe unten)
python -m wc0030a web                    # Weboberfläche auf Port 5000
python -m wc0030a mqtt                   # MQTT-Brücke
```

Die alte Syntax funktioniert weiter: `python3 camera_control.py --cmd preset1_get`, `--snapshot x.jpg`, ohne Argumente startet die Weboberfläche.

## Weboberfläche

`python -m wc0030a web` → `http://<pi>:5000`

Live-Bild, Steuerkreuz mit acht Richtungen (**gedrückt halten** fährt, loslassen hält an), Presets 1–9 mit Speichermodus, Patrouille, Relais, Statusanzeige mit Bewegungsmeldung. Der MJPEG-Stream wird über `/video_feed` durchgereicht, das Kamera-Passwort verlässt den Pi also nicht.

## Bibliothek

```python
from wc0030a import Camera

cam = Camera("192.168.0.35", "admin", "geheim")
cam.step("right")              # kurz fahren, anhalten
cam.step("right", count=3)     # drei Einzelschritte
cam.move("up"); cam.stop()     # Dauerfahrt
cam.preset_goto(2)
print(cam.real_status()["realstatus_motion"])
open("x.jpg", "wb").write(cam.snapshot())
for frame in cam.mjpeg_frames():   # einzelne JPEGs, z. B. für OpenCV
    ...
```

## openHAB-Integration

Die Kamera-Logik steckt in **einem** Python-Programm (`python -m wc0030a mqtt`), das HTTP zur Kamera und MQTT zum Broker vereint. openHAB bindet es über das MQTT-Binding an; Regeln verknüpfen nur noch Ereignisse mit Befehlen.

Beispieldateien liegen in `openhab/` (Things, Items, Sitemap, MAP-Transformation, JS-Regel).

### Topics

| Topic | Richtung | Inhalt |
|---|---|---|
| `wc0030a/status` | → openHAB | `online` / `offline` (LWT, retained) |
| `wc0030a/state/motion` | → | `ON` / `OFF` (Poll alle 2 s) |
| `wc0030a/state/alarm`, `input1`, `input2`, `sd_alarm` | → | `ON` / `OFF` |
| `wc0030a/state/resolution`, `framerate`, `ip` | → | Laufzeitwerte |
| `wc0030a/state/model`, `firmware`, `webui`, `alias`, `lamp` | → | Geräteinfo (alle 60 s) |
| `wc0030a/state/sd_ok`, `sd_free_mb`, `sd_total_mb` | → | SD-Karte |
| `wc0030a/state/presets` | → | Anzahl Presets (9) |
| `wc0030a/state/relay`, `patrol` | → | zuletzt gesendeter Zustand (Kamera meldet ihn nicht zurück) |
| `wc0030a/state/camera/<name>` | → | Bildparameter aus `get_camera_vars.cgi` |
| `wc0030a/state/json/<cgi>` | → | vollständige Antwort als JSON |
| `wc0030a/state/last_error` | → | letzte Fehlermeldung |
| `wc0030a/snapshot` | → | JPEG-Bytes (Image-Channel), auf Befehl, bei Bewegung oder im Intervall |
| `wc0030a/cmd/ptz` | ← | `UP` `DOWN` `LEFT` `RIGHT` `UP_LEFT` `UP_RIGHT` `DOWN_LEFT` `DOWN_RIGHT` `CENTER` `STOP` – Einzelschritt; `LEFT:3` = drei Schritte |
| `wc0030a/cmd/ptz/move` | ← | Richtung → Dauerfahrt, `STOP` beendet |
| `wc0030a/cmd/preset` | ← | `1`–`9` anfahren |
| `wc0030a/cmd/preset/set` | ← | `1`–`9` speichern |
| `wc0030a/cmd/patrol` | ← | `HORIZONTAL` / `VERTICAL` / `STOP` |
| `wc0030a/cmd/relay` | ← | `ON` / `OFF` |
| `wc0030a/cmd/snapshot` | ← | beliebig → neues Bild |
| `wc0030a/cmd/refresh` | ← | alle Zustände neu lesen |
| `wc0030a/state/motion/enable`, `motion/level`, `motion/timeout` | → | Einstellungen der Bewegungserkennung |
| `wc0030a/cmd/camera_vars` | ← | JSON, z. B. `{"brightness": 140, "flip": 1}` |
| `wc0030a/cmd/camera/<name>` | ← | Einzelwert: `brightness` `contrast` `hue` `saturation` `ptzspeed` `mirror` `flip` `OSDTimer` `aec_value` (`ON`/`OFF` für 0/1) |
| `wc0030a/cmd/motion/enable` | ← | `ON` / `OFF` – Bewegungserkennung der Kamera |
| `wc0030a/cmd/motion/level` | ← | `1`–`5` Empfindlichkeit |
| `wc0030a/cmd/motion/timeout` | ← | `0`–`5` (dauerhaft, 5/10/15/30/60 s) |
| `wc0030a/cmd/lamp` | ← | `0`–`3` Status-LED |
| `wc0030a/cmd/cruise` | ← | Kursindex starten, `STOP` |
| `wc0030a/cmd/reboot` | ← | `REBOOT` |
| `wc0030a/cmd/raw` | ← | `{"cgi": "...", "params": {...}}`, nur mit `mqtt.allow_raw: true` |

### Video in openHAB

Zwei Wege, beide in den Beispieldateien vorbereitet:

1. **Über den Pi:** `web`-Dienst laufen lassen, in der Sitemap `Video url="http://<pi>:5000/video_feed" encoding="mjpeg"`. Kein Kamera-Passwort in openHAB.
2. **IpCamera-Binding** (`ipcamera:httponly`) mit `snapshotUrl`/`mjpegUrl` direkt zur Kamera. Die URLs gibt `python -m wc0030a urls` aus.

### Dienste

```bash
sudo cp -r . /opt/LogiLink-WC0030A-Python
sudo cp systemd/wc0030a-mqtt.service systemd/wc0030a-web.service /etc/systemd/system/
sudo systemctl enable --now wc0030a-mqtt wc0030a-web
```

## CGI-Referenz

Quelle: Weboberfläche der Kamera (`live.htm`, `mobile.htm`, `osdset.htm`, `setmenu/*.htm`), mit `python -m wc0030a probe` heruntergeladen. Authentifizierung überall per `user=…&pwd=…`.

### PTZ: `decoder_control.cgi?type=T&cmd=C`

| type | Bedeutung | cmd |
|---|---|---|
| 0 | Bewegung | 0 hoch, 1 runter, 2 links, 3 rechts, 13 links-oben, 14 links-unten, 15 rechts-oben, 16 rechts-unten, **10 Stopp**, 11 Mitte, 12 Auto aus, 17/18 Patrouille horizontal/vertikal, 19/20 deren Stopp |
| 1 | Preset speichern | 0–8 (Preset 1–9) |
| 2 | Preset anfahren | 0–8 |
| 3 | Schaltausgang | 1 an, 0 aus |

Bewegungen laufen, bis Stopp (`type=0&cmd=10`) kommt. Die Browser-Oberfläche sendet Stopp beim Loslassen, die Mobil-Oberfläche 500 ms nach dem Start. cmd 4–9 (Fokus, Zoom, Iris) existieren im Protokoll, das Modell hat die Hardware aber nicht.

### Bild: `set_camera_vars.cgi?type=T&value=V`

Lesen mit `get_camera_vars.cgi`.

| type | Variable | Bereich |
|---|---|---|
| 1 | `OSDTimer` | OSD-Farbe: 0 aus, 1 schwarz, 2 rot, 3 grün, 4 blau, 5 lila, 6 grau, 7 silber, 8 gelb, 9 oliv, 10 türkis, 11 weiß, 12 hellblau |
| 2 | `brightness` | 0–255 |
| 3 | `contrast` | 0–255 |
| 4 | `hue` | −128–127 |
| 5 | `saturation` | 0–200 |
| 6 | `ptzspeed` | 1–100 |
| 7 | `mirror` | 0/1 |
| 8 | `flip` | 0/1 |
| 9 | `aec_value` | 1 = 50 Hz, 2 = 60 Hz, 3 = Außenbereich |

### Weitere

| Funktion | Aufruf |
|---|---|
| Snapshot | `video_snapshot.cgi` (Browser), `mobile_snapshot.cgi` (Mobil) |
| MJPEG | `videostream.cgi` |
| RTSP (H.264) | `rtsp://<ip>:554/live/av0?user=…&passwd=…` – Parameter heißt `passwd`, nicht `pwd` |
| Status-LED | `set_lamp.cgi?type=0…3` |
| Bewegungsmelder lesen | `get_params.cgi?type=2` → `motion_Enable`, `byMotionSensitive`, `mtimeout`, `msdrec_enable`, `mmail_enable`, `mftp_enable`, `malarmout_enable` |
| Bewegungsmelder setzen | `set_motion_alarm.cgi` mit allen Werten: `motion_enable`, `motion_level` (1–5), `mtimeout` (0–5), `start_x=0&start_y=0&end_x=320&end_y=240`, `msdrec_enable`, `mmail_enable`, `mftp_enable`, `malarmout_enable` |
| Kurs starten/stoppen | `control_cruise.cgi?index=N`, Stopp mit `index=100` |
| Einstellungsgruppen | `get_params.cgi?type=1…14` (1 Benutzer, 2 Alarm, 3 Audio, 4 Gerät, 5 FTP, 6 Multi-Gerät, 7 Netzwerk, 8 WLAN, 9 Zeit, 10 PTZ, 11 E-Mail, 12 Video, 13 Netzwerk/DDNS, 14 SD) |
| Log | `get_log_page.cgi?line=20`, `get_log_info.cgi?page=N&line=20` |
| Log-Eintrag schreiben | `write_log.cgi?type=N` (nur Protokoll, keine Steuerung) |

Die übrigen Setter (`set_video`, `set_audio`, `set_ftp`, `set_smtp`, `set_datetime` …) stehen mit ihren Parametern in `probe_out/report.md` und sind über `python -m wc0030a raw <cgi> key=value …` erreichbar. Netzwerk-, Benutzer- und WLAN-Setter sowie Reboot/Reset/Format sind gesperrt und brauchen `--force`.

`probe` sichert zusätzlich alle `get_params`-Gruppen (Passwörter geschwärzt).

## Entwickeln ohne Kamera

`tools/fake_camera.py` simuliert die Kamera mit den Antworten aus dem Dump, protokolliert PTZ-Befehle, liefert Test-JPEGs und einen MJPEG-Stream. Bewegung per `http://localhost:8080/sim/motion?on=1`.

```bash
python tools/fake_camera.py --port 8080 &
WC0030A_HOST=127.0.0.1 WC0030A_PORT=8080 WC0030A_PASSWORD=test python -m wc0030a web
```

PowerShell:

```powershell
Start-Process python "tools/fake_camera.py --port 8080"
$env:WC0030A_HOST="127.0.0.1"; $env:WC0030A_PORT="8080"; $env:WC0030A_PASSWORD="test"
python -m wc0030a web
```

## Sicherheit

Die Apexis-Firmware dieser Generation hat bekannte, nicht behobene Lücken (u. a. CVE-2017-17101, CVSS 9.8: Zugriff auf Stream und Konfiguration ohne Login). `get_status.cgi` und `get_real_status.cgi` antworten schon jetzt ohne Anmeldung. Empfehlung: Kamera in ein eigenes VLAN/IoT-Netz ohne Internetzugang, keine Portweiterleitung, UPnP, DDNS (`oipcam.com`) und P2P (TUTK) in der Kamera abschalten. Zugriff von außen nur über openHAB bzw. den Pi.
