/**
 * api.js — Backend API client
 * All calls go through here. Falls back to local-only mode if backend is offline.
 */

const API_BASE = 'http://localhost:8000';
let backendOnline = false;

export async function checkHealth() {
  try {
    const r = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
    backendOnline = r.ok;
  } catch {
    backendOnline = false;
  }
  updateBackendStatus(backendOnline);
  return backendOnline;
}

function updateBackendStatus(online) {
  const el = document.getElementById('backend-status');
  if (!el) return;
  el.textContent = online ? '● BACKEND ONLINE' : '○ LOCAL MODE';
  el.className = `backend-status ${online ? 'online' : 'offline'}`;
}

export function isOnline() { return backendOnline; }

async function request(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
    signal: AbortSignal.timeout(8000),
  };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(`${API_BASE}${path}`, opts);
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || r.statusText);
  }
  return r.json();
}

export const api = {
  getStats:          ()           => request('GET',  '/stats'),
  getUnits:          ()           => request('GET',  '/units'),
  getIncidents:      (status)     => request('GET',  `/incidents${status ? `?status=${status}` : ''}`),
  createIncident:    (data)       => request('POST', '/incidents', data),
  resolveIncident:   (id)         => request('POST', `/incidents/${id}/resolve`),
  manualDispatch:    (id)         => request('POST', `/incidents/${id}/dispatch`),
  getRoute:          (fLat,fLng,tLat,tLng) => request('GET', `/route?from_lat=${fLat}&from_lng=${fLng}&to_lat=${tLat}&to_lng=${tLng}`),
  runDemo:           (scenario)   => request('POST', `/demo/${scenario}`),
  getLog:            ()           => request('GET',  '/log?limit=50'),
  reportObstruction: (data)       => request('POST', '/obstructions', data),
  manualReplan:      (id,lat,lng) => request('POST', `/incidents/${id}/replan?current_unit_lat=${lat}&current_unit_lng=${lng}`),
  unitUnavailable:   (id)         => request('POST', `/incidents/${id}/unit-unavailable`),
  getReplanHistory:  ()           => request('GET',  '/replan/history?limit=20'),
  // ── Replanning ──
  reportObstruction: (id, body)   => request('POST', `/incidents/${id}/obstruction`, body),
  manualReplan:      (id, body)   => request('POST', `/incidents/${id}/replan`, body),
  unitBreakdown:     (id)         => request('POST', `/incidents/${id}/unit-breakdown`),
  getReplanHistory:  ()           => request('GET',  '/replan-history'),
  getObstructions:   ()           => request('GET',  '/obstructions'),
};
