/**
 * dispatch.js — Incident state, unit management, dispatch & replanning logic.
 * Works fully offline (local mode) or connected to the FastAPI backend.
 */

import {
  placeIncidentMarker, placeUnitMarker, updateUnitMarker,
  removeIncidentMarker, clearRoutesForIncident,
  drawRoute, animateReroute,
  placeObstructionMarker, clearObstructionMarker,
  focusIncident, enablePinMode, disablePinMode,
} from './map.js';
import { addLog, toast, updateStats } from './app.js';
import { api, isOnline } from './api.js';

// ── State ─────────────────────────────────────────────────────────────────────
export let incidents     = [];
export let units         = [];
export let resolvedCount = 0;
let idCounter = 1;
let obsPinActive = false;

// ── Seed units (used when backend is offline) ──────────────────────────────────
const SEED_UNITS = [
  { id:'AMB-01',  type:'ambulance', name:'Ambulance 01',   lat:28.6415, lng:77.1800, status:'available' },
  { id:'AMB-02',  type:'ambulance', name:'Ambulance 02',   lat:28.5890, lng:77.2500, status:'available' },
  { id:'AMB-03',  type:'ambulance', name:'Ambulance 03',   lat:28.6700, lng:77.2300, status:'available' },
  { id:'FIRE-01', type:'fire',      name:'Fire Engine 01', lat:28.6500, lng:77.2200, status:'available' },
  { id:'FIRE-02', type:'fire',      name:'Fire Engine 02', lat:28.6050, lng:77.1600, status:'available' },
  { id:'POL-01',  type:'police',    name:'Police Unit 01', lat:28.6700, lng:77.2050, status:'available' },
  { id:'POL-02',  type:'police',    name:'Police Unit 02', lat:28.6200, lng:77.2800, status:'available' },
  { id:'POL-03',  type:'police',    name:'Police Unit 03', lat:28.5500, lng:77.2000, status:'available' },
  { id:'POL-04',  type:'police',    name:'Police Unit 04', lat:28.6800, lng:77.1600, status:'available' },
];

// ── Init units ────────────────────────────────────────────────────────────────
export async function initUnits() {
  if (isOnline()) {
    try { units = await api.getUnits(); } catch { units = SEED_UNITS.map(u => ({...u})); }
  } else {
    units = SEED_UNITS.map(u => ({...u}));
  }
  units.forEach(u => placeUnitMarker(u));
  renderUnitsPanel();
}

// ── Render units panel ────────────────────────────────────────────────────────
const UNIT_ICONS = { ambulance:'🚑', fire:'🚒', police:'🚔' };

export function renderUnitsPanel() {
  const list = document.getElementById('units-list');
  if (!list) return;
  list.innerHTML = units.map(u => {
    const dot   = u.status === 'available' ? 'available' : u.status === 'dispatched' ? 'dispatched' : 'busy';
    const color = u.status === 'available' ? 'var(--green)' : u.status === 'dispatched' ? 'var(--amber)' : 'var(--red)';
    return `<div class="unit-item" onclick="window.focusUnit('${u.id}')">
      <div class="unit-name"><span class="unit-dot ${dot}"></span>${UNIT_ICONS[u.type]||'🚗'} ${u.id}</div>
      <div class="unit-meta"><span>${u.name}</span><span style="color:${color}">${u.status.toUpperCase()}</span></div>
    </div>`;
  }).join('');
}

// ── Render incidents panel ────────────────────────────────────────────────────
const INC_ICONS = { fire:'🔥', medical:'🚑', accident:'💥', flood:'🌊', crime:'🚔', building:'🏚️', gas:'☢️' };
let selectedId = null;

