/* SpoofNet public map.
 *
 * Data comes from the API when one answers at ?api=<base> or at the page origin,
 * otherwise from the static snapshot in ./data (written by `save_snapshot`).
 * Only public data is ever requested: coarse cells, delayed, K-anonymous.
 */
'use strict';

const COLORS = { jam: '#e4572e', spoof: '#8a4fd6', meacon: '#1f8a9b' };
const NAMES = { jam: 'Jamming', spoof: 'Spoofing', meacon: 'Meaconing (rebroadcast)' };
const ADSB = {
  agrees: 'Also seen in aircraft data',
  not_seen_in_adsb: 'Not seen in aircraft data (ground-level sources often are not)',
  no_adsb_coverage: 'No aircraft data for this area and time',
  not_checked: 'Not checked against aircraft data',
};
const params = new URLSearchParams(location.search);
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const dark = matchMedia('(prefers-color-scheme: dark)').matches;
const $ = (id) => document.getElementById(id);

const state = { mode: null, api: '', meta: null, slots: [], incidents: [], coverageCache: new Map(), playing: null, popup: null };

function showState(text) {
  const el = $('state');
  el.hidden = !text;
  el.textContent = text || '';
}

const fmt = new Intl.DateTimeFormat('en-GB', {
  weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC', hour12: false,
});
const utc = (t) => fmt.format(new Date(t * 1000)) + ' UTC';

async function getJson(url) {
  const r = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

async function loadData() {
  const candidates = [];
  if (params.get('api')) candidates.push(params.get('api').replace(/\/$/, ''));
  if (location.protocol.startsWith('http')) candidates.push('');
  for (const base of candidates) {
    try {
      const meta = await getJson(`${base}/v1/public/meta`);
      const hours = 24;
      const step = 3600;
      const end = Math.floor(meta.now / step) * step;
      state.mode = 'api';
      state.api = base;
      state.meta = meta;
      state.slots = Array.from({ length: hours }, (_, i) => ({ t: end - (hours - 1 - i) * step }));
      state.step = step;
      state.incidents = (await getJson(`${base}/v1/public/incidents?hours=${hours}`)).features;
      return;
    } catch (e) { /* try the next source */ }
  }
  const meta = await getJson('data/meta.json');
  state.mode = 'static';
  state.meta = meta;
  state.slots = meta.slots;
  state.step = meta.step_s;
  state.incidents = (await getJson('data/incidents.geojson')).features;
}

async function coverageFor(slot) {
  if (state.coverageCache.has(slot.t)) return state.coverageCache.get(slot.t);
  const url = state.mode === 'api'
    ? `${state.api}/v1/public/coverage?t=${slot.t + state.step}&hours=${state.step / 3600}`
    : `data/${slot.coverage}`;
  let fc;
  try { fc = await getJson(url); } catch (e) { fc = { type: 'FeatureCollection', features: [] }; }
  state.coverageCache.set(slot.t, fc);
  return fc;
}

/* The no-data veil is the whole world with a hole for every covered cell. Holes are
 * shrunk a little so neighbours do not touch, which keeps the polygon valid. */
function veil(coverage) {
  const outer = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
  const holes = coverage.features.map((f) => {
    const ring = f.geometry.coordinates[0];
    const n = ring.length - 1;
    let cx = 0, cy = 0;
    for (let i = 0; i < n; i++) { cx += ring[i][0]; cy += ring[i][1]; }
    cx /= n; cy /= n;
    return ring.map(([x, y]) => [cx + (x - cx) * 0.985, cy + (y - cy) * 0.985]).reverse();
  });
  return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [outer, ...holes] } };
}

function hatchImage() {
  const size = 16;
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const g = c.getContext('2d');
  g.strokeStyle = dark ? 'rgba(235,235,245,0.42)' : 'rgba(60,60,67,0.42)';
  g.lineWidth = 1.5;
  for (const o of [-size, 0, size]) {
    g.beginPath(); g.moveTo(o, size); g.lineTo(o + size, 0); g.stroke();
  }
  return g.getImageData(0, 0, size, size);
}

