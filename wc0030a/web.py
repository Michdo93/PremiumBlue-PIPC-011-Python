"""Flask-Weboberfläche: Live-Bild, PTZ (gedrückt halten), Presets, Status."""

from __future__ import annotations

import io
import logging
import time

from flask import Flask, Response, jsonify, render_template_string, request, send_file

from .api import Camera, CameraError
from . import commands as C

log = logging.getLogger(__name__)

PAGE = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WC0030A</title>
<style>
  :root { --bg:#12161b; --panel:#1b2128; --line:#2b333d; --text:#e6e9ed; --dim:#8b95a1;
          --act:#3d8bfd; --warn:#e5534b; --ok:#3fb950; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.45 system-ui, sans-serif; background:var(--bg); color:var(--text); }
  header { display:flex; align-items:baseline; gap:1rem; padding:.9rem 1.2rem; border-bottom:1px solid var(--line); }
  header h1 { font-size:1.05rem; margin:0; font-weight:600; }
  header span { color:var(--dim); font-size:.85rem; }
  main { display:grid; grid-template-columns:minmax(0,2fr) minmax(280px,1fr); gap:1.2rem; padding:1.2rem; max-width:1300px; margin:auto; }
  @media (max-width:860px){ main { grid-template-columns:1fr; } }
  .video { background:#000; border-radius:6px; overflow:hidden; aspect-ratio:16/9; position:relative; }
  .video img { width:100%; height:100%; object-fit:contain; display:block; }
  .badge { position:absolute; top:.6rem; left:.6rem; padding:.15rem .55rem; border-radius:3px;
           font-size:.8rem; background:rgba(0,0,0,.6); }
  .badge.motion { background:var(--warn); }
  section { background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:1rem; margin-bottom:1rem; }
  h2 { font-size:.95rem; margin:0 0 .7rem; font-weight:600; }
  .pad { display:grid; grid-template-columns:repeat(3,3.4rem); gap:.4rem; justify-content:center; touch-action:none; }
  button { background:#27303a; color:var(--text); border:1px solid var(--line); border-radius:4px;
           padding:.55rem .6rem; font:inherit; cursor:pointer; user-select:none; }
  button:hover { border-color:var(--act); }
  button:active, button.on { background:var(--act); border-color:var(--act); }
  button:focus-visible { outline:2px solid var(--act); outline-offset:2px; }
  .pad button { height:3.4rem; font-size:1.2rem; }
  .row { display:flex; flex-wrap:wrap; gap:.4rem; }
  .row button { flex:1 1 auto; }
  .hint { color:var(--dim); font-size:.82rem; margin:.5rem 0 0; }
  dl { display:grid; grid-template-columns:auto 1fr; gap:.25rem .8rem; margin:0; font-size:.88rem; }
  dt { color:var(--dim); } dd { margin:0; }
  .slider { display:grid; grid-template-columns:7rem 1fr 2.5rem; align-items:center; gap:.5rem; font-size:.88rem; margin-bottom:.3rem; }
  .slider output { text-align:right; color:var(--dim); }
  #msg { min-height:1.2em; font-size:.85rem; color:var(--dim); margin-top:.6rem; }
  #msg.err { color:var(--warn); }
</style>
</head>
<body>
<header><h1>LogiLink WC0030A</h1><span id="model"></span></header>
<main>
  <div>
    <div class="video"><img src="/video_feed" alt="Live-Bild der Kamera"><span id="motion" class="badge">Keine Bewegung</span></div>
    <div class="row" style="margin-top:.7rem">
      <button onclick="location.href='/snapshot'">Schnappschuss herunterladen</button>
    </div>
    <div id="msg"></div>
  </div>
  <div>
    <section>
      <h2>Schwenken und neigen</h2>
      <div class="pad">
        <button data-dir="up_left" aria-label="Links oben">↖</button>
        <button data-dir="up" aria-label="Oben">▲</button>
        <button data-dir="up_right" aria-label="Rechts oben">↗</button>
        <button data-dir="left" aria-label="Links">◀</button>
        <button onclick="api('/api/ptz/center')" aria-label="Mitte">●</button>
        <button data-dir="right" aria-label="Rechts">▶</button>
        <button data-dir="down_left" aria-label="Links unten">↙</button>
        <button data-dir="down" aria-label="Unten">▼</button>
        <button data-dir="down_right" aria-label="Rechts unten">↘</button>
      </div>
      <p class="hint">Gedrückt halten zum Fahren, loslassen zum Anhalten.</p>
    </section>
    <section>
      <h2>Positionen</h2>
      <div class="row" id="presets"></div>
      <p class="hint"><label><input type="checkbox" id="saveMode"> Aktuelle Position beim Klick speichern</label></p>
    </section>
    <section>
      <h2>Patrouille und Schaltausgang</h2>
      <div class="row">
        <button onclick="api('/api/patrol/h/start')">Horizontal</button>
        <button onclick="api('/api/patrol/v/start')">Vertikal</button>
        <button onclick="api('/api/patrol/stop')">Anhalten</button>
      </div>
      <div class="row" style="margin-top:.4rem">
        <button onclick="api('/api/relay/on')">Relais an</button>
        <button onclick="api('/api/relay/off')">Relais aus</button>
      </div>
    </section>
    <section>
      <h2>Bild und Geschwindigkeit</h2>
      <div id="image"></div>
      <div class="row" style="margin-top:.4rem">
        <label><input type="checkbox" id="img_mirror"> Spiegeln</label>
        <label><input type="checkbox" id="img_flip"> Drehen</label>
        <label>Netz <select id="img_aec_value"><option value="1">50 Hz</option><option value="2">60 Hz</option><option value="3">Außen</option></select></label>
      </div>
    </section>
    <section>
      <h2>Status</h2>
      <dl id="status"></dl>
    </section>
  </div>
</main>
<script>
const msg = document.getElementById('msg');
function show(text, err){ msg.textContent = text; msg.className = err ? 'err' : ''; }
async function api(url){
  try {
    const r = await fetch(url, {method:'POST'});
    const j = await r.json();
    show(j.ok ? '' : (j.error || 'Befehl fehlgeschlagen'), !j.ok);
    return j;
  } catch(e){ show('Server nicht erreichbar', true); }
}
// Gedrückt halten
document.querySelectorAll('[data-dir]').forEach(b => {
  let active = false;
  const start = e => { e.preventDefault(); active = true; b.classList.add('on'); b.setPointerCapture?.(e.pointerId); api('/api/ptz/'+b.dataset.dir+'/start'); };
  const stop  = () => { if(!active) return; active = false; b.classList.remove('on'); api('/api/ptz/'+b.dataset.dir+'/stop'); };
  b.addEventListener('pointerdown', start);
  ['pointerup','pointercancel','lostpointercapture'].forEach(ev => b.addEventListener(ev, stop));
  b.addEventListener('keydown', e => { if((e.key===' '||e.key==='Enter') && !active){ start(e); } });
  b.addEventListener('keyup', e => { if(e.key===' '||e.key==='Enter'){ stop(); } });
});
// Presets
fetch('/api/presets').then(r=>r.json()).then(j => {
  const box = document.getElementById('presets');
  for(let i=1;i<=j.count;i++){
    const b = document.createElement('button'); b.textContent = i;
    b.onclick = () => {
      const save = document.getElementById('saveMode').checked;
      api('/api/preset/'+i+(save?'/set':'/goto')).then(()=>{ if(save) show('Position '+i+' gespeichert'); });
    };
    box.appendChild(b);
  }
});
// Bildparameter (Namen wie in get_camera_vars.cgi)
const SLIDERS = [['brightness','Helligkeit',0,255],['contrast','Kontrast',0,255],
                 ['hue','Farbton',-128,127],['saturation','Sättigung',0,200],['ptzspeed','PTZ-Tempo',1,100]];
fetch('/api/camera_vars').then(r=>r.json()).then(j => {
  if(!j.ok){ show(j.error, true); return; }
  const v = j.vars, box = document.getElementById('image');
  for(const [k,label,min,max] of SLIDERS){
    if(!(k in v)) continue;
    const row = document.createElement('label'); row.className = 'slider';
    row.innerHTML = `<span>${label}</span><input type="range" min="${min}" max="${max}" value="${v[k]}"><output>${v[k]}</output>`;
    const inp = row.querySelector('input'), out = row.querySelector('output');
    inp.oninput = () => out.textContent = inp.value;
    inp.onchange = () => api(`/api/camera_vars/${k}/${inp.value}`);
    box.appendChild(row);
  }
  const hz = document.getElementById('img_aec_value');
  hz.value = v.aec_value; hz.onchange = () => api(`/api/camera_vars/aec_value/${hz.value}`);
  for(const k of ['mirror','flip']){
    const cb = document.getElementById('img_'+k);
    cb.checked = +v[k] === 1;
    cb.onchange = () => api(`/api/camera_vars/${k}/${cb.checked?1:0}`);
  }
});
// Status
async function poll(){
  try {
    const j = await (await fetch('/api/status')).json();
    if(j.ok){
      const s = j.status, st = j.info || {};
      document.getElementById('model').textContent = (st.prot_mode||'') + ' · FW ' + (st.server_version||'');
      const m = document.getElementById('motion');
      const moving = +s.realstatus_motion === 1;
      m.textContent = moving ? 'Bewegung erkannt' : 'Keine Bewegung';
      m.className = 'badge' + (moving ? ' motion' : '');
      const rows = {
        'Auflösung': s.realstatus_videoW + '×' + s.realstatus_videoH,
        'Bildrate': s.realstatus_mrate + ' fps',
        'IP-Adresse': s.realstatus_ipaddr,
        'Alarm': +s.realstatus_alstatus ? 'aktiv' : 'aus',
        'SD-Karte': j.sd ? Math.round(j.sd.sdc_status_freespace/1024) + ' MB frei von ' + Math.round(j.sd.sdc_status_allspace/1024) + ' MB' : '–',
      };
      document.getElementById('status').innerHTML = Object.entries(rows).map(([k,v]) => '<dt>'+k+'</dt><dd>'+v+'</dd>').join('');
    }
  } catch(e) {}
  setTimeout(poll, 2000);
}
poll();
</script>
</body>
</html>"""


def create_app(cam: Camera) -> Flask:
    app = Flask(__name__)
    cache: dict = {}

    def run(fn, *a):
        try:
            fn(*a)
            return jsonify(ok=True)
        except (CameraError, ValueError) as exc:
            log.warning("%s", exc)
            return jsonify(ok=False, error=str(exc)), 502 if isinstance(exc, CameraError) else 400

    @app.get("/")
    def index():
        return render_template_string(PAGE)

    @app.get("/video_feed")
    def video_feed():
        def gen():
            try:
                for jpg in cam.mjpeg_frames():
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
            except CameraError as exc:
                log.warning("Stream: %s", exc)
        return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.get("/snapshot")
    def snapshot():
        try:
            data = cam.snapshot()
        except CameraError as exc:
            return str(exc), 502
        inline = request.args.get("inline") is not None
        return send_file(io.BytesIO(data), mimetype="image/jpeg",
                         as_attachment=not inline, download_name="snapshot.jpg")

    @app.post("/api/ptz/<direction>/<action>")
    def ptz(direction, action):
        if direction not in C.MOVE:
            return jsonify(ok=False, error="unbekannte Richtung"), 400
        fn = {"start": cam.move, "stop": cam.stop, "step": cam.step}.get(action)
        if not fn:
            return jsonify(ok=False, error="Aktion start|stop|step"), 400
        if action == "step":  # optional ?count=N
            try:
                count = int(request.args.get("count", 1))
            except ValueError:
                return jsonify(ok=False, error="count muss eine ganze Zahl sein"), 400
            return run(fn, direction, count)
        return run(fn, direction)

    @app.post("/api/ptz/center")
    def center():
        return run(cam.center)

    @app.post("/api/ptz/stop")
    def stop():
        return run(cam.stop)

    @app.get("/api/presets")
    def presets():
        return jsonify(count=cam.preset_count())

    @app.post("/api/preset/<int:n>/<action>")
    def preset(n, action):
        fn = {"goto": cam.preset_goto, "set": cam.preset_set}.get(action)
        if not fn:
            return jsonify(ok=False, error="Aktion goto|set"), 400
        return run(fn, n)

    @app.post("/api/patrol/<axis>/start")
    def patrol(axis):
        def go():
            cam.patrol_stop()
            cam.patrol(axis, True)
        return run(go)

    @app.post("/api/patrol/stop")
    def patrol_stop():
        return run(cam.patrol_stop)

    @app.post("/api/relay/<state>")
    def relay(state):
        return run(cam.io_output, state == "on")

    @app.get("/api/camera_vars")
    def camera_vars():
        try:
            return jsonify(ok=True, vars=cam.camera_vars())
        except CameraError as exc:
            return jsonify(ok=False, error=str(exc)), 502

    @app.post("/api/camera_vars/<name>/<int(signed=True):value>")
    def set_camera_var(name, value):
        return run(cam.set_camera_var, name, int(value))

    @app.get("/api/status")
    def status():
        try:
            if "info" not in cache:
                cache["info"] = cam.status()
            out = {"ok": True, "status": cam.real_status(), "info": cache["info"]}
            if time.monotonic() - cache.get("sd_t", -1e9) > 60:
                try:
                    cache["sd"] = cam.sd_status()
                except CameraError:
                    cache["sd"] = None
                cache["sd_t"] = time.monotonic()
            out["sd"] = cache["sd"]
            return jsonify(out)
        except CameraError as exc:
            return jsonify(ok=False, error=str(exc)), 502

    return app
