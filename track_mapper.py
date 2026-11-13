#!/usr/bin/env python3
"""
Track Mapper : pose des points sur une voie de train / métro, déplace-les à la main
et lis les distances en pieds (ft) entre chaque point.

Aucune installation : Python 3.8+ (bibliothèque standard uniquement).
    python track_mapper.py
Le navigateur s'ouvre sur http://127.0.0.1:8765 (internet requis pour les cartes
OpenStreetMap / satellite et pour la recherche de la voie via Overpass).
"""
import json
import math
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8765
SESSION_FILE = Path(__file__).with_name("track_session.json")
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
FT_PER_M = 3.28084
EARTH_R = 6371008.8


# --------------------------------------------------------------------------- géométrie
def haversine_m(a, b):
    """Distance en mètres entre deux points (lat, lon)."""
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(h))


def chain_ways(ways, tol=1e-6, max_gap_m=150.0):
    """
    Assemble des tronçons (listes de (lat, lon)) en une seule polyligne ordonnée.
    Retourne (polyligne, nombre_de_troncons_non_utilises).
    """
    ways = [list(w) for w in ways if len(w) >= 2]
    if not ways:
        return [], 0

    def close(a, b):
        return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol

    # départ : un tronçon dont une extrémité n'est reliée à aucun autre
    start, flip = ways[0], False
    for w in ways:
        for end, is_first in ((w[0], True), (w[-1], False)):
            if not any(o is not w and (close(end, o[0]) or close(end, o[-1])) for o in ways):
                start, flip = w, not is_first
                break
        else:
            continue
        break

    chain = list(reversed(start)) if flip else list(start)
    remaining = [w for w in ways if w is not start]

    while remaining:
        tail = chain[-1]
        picked = None
        for w in remaining:
            if close(tail, w[0]):
                picked = (w, w[1:])
                break
            if close(tail, w[-1]):
                picked = (w, w[-2::-1])
                break
        if picked is None:  # trou : on saute vers l'extrémité la plus proche
            best = None
            for w in remaining:
                for pts in (w, w[::-1]):
                    d = haversine_m(tail, pts[0])
                    if best is None or d < best[0]:
                        best = (d, w, pts)
            if best is None or best[0] > max_gap_m:
                break
            picked = (best[1], best[2])
        chain.extend(picked[1])
        remaining.remove(picked[0])
    return chain, len(remaining)


# --------------------------------------------------------------------------- Overpass
def overpass(query):
    data = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for url in OVERPASS_URLS:
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "track-mapper/1.0"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"Overpass indisponible : {last}")


def esc(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def find_relations(name):
    q = (
        '[out:json][timeout:60];'
        f'relation["route"~"^(light_rail|tram|subway|train|railway)$"]["name"~"{esc(name)}",i];'
        'out tags;'
    )
    out = []
    for el in overpass(q).get("elements", []):
        t = el.get("tags", {})
        out.append({
            "id": el["id"],
            "name": t.get("name", f"relation {el['id']}"),
            "from": t.get("from", ""),
            "to": t.get("to", ""),
        })
    return out


def load_track(rel_id):
    data = overpass(f"[out:json][timeout:90];relation({int(rel_id)});out geom;")
    ways = []
    for el in data.get("elements", []):
        for m in el.get("members", []):
            role = (m.get("role") or "").lower()
            if m.get("type") != "way" or role.startswith(("platform", "stop")):
                continue
            geom = [(g["lat"], g["lon"]) for g in m.get("geometry", [])]
            if len(geom) >= 2:
                ways.append(geom)
    line, unused = chain_ways(ways)
    return {"coords": [[a, b] for a, b in line], "unused": unused}


def load_stations(s, w, n, e):
    q = (
        '[out:json][timeout:60];('
        f'node["railway"~"^(station|tram_stop|halt)$"]["name"]({s},{w},{n},{e});'
        ');out;'
    )
    seen, out = set(), []
    for el in overpass(q).get("elements", []):
        name = el.get("tags", {}).get("name")
        key = (name, round(el["lat"], 3), round(el["lon"], 3))
        if name and key not in seen:
            seen.add(key)
            out.append({"name": name, "lat": el["lat"], "lon": el["lon"]})
    return out


# --------------------------------------------------------------------------- serveur HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj))

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        qs = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            if url.path == "/":
                self._send(200, HTML, "text/html; charset=utf-8")
            elif url.path == "/api/relations":
                self._json(find_relations(qs.get("name", "")))
            elif url.path == "/api/track":
                self._json(load_track(qs["id"]))
            elif url.path == "/api/stations":
                self._json(load_stations(qs["s"], qs["w"], qs["n"], qs["e"]))
            elif url.path == "/api/session":
                if SESSION_FILE.exists():
                    self._send(200, SESSION_FILE.read_text(encoding="utf-8"))
                else:
                    self._json({"error": "Aucune session sauvegardée."}, 404)
            else:
                self._json({"error": "introuvable"}, 404)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, 500)

    def do_POST(self):
        if self.path != "/api/session":
            return self._json({"error": "introuvable"}, 404)
        size = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(size).decode("utf-8")
        try:
            json.loads(body)
            SESSION_FILE.write_text(body, encoding="utf-8")
            self._json({"ok": True, "file": str(SESSION_FILE)})
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, 400)


HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Track Mapper</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  :root{
    --ink:#18212b; --muted:#5d6b7a; --paper:#f4f6f8; --card:#ffffff; --line:#d5dce3;
    --track:#1f5fbf; --track2:#e08a00; --signal:#c9302c; --ok:#1d8a4e;
  }
  *{box-sizing:border-box}
  html,body{height:100%;margin:0}
  body{display:grid;grid-template-columns:420px 1fr;font:14px/1.4 "Segoe UI",system-ui,sans-serif;color:var(--ink);background:var(--paper)}
  aside{display:flex;flex-direction:column;min-height:0;border-right:1px solid var(--line);background:var(--card)}
  header{padding:14px 16px 10px;border-bottom:1px solid var(--line)}
  header h1{margin:0;font-size:17px;letter-spacing:.2px}
  header p{margin:2px 0 0;color:var(--muted);font-size:12.5px}
  .scroll{overflow:auto;flex:1;min-height:0}
  section{padding:12px 16px;border-bottom:1px solid var(--line)}
  section h2{margin:0 0 8px;font-size:13px;font-weight:650}
  .row{display:flex;gap:6px;margin-bottom:6px;align-items:center}
  .row>*{min-width:0}
  input[type=text],input[type=number],select{width:100%;padding:6px 8px;border:1px solid var(--line);border-radius:6px;font:inherit;background:#fff;color:inherit}
  button{padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;font:inherit;cursor:pointer;color:inherit;white-space:nowrap}
  button:hover{border-color:var(--track)}
  button.primary{background:var(--track);border-color:var(--track);color:#fff}
  button.on{background:var(--track2);border-color:var(--track2);color:#fff}
  button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--track);outline-offset:1px}
  label.chk{display:flex;gap:6px;align-items:center;color:var(--muted);font-size:13px}
  #status{padding:8px 16px;font-size:12.5px;color:var(--muted);border-top:1px solid var(--line);min-height:34px}
  #status.err{color:var(--signal)}
  table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
  th,td{padding:4px 6px;border-bottom:1px solid var(--line);text-align:right;font-size:12.5px}
  th{position:sticky;top:0;background:var(--card);font-weight:600;color:var(--muted)}
  th:nth-child(2),td:nth-child(2){text-align:left}
  td input{width:100%;border:1px solid transparent;border-radius:4px;padding:2px 4px;font:inherit;background:transparent}
  td input:hover,td input:focus{border-color:var(--line);background:#fff}
  td.n{cursor:pointer;color:var(--track);font-weight:650;text-align:center}
  td.del button{padding:0 6px;border:none;color:var(--muted)}
  tr.total td{font-weight:650;border-bottom:none}
  #map{height:100%}
  .pin span{display:flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:50%;
    background:var(--ink);color:#fff;font:700 12px "Segoe UI",sans-serif;border:2px solid #fff;box-shadow:0 0 0 1.5px var(--ink)}
  .seg{background:#fff;border:1.5px solid var(--ink);border-radius:4px;padding:1px 5px;font:600 11.5px "Segoe UI",sans-serif;white-space:nowrap;
    transform:translate(-50%,-50%);width:max-content;color:var(--ink)}
  .leaflet-div-icon.seg-wrap{background:none;border:none}
  .stn{background:#fff;border:2px solid var(--signal)}
  .hint{color:var(--muted);font-size:12px;margin:4px 0 0}
</style>
</head>
<body>
<aside>
  <header>
    <h1>Track Mapper</h1>
    <p>Pose des points sur la voie, déplace-les, lis les pieds entre chaque point.</p>
  </header>
  <div class="scroll">
    <section>
      <h2>1. Voie</h2>
      <div class="row">
        <input type="text" id="q" value="METRORail Red Line" aria-label="Nom de la ligne">
        <button id="btnSearch">Chercher</button>
      </div>
      <div class="row">
        <select id="rel" aria-label="Résultats"></select>
        <button id="btnLoad" class="primary">Charger</button>
      </div>
      <div class="row">
        <button id="btnImport">Importer GeoJSON</button>
        <button id="btnDraw">Tracer à la main</button>
        <input type="file" id="file" accept=".geojson,.json" hidden>
      </div>
      <p class="hint">Pas de résultat ? Importe un GeoJSON ou trace la voie en cliquant le long des rails (satellite conseillé).</p>
    </section>

    <section>
      <h2>2. Points</h2>
      <div class="row">
        <input type="number" id="nPts" min="2" max="500" value="10" aria-label="Nombre de points">
        <button id="btnPlace" class="primary">Placer N points</button>
      </div>
      <div class="row">
        <button id="btnStations">Un point par station</button>
        <button id="btnAdd">Ajouter au clic</button>
      </div>
      <div class="row">
        <input type="number" id="pk0" step="0.01" placeholder="Pk du point 0 (ft), optionnel" aria-label="Pk du point 0">
      </div>
      <label class="chk"><input type="checkbox" id="chkNames"> Afficher le nom des stations</label>
      <p class="hint">Glisse un point : il reste collé à la voie. Les distances sont mesurées le long de la voie.</p>
    </section>

    <section>
      <h2>3. Distances (ft)</h2>
      <table>
        <thead><tr><th>#</th><th>Nom</th><th>Depuis 0</th><th>Depuis préc.</th><th>Pk</th><th></th></tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </section>

    <section>
      <h2>4. Export</h2>
      <div class="row">
        <button id="btnCsv">Télécharger CSV</button>
        <button id="btnCopy">Copier (Excel)</button>
      </div>
      <div class="row">
        <button id="btnSave">Sauver la session</button>
        <button id="btnRestore">Recharger la session</button>
      </div>
    </section>
  </div>
  <div id="status">Charge une voie pour commencer.</div>
</aside>
<div id="map"></div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const FT = 3.28084, R = 6371008.8;
const $ = id => document.getElementById(id);
const fmt = v => v.toLocaleString('fr-FR', {minimumFractionDigits: 2, maximumFractionDigits: 2});

/* ---------- carte ---------- */
const map = L.map('map').setView([29.72, -95.39], 12);
const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '© OpenStreetMap'}).addTo(map);
const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {maxZoom: 19, attribution: 'Esri World Imagery'});
L.control.layers({'Plan': osm, 'Satellite': sat}).addTo(map);
L.control.scale({imperial: true, metric: true}).addTo(map);

/* ---------- état ---------- */
let track = [], cum = [], total = 0, trackLine = null;
let stations = [], P = [];
let addMode = false, drawMode = false, drawPts = [], drawLine = null;
const stationLayer = L.layerGroup().addTo(map);
const segLayer = L.layerGroup().addTo(map);
const ptLayer = L.layerGroup().addTo(map);

function setStatus(msg, err) { const s = $('status'); s.textContent = msg; s.className = err ? 'err' : ''; }

/* ---------- géométrie ---------- */
function hav(a, b) {
  const r = Math.PI / 180, dLat = (b[0] - a[0]) * r, dLon = (b[1] - a[1]) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h)) * FT;
}
function setTrack(coords) {
  track = coords; cum = [0];
  for (let i = 1; i < track.length; i++) cum.push(cum[i - 1] + hav(track[i - 1], track[i]));
  total = cum[cum.length - 1];
  if (trackLine) map.removeLayer(trackLine);
  trackLine = L.polyline(track, {color: '#1f5fbf', weight: 4, opacity: .55}).addTo(map);
  map.fitBounds(trackLine.getBounds(), {padding: [30, 30]});
  clearPoints();
}
function project(lat, lon) {
  const k = Math.cos(lat * Math.PI / 180);
  let best = {d: Infinity, i: 0, t: 0};
  for (let i = 0; i < track.length - 1; i++) {
    const a = track[i], b = track[i + 1];
    const ax = (a[1] - lon) * k, ay = a[0] - lat, bx = (b[1] - lon) * k, by = b[0] - lat;
    const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
    const t = L2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / L2)) : 0;
    const px = ax + t * dx, py = ay + t * dy, d = px * px + py * py;
    if (d < best.d) best = {d, i, t};
  }
  const a = track[best.i], b = track[best.i + 1];
  return {
    lat: a[0] + best.t * (b[0] - a[0]), lon: a[1] + best.t * (b[1] - a[1]),
    chain: cum[best.i] + best.t * (cum[best.i + 1] - cum[best.i]),
    distM: Math.sqrt(best.d) * 111320
  };
}
function pointAt(chain) {
  chain = Math.max(0, Math.min(total, chain));
  let i = 0;
  while (i < cum.length - 2 && cum[i + 1] < chain) i++;
  const span = cum[i + 1] - cum[i], t = span ? (chain - cum[i]) / span : 0;
  return [track[i][0] + t * (track[i + 1][0] - track[i][0]), track[i][1] + t * (track[i + 1][1] - track[i][1])];
}
function coordsBetween(c1, c2) {
  const out = [pointAt(c1)];
  for (let i = 0; i < track.length; i++) if (cum[i] > c1 && cum[i] < c2) out.push(track[i]);
  out.push(pointAt(c2));
  return out;
}