export function renderIncidentsList() {
  const list  = document.getElementById('incidents-list');
  const badge = document.getElementById('inc-badge');
  if (!list) return;

  const sevOrder = { critical:0, high:1, medium:2, low:3 };
  const active = incidents.filter(i => i.status !== 'resolved')
    .sort((a,b) => sevOrder[a.severity] - sevOrder[b.severity]);

  if (badge) badge.textContent = active.length;

  if (!active.length) {
    list.innerHTML = `<div style="padding:16px;text-align:center;color:var(--text-muted);font-size:12px;">No active incidents</div>`;
    return;
  }
  list.innerHTML = active.map(inc => `
    <div class="incident-card ${selectedId===inc.id?'active':''}" onclick="window.selectIncident('${inc.id}')">
      <div class="inc-header">
        <span class="inc-type-icon">${INC_ICONS[inc.type]||'🚨'}</span>
        <span class="inc-title">${cap(inc.type)} Emergency</span>
        <span class="sev-badge ${inc.severity}">${inc.severity}</span>
      </div>
      <div class="inc-location">📍 ${inc.location_name || inc.locationName || ''}</div>
      <div class="inc-footer">
        <span class="inc-time">⏱ ${inc.timeStr || fmtTime(inc.created_at)}</span>
        <span class="inc-status ${inc.status}">${inc.status}</span>
      </div>
      ${inc.analysis ? `<div class="ai-brief">
        <div><b>AI ANALYSIS</b> · ${String(inc.analysis.severity || inc.severity).toUpperCase()}</div>
        <div>${inc.analysis.number_of_people ?? '—'} people · Injuries: ${inc.analysis.injuries ? 'Yes' : 'No'} · Fire: ${inc.analysis.fire_present ? 'Yes' : 'No'}</div>
        <div class="ai-reasoning">${inc.analysis.reasoning || ''}</div>
      </div>` : ''}
      ${inc.dispatches?.length ? `<div class="ai-dispatches">${inc.dispatches.map(d => `
        <div><span>${String(d.service).replaceAll('_',' ')}</span><b class="${d.status === 'DISPATCHED' ? 'ai-ok' : 'ai-pending'}">${d.unit_id || d.status}</b></div>
      `).join('')}</div>` : ''}
      ${inc.status==='dispatched'&&inc.assigned_unit ? `
        <div style="display:flex;gap:4px;margin-top:6px;">
          <button onclick="event.stopPropagation();window.openReplanPanel('${inc.id}')" class="inc-action-btn amber">🚧 Obstruction</button>
          <button onclick="event.stopPropagation();window.triggerUnitBreakdown('${inc.id}')" class="inc-action-btn red">🔧 Breakdown</button>
          <button onclick="event.stopPropagation();window.triggerManualReplan('${inc.id}')" class="inc-action-btn blue">🔄 Replan</button>
        </div>` : ''}
    </div>`).join('');
}

export function selectIncident(id) {
  selectedId = id;
  renderIncidentsList();
  focusIncident(id);
}

// ── Add incident ──────────────────────────────────────────────────────────────
export async function addIncident(data) {
  let inc;
  if (isOnline()) {
    try {
      const description = data.desc || data.description || `${data.severity} ${data.type} incident`;
      const aiResult = await api.analyzeIncident({
        description,
        location: {
          lat: data.lat, lng: data.lng,
          name: data.locationName || data.location_name || 'Pinned location',
        },
      });
      inc = aiResult.incident || {};
      inc.analysis = aiResult.analysis;
      inc.dispatches = aiResult.dispatches || [];
      await _syncUnits();
    } catch(e) {
      toast(`Backend error: ${e.message} — local dispatch`, 'warn');
      inc = _localDispatch(data);
    }
  } else {
    inc = _localDispatch(data);
  }

  incidents.push(inc);
  placeIncidentMarker(inc, selectIncident);
  renderIncidentsList();
  updateStats();

  const assignedIds = (inc.dispatches || []).filter(d => d.unit_id).map(d => d.unit_id);
  if (assignedIds.length) {
    for (const unitId of assignedIds) {
      const unit = units.find(u => u.id === unitId);
      if (unit) await _fetchAndDrawRoute(unit, inc);
    }
  } else if (inc.assigned_unit) {
    const unit = units.find(u => u.id === inc.assigned_unit);
    if (unit) await _fetchAndDrawRoute(unit, inc);
  }
  return inc;
}

async function _syncUnits() {
  try {
    const data = await api.getUnits();
    data.forEach(s => {
      const l = units.find(u => u.id === s.id);
      if (l) { l.status = s.status; l.assigned_incident = s.assigned_incident; updateUnitMarker(l); }
    });
    renderUnitsPanel();
  } catch {}
}

