import os
import asyncio
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

OUTPUT_BASE = os.path.join(os.path.dirname(__file__), "output")
DB_PATH = os.path.join(os.path.dirname(__file__), "leads.db")

# ── Database ──────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            address TEXT,
            status TEXT,
            landing_url TEXT,
            finance_json TEXT,
            lob_id TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT,
            first_name TEXT,
            last_name TEXT,
            phone TEXT,
            email TEXT,
            call_time TEXT,
            budget TEXT,
            notes TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    Path(OUTPUT_BASE).mkdir(exist_ok=True)
    yield


app = FastAPI(lifespan=lifespan, title="Pool AI System")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/output", StaticFiles(directory=OUTPUT_BASE), name="output")


# ── UI ────────────────────────────────────────────────────────────────────────

UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pool AI System — TAMGO</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0a0f1e; color: #fff; min-height: 100vh; }
  .header { padding: 24px 32px; border-bottom: 1px solid rgba(255,255,255,0.08); display: flex; align-items: center; gap: 12px; }
  .logo { font-size: 20px; font-weight: 800; color: #00b4ff; }
  .logo span { color: #fff; }
  .badge { background: rgba(0,180,255,0.15); border: 1px solid rgba(0,180,255,0.3); color: #00b4ff; padding: 3px 10px; border-radius: 20px; font-size: 12px; }
  .main { max-width: 800px; margin: 60px auto; padding: 0 24px; }
  h1 { font-size: 42px; font-weight: 800; line-height: 1.1; margin-bottom: 12px; }
  h1 span { color: #00b4ff; }
  .sub { color: rgba(255,255,255,0.5); font-size: 16px; margin-bottom: 48px; }
  .input-row { display: flex; gap: 12px; margin-bottom: 20px; }
  .addr-input { flex: 1; background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.15); border-radius: 14px; color: #fff; padding: 16px 20px; font-size: 16px; }
  .addr-input:focus { outline: none; border-color: #00b4ff; background: rgba(0,180,255,0.08); }
  .send-toggle { display: flex; align-items: center; gap: 8px; color: rgba(255,255,255,0.6); font-size: 14px; margin-bottom: 24px; }
  .send-toggle input { width: 18px; height: 18px; cursor: pointer; }
  .go-btn { background: linear-gradient(135deg, #00b4ff, #0066ff); color: #fff; font-size: 17px; font-weight: 700; padding: 16px 36px; border: none; border-radius: 14px; cursor: pointer; white-space: nowrap; transition: opacity 0.2s; }
  .go-btn:hover { opacity: 0.9; }
  .go-btn:disabled { opacity: 0.5; cursor: not-allowed; }

  .progress-box { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 24px; margin-top: 32px; display: none; }
  .progress-title { font-size: 14px; color: rgba(255,255,255,0.5); margin-bottom: 16px; text-transform: uppercase; letter-spacing: 1px; }
  .step { display: flex; align-items: flex-start; gap: 12px; padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
  .step:last-child { border-bottom: none; }
  .step-icon { width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; flex-shrink: 0; background: rgba(255,255,255,0.1); }
  .step-icon.done { background: rgba(0,255,100,0.2); }
  .step-icon.active { background: rgba(0,180,255,0.2); animation: pulse 1.5s infinite; }
  .step-icon.error { background: rgba(255,60,60,0.2); }
  @keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.5 } }
  .step-text { flex: 1; }
  .step-name { font-weight: 600; font-size: 14px; }
  .step-msg { font-size: 13px; color: rgba(255,255,255,0.5); margin-top: 2px; }

  .result-box { background: linear-gradient(135deg, rgba(0,100,255,0.1), rgba(0,180,255,0.05)); border: 1px solid rgba(0,180,255,0.3); border-radius: 16px; padding: 32px; margin-top: 24px; display: none; }
  .result-title { font-size: 22px; font-weight: 800; margin-bottom: 20px; }
  .result-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 600px) { .result-grid { grid-template-columns: 1fr; } }
  .result-card { background: rgba(255,255,255,0.05); border-radius: 12px; padding: 16px; }
  .rc-label { font-size: 12px; color: rgba(255,255,255,0.5); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
  .rc-value { font-size: 15px; font-weight: 600; }
  .rc-value a { color: #00b4ff; text-decoration: none; }
  .rc-value a:hover { text-decoration: underline; }
  .render-preview { width: 100%; border-radius: 12px; margin-top: 20px; }
  .postcard-preview { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 16px; }
  .postcard-preview img { width: 100%; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1); }

  .leads-section { margin-top: 60px; }
  .leads-title { font-size: 24px; font-weight: 800; margin-bottom: 20px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 12px 16px; background: rgba(255,255,255,0.05); color: rgba(255,255,255,0.5); font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
  td { padding: 12px 16px; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 14px; }
  tr:hover td { background: rgba(255,255,255,0.02); }
  .status-badge { padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
  .status-complete { background: rgba(0,255,100,0.15); color: #00ff9d; }
  .status-running { background: rgba(0,180,255,0.15); color: #00b4ff; }
  .status-error { background: rgba(255,60,60,0.15); color: #ff6060; }
</style>
</head>
<body>
<div class="header">
  <div class="logo">Pool<span>AI</span></div>
  <div class="badge">by TAMGO AI</div>
</div>

<div class="main">
  <h1>Drop a <span>Pool</span><br>on Any House.</h1>
  <p class="sub">Enter an address → AI renders the pool → personalized landing page → physical postcard mailed automatically.</p>

  <div class="input-row">
    <input id="addrInput" class="addr-input" type="text" placeholder="12249 Appian Dr, Rancho Cucamonga CA 91739" value="12249 Appian Dr, Rancho Cucamonga CA 91739">
    <button id="goBtn" class="go-btn" onclick="runPipeline()">Generate →</button>
  </div>
  <label class="send-toggle">
    <input type="checkbox" id="sendPostcard">
    Mail physical postcard via Lob (requires Lob API key)
  </label>

  <div id="progressBox" class="progress-box">
    <div class="progress-title">Pipeline Progress</div>
    <div id="steps"></div>
  </div>

  <div id="resultBox" class="result-box">
    <div class="result-title">🎉 Done! Here's your lead.</div>
    <div id="resultContent"></div>
  </div>

  <div class="leads-section">
    <div class="leads-title">Recent Jobs</div>
    <table id="jobsTable">
      <thead><tr><th>Job ID</th><th>Address</th><th>Status</th><th>Landing Page</th><th>Date</th></tr></thead>
      <tbody id="jobsBody"></tbody>
    </table>
  </div>
</div>

<script>
const STEP_DEFS = [
  {key: 'geocode', label: 'Geocode', icon: '📍'},
  {key: 'images', label: 'Satellite + Street View', icon: '🛰️'},
  {key: 'analysis', label: 'AI Analysis', icon: '🧠'},
  {key: 'render', label: 'Pool Render (Nano Banana)', icon: '🏊'},
  {key: 'finance', label: 'Finance Estimate', icon: '💰'},
  {key: 'video', label: 'Cinematic Video', icon: '🎬'},
  {key: 'landing', label: 'Landing Page', icon: '🌐'},
  {key: 'qr', label: 'QR Code', icon: '📲'},
  {key: 'postcard', label: 'Postcard Design', icon: '📮'},
  {key: 'mail', label: 'Lob Mail', icon: '✉️'},
];

let stepStates = {};

function initSteps() {
  stepStates = {};
  const el = document.getElementById('steps');
  el.innerHTML = STEP_DEFS.map(s => `
    <div class="step" id="step_${s.key}">
      <div class="step-icon" id="icon_${s.key}">${s.icon}</div>
      <div class="step-text">
        <div class="step-name">${s.label}</div>
        <div class="step-msg" id="msg_${s.key}">Waiting...</div>
      </div>
    </div>
  `).join('');
}

function updateStep(key, msg, state) {
  const icon = document.getElementById('icon_' + key);
  const msgEl = document.getElementById('msg_' + key);
  if (!icon) return;
  icon.className = 'step-icon ' + state;
  if (state === 'done') icon.textContent = '✅';
  else if (state === 'error') icon.textContent = '❌';
  else if (state === 'active') icon.textContent = STEP_DEFS.find(s=>s.key===key)?.icon || '⏳';
  if (msgEl) msgEl.textContent = msg;
}

async function runPipeline() {
  const address = document.getElementById('addrInput').value.trim();
  const sendPostcard = document.getElementById('sendPostcard').checked;
  if (!address) return;

  document.getElementById('goBtn').disabled = true;
  document.getElementById('progressBox').style.display = 'block';
  document.getElementById('resultBox').style.display = 'none';
  initSteps();

  try {
    const resp = await fetch('/api/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({address, send_postcard: sendPostcard})
    });
    const {job_id} = await resp.json();
    pollJob(job_id);
  } catch(e) {
    alert('Error: ' + e.message);
    document.getElementById('goBtn').disabled = false;
  }
}

function pollJob(job_id) {
  const interval = setInterval(async () => {
    const r = await fetch('/api/job/' + job_id);
    const data = await r.json();
    if (data.log) {
      data.log.forEach(({step, msg, state}) => updateStep(step, msg, state));
    }
    if (data.status === 'complete' || data.status === 'error' || data.status === 'skipped_has_pool') {
      clearInterval(interval);
      document.getElementById('goBtn').disabled = false;
      if (data.status === 'complete') showResult(data);
      loadJobs();
    }
  }, 1500);
}

function showResult(data) {
  const box = document.getElementById('resultBox');
  const job = data.job_id;
  const finance = data.finance || {};
  const landing = data.landing_url || '';
  box.style.display = 'block';
  document.getElementById('resultContent').innerHTML = `
    <div class="result-grid">
      <div class="result-card"><div class="rc-label">Job ID</div><div class="rc-value">${job}</div></div>
      <div class="result-card"><div class="rc-label">Address</div><div class="rc-value">${data.address}</div></div>
      <div class="result-card"><div class="rc-label">Estimate Range</div><div class="rc-value">$${(finance.price_low||0).toLocaleString()} – $${(finance.price_high||0).toLocaleString()}</div></div>
      <div class="result-card"><div class="rc-label">Monthly Payment</div><div class="rc-value">From $${finance.monthly_payment_15yr||0}/mo</div></div>
      <div class="result-card" style="grid-column:1/-1"><div class="rc-label">Landing Page</div><div class="rc-value"><a href="${landing}" target="_blank">${landing} →</a></div></div>
    </div>
    <img src="/output/${job}/render.jpg" class="render-preview" onerror="this.style.display='none'">
    <div class="postcard-preview">
      <img src="/output/${job}/postcard_front.jpg" alt="Postcard Front" onerror="this.style.display='none'">
      <img src="/output/${job}/postcard_back.jpg" alt="Postcard Back" onerror="this.style.display='none'">
    </div>
  `;
}

async function loadJobs() {
  const r = await fetch('/api/jobs');
  const jobs = await r.json();
  document.getElementById('jobsBody').innerHTML = jobs.map(j => `
    <tr>
      <td><code>${j.job_id}</code></td>
      <td>${j.address}</td>
      <td><span class="status-badge status-${j.status}">${j.status}</span></td>
      <td>${j.landing_url ? '<a href="' + j.landing_url + '" target="_blank" style="color:#00b4ff">View →</a>' : '—'}</td>
      <td>${j.created_at?.substring(0,16) || ''}</td>
    </tr>
  `).join('');
}

loadJobs();
</script>
</body>
</html>"""

# ── In-memory job log ─────────────────────────────────────────────────────────
job_logs: dict[str, list] = {}
job_data: dict[str, dict] = {}


@app.get("/", response_class=HTMLResponse)
async def index():
    return UI_HTML


@app.post("/api/generate")
async def generate(request: Request):
    body = await request.json()
    address = body.get("address", "").strip()
    send_postcard = body.get("send_postcard", False)
    if not address:
        raise HTTPException(400, "address required")

    from orchestrator import PoolOrchestrator
    job_id_holder = {}

    def progress(step: str, msg: str):
        jid = job_id_holder.get("id")
        if not jid:
            return
        state = "error" if step == "error" else ("done" if not msg.startswith("⚠") else "done")
        # mark previous steps done, current active
        log = job_logs.setdefault(jid, [])
        existing = next((l for l in log if l["step"] == step), None)
        if existing:
            existing["msg"] = msg
            existing["state"] = state
        else:
            log.append({"step": step, "msg": msg, "state": "active"})
        # mark as done once we move past it
        for l in log[:-1]:
            if l["state"] == "active":
                l["state"] = "done"

    async def run_pipeline():
        orch = PoolOrchestrator(progress_callback=progress)
        try:
            result = await orch.run(address, send_postcard=send_postcard)
        except Exception as e:
            result = {"status": "error", "error": str(e)}
        jid = job_id_holder["id"]
        job_data[jid] = result
        # save to DB
        conn = sqlite3.connect(DB_PATH)
        import json
        conn.execute(
            "INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?)",
            (jid, address, result.get("status"), result.get("landing_url"),
             json.dumps(result.get("steps", {}).get("finance")), result.get("steps", {}).get("lob"),
             datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()
        # mark all steps done
        for l in job_logs.get(jid, []):
            if l["state"] == "active":
                l["state"] = "done" if result["status"] != "error" else "error"

    # start pipeline in background, get job_id from orchestrator
    import uuid
    job_id = str(uuid.uuid4())[:8]
    job_id_holder["id"] = job_id
    job_logs[job_id] = []
    job_data[job_id] = {"status": "running", "address": address}
    asyncio.create_task(run_pipeline())
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
async def get_job(job_id: str):
    data = job_data.get(job_id, {})
    log = job_logs.get(job_id, [])
    result = dict(data)
    result["log"] = log
    if "steps" in result and "finance" in result["steps"]:
        result["finance"] = result["steps"]["finance"]
    return result


@app.get("/api/jobs")
async def list_jobs():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/lead")
async def save_lead(request: Request):
    data = await request.json()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO leads (job_id,first_name,last_name,phone,email,call_time,budget,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (data.get("job_id"), data.get("first_name"), data.get("last_name"),
         data.get("phone"), data.get("email"), data.get("call_time"),
         data.get("budget"), data.get("notes"), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/p/{job_id}", response_class=HTMLResponse)
async def landing_page(job_id: str):
    path = Path(f"{OUTPUT_BASE}/{job_id}/landing.html")
    if not path.exists():
        raise HTTPException(404, "Landing page not found")
    return HTMLResponse(content=path.read_text())


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
