/**
 * map.js — Leaflet map, markers, animated routes, obstruction markers
 */

export let map;
const routeLayers        = {};  // `${unitId}-${incidentId}` → L.LayerGroup
const incMarkers         = {};  // incidentId → L.Marker
const unitMarkers        = {};  // unitId → L.Marker
const obstructionMarkers = {};  // obsKey → L.Marker

const UNIT_ICONS  = { ambulance: '🚑', fire: '🚒', police: '🚔' };
const INC_ICONS   = { fire: '🔥', medical: '🚑', accident: '💥', flood: '🌊', crime: '🚔', building: '🏚️', gas: '☢️' };
const UNIT_COLORS = { ambulance: '#10b981', fire: '#f03c3c', police: '#3b82f6' };
const OBS_ICONS   = { road_blocked: '🚧', traffic_jam: '🚦', bridge_closed: '🌉', flood_water: '🌊', unit_breakdown: '🔧', hostile_crowd: '⚠️' };
const OBS_LABELS  = { road_blocked: 'Road Blocked', traffic_jam: 'Traffic Jam', bridge_closed: 'Bridge Closed', flood_water: 'Road Flooded', unit_breakdown: 'Unit Breakdown', hostile_crowd: 'Hostile Crowd' };
let pinHandler = null;

// ── Init ──────────────────────────────────────────────────────────────────────
export function initMap() {
  map = L.map('map', { zoomControl: true, attributionControl: false })
    .setView([28.6300, 77.2090], 12);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    subdomains: 'abcd', maxZoom: 19
  }).addTo(map);
  L.control.attribution({ position: 'bottomright', prefix: '© CartoDB © OSM' }).addTo(map);
  return map;
}

// ── Unit markers ──────────────────────────────────────────────────────────────
function buildUnitIcon(type, status) {
  const extra = status === 'dispatched' ? ' dispatched' : '';
  return L.divIcon({
    html: `<div class="unit-marker ${type}${extra}">${UNIT_ICONS[type] || '🚗'}</div>`,
    className: '', iconSize: [28, 28], iconAnchor: [14, 14],
  });
}

export function placeUnitMarker(unit) {
  if (unitMarkers[unit.id]) map.removeLayer(unitMarkers[unit.id]);
  const statusColor = unit.status === 'available' ? 'var(--green)' : unit.status === 'dispatched' ? 'var(--amber)' : 'var(--red)';
  unitMarkers[unit.id] = L.marker([unit.lat, unit.lng], { icon: buildUnitIcon(unit.type, unit.status) })
    .addTo(map)
    .bindPopup(`<div class="popup-title">${UNIT_ICONS[unit.type] || '🚗'} ${unit.name}</div>
<div class="popup-row"><span>Type</span><span>${unit.type.toUpperCase()}</span></div>
<div class="popup-row"><span>Status</span><span style="color:${statusColor}">${unit.status.toUpperCase()}</span></div>
<div class="popup-row"><span>ID</span><span>${unit.id}</span></div>`);
}

export function updateUnitMarker(unit) { placeUnitMarker(unit); }
export function removeUnitMarker(id) { if (unitMarkers[id]) { map.removeLayer(unitMarkers[id]); delete unitMarkers[id]; } }
export function focusUnit(id) { const m = unitMarkers[id]; if (m) { map.panTo(m.getLatLng()); m.openPopup(); } }

// ── Incident markers ──────────────────────────────────────────────────────────
export function buildIncidentPopupHtml(inc) {
  const sevColors = { critical: 'var(--red)', high: 'var(--amber)', medium: 'var(--blue)', low: 'var(--green)' };
  const hasUnit   = inc.assigned_unit && inc.status !== 'resolved';
  return `<div class="popup-title">${INC_ICONS[inc.type] || '🚨'} ${cap(inc.type)} Emergency</div>
<div class="popup-row"><span>Severity</span><span style="color:${sevColors[inc.severity]}">${inc.severity.toUpperCase()}</span></div>
<div class="popup-row"><span>Location</span><span>${inc.location_name || inc.locationName || ''}</span></div>
<div class="popup-row"><span>Status</span><span>${inc.status.toUpperCase()}</span></div>
${inc.assigned_unit ? `<div class="popup-row"><span>Unit</span><span>${inc.assigned_unit}</span></div>` : ''}
${inc.eta_minutes   ? `<div class="popup-row"><span>ETA</span><span>${Number(inc.eta_minutes).toFixed(0)} min</span></div>` : ''}
${inc.description   ? `<div style="font-size:11px;color:var(--text-muted);margin-top:4px;">${inc.description}</div>` : ''}
<div style="display:flex;gap:6px;margin-top:8px;">
  <button class="popup-btn" style="background:var(--red);" onclick="window.resolveIncident('${inc.id}')">✓ Resolved</button>
  ${hasUnit ? `<button class="popup-btn" style="background:var(--amber);color:#0a0e1a;" onclick="window.openReplanPanel('${inc.id}')">🚧 Replan</button>` : ''}
</div>`;
}

export function placeIncidentMarker(inc, onClick) {
  if (incMarkers[inc.id]) map.removeLayer(incMarkers[inc.id]);
  const icon = L.divIcon({
    html: `<div class="inc-marker ${inc.severity}">${INC_ICONS[inc.type] || '🚨'}</div>`,
    className: '', iconSize: [32, 32], iconAnchor: [16, 16],
  });
  incMarkers[inc.id] = L.marker([inc.lat, inc.lng], { icon, zIndexOffset: 1000 })
    .addTo(map)
    .bindPopup(buildIncidentPopupHtml(inc))
    .on('click', () => onClick && onClick(inc.id));
}