async function _fetchAndDrawRoute(unit, inc) {
  const key = `${unit.id}-${inc.id}`;
  try {
    let coords;
    if (isOnline()) {
      const r = await api.getRoute(unit.lat, unit.lng, inc.lat, inc.lng);
      coords = r.coordinates;
    } else {
      const url = `https://router.project-osrm.org/route/v1/driving/${unit.lng},${unit.lat};${inc.lng},${inc.lat}?overview=full&geometries=geojson`;
      const d = await (await fetch(url)).json();
      coords = d.routes?.[0]?.geometry.coordinates.map(c=>[c[1],c[0]]) || [[unit.lat,unit.lng],[inc.lat,inc.lng]];
    }
    drawRoute(key, coords, unit.type);
  } catch {
    drawRoute(key, [[unit.lat,unit.lng],[inc.lat,inc.lng]], unit.type);
  }
}

// ── Local dispatch (offline) ──────────────────────────────────────────────────
const PREF_TYPES = { fire:'fire', medical:'ambulance', accident:'ambulance', flood:'police', crime:'police', building:'fire', gas:'fire' };

function _localDispatch(data) {
  const now = new Date();
  const inc = {
    id: `L${String(idCounter++).padStart(3,'0')}`,
    type: data.type, severity: data.severity,
    lat: data.lat, lng: data.lng,
    location_name: data.locationName || data.location_name || '',
    description: data.desc || data.description || '',
    status: 'pending', assigned_unit: null,
    created_at: now.toISOString(), timeStr: now.toLocaleTimeString('en-IN',{hour12:false}),
    eta_minutes: null, route_distance_km: null,
  };

  const pref  = PREF_TYPES[inc.type] || 'police';
  const avail = units.filter(u => u.status === 'available');
  if (!avail.length) { addLog(`No units available for #${inc.id} — queued PENDING`, 'warn'); toast('No units available — incident queued', 'err'); return inc; }

  const pool   = avail.filter(u => u.type === pref).length ? avail.filter(u => u.type === pref) : avail;
  const unit   = pool.sort((a,b) => _hav(a.lat,a.lng,inc.lat,inc.lng) - _hav(b.lat,b.lng,inc.lat,inc.lng))[0];
  const dist   = _hav(unit.lat,unit.lng,inc.lat,inc.lng);
  const eta    = (dist/40)*60;

  unit.status = 'dispatched'; unit.assigned_incident = inc.id;
  inc.status = 'dispatched'; inc.assigned_unit = unit.id;
  inc.eta_minutes = eta; inc.route_distance_km = dist;

  updateUnitMarker(unit);
  renderUnitsPanel();
  addLog(`Dispatched ${unit.id} → #${inc.id} | ${dist.toFixed(1)} km | ETA ${eta.toFixed(0)} min`, 'ok');
  toast(`${unit.id} dispatched → ${cap(inc.type)} @ ${inc.location_name}`, 'ok');
  return inc;
}

// ── Resolve incident ──────────────────────────────────────────────────────────
export async function resolveIncident(id) {
  const inc = incidents.find(i => i.id === id);
  if (!inc || inc.status === 'resolved') return;
  if (isOnline()) { try { await api.resolveIncident(id); } catch {} }

  inc.status = 'resolved';
  resolvedCount++;

  const unit = inc.assigned_unit ? units.find(u => u.id === inc.assigned_unit) : null;
  if (unit) {
    unit.status = 'available'; unit.assigned_incident = null;
    unit.lat += (Math.random()-.5)*.02; unit.lng += (Math.random()-.5)*.02;
    updateUnitMarker(unit);
  }

  clearRoutesForIncident(id);
  removeIncidentMarker(id);
  renderIncidentsList();
  renderUnitsPanel();
  updateStats();
  addLog(`Incident #${id} resolved.${unit?` ${unit.id} returning to patrol.`:''}`, 'ok');
  toast(`Incident #${id} resolved ✓`, 'ok');
}

export function resolveOldest() {
  const oldest = incidents.find(i => i.status !== 'resolved');
  if (oldest) resolveIncident(oldest.id);
}

export async function clearAll() {
  incidents.forEach(inc => { removeIncidentMarker(inc.id); clearRoutesForIncident(inc.id); });
  incidents.length = 0;
  resolvedCount = 0;
  units.forEach(u => { u.status = 'available'; u.assigned_incident = null; updateUnitMarker(u); });
  renderUnitsPanel(); renderIncidentsList(); updateStats();
  addLog('System cleared. All units available.', 'info');
  toast('System cleared — all units available', 'ok');
}