/* ---------- stations ---------- */
async function loadStations() {
  if (!track.length) return;
  const lats = track.map(p => p[0]), lons = track.map(p => p[1]);
  const pad = 0.002;
  const qs = new URLSearchParams({s: Math.min(...lats) - pad, w: Math.min(...lons) - pad, n: Math.max(...lats) + pad, e: Math.max(...lons) + pad});
  try {
    const r = await fetch('/api/stations?' + qs); const j = await r.json();
    if (j.error) throw new Error(j.error);
    stations = j.filter(s => project(s.lat, s.lon).distM < 150);
    drawStations();
  } catch (e) { setStatus('Stations non chargées : ' + e.message, true); }
}
function drawStations() {
  stationLayer.clearLayers();
  const named = $('chkNames').checked;
  stations.forEach(s => {
    const m = L.circleMarker([s.lat, s.lon], {radius: 7, color: '#c9302c', weight: 3, fillColor: '#fff', fillOpacity: 1});
    m.bindTooltip(s.name, {permanent: named, direction: 'top', offset: [0, -6]});
    stationLayer.addLayer(m);
  });
}
function nearestStation(lat, lon) {
  let best = null;
  stations.forEach(s => { const d = hav([lat, lon], [s.lat, s.lon]); if (d < 130 && (!best || d < best.d)) best = {d, name: s.name}; });
  return best ? best.name : '';
}

