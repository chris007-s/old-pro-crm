#!/usr/bin/env python3
"""
Old Pro Construction Services — Mobile Web CRM
Same DB as the desktop app. Access from phone via ngrok or local WiFi.
Usage: python3 old_pro_web.py
"""

from flask import Flask, request, jsonify, render_template_string
import sqlite3, json, re, os
from pathlib import Path
from datetime import date

app = Flask(__name__)
DB_PATH     = Path.home() / ".old_pro_crm.db"
IMAGES_PATH = Path.home() / ".old_pro_crm_images"
IMAGES_PATH.mkdir(exist_ok=True)

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ─── HTML ────────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>Old Pro CRM</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
:root {
  --bg:#121826; --bg2:#1e2535; --bg3:#161e2e; --border:#2d3748;
  --orange:#f97316; --text:#e2e8f0; --muted:#64748b;
  --green:#22c55e; --called-bg:#0e2a1a; --called-fg:#86efac;
}
body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; font-size:14px; }

.header { background:#0e1420; border-bottom:1px solid var(--border); padding:12px 16px; position:sticky; top:0; z-index:100; display:flex; align-items:center; justify-content:space-between; }
.header-title { color:var(--orange); font-weight:800; font-size:16px; letter-spacing:2px; }
.header-sub { color:var(--muted); font-size:10px; letter-spacing:3px; }

.stats { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; padding:12px; }
.stat-card { background:var(--bg2); border-radius:8px; padding:10px 8px; text-align:center; border:1px solid var(--border); }
.stat-val { font-size:22px; font-weight:700; color:#f0f4ff; }
.stat-lbl { font-size:9px; color:var(--muted); margin-top:2px; text-transform:uppercase; letter-spacing:.5px; }

.list-tabs { display:flex; overflow-x:auto; padding:0 12px; gap:8px; background:var(--bg); border-bottom:1px solid var(--border); scrollbar-width:none; }
.list-tabs::-webkit-scrollbar { display:none; }
.tab { flex-shrink:0; padding:10px 14px; color:var(--muted); font-size:12px; font-weight:600; cursor:pointer; border-bottom:2px solid transparent; white-space:nowrap; background:none; border-top:none; border-left:none; border-right:none; }
.tab.active { color:var(--text); border-bottom-color:var(--orange); }

.search-wrap { padding:10px 12px; }
.search-input { width:100%; background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:10px 14px; color:var(--text); font-size:14px; }
.search-input:focus { outline:none; border-color:var(--orange); }

.type-filter { width:calc(100% - 24px); margin:0 12px 10px; background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:10px 14px; color:var(--text); font-size:13px; }

.leads-list { padding:8px 12px; display:flex; flex-direction:column; gap:8px; padding-bottom:80px; }

.lead-card { background:var(--bg2); border:1px solid var(--border); border-radius:10px; padding:12px; cursor:pointer; }
.lead-card.called { background:var(--called-bg); border-color:#1a4a2a; }
.lead-name { font-weight:700; font-size:15px; color:#f0f4ff; }
.lead-card.called .lead-name { color:var(--called-fg); }
.lead-company { color:var(--muted); font-size:12px; margin-top:2px; }
.lead-phone { color:#7ecfff; font-size:16px; font-weight:700; margin-top:6px; }
.lead-card.called .lead-phone { color:var(--called-fg); }
.lead-badges { display:flex; gap:4px; flex-wrap:wrap; margin-top:8px; }
.badge { font-size:10px; padding:2px 8px; border-radius:20px; font-weight:600; white-space:nowrap; }
.badge-Leads      { background:#1e3a5f; color:#7ecfff; }
.badge-Follow-Up  { background:#3a2010; color:#fb923c; }
.badge-Warm       { background:#14532d; color:#4ade80; }
.badge-Won        { background:#3b1f5e; color:#c084fc; }
.badge-Dead       { background:#1f2937; color:#6b7280; }
.badge-type       { background:#1e2535; color:#94a3b8; border:1px solid #2d3748; }
.badge-calls      { background:#1a2235; color:#64748b; }
.badge-due        { background:#3a1a00; color:#fb923c; }
.badge-na         { background:#2a1a1a; color:#f87171; }

.overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,.6); z-index:200; }
.overlay.open { display:block; }
.sheet { position:fixed; bottom:0; left:0; right:0; background:var(--bg3); border-top:1px solid var(--border); border-radius:16px 16px 0 0; z-index:201; max-height:92vh; overflow-y:auto; transform:translateY(100%); transition:transform .25s ease; }
.sheet.open { transform:translateY(0); }
.sheet-handle { width:36px; height:4px; background:var(--border); border-radius:2px; margin:12px auto 0; }
.sheet-content { padding:16px; }
.sheet-name { font-size:20px; font-weight:700; color:#f0f4ff; }
.sheet-phone { font-size:28px; font-weight:900; color:#4ade80; letter-spacing:2px; margin:8px 0; }
.sheet-phone.na { color:#f87171; font-size:16px; font-weight:400; }
.sheet-meta { color:var(--muted); font-size:12px; margin-top:4px; line-height:1.6; }
.sheet-notes { background:var(--bg2); border-radius:8px; padding:10px; margin-top:10px; font-size:12px; color:#94a3b8; line-height:1.6; white-space:pre-wrap; max-height:150px; overflow-y:auto; }
.sheet-notes a { color:#7ecfff; }

.sheet-photo { width:100%; max-height:180px; object-fit:cover; border-radius:8px; margin-top:10px; cursor:pointer; }

.btn-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:12px 0; }
.btn { padding:12px 10px; border:none; border-radius:8px; font-size:13px; font-weight:700; cursor:pointer; text-align:center; }
.btn-orange { background:var(--orange); color:#fff; }
.btn-blue   { background:#1e3a5f; color:#7ecfff; }
.btn-green  { background:#1a3a2a; color:#4ade80; }
.btn-purple { background:#2a1a3a; color:#c084fc; }
.btn-red    { background:#3a0f0f; color:#f87171; }
.btn-gray   { background:var(--bg2); color:var(--text); border:1px solid var(--border); }
.btn:active { opacity:.8; }
.btn-full   { grid-column:1/-1; }

.move-select { width:100%; background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:12px; color:var(--text); font-size:14px; margin:8px 0; }

.modal { display:none; position:fixed; inset:0; z-index:300; background:rgba(0,0,0,.75); align-items:flex-end; }
.modal.open { display:flex; }
.modal-box { background:var(--bg3); border-radius:16px 16px 0 0; padding:20px; width:100%; max-height:85vh; overflow-y:auto; }
.modal-title { font-size:17px; font-weight:700; margin-bottom:14px; }
label { display:block; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.5px; margin:12px 0 4px; }
select, textarea, input[type=date] { width:100%; background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:10px 12px; color:var(--text); font-size:14px; }
select:focus, textarea:focus, input:focus { outline:none; border-color:var(--orange); }
textarea { min-height:80px; resize:vertical; }
.modal-btns { display:flex; gap:10px; margin-top:16px; }
.modal-btns .btn { flex:1; }
.last-call-ref { background:#0e1420; border-radius:6px; padding:8px; margin-top:8px; font-size:11px; color:#4b5563; line-height:1.5; }

.empty { text-align:center; padding:60px 20px; color:var(--muted); }
.empty-icon { font-size:48px; margin-bottom:12px; }

.fab { position:fixed; bottom:24px; right:20px; width:56px; height:56px; background:var(--orange); border-radius:50%; border:none; font-size:28px; color:#fff; cursor:pointer; box-shadow:0 4px 20px rgba(249,115,22,.4); z-index:150; display:flex; align-items:center; justify-content:center; }

.toast { position:fixed; bottom:90px; left:50%; transform:translateX(-50%); background:#1e3a5f; color:#7ecfff; padding:10px 20px; border-radius:20px; font-size:13px; font-weight:600; z-index:400; opacity:0; transition:opacity .3s; white-space:nowrap; }
.toast.show { opacity:1; }

@media(min-width:600px) { .leads-list,.stats { max-width:680px; margin:0 auto; } }
</style>
</head>
<body>

<div class="header">
  <div><div class="header-title">OLD PRO</div><div class="header-sub">CRM</div></div>
  <div id="lead-count" style="color:var(--muted);font-size:12px;"></div>
  <button onclick="shutdownServer()" style="background:#3a0f0f;color:#f87171;border:none;border-radius:6px;padding:6px 12px;font-size:12px;font-weight:700;cursor:pointer;">⏻ Stop</button>
</div>

<div class="stats">
  <div class="stat-card"><div class="stat-val" id="stat-total">0</div><div class="stat-lbl">Total</div></div>
  <div class="stat-card"><div class="stat-val" id="stat-due" style="color:var(--orange)">0</div><div class="stat-lbl">Due</div></div>
  <div class="stat-card"><div class="stat-val" id="stat-warm" style="color:var(--green)">0</div><div class="stat-lbl">Warm</div></div>
  <div class="stat-card"><div class="stat-val" id="stat-won" style="color:#a855f7">0</div><div class="stat-lbl">Won</div></div>
</div>

<div class="list-tabs">
  <button class="tab active" onclick="setList('All',this)">All</button>
  <button class="tab" onclick="setList('Leads',this)">Leads</button>
  <button class="tab" onclick="setList('Follow-Up',this)">Follow-Up</button>
  <button class="tab" onclick="setList('Warm',this)">Warm</button>
  <button class="tab" onclick="setList('Won',this)">Won</button>
  <button class="tab" onclick="setList('Dead',this)">Dead</button>
</div>

<div class="search-wrap">
  <input class="search-input" type="search" placeholder="🔍  Search name, phone, notes…" oninput="onSearch(this.value)">
</div>

<select class="type-filter" onchange="onTypeFilter(this.value)">
  <option value="">All Types</option>
  <option>Agent</option>
  <option>Property Mgr</option>
  <option>Landlord</option>
  <option>Condo Owner</option>
  <option>Staging</option>
  <option>Other</option>
</select>

<div class="leads-list" id="leads-list">
  <div class="empty"><div class="empty-icon">📋</div>Loading…</div>
</div>

<button class="fab" onclick="showToast('Use desktop app to add leads')">＋</button>

<div class="overlay" id="overlay" onclick="closeSheet()"></div>

<div class="sheet" id="sheet">
  <div class="sheet-handle"></div>
  <div class="sheet-content">
    <div class="sheet-name" id="sheet-name"></div>
    <div class="sheet-phone" id="sheet-phone"></div>
    <div class="sheet-meta" id="sheet-meta"></div>
    <img id="sheet-photo" class="sheet-photo" src="" style="display:none" onclick="openPhotoFullsize()">
    <div class="sheet-notes" id="sheet-notes"></div>

    <div class="btn-grid" style="margin-top:14px;">
      <button class="btn btn-orange" onclick="openLogCall()">📞 Log Call</button>
      <button class="btn btn-green" id="call-btn" onclick="callViaPhone()">📱 Call</button>
      <button class="btn btn-blue" onclick="openAd()">🌐 Open Ad</button>
      <button class="btn btn-gray" onclick="toggleMove()">📋 Move List</button>
    </div>

    <select class="move-select" id="move-select" style="display:none" onchange="moveLead(this.value)">
      <option value="">— Move to list —</option>
      <option>Leads</option>
      <option>Follow-Up</option>
      <option>Warm</option>
      <option>Won</option>
      <option>Dead</option>
    </select>

    <div style="height:20px;"></div>
  </div>
</div>

<div class="modal" id="log-modal">
  <div class="modal-box">
    <div class="modal-title">📞 Log a Call</div>
    <label>Outcome</label>
    <select id="log-outcome" onchange="autoSetFollowup(this.value)">
      <option>Answered — Interested</option>
      <option>Answered — Not Interested</option>
      <option>Answered — Call Back</option>
      <option>Answered — Call back in 8 days</option>
      <option>Answered — Call back in 14 days</option>
      <option>Answered — Call back in 30 days</option>
      <option>Voicemail Left</option>
      <option>No Answer</option>
      <option>Job Booked 🎉</option>
    </select>
    <label>Notes</label>
    <textarea id="log-notes" placeholder="What did they say?"></textarea>
    <div class="last-call-ref" id="last-call-ref" style="display:none;"></div>
    <label>Move to list</label>
    <select id="log-move">
      <option value="">— keep current —</option>
      <option>Leads</option>
      <option>Follow-Up</option>
      <option>Warm</option>
      <option>Won</option>
      <option>Dead</option>
    </select>
    <label>Follow-up date</label>
    <input type="date" id="log-followup">
    <div class="modal-btns">
      <button class="btn btn-gray" onclick="closeLogCall()">Cancel</button>
      <button class="btn btn-orange" onclick="saveLog()">Save</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let currentList = 'All', searchText = '', typeFilter = '', currentLead = null, searchTimer = null;

async function loadLeads() {
  const p = new URLSearchParams({list: currentList, search: searchText, type_filter: typeFilter});
  const res = await fetch('/api/leads?' + p, {headers: {'ngrok-skip-browser-warning': 'true'}});
  const data = await res.json();
  renderLeads(data.leads);
  renderStats(data.stats);
}

function renderLeads(leads) {
  const el = document.getElementById('leads-list');
  document.getElementById('lead-count').textContent = leads.length + ' leads';
  if (!leads.length) { el.innerHTML = '<div class="empty"><div class="empty-icon">📭</div>No leads</div>'; return; }
  const today = new Date().toISOString().slice(0,10);
  window._leads = {};
  leads.forEach(function(l) { window._leads[l.id] = l; });
  var today2 = new Date().toISOString().slice(0,10);
  var html2 = '';
  leads.forEach(function(l) {
    var called = (l.call_count||0) > 0;
    var overdue = l.next_followup && l.next_followup <= today2;
    var isNA = l.phone === 'N/A';
    var name = (l.name||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    var phone = (l.phone||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');
    html2 += '<div class="lead-card' + (called?' called':'') + '" onclick="openLeadById(' + l.id + ')">';
    html2 += '<div class="lead-name">' + name + '</div>';
    if (phone && !isNA) html2 += '<div class="lead-phone">' + phone + '</div>';
    if (isNA) html2 += '<div style="color:#f87171;font-size:12px;">No phone available</div>';
    html2 += '<div class="lead-badges">';
    html2 += '<span class="badge badge-' + (l.list||'') + '">' + (l.list||'') + '</span>';
    html2 += '<span class="badge badge-type">' + (l.type||'') + '</span>';
    if (l.call_count) html2 += '<span class="badge badge-calls">📞 ' + l.call_count + 'x</span>';
    if (overdue) html2 += '<span class="badge badge-due">⏰ ' + (l.next_followup||'') + '</span>';
    html2 += '</div></div>';
  });
  el.innerHTML = html2;
}

function renderStats(s) {
  document.getElementById('stat-total').textContent = s.total;
  document.getElementById('stat-due').textContent   = s.due;
  document.getElementById('stat-warm').textContent  = s.warm;
  document.getElementById('stat-won').textContent   = s.won;
}

function setList(l, btn) {
  currentList = l;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  loadLeads();
}
function onSearch(v) { clearTimeout(searchTimer); searchTimer = setTimeout(()=>{searchText=v;loadLeads();},300); }
function onTypeFilter(v) { typeFilter = v; loadLeads(); }

function openLeadById(id) {
  var lead = window._leads[id];
  if (lead) openLead(lead);
}

function openLead(lead) {
  currentLead = lead;
  document.getElementById('sheet-name').textContent = lead.name;
  const ph = document.getElementById('sheet-phone');
  if (lead.phone && lead.phone !== 'N/A') {
    ph.textContent = lead.phone; ph.className = 'sheet-phone';
    document.getElementById('call-btn').style.display = '';
  } else if (lead.phone === 'N/A') {
    ph.textContent = 'No phone available'; ph.className = 'sheet-phone na';
    document.getElementById('call-btn').style.display = 'none';
  } else {
    ph.textContent = 'No phone yet'; ph.className = 'sheet-phone na';
    document.getElementById('call-btn').style.display = 'none';
  }
  let meta = [];
  if (lead.company) meta.push(lead.company);
  if (lead.area)    meta.push(lead.area);
  if (lead.last_contact) meta.push('Last call: ' + lead.last_contact);
  if (lead.next_followup) meta.push('Follow-up: ' + lead.next_followup);
  meta.push((lead.call_count||0) + ' calls logged');
  document.getElementById('sheet-meta').textContent = meta.join('  ·  ');

  // Notes with clickable URLs
  document.getElementById('sheet-notes').textContent = (lead.notes||'No notes yet.');

  // Photo
  var photoMatch = (lead.notes||'').match(/\[PHOTO:([^\]]+)\]/);
  const photoEl = document.getElementById('sheet-photo');
  if (photoMatch) {
    photoEl.src = '/photo?path=' + encodeURIComponent(photoMatch[1]);
    photoEl.style.display = '';
  } else {
    photoEl.style.display = 'none';
  }

  document.getElementById('move-select').style.display = 'none';
  document.getElementById('overlay').classList.add('open');
  document.getElementById('sheet').classList.add('open');

  // Load last call for reference
  fetch('/api/leads/' + lead.id + '/last_call', {headers: {'ngrok-skip-browser-warning': 'true'}}).then(r=>r.json()).then(d => {
    const ref = document.getElementById('last-call-ref');
    if (d.outcome) {
      ref.textContent = 'Last call (' + (d.called_at||'').slice(0,10) + '): ' + d.outcome + (d.notes ? ' | ' + d.notes.slice(0,100) : '');
      ref.style.display = '';
    } else {
      ref.style.display = 'none';
    }
  });
}

function closeSheet() {
  document.getElementById('overlay').classList.remove('open');
  document.getElementById('sheet').classList.remove('open');
  currentLead = null;
}

function callViaPhone() {
  if (!currentLead?.phone || currentLead.phone === 'N/A') return;
  // Copy to clipboard and open TextNow
  navigator.clipboard.writeText(currentLead.phone).then(()=>{
    showToast('📋 ' + currentLead.phone + ' — paste in TextNow');
    window.open('https://www.textnow.com/messaging', '_blank');
    markCalled();
  });
}

async function markCalled() {
  if (!currentLead) return;
  await fetch('/api/leads/' + currentLead.id + '/called', {method:'POST'});
  loadLeads();
}

function openAd() {
  if (!currentLead) return;
  const notes = currentLead.notes || '';
  var kMatch = (currentLead.notes||'').match(/https?:\/\/\S+kijiji\S+/);
  var url = kMatch ? kMatch[0] : 'https://www.kijiji.ca/b-apartments-condos/city-of-toronto/k0c37l1700273';
  window.open(url, '_blank');
}

function openPhotoFullsize() {
  if (!currentLead) return;
  const match = (currentLead.notes||'').match(/\[PHOTO:([^\]]+)\]/);
  if (match) window.open('/photo?path=' + encodeURIComponent(match[1]), '_blank');
}

function toggleMove() {
  const el = document.getElementById('move-select');
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

async function moveLead(list) {
  if (!list || !currentLead) return;
  await fetch('/api/leads/' + currentLead.id + '/move', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({list})});
  showToast('Moved to ' + list);
  closeSheet(); loadLeads();
}

function openLogCall() {
  document.getElementById('log-notes').value = '';
  document.getElementById('log-outcome').selectedIndex = 0;
  document.getElementById('log-move').selectedIndex = 0;
  document.getElementById('log-followup').value = '';
  document.getElementById('log-modal').classList.add('open');
}
function closeLogCall() { document.getElementById('log-modal').classList.remove('open'); }

function autoSetFollowup(outcome) {
  const days = outcome.includes('8 days') ? 8 : outcome.includes('14 days') ? 14 : outcome.includes('30 days') ? 30 : outcome.includes('Voicemail') ? 3 : outcome.includes('Call Back') ? 2 : 0;
  if (days) {
    const d = new Date(); d.setDate(d.getDate() + days);
    document.getElementById('log-followup').value = d.toISOString().slice(0,10);
  }
}

async function saveLog() {
  if (!currentLead) return;
  const payload = {
    outcome: document.getElementById('log-outcome').value,
    notes:   document.getElementById('log-notes').value,
    move_to: document.getElementById('log-move').value,
    next_followup: document.getElementById('log-followup').value,
  };
  await fetch('/api/leads/' + currentLead.id + '/log', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  closeLogCall(); closeSheet(); loadLeads();
  showToast('Call logged ✓');
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'), 2800);
}

loadLeads();
setInterval(loadLeads, 30000);
function shutdownServer() { if(confirm("Stop the web server?")) fetch("/shutdown", {method:"POST"}).then(()=>document.body.innerHTML="<div style=padding:40px;color:#f87171;font-size:20px;>Server stopped. Close this tab.</div>"); }
</script>
</body>
</html>"""

# ─── API ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/photo')
def serve_photo():
    from flask import send_file, abort
    path = request.args.get('path', '')
    p = Path(path)
    if p.exists() and str(p).startswith(str(Path.home() / ".old_pro_crm_images")):
        return send_file(p)
    abort(404)

@app.after_request
def add_headers(response):
    response.headers['ngrok-skip-browser-warning'] = 'true'
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

@app.route('/api/leads')
def get_leads():
    list_filter  = request.args.get('list', 'All')
    search       = request.args.get('search', '').strip()
    type_filter  = request.args.get('type_filter', '').strip()
    with get_conn() as conn:
        q = "SELECT * FROM leads WHERE 1=1"
        params = []
        if list_filter != 'All':
            q += " AND list=?"; params.append(list_filter)
        if search:
            q += " AND (name LIKE ? OR company LIKE ? OR phone LIKE ? OR notes LIKE ?)"
            s = f"%{search}%"; params += [s,s,s,s]
        if type_filter:
            q += " AND type=?"; params.append(type_filter)
        q += " ORDER BY CASE priority WHEN 'High' THEN 0 WHEN 'Normal' THEN 1 ELSE 2 END, added DESC"
        rows = conn.execute(q, params).fetchall()
        today = date.today().isoformat()
        total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        warm  = conn.execute("SELECT COUNT(*) FROM leads WHERE list='Warm'").fetchone()[0]
        won   = conn.execute("SELECT COUNT(*) FROM leads WHERE list='Won'").fetchone()[0]
        due   = conn.execute("SELECT COUNT(*) FROM leads WHERE next_followup<=? AND next_followup IS NOT NULL AND next_followup!=''", (today,)).fetchone()[0]
    return jsonify({'leads': [dict(r) for r in rows], 'stats': {'total':total,'warm':warm,'won':won,'due':due}})

@app.route('/api/leads/<int:lead_id>/log', methods=['POST'])
def log_call(lead_id):
    data = request.json
    outcome      = data.get('outcome','')
    notes        = data.get('notes','')
    move_to      = data.get('move_to','')
    next_followup = data.get('next_followup','')
    with get_conn() as conn:
        conn.execute("INSERT INTO call_log (lead_id,outcome,notes) VALUES (?,?,?)", (lead_id,outcome,notes))
        conn.execute("UPDATE leads SET last_contact=?,call_count=call_count+1 WHERE id=?", (date.today().isoformat(),lead_id))
        if move_to:
            conn.execute("UPDATE leads SET list=? WHERE id=?", (move_to,lead_id))
        if next_followup:
            conn.execute("UPDATE leads SET next_followup=? WHERE id=?", (next_followup,lead_id))
        if notes:
            existing = conn.execute("SELECT notes FROM leads WHERE id=?", (lead_id,)).fetchone()
            existing_notes = (existing[0] or '') if existing else ''
            stamp = f"[{date.today().isoformat()} — {outcome}]\n{notes}"
            new_notes = (existing_notes + "\n\n" + stamp).strip()
            conn.execute("UPDATE leads SET notes=? WHERE id=?", (new_notes, lead_id))
    return jsonify({'ok':True})

@app.route('/api/leads/<int:lead_id>/move', methods=['POST'])
def move_lead(lead_id):
    list_name = request.json.get('list','')
    if list_name:
        with get_conn() as conn:
            conn.execute("UPDATE leads SET list=? WHERE id=?", (list_name,lead_id))
    return jsonify({'ok':True})

@app.route('/api/leads/<int:lead_id>/called', methods=['POST'])
def mark_called(lead_id):
    with get_conn() as conn:
        conn.execute("UPDATE leads SET last_contact=?,call_count=call_count+1 WHERE id=?", (date.today().isoformat(),lead_id))
    return jsonify({'ok':True})

@app.route('/api/leads/<int:lead_id>/last_call')
def last_call(lead_id):
    with get_conn() as conn:
        row = conn.execute("SELECT outcome,notes,called_at FROM call_log WHERE lead_id=? ORDER BY id DESC LIMIT 1", (lead_id,)).fetchone()
    return jsonify(dict(row) if row else {})

# ─── Entry Point ─────────────────────────────────────────────────────────────

def get_local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def print_qr(url):
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except ImportError:
        print("  (pip install qrcode for a scannable QR code)")

@app.route('/shutdown', methods=['POST'])
def shutdown():
    import os, signal
    os.kill(os.getpid(), signal.SIGTERM)
    return 'Stopping...'

if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    ip   = get_local_ip()
    url  = f"http://{ip}:{port}"
    print(f"\n{'='*50}")
    print(f"  Old Pro CRM — Web Server")
    print(f"  Local:  http://localhost:{port}")
    print(f"  Phone:  {url}")
    print(f"{'='*50}\n")
    print("  Scan with your phone camera:\n")
    print_qr(url)
    print(f"\n  URL: {url}")
    print("  For remote access: ngrok http 5000\n")
    app.run(host='0.0.0.0', port=port, debug=False)