// ─────────────────────────────────────────────────────────────────────────────
// ★ REPLANNING ENGINE
// ─────────────────────────────────────────────────────────────────────────────

const OBS_LABELS = {
  road_blocked:'🚧 Road Blocked', traffic_jam:'🚦 Traffic Jam',
  bridge_closed:'🌉 Bridge Closed', flood_water:'🌊 Road Flooded',
  unit_breakdown:'🔧 Unit Breakdown', hostile_crowd:'⚠️ Hostile Crowd',
};

// ── Open/close the replan modal ───────────────────────────────────────────────
export function openReplanPanel(incidentId) {
  const inc = incidents.find(i => i.id === incidentId);
  if (!inc) return;

  const el = id => document.getElementById(id);
  el('rp-incident-id').textContent = `#${inc.id}`;
  el('rp-unit-id').textContent     = inc.assigned_unit || '—';
  el('rp-inc-id-hidden').value     = inc.id;
  el('rp-unit-id-hidden').value    = inc.assigned_unit || '';
  el('rp-obs-lat').value           = '';
  el('rp-obs-lng').value           = '';
  el('rp-unit-lat').value          = inc.lat.toFixed(5);
  el('rp-unit-lng').value          = inc.lng.toFixed(5);
  el('rp-description').value       = '';
  el('rp-geocode-result').style.display = 'none';
  el('obs-pin-hint').classList.remove('visible');
  el('replan-panel').style.display = 'flex';
}

export function closeReplanPanel() {
  document.getElementById('replan-panel').style.display = 'none';
  if (obsPinActive) _cancelObsPin();
}

// ── Obstruction pin mode ──────────────────────────────────────────────────────
export function startObsPin() {
  obsPinActive = true;
  document.getElementById('obs-pin-btn').classList.add('active');
  document.getElementById('obs-pin-hint').classList.add('visible');
  enablePinMode((lat, lng) => {
    document.getElementById('rp-obs-lat').value = lat.toFixed(5);
    document.getElementById('rp-obs-lng').value = lng.toFixed(5);
    const res = document.getElementById('rp-geocode-result');
    res.textContent = `📍 Obstruction pinned: (${lat.toFixed(4)}, ${lng.toFixed(4)})`;
    res.style.display = 'block';
    _cancelObsPin();
  });
}

function _cancelObsPin() {
  obsPinActive = false;
  const btn = document.getElementById('obs-pin-btn');
  if (btn) btn.classList.remove('active');
  const hint = document.getElementById('obs-pin-hint');
  if (hint) hint.classList.remove('visible');
  disablePinMode();
}

// ── Submit obstruction from modal ─────────────────────────────────────────────
export async function submitObstruction() {
  const g    = id => document.getElementById(id);
  const obsLat = parseFloat(g('rp-obs-lat').value);
  const obsLng = parseFloat(g('rp-obs-lng').value);

  if (isNaN(obsLat) || isNaN(obsLng)) {
    toast('Pin the obstruction location on the map first', 'warn'); return;
  }

  const payload = {
    incident_id:      g('rp-inc-id-hidden').value,
    unit_id:          g('rp-unit-id-hidden').value,
    obstruction_type: g('rp-obs-type').value,
    obstruction_lat:  obsLat,
    obstruction_lng:  obsLng,
    current_unit_lat: parseFloat(g('rp-unit-lat').value),
    current_unit_lng: parseFloat(g('rp-unit-lng').value),
    description:      g('rp-description').value || '',
  };

  closeReplanPanel();
  await _executeReplan(payload);
}

// ── Trigger from incident list buttons ────────────────────────────────────────
export async function triggerUnitBreakdown(incidentId) {
  const inc = incidents.find(i => i.id === incidentId);
  if (!inc || !inc.assigned_unit) return;
  const unit = units.find(u => u.id === inc.assigned_unit);
  toast(`🔧 ${inc.assigned_unit} broke down — finding replacement...`, 'err');
  await _executeReplan({
    incident_id: incidentId, unit_id: inc.assigned_unit,
    obstruction_type: 'unit_breakdown',
    obstruction_lat: unit ? unit.lat : inc.lat,
    obstruction_lng: unit ? unit.lng : inc.lng,
    current_unit_lat: unit ? unit.lat : inc.lat,
    current_unit_lng: unit ? unit.lng : inc.lng,
    description: 'Unit mechanical failure',
  });
}