export function updateIncidentMarker(inc) {
  if (incMarkers[inc.id]) incMarkers[inc.id].setPopupContent(buildIncidentPopupHtml(inc));
}
export function removeIncidentMarker(id) { if (incMarkers[id]) { map.removeLayer(incMarkers[id]); delete incMarkers[id]; } }
export function focusIncident(id) { const m = incMarkers[id]; if (m) { map.panTo(m.getLatLng()); m.openPopup(); } }

// ── Route drawing ─────────────────────────────────────────────────────────────
export function drawRoute(routeKey, coords, unitType) {
  clearRoute(routeKey);
  const color = UNIT_COLORS[unitType] || '#94a3b8';
  const shadow = L.polyline(coords, { color, weight: 6, opacity: 0.1, smoothFactor: 1 });
  const line   = L.polyline(coords, { color, weight: 3, opacity: 0.9, dashArray: '12, 8', className: 'route-animated', smoothFactor: 1 });
  routeLayers[routeKey] = L.layerGroup([shadow, line]).addTo(map);
  const all = coords.map(c => L.latLng(c[0], c[1]));
  if (all.length) map.fitBounds(L.latLngBounds(all), { padding: [60, 60] });
}

/** Reroute animation: flash amber → fade → draw new cyan-tinted route */
export function animateReroute(routeKey, newCoords, unitType) {
  const color = UNIT_COLORS[unitType] || '#94a3b8';
  // Flash amber on the existing route for 800ms then replace
  if (routeLayers[routeKey]) {
    const layers = routeLayers[routeKey].getLayers ? routeLayers[routeKey].getLayers() : [];
    layers.forEach(l => { if (l.setStyle) l.setStyle({ color: '#f59e0b', weight: 5, opacity: 0.9 }); });
    setTimeout(() => {
      clearRoute(routeKey);
      const glow = L.polyline(newCoords, { color: '#06b6d4', weight: 8, opacity: 0.07, smoothFactor: 1 });
      const line = L.polyline(newCoords, { color, weight: 3, opacity: 1, dashArray: '6, 5', className: 'route-animated', smoothFactor: 1 });
      routeLayers[routeKey] = L.layerGroup([glow, line]).addTo(map);
      const all = newCoords.map(c => L.latLng(c[0], c[1]));
      if (all.length) map.fitBounds(L.latLngBounds(all), { padding: [60, 60] });
    }, 800);
  } else {
    drawRoute(routeKey, newCoords, unitType);
  }
}

export function clearRoute(key) { if (routeLayers[key]) { map.removeLayer(routeLayers[key]); delete routeLayers[key]; } }
export function clearRoutesForIncident(incidentId) { Object.keys(routeLayers).forEach(k => { if (k.endsWith(`-${incidentId}`)) clearRoute(k); }); }

// ── Obstruction markers ───────────────────────────────────────────────────────
export function placeObstructionMarker(key, lat, lng, obType) {
  if (!document.getElementById('obs-pulse-style')) {
    const s = document.createElement('style'); s.id = 'obs-pulse-style';
    s.textContent = '@keyframes obs-pulse{0%,100%{box-shadow:0 0 8px rgba(245,158,11,0.4)}50%{box-shadow:0 0 20px rgba(245,158,11,0.8)}}';
    document.head.appendChild(s);
  }
  const icon = L.divIcon({
    html: `<div style="width:30px;height:30px;border-radius:4px;background:rgba(245,158,11,0.25);border:2px solid #f59e0b;display:flex;align-items:center;justify-content:center;font-size:15px;animation:obs-pulse 1.2s infinite;">${OBS_ICONS[obType] || '⚠️'}</div>`,
    className: '', iconSize: [30, 30], iconAnchor: [15, 15],
  });
  if (obstructionMarkers[key]) map.removeLayer(obstructionMarkers[key]);
  obstructionMarkers[key] = L.marker([lat, lng], { icon, zIndexOffset: 2000 })
    .addTo(map)
    .bindPopup(`<div class="popup-title">⚠️ ${OBS_LABELS[obType] || 'Obstruction'}</div>
<div class="popup-row"><span>Type</span><span>${(obType || '').replace(/_/g,' ').toUpperCase()}</span></div>
<div class="popup-row"><span>Coords</span><span>${lat.toFixed(4)}, ${lng.toFixed(4)}</span></div>`);
}

export function clearObstructionMarker(key) { if (obstructionMarkers[key]) { map.removeLayer(obstructionMarkers[key]); delete obstructionMarkers[key]; } }

// ── Pin mode ──────────────────────────────────────────────────────────────────
export function panTo(lat, lng) { map.panTo([lat, lng]); }

export function enablePinMode(callback) {
  disablePinMode();
  pinHandler = e => {
    disablePinMode();
    callback(e.latlng.lat, e.latlng.lng);
  };
  map.getContainer().style.cursor = 'crosshair';
  map.getPane('markerPane').style.pointerEvents = 'none';
  map.on('click', pinHandler);
}

export function disablePinMode() {
  if (pinHandler) map.off('click', pinHandler);
  pinHandler = null;
  map.getContainer().style.cursor = '';
  map.getPane('markerPane').style.pointerEvents = '';
}

// ── Util ──────────────────────────────────────────────────────────────────────
function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
