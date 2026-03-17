/**
 * app.js — Main controller: bootstrap, UI events, clock, log, toast.
 */

import { initMap, enablePinMode, disablePinMode, panTo, focusUnit as mapFocusUnit } from './map.js';
import {
  initUnits, addIncident,
  resolveIncident as doResolve, resolveOldest, clearAll,
  runDemo, renderIncidentsList, renderUnitsPanel,
  selectIncident as doSelect, geocodeQuery,
  incidents, units,
  openReplanPanel, closeReplanPanel, startObsPin,
  submitObstruction, triggerUnitBreakdown, triggerManualReplan,
} from './dispatch.js';
import { checkHealth, isOnline } from './api.js';

// ── Globals exposed for Leaflet popup onclick + inline HTML buttons ────────────
window.resolveIncident      = (id) => doResolve(id);
window.selectIncident       = (id) => doSelect(id);
window.focusUnit            = (id) => mapFocusUnit(id);
window.openReplanPanel      = (id) => openReplanPanel(id);
window.closeReplanPanel     = ()   => closeReplanPanel();
window.startObsPin          = ()   => startObsPin();
window.submitObstruction    = ()   => submitObstruction();
window.triggerUnitBreakdown = (id) => triggerUnitBreakdown(id);
window.triggerManualReplan  = (id) => triggerManualReplan(id);

const $ = (id) => document.getElementById(id);

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  initMap();
  updateClock();
  setInterval(updateClock, 1000);

  await checkHealth();
  setInterval(checkHealth, 15000);

  await initUnits();
  updateStats();
  addLog('CRC System online. All units operational.', 'ok');
  addLog(`Coverage: Delhi NCR  |  Backend: ${isOnline() ? 'connected' : 'offline (local mode)'}`, 'info');

  // Poll stats from backend when connected
  setInterval(async () => {
    if (isOnline()) {
      try {
        const { api } = await import('./api.js');
        const s = await api.getStats();
        $('stat-active').textContent     = s.active_incidents;
        $('stat-dispatched').textContent = s.dispatched;
        $('stat-units').textContent      = s.units.available;
        $('stat-resolved').textContent   = s.resolved_total;
      } catch {}
    }
  }, 5000);
});

// ── Clock ─────────────────────────────────────────────────────────────────────
function updateClock() {
  $('clock').textContent = new Date().toLocaleTimeString('en-IN', { hour12: false }) + ' IST';
}

// ── Stats ─────────────────────────────────────────────────────────────────────
export function updateStats() {
  const active     = incidents.filter(i => i.status !== 'resolved').length;
  const dispatched = incidents.filter(i => i.status === 'dispatched').length;
  const avail      = units.filter(u => u.status === 'available').length;
  if ($('stat-active'))     $('stat-active').textContent     = active;
  if ($('stat-dispatched')) $('stat-dispatched').textContent = dispatched;
  if ($('stat-units'))      $('stat-units').textContent      = avail;
  import('./dispatch.js').then(m => { if ($('stat-resolved')) $('stat-resolved').textContent = m.resolvedCount; });
}

// ── Log ───────────────────────────────────────────────────────────────────────
export function addLog(msg, level = 'info') {
  const list = $('log-list');
  if (!list) return;
  const now   = new Date().toLocaleTimeString('en-IN', { hour12:false });
  const entry = document.createElement('div');
  entry.className = `log-entry ${level}`;
  entry.innerHTML = `<span class="lt">[${now}]</span><span class="lm">${msg}</span>`;
  list.insertBefore(entry, list.firstChild);
  while (list.children.length > 80) list.removeChild(list.lastChild);
}

// ── Toast ─────────────────────────────────────────────────────────────────────
export function toast(msg, type = 'ok') {
  const c = $('toast-container');
  if (!c) return;
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => {
    t.style.cssText += 'opacity:0;transform:translateX(20px);transition:all 0.3s';
    setTimeout(() => c.contains(t) && c.removeChild(t), 300);
  }, 3500);
}

// ── Form tabs ─────────────────────────────────────────────────────────────────
window.switchTab = (tab) => {
  $('manual-form').style.display = tab === 'manual' ? 'block' : 'none';
  $('demo-form').style.display   = tab === 'demo'   ? 'block' : 'none';
  document.querySelectorAll('.form-tab').forEach((el, i) => {
    el.classList.toggle('active', (i===0&&tab==='manual')||(i===1&&tab==='demo'));
  });
};

// ── Geocode ───────────────────────────────────────────────────────────────────
let pendingLat = null, pendingLng = null, pendingName = null;

window.geocodeLocation = async () => {
  const q = $('inc-location').value.trim();
  if (!q) { toast('Enter a location or 6-digit pincode', 'warn'); return; }
  try {
    const res = await geocodeQuery(q);
    pendingLat = res.lat; pendingLng = res.lng; pendingName = res.name;
    const el = $('geocode-result');
    el.textContent   = `✓ ${res.name} (${res.lat.toFixed(4)}, ${res.lng.toFixed(4)})`;
    el.style.display = 'block';
    panTo(res.lat, res.lng);
    toast(`Location found: ${res.name}`, 'ok');
    addLog(`Geocoded: "${q}" → ${res.name}`, 'info');
  } catch(e) { toast(e.message || 'Location not found', 'warn'); }
};

// ── Pin mode ──────────────────────────────────────────────────────────────────
let pinActive = false;

window.togglePinMode = () => {
  pinActive = !pinActive;
  $('pin-btn').classList.toggle('active', pinActive);
  $('pin-hint').classList.toggle('visible', pinActive);
  if (pinActive) {
    enablePinMode((lat, lng) => {
      pendingLat = lat; pendingLng = lng;
      pendingName = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
      $('geocode-result').textContent   = `📍 Pinned: (${lat.toFixed(4)}, ${lng.toFixed(4)})`;
      $('geocode-result').style.display = 'block';
      $('inc-location').value           = pendingName;
      toast('Location pinned on map', 'ok');
      pinActive = false;
      $('pin-btn').classList.remove('active');
      $('pin-hint').classList.remove('visible');
    });
  } else {
    disablePinMode();
  }
};

// ── Submit incident ───────────────────────────────────────────────────────────
window.submitManual = async () => {
  const type     = $('inc-type').value;
  const severity = $('inc-severity').value;
  const desc     = $('inc-desc').value.trim();
  const locInput = $('inc-location').value.trim();

  if (!locInput && pendingLat === null) { toast('Enter a location or pin it on the map', 'warn'); return; }

  const dispatch = async (lat, lng, name) => {
    await addIncident({ type, severity, desc, lat, lng, locationName: name });
    $('inc-location').value = '';
    $('inc-desc').value     = '';
    $('geocode-result').style.display = 'none';
    pendingLat = pendingLng = pendingName = null;
  };

  if (pendingLat !== null) {
    await dispatch(pendingLat, pendingLng, pendingName || locInput);
  } else {
    try {
      const res = await geocodeQuery(locInput);
      await dispatch(res.lat, res.lng, res.name);
    } catch { toast('Could not geocode location — try the pin tool', 'warn'); }
  }
};

// ── Demo + helpers ────────────────────────────────────────────────────────────
window.runDemo       = async () => { await runDemo($('demo-scenario').value); };
window.resolveOldest = resolveOldest;
window.clearAll      = clearAll;

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    if (pinActive) window.togglePinMode();
    closeReplanPanel();
  }
});