/* ---------- points ---------- */
function numIcon(i) { return L.divIcon({className: 'pin', html: `<span>${i}</span>`, iconSize: [26, 26], iconAnchor: [13, 13]}); }
function clearPoints() { P.forEach(p => ptLayer.removeLayer(p.marker)); P = []; render(); }
function autoLabel(pt) { if (pt.auto) { const ll = pt.marker.getLatLng(); pt.label = nearestStation(ll.lat, ll.lng); } }

function addPoint(chain, label) {
  const pt = {chain, label: label || '', auto: !label};
  const m = L.marker(pointAt(chain), {draggable: true, icon: numIcon(P.length), zIndexOffset: 1000});
  pt.marker = m;
  m.on('drag', e => {
    const ll = e.target.getLatLng(), p = project(ll.lat, ll.lng);
    e.target.setLatLng([p.lat, p.lon]); pt.chain = p.chain; render(true);
  });
  m.on('dragend', () => { autoLabel(pt); sortAndRender(); });
  ptLayer.addLayer(m); P.push(pt);
  autoLabel(pt);
  return pt;
}
function sortAndRender() { P.sort((a, b) => a.chain - b.chain); P.forEach((p, i) => p.marker.setIcon(numIcon(i))); render(); }

function placeN() {
  if (!track.length) return setStatus('Charge d’abord une voie.', true);
  const n = Math.max(2, Math.min(500, parseInt($('nPts').value) || 2));
  if (P.length && !confirm('Remplacer les points existants ?')) return;
  P.forEach(p => ptLayer.removeLayer(p.marker)); P = [];
  for (let i = 0; i < n; i++) addPoint(total * i / (n - 1));
  sortAndRender();
  setStatus(`${n} points placés, longueur de la voie : ${fmt(total)} ft.`);
}
function placeAtStations() {
  if (!stations.length) return setStatus('Aucune station chargée.', true);
  if (P.length && !confirm('Remplacer les points existants ?')) return;
  P.forEach(p => ptLayer.removeLayer(p.marker)); P = [];
  const byName = new Map();
  stations.forEach(s => { const p = project(s.lat, s.lon); if (!byName.has(s.name)) byName.set(s.name, p.chain); });
  [...byName.entries()].sort((a, b) => a[1] - b[1]).forEach(([name, chain]) => addPoint(chain, name));
  sortAndRender();
  setStatus(`${P.length} points posés sur les stations.`);
}