const map = new maplibregl.Map({
  container: 'map',
  center: [18.8, 54.52],
  zoom: 7,
  attributionControl: false,
  style: {
    version: 8,
    sources: {
      osm: {
        type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, maxzoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      },
      sea: {
        type: 'raster', tiles: ['https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png'], tileSize: 256, maxzoom: 18,
        attribution: 'Sea marks © <a href="https://www.openseamap.org">OpenSeaMap</a>',
      },
    },
    layers: [
      { id: 'osm', type: 'raster', source: 'osm',
        paint: dark ? { 'raster-brightness-max': 0.55, 'raster-saturation': -0.7, 'raster-contrast': 0.1 } : { 'raster-saturation': -0.35 } },
      { id: 'sea', type: 'raster', source: 'sea', layout: { visibility: 'none' } },
    ],
  },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-left');

function incidentsAt(slot) {
  const a = slot.t, b = slot.t + state.step;
  return state.incidents.filter((f) => f.properties.t_start < b && f.properties.t_end > a);
}

async function render(i) {
  const slot = state.slots[i];
  if (!slot) return;
  const cov = await coverageFor(slot);
  if (Number($('time').value) !== i) return;          // the slider moved on while we were loading
  const inc = incidentsAt(slot);
  if (state.popup) { state.popup.remove(); state.popup = null; }   // a popup belongs to the hour it was opened in
  map.getSource('coverage').setData(cov);
  map.getSource('veil').setData(veil(cov));
  map.getSource('incidents').setData({ type: 'FeatureCollection', features: inc });
  const label = `${utc(slot.t)} to ${fmt.format(new Date((slot.t + state.step) * 1000)).slice(-5)}`;
  $('time-label').textContent = label;
  $('time').setAttribute('aria-valuetext', label);
  const ids = new Set(inc.map((f) => f.properties.id));
  const n = ids.size;
  $('summary').textContent = (n === 0 ? 'No incident detected in this hour where there is coverage. '
    : `${n} incident${n === 1 ? '' : 's'} in this hour. `)
    + `${cov.features.length} covered cell${cov.features.length === 1 ? '' : 's'}; everything hatched has no data.`;
}

function popupHtml(p) {
  const pct = Math.round(p.confidence * 100);
  const label = p.evidence === 'real' ? 'Detected on real-world data' : 'Software replay (simulated or injected)';
  return `<div class="pop"><h3>${NAMES[p.type] || p.type}</h3><dl>
    <dt>Confidence</dt><dd>${pct}%</dd>
    <dt>Devices</dt><dd>${p.devices}</dd>
    <dt>Coverage</dt><dd>${p.coverage || 'unknown'}</dd>
    <dt>From</dt><dd>${utc(p.t_start)}</dd>
    <dt>Until</dt><dd>${utc(p.t_end)}</dd>
    <dt>Evidence</dt><dd>${label}</dd>
    <dt>Aircraft data</dt><dd>${ADSB[p.adsb] || p.adsb}</dd></dl>
    <p class="note">Area shown is coarse on purpose. Times are rounded and delayed.</p></div>`;
}

map.on('load', async () => {
  map.addImage('hatch', hatchImage(), { pixelRatio: 1 });
  const empty = { type: 'FeatureCollection', features: [] };
  map.addSource('coverage', { type: 'geojson', data: empty });
  map.addSource('veil', { type: 'geojson', data: veil(empty) });
  map.addSource('incidents', { type: 'geojson', data: empty });
  map.addLayer({ id: 'veil', type: 'fill', source: 'veil', paint: { 'fill-pattern': 'hatch', 'fill-opacity': 0.9 } });
  map.addLayer({ id: 'coverage', type: 'fill', source: 'coverage', paint: {
    'fill-color': '#34a86e', 'fill-opacity': ['match', ['get', 'level'], 'good', 0.20, 0.08] } });
  map.addLayer({ id: 'coverage-line', type: 'line', source: 'coverage', paint: {
    'line-color': '#34a86e', 'line-opacity': 0.45, 'line-width': 1 } });
  map.addLayer({ id: 'incidents', type: 'fill', source: 'incidents', paint: {
    'fill-color': ['match', ['get', 'type'], 'jam', COLORS.jam, 'spoof', COLORS.spoof, 'meacon', COLORS.meacon, '#888'],
    'fill-opacity': ['interpolate', ['linear'], ['get', 'confidence'], 0.3, 0.25, 1, 0.7] } });
  map.addLayer({ id: 'incidents-line', type: 'line', source: 'incidents', paint: {
    'line-color': ['match', ['get', 'type'], 'jam', COLORS.jam, 'spoof', COLORS.spoof, 'meacon', COLORS.meacon, '#888'],
    'line-width': 1.5 } });

  map.on('click', 'incidents', (e) => {
    if (state.popup) state.popup.remove();
    state.popup = new maplibregl.Popup({ maxWidth: '320px' }).setLngLat(e.lngLat).setHTML(popupHtml(e.features[0].properties)).addTo(map);
  });
  map.on('mouseenter', 'incidents', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'incidents', () => { map.getCanvas().style.cursor = ''; });

  showState('Loading incidents and coverage…');
  try {
    await loadData();
  } catch (e) {
    $('evidence').textContent = 'No data source';
    showState('Could not load map data. Start the API, or create a snapshot in web/data. Nothing shown here means no data, not no interference.');
    $('play').disabled = true;
    return;
  }
  showState('');
  const anyReal = state.incidents.some((f) => f.properties.evidence === 'real');
  const ev = $('evidence');
  ev.textContent = anyReal ? 'Includes real-world detections' : 'Software replay only. No real-world detections yet.';
  ev.className = 'pill ' + (anyReal ? 'pill-real' : 'pill-replay');

  const slider = $('time');
  slider.max = String(Math.max(state.slots.length - 1, 0));
  // Start on the most recent hour that has an incident, else on the latest hour.
  let start = state.slots.length - 1;
  for (let i = state.slots.length - 1; i >= 0; i--) {
    if (incidentsAt(state.slots[i]).length) { start = i; break; }
  }
  slider.value = String(start);
  await render(start);
  const first = incidentsAt(state.slots[start])[0] || (await coverageFor(state.slots[start])).features[0];
  if (first) {
    const [x, y] = first.geometry.coordinates[0][0];
    map.jumpTo({ center: [x, y], zoom: 8 });
  }
  let pending = 0;
  slider.addEventListener('input', () => {
    clearTimeout(pending);
    pending = setTimeout(() => render(Number(slider.value)), 60);
  });

  $('play').addEventListener('click', () => {
    const btn = $('play');
    if (state.playing) {
      clearInterval(state.playing);
      state.playing = null;
    } else {
      state.playing = setInterval(() => {
        slider.value = String((Number(slider.value) + 1) % state.slots.length);
        render(Number(slider.value));
      }, reduceMotion ? 1800 : 900);
    }
    btn.textContent = state.playing ? 'Pause' : 'Play';
    btn.setAttribute('aria-pressed', String(Boolean(state.playing)));
  });
});

const vis = (id, on) => map.getLayer(id) && map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
$('t-incidents').addEventListener('change', (e) => { vis('incidents', e.target.checked); vis('incidents-line', e.target.checked); });
$('t-coverage').addEventListener('change', (e) => { ['veil', 'coverage', 'coverage-line'].forEach((l) => vis(l, e.target.checked)); });
$('t-sea').addEventListener('change', (e) => vis('sea', e.target.checked));
