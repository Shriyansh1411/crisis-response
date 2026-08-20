# 🚨 Crisis Response Coordinator (CRC)

> Agentic AI-powered emergency dispatch system — QuadCoders Hackathon Project

---

## 📁 Project Structure

```
crisis-response-coordinator/
├── backend/               # FastAPI Python backend
│   ├── main.py            # App entrypoint + all API routes
│   ├── requirements.txt
│   ├── agents/            # Autonomous AI agents
│   │   ├── dispatcher_agent.py   # Classifies & prioritizes incidents
│   │   ├── resource_agent.py     # Finds & assigns nearest unit
│   │   ├── routing_agent.py      # Computes optimal routes via OSRM
│   │   └── replanning_agent.py   # Detects conflicts & re-routes
│   ├── models/            # Pydantic data models
│   │   ├── incident.py
│   │   └── unit.py
│   ├── services/
│   │   ├── dispatch_service.py   # Orchestrates all agents
│   │   └── routing_service.py    # OSRM route fetching
│   └── data/
│       └── units.json            # Seed data for emergency units
└── frontend/              # Pure HTML/CSS/JS (no build step)
    ├── index.html
    ├── css/styles.css
    └── js/
        ├── app.js         # Main controller
        ├── map.js         # Leaflet map + markers + routes
        ├── dispatch.js    # Incident reporting & dispatch logic
        └── api.js         # Backend API calls
```

---

## 🚀 Quick Start

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

API docs available at: `http://localhost:8000/docs`

### Frontend

Just open `frontend/index.html` in your browser — **no build step needed**.

Or serve it with Python:

```bash
cd frontend
python -m http.server 3000
# Open http://localhost:3000
```

> Make sure the backend is running on port 8000 before opening the frontend.

### LangChain configuration

Copy `.env.example` to `.env` and set `OPENAI_API_KEY` to enable model-backed
structured incident analysis. Without a key, the same workflow uses a
deterministic local parser, so the backend remains usable and tests do not call
an external API. LangChain tools only call the existing in-memory dispatch
service; unit selection, distance, availability, and dispatch validation stay
in backend code.

The AI endpoint is `POST /incidents/analyze`:

```json
{
    "description": "Major accident reported on NH-44. Three people are involved and one person has a serious injury. The vehicle is blocking one lane.",
    "location": {"lat": 28.61, "lng": 77.23, "name": "NH-44"}
}
```

---

## ⚙️ Features

| Feature | Description |
|--------|-------------|
| 🤖 Auto Dispatch | AI agent finds nearest available unit and dispatches instantly |
| 🗺️ Live Routing | OSRM-powered shortest path (same engine as OpenStreetMap) |
| 📍 Pin Location | Click map to drop incident pin OR search by pincode/area name |
| 🎭 Demo Scenarios | 5 pre-built scenarios: mass casualty, fire spread, flood, etc. |
| 🔄 Replanning | Detects road blocks & re-routes units dynamically |
| 🔒 Guardrails | Human approval required for mass-evacuation decisions |
| 📡 Real-time Log | Live dispatch activity log with timestamps |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Agents | Rule-based + LangChain-ready architecture |
| Routing | OSRM public API / NetworkX fallback |
| Geocoding | Nominatim (OpenStreetMap) |
| Frontend | Vanilla HTML/CSS/JS |
| Maps | Leaflet.js + CartoDB Dark tiles |
| Data | In-memory store (swap for PostgreSQL in prod) |

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | System health check |
| `GET` | `/units` | List all emergency units |
| `GET` | `/incidents` | List all incidents |
| `POST` | `/incidents` | Report new incident |
| `POST` | `/incidents/{id}/resolve` | Mark incident resolved |
| `POST` | `/incidents/{id}/dispatch` | Manually trigger dispatch |
| `GET` | `/route` | Get route between two coordinates |
| `POST` | `/demo/{scenario}` | Trigger demo scenario |
| `GET` | `/stats` | System statistics |

---

## 👥 Team — QuadCoders

- Hritika Chawla
- Ria Mehta  
- Kritika Madan
- Shriyansh Mishra

---

## 📄 License

MIT