/* ---------- rendu ---------- */
function render(light) {
  const S = [...P].sort((a, b) => a.chain - b.chain);
  window._S = S;
  segLayer.clearLayers();
  for (let i = 1; i < S.length; i++) {
    const a = S[i - 1].chain, b = S[i].chain;
    segLayer.addLayer(L.polyline(coordsBetween(a, b), {color: i % 2 ? '#1f5fbf' : '#e08a00', weight: 6, opacity: .9, interactive: false}));
    const mid = pointAt((a + b) / 2);
    segLayer.addLayer(L.marker(mid, {interactive: false, icon: L.divIcon({className: 'seg-wrap', html: `<div class="seg">${fmt(b - a)} ft</div>`, iconSize: [0, 0]})}));
  }
  const pk0 = parseFloat($('pk0').value), hasPk = !isNaN(pk0);
  const tb = $('tbody'); tb.innerHTML = '';
  S.forEach((p, i) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td class="n" title="Centrer">${i}</td>
      <td><input type="text" value="${(p.label || '').replace(/"/g, '&quot;')}" placeholder="station, panneau, rue…" aria-label="Nom du point ${i}"></td>
      <td>${fmt(p.chain - S[0].chain)}</td>
      <td>${i ? fmt(p.chain - S[i - 1].chain) : '—'}</td>
      <td>${hasPk ? fmt(pk0 + p.chain - S[0].chain) : ''}</td>
      <td class="del"><button title="Supprimer" aria-label="Supprimer le point ${i}">✕</button></td>`;
    tr.querySelector('.n').onclick = () => map.setView(p.marker.getLatLng(), Math.max(map.getZoom(), 18));
    tr.querySelector('input').oninput = e => { p.label = e.target.value; p.auto = false; };
    tr.querySelector('button').onclick = () => { ptLayer.removeLayer(p.marker); P = P.filter(x => x !== p); sortAndRender(); };
    tb.appendChild(tr);
  });
  if (S.length > 1) {
    const tr = document.createElement('tr'); tr.className = 'total';
    tr.innerHTML = `<td></td><td>Total</td><td>${fmt(S[S.length - 1].chain - S[0].chain)}</td><td></td><td></td><td></td>`;
    tb.appendChild(tr);
  }
}

/* ---------- export ---------- */
function rows() {
  const S = [...P].sort((a, b) => a.chain - b.chain), pk0 = parseFloat($('pk0').value);
  return S.map((p, i) => {
    const ll = p.marker.getLatLng();
    return [i, p.label || '', ll.lat.toFixed(7), ll.lng.toFixed(7), (p.chain - S[0].chain).toFixed(2),
            i ? (p.chain - S[i - 1].chain).toFixed(2) : '0.00', isNaN(pk0) ? '' : (pk0 + p.chain - S[0].chain).toFixed(2)];
  });
}
const HEAD = ['index', 'nom', 'lat', 'lon', 'depuis_0_ft', 'depuis_prec_ft', 'pk_ft'];
$('btnCsv').onclick = () => {
  if (!P.length) return setStatus('Aucun point à exporter.', true);
  const csv = [HEAD, ...rows()].map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(';')).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['\ufeff' + csv], {type: 'text/csv'})); a.download = 'points_voie.csv'; a.click();
};
$('btnCopy').onclick = async () => {
  if (!P.length) return setStatus('Aucun point à copier.', true);
  await navigator.clipboard.writeText([HEAD, ...rows()].map(r => r.join('\t')).join('\n'));
  setStatus('Copié : colle dans Excel.');
};

/* ---------- session ---------- */
$('btnSave').onclick = async () => {
  const body = {track, stations, pk0: $('pk0').value, points: [...P].sort((a, b) => a.chain - b.chain).map(p => ({chain: p.chain, label: p.label, auto: p.auto}))};
  const r = await fetch('/api/session', {method: 'POST', body: JSON.stringify(body)}); const j = await r.json();
  setStatus(j.ok ? 'Session sauvegardée : ' + j.file : 'Erreur : ' + j.error, !j.ok);
};
$('btnRestore').onclick = async () => {
  const r = await fetch('/api/session'); const j = await r.json();
  if (j.error) return setStatus(j.error, true);
  setTrack(j.track); stations = j.stations || []; drawStations(); $('pk0').value = j.pk0 || '';
  j.points.forEach(p => { const pt = addPoint(p.chain, p.label); pt.auto = p.auto; });
  sortAndRender(); setStatus('Session rechargée.');
};

/* ---------- chargement de la voie ---------- */
$('btnSearch').onclick = async () => {
  setStatus('Recherche…');
  try {
    const r = await fetch('/api/relations?name=' + encodeURIComponent($('q').value)); const j = await r.json();
    if (j.error) throw new Error(j.error);
    $('rel').innerHTML = j.map(x => `<option value="${x.id}">${x.name}${x.from ? ' (' + x.from + ' → ' + x.to + ')' : ''}</option>`).join('');
    setStatus(j.length ? `${j.length} résultat(s).` : 'Aucun résultat : importe un GeoJSON ou trace à la main.', !j.length);
  } catch (e) { setStatus(e.message, true); }
};
$('btnLoad').onclick = async () => {
  const id = $('rel').value; if (!id) return setStatus('Cherche d’abord une ligne.', true);
  setStatus('Chargement de la voie…');
  try {
    const r = await fetch('/api/track?id=' + id); const j = await r.json();
    if (j.error) throw new Error(j.error);
    if (j.coords.length < 2) throw new Error('Voie vide : essaie une autre relation.');
    setTrack(j.coords);
    setStatus(`Voie chargée : ${fmt(total)} ft` + (j.unused ? ` (${j.unused} tronçon(s) ignoré(s))` : '') + '. Chargement des stations…');
    await loadStations();
    setStatus(`Voie : ${fmt(total)} ft, ${stations.length} station(s). Place des points.`);
  } catch (e) { setStatus(e.message, true); }
};
$('btnImport').onclick = () => $('file').click();
$('file').onchange = async e => {
  const f = e.target.files[0]; if (!f) return;
  try {
    const gj = JSON.parse(await f.text()), lines = [];
    (function walk(o) {
      if (!o) return;
      if (o.type === 'FeatureCollection') o.features.forEach(walk);
      else if (o.type === 'Feature') walk(o.geometry);
      else if (o.type === 'LineString') lines.push(o.coordinates);
      else if (o.type === 'MultiLineString') o.coordinates.forEach(c => lines.push(c));
    })(gj);
    const coords = lines.flat().map(c => [c[1], c[0]]);
    if (coords.length < 2) throw new Error('Aucune ligne dans ce fichier.');
    setTrack(coords); stations = []; stationLayer.clearLayers(); await loadStations();
    setStatus(`GeoJSON importé : ${fmt(total)} ft.`);
  } catch (err) { setStatus(err.message, true); }
  e.target.value = '';
};
$('btnDraw').onclick = () => {
  if (!drawMode) {
    drawMode = true; drawPts = []; $('btnDraw').textContent = 'Terminer le tracé'; $('btnDraw').className = 'on';
    setStatus('Clique le long des rails ; recliquer sur « Terminer » pour valider.');
  } else {
    drawMode = false; $('btnDraw').textContent = 'Tracer à la main'; $('btnDraw').className = '';
    if (drawLine) { map.removeLayer(drawLine); drawLine = null; }
    if (drawPts.length >= 2) { setTrack(drawPts.slice()); stations = []; stationLayer.clearLayers(); loadStations(); setStatus(`Voie tracée : ${fmt(total)} ft.`); }
    else setStatus('Il faut au moins 2 clics.', true);
  }
};
$('btnAdd').onclick = () => {
  addMode = !addMode; $('btnAdd').className = addMode ? 'on' : '';
  setStatus(addMode ? 'Clique près de la voie pour ajouter un point.' : 'Ajout au clic désactivé.');
};
map.on('click', e => {
  if (drawMode) {
    drawPts.push([e.latlng.lat, e.latlng.lng]);
    if (drawLine) map.removeLayer(drawLine);
    drawLine = L.polyline(drawPts, {color: '#c9302c', weight: 3}).addTo(map);
  } else if (addMode && track.length) {
    const p = project(e.latlng.lat, e.latlng.lng);
    if (p.distM > 80) return setStatus('Clique plus près de la voie.', true);
    addPoint(p.chain); sortAndRender();
  }
});
$('btnPlace').onclick = placeN;
$('btnStations').onclick = placeAtStations;
$('chkNames').onchange = drawStations;
$('pk0').oninput = () => render();
</script>
</body>
</html>
"""


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Track Mapper : {url}   (Ctrl+C pour quitter)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