export async function triggerManualReplan(incidentId) {
  const inc  = incidents.find(i => i.id === incidentId);
  const unit = units.find(u => u.id === inc?.assigned_unit);
  if (!inc || !unit) { toast('No active unit for this incident', 'warn'); return; }
  toast(`🔄 Recalculating route for ${unit.id}...`, 'ok');
  await _executeReplan({
    incident_id: incidentId, unit_id: unit.id,
    obstruction_type: 'road_blocked',
    obstruction_lat: (unit.lat + inc.lat) / 2,
    obstruction_lng: (unit.lng + inc.lng) / 2,
    current_unit_lat: unit.lat, current_unit_lng: unit.lng,
    description: 'Manual replan by dispatcher',
  });
}

// ── Core replan executor ──────────────────────────────────────────────────────
async function _executeReplan(payload) {
  const label = OBS_LABELS[payload.obstruction_type] || payload.obstruction_type;
  addLog(`⚠ OBSTRUCTION: ${label} reported by ${payload.unit_id} on route to #${payload.incident_id} — replanning`, 'warn');

  // Drop obstruction marker immediately
  const obsKey = `obs-${payload.incident_id}-${Date.now()}`;
  placeObstructionMarker(obsKey, payload.obstruction_lat, payload.obstruction_lng, payload.obstruction_type);

  let result;
  if (isOnline()) {
    try {
      result = await api.reportObstruction(payload.incident_id, payload);
    } catch(e) {
      addLog(`Backend replan error: ${e.message} — local fallback`, 'warn');
      result = await _localReplan(payload);
    }
  } else {
    result = await _localReplan(payload);
  }

  await _applyReplanResult(result);
}

// ── Local replan (offline) ────────────────────────────────────────────────────
async function _localReplan(payload) {
  const inc  = incidents.find(i => i.id === payload.incident_id);
  const unit = units.find(u => u.id === payload.unit_id);
  if (!inc || !unit) return { success: false, reason: 'Incident or unit not found' };

  // Unit breakdown → reassign to another unit
  if (payload.obstruction_type === 'unit_breakdown') {
    const avail = units.filter(u => u.status === 'available' && u.id !== unit.id);
    if (!avail.length) return { success: false, reason: 'No replacement units available' };

    const replacement = avail.sort((a,b) =>
      _hav(a.lat,a.lng,inc.lat,inc.lng) - _hav(b.lat,b.lng,inc.lat,inc.lng)
    )[0];
    const dist = _hav(replacement.lat, replacement.lng, inc.lat, inc.lng);
    const eta  = (dist/40)*60;

    unit.status = 'available'; unit.assigned_incident = null;
    replacement.status = 'dispatched'; replacement.assigned_incident = inc.id;
    inc.assigned_unit = replacement.id; inc.eta_minutes = eta;

    let coords = [[replacement.lat,replacement.lng],[inc.lat,inc.lng]];
    try {
      const r = await fetch(`https://router.project-osrm.org/route/v1/driving/${replacement.lng},${replacement.lat};${inc.lng},${inc.lat}?overview=full&geometries=geojson`);
      const d = await r.json();
      if (d.routes?.[0]) coords = d.routes[0].geometry.coordinates.map(c=>[c[1],c[0]]);
    } catch {}

    return {
      success: true, trigger: 'unit_unavailable',
      incident_id: inc.id, old_unit_id: unit.id, new_unit_id: replacement.id,
      new_route: coords, new_eta_min: eta, new_dist_km: dist,
      reason: `${unit.id} breakdown — reassigned to ${replacement.id}`,
      warnings: [],
    };
  }

  // Same unit — reroute from current position
  const dist = _hav(payload.current_unit_lat, payload.current_unit_lng, inc.lat, inc.lng);
  const eta  = (dist/30)*60; // slower speed (detour)
  inc.eta_minutes = eta; inc.route_distance_km = dist;

  let coords = [[payload.current_unit_lat, payload.current_unit_lng],[inc.lat,inc.lng]];
  try {
    const r = await fetch(`https://router.project-osrm.org/route/v1/driving/${payload.current_unit_lng},${payload.current_unit_lat};${inc.lng},${inc.lat}?overview=full&geometries=geojson`);
    const d = await r.json();
    if (d.routes?.[0]) coords = d.routes[0].geometry.coordinates.map(c=>[c[1],c[0]]);
  } catch {}

  return {
    success: true, trigger: 'obstruction',
    incident_id: inc.id, old_unit_id: unit.id, new_unit_id: unit.id,
    new_route: coords, new_eta_min: eta, new_dist_km: dist,
    reason: `${payload.obstruction_type.replace(/_/g,' ')} — alternate route computed from current position`,
    warnings: coords.length === 2 ? ['OSRM unavailable — straight-line fallback'] : [],
  };
}

// ── Apply result to state + map ───────────────────────────────────────────────
async function _applyReplanResult(result) {
  if (!result?.success) {
    addLog(`Replan failed: ${result?.reason || 'unknown error'}`, 'error');
    toast(`Replan failed — ${result?.reason || 'no units available'}`, 'err');
    return;
  }

  const inc      = incidents.find(i => i.id === result.incident_id);
  const isSwap   = result.old_unit_id !== result.new_unit_id;
  const routeKey = `${result.new_unit_id}-${result.incident_id}`;

  if (isSwap) {
    const oldUnit = units.find(u => u.id === result.old_unit_id);
    const newUnit = units.find(u => u.id === result.new_unit_id);
    if (oldUnit) { oldUnit.status = 'available'; oldUnit.assigned_incident = null; updateUnitMarker(oldUnit); }
    if (newUnit) { newUnit.status = 'dispatched'; newUnit.assigned_incident = inc?.id || ''; updateUnitMarker(newUnit); }
    if (inc) inc.assigned_unit = result.new_unit_id;
    clearRoutesForIncident(result.incident_id);
    addLog(`Unit reassigned: ${result.old_unit_id} → ${result.new_unit_id} | ETA ${result.new_eta_min?.toFixed(0)} min`, 'ok');
    toast(`Reassigned → ${result.new_unit_id} | ETA ~${result.new_eta_min?.toFixed(0)} min`, 'ok');
  } else {
    addLog(`🔄 Rerouted ${result.new_unit_id} → #${result.incident_id} | New ETA: ${result.new_eta_min?.toFixed(0)} min | ${result.reason}`, 'ok');
    toast(`Route updated — New ETA: ${result.new_eta_min?.toFixed(0)} min`, 'ok');
  }

  if (inc && result.new_eta_min) inc.eta_minutes = result.new_eta_min;
  if (inc && result.new_dist_km) inc.route_distance_km = result.new_dist_km;

  if (result.new_route?.length > 1) {
    const newUnit = units.find(u => u.id === result.new_unit_id);
    animateReroute(routeKey, result.new_route, newUnit?.type || 'police');
  }

  if (result.warnings?.length) result.warnings.forEach(w => addLog(w, 'warn'));

  renderUnitsPanel();
  renderIncidentsList();
  updateStats();
}

// ── Demo scenarios ────────────────────────────────────────────────────────────
const DEMO_DATA = [
  { type:'fire',     severity:'critical', lat:28.6315, lng:77.2167, locationName:'Connaught Place',  desc:'Large commercial building fire' },
  { type:'medical',  severity:'high',     lat:28.5705, lng:77.2429, locationName:'Lajpat Nagar',     desc:'Multiple cardiac cases at market' },
  { type:'accident', severity:'high',     lat:28.6562, lng:77.2410, locationName:'Kashmere Gate',    desc:'Multi-vehicle collision on NH44' },
  { type:'flood',    severity:'medium',   lat:28.6200, lng:77.0500, locationName:'Dwarka Sector 21', desc:'Waterlogging blocking roads' },
  { type:'crime',    severity:'high',     lat:28.6800, lng:77.2200, locationName:'Rohini Sector 7',  desc:'Armed robbery in progress' },
  { type:'building', severity:'critical', lat:28.6000, lng:77.3500, locationName:'Mayur Vihar',      desc:'Partial collapse of residential building' },
  { type:'gas',      severity:'critical', lat:28.6400, lng:77.1200, locationName:'Janakpuri',        desc:'Industrial gas pipeline rupture' },
  { type:'fire',     severity:'high',     lat:28.6900, lng:77.1600, locationName:'Pitampura',        desc:'Electrical fire in market' },
  { type:'medical',  severity:'critical', lat:28.5300, lng:77.2700, locationName:'Badarpur',         desc:'Mass food poisoning at school' },
  { type:'accident', severity:'medium',   lat:28.6100, lng:77.3800, locationName:'Noida Sector 18',  desc:'2-vehicle crash, minor injuries' },
];

export async function runDemo(scenario) {
  if (isOnline()) {
    try {
      const res = await api.runDemo(scenario);
      for (const inc of res.incidents) {
        incidents.push(inc);
        placeIncidentMarker(inc, selectIncident);
        if (inc.assigned_unit) {
          const unit = units.find(u => u.id === inc.assigned_unit);
          if (unit) await _fetchAndDrawRoute(unit, inc);
        }
      }
      await _syncUnits();
      renderIncidentsList(); updateStats();
      toast(`Demo "${scenario}" — ${res.incidents_created} incidents created`, 'warn');
      return;
    } catch {}
  }

  if (scenario === 'random') {
    await addIncident(DEMO_DATA[Math.floor(Math.random()*DEMO_DATA.length)]);
  } else if (scenario === 'multi') {
    const sample = [...DEMO_DATA].sort(()=>Math.random()-.5).slice(0,5);
    for (let i=0; i<sample.length; i++) setTimeout(() => addIncident(sample[i]), i*700);
    toast('MASS CASUALTY EVENT — 5 incidents incoming!', 'err');
  } else if (scenario === 'fire_spread') {
    const base = DEMO_DATA.find(d=>d.type==='fire');
    await addIncident(base);
    setTimeout(()=>addIncident({...base, lat:base.lat+0.015, lng:base.lng+0.012, locationName:base.locationName+' — Block B', desc:'Spread to adjacent block'}),1200);
    setTimeout(()=>addIncident({...base, lat:base.lat-0.008, lng:base.lng+0.020, locationName:base.locationName+' — Block C', severity:'high', desc:'Smoke in third building'}),2400);
    toast('Fire spreading — 3 locations affected!', 'err');
  } else if (scenario === 'flood') {
    const d = DEMO_DATA.find(d=>d.type==='flood');
    await addIncident(d);
    setTimeout(()=>addIncident({...d, lat:28.5950, lng:77.0650, locationName:'Dwarka Expressway', desc:'Rising water, vehicles stranded'}),1500);
    toast('Flood emergency — multiple areas', 'warn');
  } else if (scenario === 'accident_chain') {
    const base = DEMO_DATA.find(d=>d.type==='accident');
    await addIncident({...base, severity:'critical', desc:'Pile-up — multiple casualties'});
    setTimeout(()=>addIncident({...base, lat:base.lat+0.010, lng:base.lng-0.008, locationName:'NH44 Km 12', desc:'Secondary collision'}),1000);
    setTimeout(()=>addIncident({type:'medical', severity:'critical', lat:base.lat+0.005, lng:base.lng+0.005, locationName:'NH44 Km 11', desc:'Critical injuries'}),2000);
    toast('Highway pile-up — chain collision!', 'err');
  }
}

// ── Geocoding ─────────────────────────────────────────────────────────────────
export async function geocodeQuery(q) {
  const query = /^\d{6}$/.test(q) ? q+', India' : q+', India';
  const r = await fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=json&limit=1&countrycodes=in`);
  const d = await r.json();
  if (!d.length) throw new Error('Location not found');
  return { lat: parseFloat(d[0].lat), lng: parseFloat(d[0].lon), name: d[0].display_name.split(',').slice(0,2).join(', ') };
}

// ── Haversine ────────────────────────────────────────────────────────────────
function _hav(lat1,lng1,lat2,lng2) {
  const R=6371, dLat=(lat2-lat1)*Math.PI/180, dLng=(lng2-lng1)*Math.PI/180;
  const a=Math.sin(dLat/2)**2+Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLng/2)**2;
  return R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
}

function cap(s) { return s ? s.charAt(0).toUpperCase()+s.slice(1) : s; }
function fmtTime(iso) { try { return new Date(iso).toLocaleTimeString('en-IN',{hour12:false,hour:'2-digit',minute:'2-digit'}); } catch { return '--:--'; } }
