// Cylinder Atlas front end (vanilla JS + Leaflet). Every server string is escaped before rendering.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt$ = (v, d = 4) => "$" + Number(v || 0).toFixed(d);
const fmtN = (v) => Number(v || 0).toLocaleString();
const fmtM = (v) => (Math.abs(v) >= 1000 ? "$" + (v / 1000).toFixed(2) + "bn" : "$" + Number(v || 0).toFixed(0) + "m");
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
const COLORS = { sponsor: "#ff6b6b", target: "#21c2a8", consolidator: "#e0902a", consolidated: "#94a0ae", major: "#6d55c9", demo: "#d6457f" };
const LABEL = { sponsor: "PE-owned · exit candidate", target: "Independent target", consolidator: "Rival consolidator", consolidated: "Already acquired", major: "Tier-1 major", demo: "Safety demo · fictional" };
const initials = (n) => n.replace(/\(.*?\)/g, "").split(/[\s&\-]+/).filter((w) => /^[A-Za-z]/.test(w)).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
const avatar = (t) => `<div class="av" style="background:${COLORS[t.status] || "#999"}">${esc(initials(t.name))}</div>`;
function ring(score, size = 34) {
  if (score == null) return `<svg class="ring" width="${size}" height="${size}"><circle cx="${size / 2}" cy="${size / 2}" r="${size / 2 - 3}" fill="none" stroke="#eef1f5" stroke-width="3"/><text x="50%" y="54%" text-anchor="middle" dominant-baseline="middle" font-size="10" fill="#9aa5b3">–</text></svg>`;
  const r = size / 2 - 3, c = 2 * Math.PI * r, col = score >= 70 ? "#1f9d61" : score >= 55 ? "#d98e04" : "#d14b3d";
  return `<svg class="ring" width="${size}" height="${size}"><circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="#eef1f5" stroke-width="3"/>
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${col}" stroke-width="3" stroke-linecap="round" stroke-dasharray="${(c * score) / 100} ${c}" transform="rotate(-90 ${size / 2} ${size / 2})"/>
    <text x="50%" y="54%" text-anchor="middle" dominant-baseline="middle" font-size="10.5" font-weight="700" fill="#14202e">${Math.round(score)}</text></svg>`;
}

let TARGETS = [], PLAN = [], PLANDATA = null, selected = null, markers = {}, map, STATUS = {}, subtab = "overview";
const regions = new Set(["US", "Canada", "Latin America", "Europe", "Middle East", "China & SEA"]);
const statuses = new Set(["target", "sponsor", "consolidator", "consolidated", "major", "demo"]);

// ------------------------------------------------------------------ tabs
$$("#tabs button").forEach((b) => b.onclick = () => {
  $$("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
  $$(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + b.dataset.tab));
  ({ map: showMap, strategy: loadStrategy, list: loadList, outreach: loadOutreach, plan: loadPlan, pipeline: loadPipeline, costs: loadCosts, safety: loadSafety, thesis: () => {}, howto: () => {} })[b.dataset.tab]();
});
let mapShown = false;
function showMap() { setTimeout(() => { map.invalidateSize(); if (!mapShown) { map.setView([39, -40], 3); mapShown = true; } initGlobe(); sizeGlobe(); }, 60); }
const goTab = (t) => $(`#tabs button[data-tab="${t}"]`).click();
$$("[data-goto]").forEach((b) => b.onclick = () => goTab(b.dataset.goto));
const VIEWS = { canada: [[53, -98], 4, 1.2], na: [[39, -96], 4, 1.1], la: [[-5, -65], 3, 1.4], eu: [[50, 8], 5, 0.9], nordics: [[62, 16], 5, 0.7], me: [[25, 45], 5, 0.9], ap: [[18, 100], 4, 1.3], world: [[30, -20], 3, 2.4] };
$$("[data-fly]").forEach((b) => b.onclick = () => {
  const [c, z, alt] = VIEWS[b.dataset.fly];
  if (VIEW === "globe" && globe) { globe.controls().autoRotate = b.dataset.fly === "world"; globe.pointOfView({ lat: c[0], lng: c[1], altitude: alt }, 1200); }
  else map.flyTo(c, z, { duration: 0.8 });
});
$$("[data-view]").forEach((b) => b.onclick = () => setView(b.dataset.view));
function setView(v) {
  VIEW = v;
  $$("[data-view]").forEach((x) => x.classList.toggle("on", x.dataset.view === v));
  $("#mapwrap").classList.toggle("mode-map", v === "map");
  if (v === "map") setTimeout(() => map.invalidateSize(), 50); else { initGlobe(); sizeGlobe(); }
}

// ------------------------------------------------------------------ 3D globe (globe.gl)
let globe = null, VIEW = "globe";
function initGlobe() {
  if (globe || typeof Globe === "undefined") { if (typeof Globe === "undefined") setView("map"); return; }
  const el = $("#globe");
  try {
    // globe.gl changed its constructor between versions: support both styles
    try { globe = Globe()(el); } catch (e) { globe = new Globe(el); }
    if (!el.querySelector("canvas")) throw new Error("no WebGL canvas");
  } catch (e) { console.warn("Globe unavailable, using the flat map", e); globe = null; setView("map"); return; }
  globe
    .globeImageUrl("https://unpkg.com/three-globe@2.31.0/example/img/earth-night.jpg")
    .bumpImageUrl("https://unpkg.com/three-globe@2.31.0/example/img/earth-topology.png")
    .backgroundImageUrl("https://unpkg.com/three-globe@2.31.0/example/img/night-sky.png")
    .atmosphereColor("#3fb8ff").atmosphereAltitude(0.17)
    .pointLat("lat").pointLng("lon")
    .pointColor((t) => (t.id === selected ? "#ffffff" : PLAN.includes(t.id) ? "#f0c56a" : COLORS[t.status] || "#999"))
    .pointAltitude((t) => (t.status === "target" ? 0.012 + Math.min(0.16, (t.locations || 2) * 0.0028) : t.status === "major" ? 0.05 : 0.02))
    .pointRadius((t) => (t.id === selected ? 0.55 : t.status === "major" ? 0.42 : 0.3))
    .pointsMerge(false)
    .pointLabel((t) => `<div class="g-tip"><b>${esc(t.name)}</b><br><span>${esc(t.city)}${t.region_state ? ", " + esc(t.region_state) : ""} · ${esc(t.country)}</span><br>${esc(LABEL[t.status])}${t.locations ? " · " + t.locations + " branches" : ""}${t.score ? " · score " + Math.round(t.score) : ""}</div>`)
    .onPointClick((t) => select(t.id))
    .arcStartLat("a0").arcStartLng("o0").arcEndLat("a1").arcEndLng("o1")
    .arcColor(() => ["rgba(240,197,106,.95)", "rgba(33,194,168,.85)"])
    .arcAltitudeAutoScale(0.35).arcStroke(0.45).arcDashLength(0.5).arcDashGap(0.15).arcDashAnimateTime(2600)
    .ringLat("lat").ringLng("lon").ringColor(() => (t) => `rgba(240,197,106,${1 - t})`)
    .ringMaxRadius(2.6).ringPropagationSpeed(1.6).ringRepeatPeriod(1400);
  globe.controls().autoRotate = true; globe.controls().autoRotateSpeed = 0.35;
  el.addEventListener("pointerdown", () => { globe.controls().autoRotate = false; });
  globe.pointOfView({ lat: 38, lng: -40, altitude: 2.3 }, 0);
  window.addEventListener("resize", sizeGlobe);
  drawGlobe(); sizeGlobe();
}
function sizeGlobe() { if (globe) { const w = $("#mapwrap"); globe.width(w.clientWidth).height(w.clientHeight); } }
function drawGlobe() {
  if (!globe) return;
  const vis = visible();
  globe.pointsData(vis);
  const plan = PLAN.map((id) => TARGETS.find((t) => t.id === id)).filter(Boolean);
  const p0 = plan[0];
  globe.arcsData(p0 ? plan.slice(1).map((t) => ({ a0: p0.lat, o0: p0.lon, a1: t.lat, o1: t.lon })) : []);
  globe.ringsData(plan.slice(0, 40));
}

// ------------------------------------------------------------------ status
async function loadStatus() {
  STATUS = await api("/api/status");
  $("#m-spend").textContent = fmt$(STATUS.spend_today);
  $("#m-cap").textContent = fmt$(STATUS.daily_usd_cap, 2);
  $("#m-fill").style.width = Math.min(100, (100 * STATUS.spend_today) / Math.max(STATUS.daily_usd_cap, 1e-9)) + "%";
  $("#m-model").textContent = `${STATUS.model}${STATUS.mock ? " · mock" : ""}`;
  $("#m-env").textContent = STATUS.has_key ? `key: ${STATUS.env_file}` : "no key";
  $("#m-pill").classList.toggle("off", !STATUS.has_key);
  const kb = $("#keybanner");
  kb.classList.toggle("hidden", !!STATUS.has_key);
  kb.textContent = "No PORTKEY_API_KEY (or OPENAI_API_KEY) found in .env in this folder or the folder above. The map and planner work; the AI agents need the key.";
}

// ------------------------------------------------------------------ map
function initMap() {
  map = L.map("map", { worldCopyJump: true, zoomControl: false }).setView([39, -45], 3);
  L.control.zoom({ position: "bottomright" }).addTo(map);
  // Esri dark-grey basemap (no API key needed; CARTO now requires a key)
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
    attribution: "Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors", maxZoom: 16 }).addTo(map);
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 16, opacity: 0.8 }).addTo(map);
  map.on("click", (e) => openAddForm(e.latlng));
}
const radius = (t) => t.status === "target" ? 5 + Math.min(9, Math.sqrt(t.locations || 2) * 1.6) : t.status === "major" ? 8 : 6;
function visible() {
  const q = $("#search").value.toLowerCase();
  return TARGETS.filter((t) => regions.has(t.region) && statuses.has(t.status) && (!q || `${t.name} ${t.city} ${t.region_state} ${t.country}`.toLowerCase().includes(q)));
}
function drawMarkers() {
  drawGlobe();
  Object.values(markers).forEach((m) => m.remove()); markers = {};
  visible().forEach((t) => {
    const inPlan = PLAN.includes(t.id), sel = t.id === selected;
    const m = L.circleMarker([t.lat, t.lon], { radius: radius(t) + (sel ? 3 : 0), color: sel ? "#ffffff" : inPlan ? "#f0c56a" : "rgba(255,255,255,.55)",
      weight: inPlan || sel ? 2.5 : 1, fillColor: COLORS[t.status] || "#999", fillOpacity: t.status === "consolidated" ? 0.45 : 0.92,
      className: t.status === "sponsor" ? "mk-sponsor" : t.status === "target" ? "mk" : t.status === "consolidator" ? "mk-consolidator" : t.status === "major" ? "mk-major" : "" }).addTo(map);
    m.bindTooltip(`<b>${esc(t.name)}</b><br><span style="color:#6b7787">${esc(LABEL[t.status])}${t.locations ? " · " + t.locations + " branches" : ""}${t.score ? " · score " + Math.round(t.score) : ""}</span>`, { direction: "top", offset: [0, -6] });
    m.on("click", (e) => { L.DomEvent.stopPropagation(e); select(t.id); });
    markers[t.id] = m;
  });
}
function drawList() {
  const by = $("#sortBy").value;
  const pri = (t) => (t.status === "target" ? 2 : t.status === "sponsor" ? 1 : 0);
  const v = visible().sort((a, b) => pri(b) - pri(a) ||
    (by === "name" ? a.name.localeCompare(b.name) : by === "branches" ? (b.locations || 0) - (a.locations || 0) : (b.score || -1) - (a.score || -1) || (b.locations || 0) - (a.locations || 0)));
  $("#listCount").textContent = `${v.length} companies · ${v.filter((t) => t.status === "target").length} targets · ${v.filter((t) => t.status === "sponsor").length} PE-owned`;
  $("#list").innerHTML = v.map((t) => `<div class="item ${t.id === selected ? "sel" : ""}" data-id="${esc(t.id)}">${avatar(t)}
    <div style="min-width:0"><div class="nm">${esc(t.name)}${PLAN.includes(t.id) ? '<span class="tag plan">Plan</span>' : ""}</div>
    <div class="meta">${esc(t.city)}${t.region_state ? ", " + esc(t.region_state) : ""} · ${t.locations ? t.locations + " br." : "branches ?"}${t.stage && t.stage !== "new" ? " · " + esc(t.stage) : ""}</div></div>
    ${t.status === "target" || t.status === "sponsor" || t.score ? ring(t.score) : ""}</div>`).join("");
  $$("#list .item").forEach((el) => el.onclick = () => select(el.dataset.id, true));
  const tg = TARGETS.filter((t) => t.status === "target" || t.status === "sponsor");
  const rev = tg.reduce((s, t) => s + (t.locations || 3) * 4, 0);
  $("#miniKpis").innerHTML = `<div><b>${TARGETS.length}</b><span>Companies</span></div><div><b>${tg.length}</b><span>Independent targets</span></div><div><b>${fmtM(rev)}</b><span>Target revenue (est.)</span></div>`;
}
function drawGoalOverlay() {
  if (!PLANDATA) return;
  const G = PLANDATA.goal, T = PLANDATA.totals;
  $("#goalOverlay").innerHTML = `<div class="eyebrow">Path to ${fmtM(G.value_m)} ${G.type === "revenue" ? "revenue" : "EBITDA"}</div>
    <div class="big">${fmtM(G.achieved_m)} <span style="font-size:13px;color:#9fb4ca;font-weight:500">· ${G.pct}%</span></div>
    <div class="prog"><i style="width:${Math.min(100, G.pct)}%"></i></div>
    <div class="small">${PLANDATA.deals.length} deals · ${T.locations} branches · ${fmtM(T.capital_m)} capital<br>Gap ${fmtM(G.gap_m)} ≈ ${G.additional_tuckins_needed} more tuck-ins</div>`;
}
async function loadTargets() {
  TARGETS = await api("/api/targets");
  const p = await api("/api/plan"); PLAN = p.order || []; PLANDATA = p.plan;
  drawMarkers(); drawList(); drawGoalOverlay();
}
$$("#regionChips button").forEach((b) => b.onclick = () => { b.classList.toggle("on"); regions.has(b.dataset.r) ? regions.delete(b.dataset.r) : regions.add(b.dataset.r); drawMarkers(); drawList(); });
$$("#legend input").forEach((c) => c.onchange = () => { c.parentElement.classList.toggle("on", c.checked); c.checked ? statuses.add(c.dataset.s) : statuses.delete(c.dataset.s); drawMarkers(); drawList(); });
$("#search").oninput = () => { drawMarkers(); drawList(); };
$("#sortBy").onchange = drawList;
$("#closeDetail").onclick = () => { selected = null; $("#detail").classList.add("hidden"); $("#tab-map").classList.remove("detail-open"); setTimeout(sizeGlobe, 60); drawList(); drawMarkers(); setTimeout(() => map.invalidateSize(), 50); };

// ------------------------------------------------------------------ detail drawer
let CUR = null;
async function select(id, fly) {
  selected = id; drawList(); drawMarkers();
  $("#detail").classList.remove("hidden"); $("#tab-map").classList.add("detail-open"); setTimeout(() => { map.invalidateSize(); sizeGlobe(); }, 60);
  CUR = await api("/api/targets/" + id);
  const t = CUR.target;
  if (fly) { if (VIEW === "globe" && globe) { globe.controls().autoRotate = false; globe.pointOfView({ lat: t.lat, lng: t.lon, altitude: 0.9 }, 1000); } else map.flyTo([t.lat, t.lon], Math.max(map.getZoom(), 6), { duration: 0.6 }); }
  if (!t.screen_json && !t.analysis_json && !["activity", "deal"].includes(subtab)) subtab = "overview";
  renderDetail();
  const last = CUR.runs[0];
  if (last && last.status === "running") { subtab = "activity"; renderDetail(); pollRun(last.id, "#runTrace", () => select(id)); }
}
function renderDetail() {
  const d = CUR, t = d.target, screen = t.screen_json ? JSON.parse(t.screen_json) : null, an = t.analysis_json ? JSON.parse(t.analysis_json) : null;
  const inPlan = PLAN.includes(t.id), ver = d.facts.filter((f) => f.verified);
  const site = t.website ? (t.website.startsWith("local:") ? `<a href="/demo/evergreen" target="_blank">demo site ↗</a>` : `<a href="${esc(t.website)}" target="_blank" rel="noopener">${esc(t.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, ""))} ↗</a>`) : "<span class='muted'>none on file</span>";
  const tabs = [["overview", "Overview"], ["deal", "Deal"], ["analysis", "Analysis"], ["risks", "Risks", an?.risks?.length], ["facts", "Facts", ver.length], ["outreach", "Outreach"], ["activity", "Agent trace"]];
  $("#detailBody").innerHTML = `
    <div class="d-head">
      <div class="d-title">${avatar(t)}<div><h2>${esc(t.name)}</h2><div class="loc">${esc(t.city)}${t.region_state ? ", " + esc(t.region_state) : ""} · ${esc(t.country)} · ${site}</div></div></div>
      <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap"><span class="badge ${esc(t.status)}">${esc(LABEL[t.status] || t.status)}</span>${inPlan ? '<span class="badge major" style="background:#0b1726;color:#fff;border-color:#0b1726">In roll-up plan</span>' : ""}</div>
      <div class="d-stats">
        <div><b>${screen ? Math.round(screen.score) : "–"}</b><span>Score</span></div>
        <div><b>${t.locations ?? "?"}</b><span>Branches</span></div>
        <div><b style="font-size:13px;padding-top:3px">${esc(screen?.role_in_rollup || "–")}</b><span>Role</span></div>
        ${t.deal_stage ? `<div class="dst-click" data-godeal="1" title="Open the Deal tab"><b style="font-size:13px;padding-top:3px;color:var(--accent-d)">${esc(t.deal_stage)}</b><span>Deal stage</span></div>` : `<div class="dst-click" data-godeal="1" title="Track this deal"><b style="font-size:13px;padding-top:3px">${esc(t.stage)}</b><span>Research · track ›</span></div>`}
      </div>
      <div class="d-actions">
        <button class="primary" id="runDesk" ${STATUS.has_key ? "" : "disabled"}>▶ Run deal desk</button>
        <button id="planBtn">${inPlan ? "Remove from plan" : "+ Add to plan"}</button>
        <button id="editBtn" title="Edit details or paste teaser / call notes">Edit · notes</button>
      </div>
    </div>
    <div class="subtabs">${tabs.map(([k, l, n]) => `<button data-st="${k}" class="${k === subtab ? "on" : ""}">${l}${n ? `<span class="n">${n}</span>` : ""}</button>`).join("")}</div>
    <div class="d-body" id="dBody"></div>`;
  $$(".subtabs button").forEach((b) => b.onclick = () => { subtab = b.dataset.st; renderDetail(); });
  $$("[data-godeal]").forEach((b) => b.onclick = () => { subtab = "deal"; renderDetail(); });
  $("#runDesk").onclick = async () => {
    $("#runDesk").disabled = true; subtab = "activity"; renderDetail(); $("#runDesk").disabled = true;
    const r = await api(`/api/targets/${t.id}/run`, {});
    pollRun(r.run_id, "#runTrace", () => { subtab = "overview"; select(t.id); loadTargets(); });
  };
  $("#planBtn").onclick = async () => { const r = await api(`/api/targets/${t.id}/plan`, { add: !inPlan }); PLAN = r.order; await loadTargets(); renderDetail(); };
  $("#editBtn").onclick = () => openEdit(t);
  const li = (a) => `<ul class="tight">${(a || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  const none = (msg) => `<div class="empty">${msg}</div>`;
  const body = {
    overview: () => `
      ${screen ? `<div class="verdict"><div class="sc">${Math.round(screen.score)}<small>/100</small></div><p><b>${esc(screen.role_in_rollup)}</b> · confidence ${esc(screen.confidence)}<br>${esc(screen.headline)}</p></div>` : ""}
      <div class="kv"><div>Ownership</div><div>${esc(t.ownership)}</div><div>Region</div><div>${esc({ Canada: "Canada", US: "North America (US)", Europe: "Europe", "Middle East": "Middle East & Africa", "Latin America": "Latin America", "China & SEA": "Asia Pacific" }[t.region] || t.region)}</div>
        <div>Seed source</div><div class="small">${t.source && t.source.startsWith("http") ? `<a href="${esc(t.source)}" target="_blank">${esc(t.source.replace(/^https?:\/\//, "").slice(0, 52))}… ↗</a>` : esc(t.source)}</div></div>
      <p class="small muted" style="line-height:1.5">${esc(t.notes)}</p>
      ${screen ? `<div class="section-t">Thesis screen</div>` + Object.entries(screen.scores || {}).map(([k, v]) => `<div class="sbar"><span>${esc(k.replace(/_/g, " "))}</span><div class="b"><i style="width:${(v.score || 0) * 20}%;background:${v.score >= 4 ? "#1f9d61" : v.score >= 3 ? "#0e9f8e" : "#d98e04"}"></i></div><b>${esc(v.score)}</b></div><div class="why">${esc(v.why)}</div>`).join("")
        : none("Not screened yet. Click <b>Run deal desk</b>: the Scout reads the company's own website, the Screener scores it against your thesis and the Analyst writes the investment case.")}
      ${t.investor_notes ? `<div class="section-t">Your notes</div><p class="small" style="white-space:pre-wrap">${esc(t.investor_notes)}</p>` : ""}`,
    analysis: () => an ? `<div class="section-t">Investment summary</div><p style="line-height:1.55">${esc(an.investment_summary)}</p>
      <div class="section-t">Key attractions</div>${li(an.key_attractions)}<div class="section-t">Value-creation plan</div>${li(an.value_creation_plan)}
      <div class="section-t">Diligence questions</div>${li(an.diligence_questions)}` : none("No analysis yet - run the deal desk."),
    risks: () => an ? (an.risks || []).map((r) => `<div class="risk ${esc(r.severity)}"><div class="rtop"><b>${esc(r.risk)}</b><span class="sev ${esc(r.severity)}">${esc(r.severity)}</span></div>
      <div class="ev">Evidence: ${esc(r.evidence)}</div><div class="mit"><b>Mitigation · </b>${esc(r.mitigation)}</div></div>`).join("") : none("No risk assessment yet - run the deal desk."),
    facts: () => d.facts.length ? `<p class="small muted">Each fact must quote the source word-for-word; the verifier rejects anything it cannot find.</p>` +
      d.facts.map((f) => `<div class="fact ${f.verified ? "" : "bad"}"><span class="ver ${f.verified ? "ok" : "no"}">${f.verified ? "✓ VERIFIED" : "✗ REJECTED"}</span><span class="f">${esc(f.field.replace(/_/g, " "))}</span> · ${esc(f.value)}
        <blockquote>“${esc(f.quote)}”</blockquote>${f.source_url && f.source_url.startsWith("http") ? `<div class="small" style="margin-top:4px"><a href="${esc(f.source_url)}" target="_blank">${esc(f.source_url.replace(/^https?:\/\//, "").slice(0, 60))} ↗</a></div>` : ""}</div>`).join("") : none("No facts yet."),
    outreach: () => an ? `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <span class="stamp ${t.outreach_status === "approved" ? "ok" : ""}">${t.outreach_status === "approved" ? "APPROVED · NOT SENT" : "DRAFT · NEEDS YOUR APPROVAL"}</span>
        <span>${t.outreach_status === "approved" ? "" : '<button class="ok" id="approveBtn">Approve</button> <button class="danger" id="rejectBtn">Reject</button>'}</span></div>
        <div class="letter">${esc(an.outreach_letter)}</div><p class="small muted">The app cannot send email. Approval only marks the letter ready for you to send yourself.</p>` : `<div class="stamp">HOUSE TEMPLATE · FILLED FROM THE RECORD</div><div class="letter" id="drawerTpl" style="margin-top:10px">${esc(fillLetter(LETTER, t, "", tplDetail(t)))}</div>
        <div style="display:flex;gap:6px;margin-top:8px"><button id="drawerTplCopy">Copy letter</button></div><p class="small muted">Run the deal desk for a researched, personalised version written by the Analyst. Nothing is ever sent.</p>`,
    activity: () => `<div id="runTrace">${d.runs.length ? "" : none("No runs yet.")}</div>`,
    deal: () => dealPane(t),
  }[subtab]();
  $("#dBody").innerHTML = body;
  if (subtab === "deal") wireDeal(t);
  const ap = $("#approveBtn"); if (ap) ap.onclick = async () => { await api(`/api/targets/${t.id}/approve`, {}); select(t.id); loadTargets(); };
  const dc = $("#drawerTplCopy"); if (dc) dc.onclick = () => { navigator.clipboard?.writeText($("#drawerTpl").textContent); dc.textContent = "Copied ✓"; };
  const rj = $("#rejectBtn"); if (rj) rj.onclick = async () => { await api(`/api/targets/${t.id}/reject`, {}); select(t.id); };
  if (subtab === "activity" && d.runs.length && d.runs[0].status !== "running") api("/api/runs/" + d.runs[0].id).then((x) => { const el = $("#runTrace"); if (el) el.innerHTML = renderTrace(x); });
}

// ------------------------------------------------------------------ run trace
function renderTrace(d) {
  const u = d.usage || [], st = d.run.status;
  const tot = u.reduce((a, x) => ({ i: a.i + (x.input || 0), c: a.c + (x.cached || 0), o: a.o + (x.output || 0), $: a.$ + (x.cost || 0), n: a.n + x.calls }), { i: 0, c: 0, o: 0, $: 0, n: 0 });
  const head = st === "running" ? `<span class="spin"></span> Running` : st === "done" ? "✓ Complete" : st === "stopped" ? "■ Stopped by guard" : "✗ Error";
  const agentsSeen = new Set(d.steps.map((s) => s.agent));
  const stages = d.run.kind === "strategy" ? ["strategist"] : ["scout", "screener", "analyst"];
  const lastAg = [...d.steps].reverse().find((s) => stages.includes(s.agent))?.agent;
  const pipe = `<div class="pipeline">${stages.map((s) => `<span class="${st === "running" && s === lastAg ? "act" : agentsSeen.has(s) ? "done" : ""}">${s[0].toUpperCase() + s.slice(1)}</span>`).join("")}</div>`;
  return `<div class="run"><div class="run-h"><b>${head}</b><span class="meta">run #${d.run.id} · ${tot.n} calls · in ${fmtN(tot.i)} (cached ${fmtN(tot.c)}) · out ${fmtN(tot.o)} · ${fmt$(tot.$, 5)}</span></div>${pipe}
    <div class="trace">${d.steps.map((s) => `<div class="step ${esc(s.agent)} ${esc(s.kind)}"><span class="ag">${esc(s.agent)}</span><div>${esc(s.title)}
      ${s.detail ? `<details><summary>details</summary><pre>${esc(s.detail)}</pre></details>` : ""}</div></div>`).join("")}</div></div>`;
}
async function pollRun(id, sel, done) {
  for (;;) {
    const d = await api("/api/runs/" + id);
    const el = $(sel); if (el) el.innerHTML = renderTrace(d);
    loadStatus();
    if (d.run.status !== "running") { if (done) done(d); return d; }
    await new Promise((r) => setTimeout(r, 1200));
  }
}

// ------------------------------------------------------------------ add / edit
function modal(html) { $("#modalCard").innerHTML = html; $("#modal").classList.remove("hidden"); }
const closeModal = () => $("#modal").classList.add("hidden");
$("#modal").onclick = (e) => { if (e.target.id === "modal") closeModal(); };
$("#addBtn").onclick = () => openAddForm(map.getCenter());
function openAddForm(ll) {
  modal(`<h3>Add a target</h3><div class="assump">
    <label>Company name<input id="fName"></label><label>Website<input id="fSite" placeholder="https://"></label>
    <label>City<input id="fCity"></label><label>Country<input id="fCountry" value="USA"></label>
    <label>Region<select id="fRegion"><option value="US">USA</option><option>Canada</option><option>Latin America</option><option>Europe</option><option value="Middle East">Middle East &amp; Africa</option><option value="China & SEA">Asia Pacific</option></select></label>
    <label>Branches (if known)<input id="fLoc" type="number"></label>
    <label>Latitude<input id="fLat" value="${ll.lat.toFixed(3)}"></label><label>Longitude<input id="fLon" value="${ll.lng.toFixed(3)}"></label></div>
    <div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end"><button id="fCancel">Cancel</button><button class="primary" id="fSave">Add to map</button></div>`);
  $("#fCancel").onclick = closeModal;
  $("#fSave").onclick = async () => {
    if (!$("#fName").value.trim()) return $("#fName").focus();
    const r = await api("/api/targets", { name: $("#fName").value, website: $("#fSite").value, city: $("#fCity").value, country: $("#fCountry").value,
      region: $("#fRegion").value, locations: $("#fLoc").value, lat: $("#fLat").value, lon: $("#fLon").value });
    closeModal(); await loadTargets(); select(r.id, true);
  };
}
function openEdit(t) {
  modal(`<h3>Edit ${esc(t.name)}</h3><div class="assump">
    <label>Website<input id="eSite" value="${esc(t.website)}"></label><label>Branches<input id="eLoc" type="number" value="${t.locations ?? ""}"></label>
    <label>Status<select id="eStatus">${Object.keys(LABEL).map((s) => `<option value="${s}" ${s === t.status ? "selected" : ""}>${LABEL[s]}</option>`).join("")}</select></label>
    <label>Ownership<input id="eOwn" value="${esc(t.ownership)}"></label></div>
    <label class="small muted" style="display:block;margin-top:10px">Investor notes - teaser, CIM excerpt or call notes (the Scout treats these as trusted)<textarea id="eNotes">${esc(t.investor_notes)}</textarea></label>
    <div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end"><button id="eCancel">Cancel</button><button class="primary" id="eSave">Save</button></div>`);
  $("#eCancel").onclick = closeModal;
  $("#eSave").onclick = async () => {
    await api(`/api/targets/${t.id}/update`, { website: $("#eSite").value, locations: $("#eLoc").value, status: $("#eStatus").value, ownership: $("#eOwn").value, investor_notes: $("#eNotes").value });
    closeModal(); await loadTargets(); select(t.id);
  };
}

// ------------------------------------------------------------------ plan
const ALABEL = { rev_per_location_m: "Revenue / branch ($m)", ebitda_margin_pct: "EBITDA margin %", synergy_margin_pts: "Synergy (margin pts)",
  synergy_radius_miles: "Synergy radius (mi)", platform_multiple: "Platform multiple (x)", tuckin_multiple: "Tuck-in multiple (x)",
  exit_multiple: "Exit multiple (x)", hold_years: "Hold period (yrs)", leverage_x: "Debt (x EBITDA)", debt_paydown_pct: "Debt repaid over hold %",
  organic_growth_pct: "Organic EBITDA growth %/yr", fees_pct: "Deal fees %", max_platform_ev_m: "Max first-deal EV ($m)", default_locations: "Branches if unknown", typical_tuckin_locations: "Typical tuck-in branches", goal_value_m: "Goal ($m)" };
async function loadPlan() { const d = await api("/api/plan"); PLAN = d.order; PLANDATA = d.plan; if (!TARGETS.length) TARGETS = await api("/api/targets"); renderPlan(d.plan); renderStrategy(d.strategy); }
function renderPlan(p) {
  PLANDATA = p; const a = p.assumptions, T = p.totals, G = p.goal, gl = G.type === "revenue" ? "revenue" : "EBITDA";
  $$("#goalChips button").forEach((b) => b.classList.toggle("on", b.dataset.g === `${a.goal_type}:${Number(a.goal_value_m)}`));
  $("#heroGoal").innerHTML = `<div class="hero-goal"><div><div class="t">Goal · ${fmtM(G.value_m)} ${gl}</div><div class="big">${fmtM(G.achieved_m)} <span style="font-size:15px;color:#9fb4ca">${G.pct}% of goal</span></div>
      <div class="prog" style="width:300px"><i style="width:${Math.min(100, G.pct)}%"></i></div><div class="small" style="color:#9fb4ca">Gap ${fmtM(G.gap_m)} ≈ ${G.additional_tuckins_needed} more tuck-ins (${esc(G.tuckin_size_note)})</div></div>
    <div class="stats"><div><b>${p.deals.length}</b><span>Deals</span></div><div><b>${T.locations}</b><span>Branches</span></div><div><b>${fmtM(T.capital_m)}</b><span>Capital</span></div><div><b>${fmtM(T.value_created_m)}</b><span>Value created</span></div></div></div>`;
  $("#assump").innerHTML = Object.keys(ALABEL).map((k) => `<label>${ALABEL[k]}<input data-k="${k}" type="number" step="any" value="${a[k]}"></label>`).join("");
  $$("#assump input").forEach((i) => i.onchange = async () => renderPlan(await api("/api/plan/assumptions", { [i.dataset.k]: i.value })));
  $("#planList").innerHTML = p.deals.map((d, i) => `<li><div style="min-width:0"><b>${esc(d.name)}</b><div class="role">${d.role} · ${d.locations}${d.locations_estimated ? "*" : ""} br. · ${fmtM(d.revenue_m)}</div></div>
      <span class="r"><button data-up="${i}" title="Move up">↑</button><button data-dn="${i}" title="Move down">↓</button><button data-rm="${esc(d.id)}" title="Remove">✕</button></span></li>`).join("") || `<div class="empty">Add targets from the map, or auto-fill.</div>`;
  $$("#planList [data-up]").forEach((b) => b.onclick = () => move(+b.dataset.up, -1));
  $$("#planList [data-dn]").forEach((b) => b.onclick = () => move(+b.dataset.dn, 1));
  $$("#planList [data-rm]").forEach((b) => b.onclick = async () => { await api(`/api/targets/${b.dataset.rm}/plan`, { add: false }); loadPlan(); loadTargets(); });
  $("#planKpis").innerHTML = [
    ["Pro-forma revenue", fmtM(T.revenue_m), `${T.locations} branches`],
    ["Pro-forma EBITDA", fmtM(T.pro_forma_ebitda_m), `incl. ${fmtM(T.synergy_m)} route-density synergies`],
    ["Capital required", fmtM(T.capital_m), T.blended_multiple ? `blended ${T.blended_multiple}x EBITDA` : "–"],
    ["Exit value", fmtM(T.exit_value_m), `at ${a.exit_multiple}x pro-forma EBITDA`],
  ].map(([l, v, s]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${esc(s)}</div></div>`).join("");
  $("#bridgeNote").textContent = G.type === "revenue" ? "revenue by deal" : "EBITDA incl. synergies by deal";
  $("#bridge").innerHTML = bridgeSVG(p);
  $("#returns").innerHTML = returnsHTML(p);
  $("#dealTable").innerHTML = p.deals.length ? `<table><tr><th>#</th><th>Company</th><th>Role</th><th class="n">Branches</th><th class="n">Revenue</th><th class="n">EBITDA</th><th class="n">Synergy</th><th class="n">Multiple</th><th class="n">Price</th><th>Route density</th></tr>
    ${p.deals.map((d, i) => `<tr><td>${i + 1}</td><td><b>${esc(d.name)}</b></td><td>${d.role}</td><td class="n">${d.locations}${d.locations_estimated ? "*" : ""}</td><td class="n">${fmtM(d.revenue_m)}${d.reported ? ' <span class="rep" title="Uses your own reported figures">R</span>' : ""}</td>
      <td class="n">${fmtM(d.ebitda_m)}</td><td class="n">${d.synergy_m ? fmtM(d.synergy_m) : "–"}</td><td class="n">${d.multiple}x</td><td class="n">${fmtM(d.price_m)}</td>
      <td class="small muted">${d.nearest_prior ? `${d.miles_to_nearest} mi → ${esc(d.nearest_prior)}` : "platform"}</td></tr>`).join("")}</table>
    <p class="small muted">* branch count unknown - uses the "Branches if unknown" assumption. Remaining independents on the map: ${p.universe.independent_targets_not_in_plan} ≈ ${fmtM(p.universe.their_est_revenue_m)} revenue. All figures are estimates from the assumptions shown.</p>` : `<div class="empty">No deals yet.</div>`;
  drawGoalOverlay();
}
function bridgeSVG(p) {
  const G = p.goal, key = G.type === "revenue" ? "revenue_m" : "ebitda_m";
  const deals = p.deals, n = deals.length + (G.gap_m > 0 ? 1 : 0) + 1;
  const W = 860, H = 280, L0 = 50, bw = Math.max(10, Math.min(56, (W - L0 - 20) / n - 8));
  const max = Math.max(G.value_m, G.achieved_m) * 1.1 || 1, y = (v) => H - 34 - (v / max) * (H - 70);
  let cum = 0, x = L0, out = "";
  for (let k = 0; k <= 4; k++) { const v = (max / 4) * k; out += `<line x1="${L0 - 6}" x2="${W}" y1="${y(v)}" y2="${y(v)}" stroke="#eef1f5"/><text x="${L0 - 10}" y="${y(v) + 4}" font-size="10" text-anchor="end" fill="#9aa5b3">${fmtM(v)}</text>`; }
  deals.forEach((d) => {
    const v = d[key] + (G.type === "ebitda" ? d.synergy_m : 0);
    out += `<rect x="${x}" y="${y(cum + v)}" width="${bw}" height="${Math.max(1, y(cum) - y(cum + v))}" fill="${d.role === "platform" ? "#0b1726" : "#0e9f8e"}" rx="3"><title>${esc(d.name)}: ${fmtM(v)}</title></rect>`;
    if (deals.length <= 18) out += `<text x="${x + bw / 2}" y="${H - 18}" font-size="9.5" text-anchor="middle" fill="#6b7787">${esc(initials(d.name))}</text>`;
    if (bw > 24) out += `<text x="${x + bw / 2}" y="${y(cum + v) - 5}" font-size="9.5" text-anchor="middle" fill="#14202e">${fmtM(v)}</text>`;
    out += `<line x1="${x + bw}" x2="${x + bw + 8}" y1="${y(cum + v)}" y2="${y(cum + v)}" stroke="#c7ced8" stroke-dasharray="2 2"/>`;
    cum += v; x += bw + 8;
  });
  if (G.gap_m > 0) {
    out += `<rect x="${x}" y="${y(G.value_m)}" width="${bw}" height="${y(cum) - y(G.value_m)}" fill="#fdeeec" stroke="#d14b3d" stroke-dasharray="4 3" rx="3"/>
      <text x="${x + bw / 2}" y="${H - 18}" font-size="9.5" text-anchor="middle" fill="#d14b3d">Gap</text><text x="${x + bw / 2}" y="${y(G.value_m) - 5}" font-size="9.5" text-anchor="middle" fill="#d14b3d">${fmtM(G.gap_m)}</text>`;
    x += bw + 8;
  }
  out += `<rect x="${x}" y="${y(G.value_m)}" width="${bw}" height="${y(0) - y(G.value_m)}" fill="#c99a3b" rx="3"/><text x="${x + bw / 2}" y="${H - 18}" font-size="9.5" text-anchor="middle" fill="#8a6a1f">Goal</text>`;
  out += `<line x1="${L0 - 6}" x2="${W}" y1="${y(G.value_m)}" y2="${y(G.value_m)}" stroke="#c99a3b" stroke-width="1.5" stroke-dasharray="6 4"/>`;
  return `<svg viewBox="0 0 ${W} ${H}" width="100%">${out}</svg>`;
}
async function move(i, dir) {
  const o = [...PLAN], j = i + dir; if (j < 0 || j >= o.length) return;
  [o[i], o[j]] = [o[j], o[i]]; await api("/api/plan/order", { order: o }); loadPlan(); loadTargets();
}
$$("#goalChips button").forEach((b) => b.onclick = async () => { const [t, v] = b.dataset.g.split(":"); renderPlan(await api("/api/plan/assumptions", { goal_type: t, goal_value_m: v })); });
$("#clearPlan").onclick = async () => { await api("/api/plan/order", { order: [] }); loadPlan(); loadTargets(); };
$("#autoFill").onclick = async () => {
  // server picks the platform (best-scoring company you can afford as a first deal), then nearest tuck-ins to $1B
  const r = await api("/api/plan/auto", {});
  await loadPlan(); loadTargets();
  if (r.skipped && r.skipped.length) $("#planSkipped").innerHTML = skippedNote(r.skipped);
};
function skippedNote(sk) {
  return `<div class="skip-note"><b>Left out of the entry plan:</b> ${sk.slice(0, 6).map((x) => `${esc(x.name)} <span class="muted">(${esc(x.why === "Later stage" ? "rival roll-up — later merger / exit buyer" : "too large for a first deal")})</span>`).join(", ")}. Raise <i>Max first-deal EV</i> if you have a bigger cheque.</div>`;
}
$("#runStrategy").onclick = async () => {
  if (!STATUS.has_key) return alert("Add PORTKEY_API_KEY to .env first.");
  $("#runStrategy").disabled = true;
  const r = await api("/api/strategy/run", {});
  await pollRun(r.run_id, "#stratTrace", () => { $("#runStrategy").disabled = false; loadPlan(); });
};
function renderStrategy(s) {
  if (!s) return;
  const r = s.result, name = (id) => (TARGETS.find((t) => t.id === id) || { name: id }).name;
  $("#stratWhen").textContent = new Date(s.ts * 1000).toLocaleString();
  $("#strategy").innerHTML = `<div class="verdict"><div class="sc" style="font-size:13px;color:#9fb4ca;width:90px">PLATFORM</div><p><b style="font-size:14px;color:#fff">${esc(name(r.recommended_platform?.id))}</b><br>${esc(r.recommended_platform?.why)}</p></div>
    ${(r.phases || []).map((ph) => `<div class="phase"><div class="ph">${esc(ph.name)}</div><div class="deals">${ph.deals.map((d) => `<span class="chipd">${esc(name(d))}</span>`).join("") || '<span class="small muted">New targets to source</span>'}</div>
      <p class="small" style="margin:4px 0 8px">${esc(ph.rationale)}</p>${(ph.key_risks || []).map((k) => `<div class="risk medium"><div class="rtop"><b>${esc(k.risk)}</b></div><div class="mit"><b>Mitigation · </b>${esc(k.mitigation)}</div></div>`).join("")}</div>`).join("")}
    <div class="grid2" style="margin-top:6px"><div><div class="section-t">Closing the gap</div><p class="small" style="line-height:1.55">${esc(r.gap_closing_plan)}</p></div>
    <div><div class="section-t">White space</div><ul class="tight small">${(r.white_space || []).map((w) => `<li>${esc(w)}</li>`).join("")}</ul>
    <div class="section-t">Next 30 days</div><ol class="small" style="padding-left:18px">${(r.top_3_actions_next_30_days || []).map((w) => `<li>${esc(w)}</li>`).join("")}</ol></div></div>`;
}

// ------------------------------------------------------------------ costs
async function loadCosts() {
  const u = await api("/api/usage"); await loadStatus();
  const T = u.total;
  $("#costKpis").innerHTML = [["Model calls", fmtN(T.calls), ""], ["Input tokens", fmtN(T.input), ""], ["Cached input", fmtN(T.cached), T.input ? `${Math.round((100 * T.cached) / T.input)}% of input served from cache` : ""],
    ["Output tokens", fmtN(T.output), ""], ["Total spend", fmt$(T.cost, 4), STATUS.model], ["Spend today", fmt$(u.spend_today, 4), `cap ${fmt$(STATUS.daily_usd_cap, 2)}`]]
    .map(([l, v, s], i) => `<div class="kpi ${i === 4 ? "hero" : ""}"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${esc(s)}</div></div>`).join("");
  const maxc = Math.max(...u.by_agent.map((a) => a.cost || 0), 1e-9);
  $("#byAgent").innerHTML = `<table><tr><th>Agent</th><th class="n">Calls</th><th class="n">Input</th><th class="n">Cached</th><th class="n">Output</th><th class="n">Cost</th><th></th></tr>
    ${u.by_agent.map((a) => `<tr><td><b style="text-transform:capitalize">${esc(a.agent)}</b></td><td class="n">${a.calls}</td><td class="n">${fmtN(a.input)}</td><td class="n">${fmtN(a.cached)}</td><td class="n">${fmtN(a.output)}</td><td class="n">${fmt$(a.cost, 5)}</td>
      <td style="width:90px"><div style="height:6px;background:#eef1f5;border-radius:3px"><div style="height:6px;border-radius:3px;background:#0e9f8e;width:${(100 * (a.cost || 0)) / maxc}%"></div></div></td></tr>`).join("") || "<tr><td colspan=7 class='muted'>No calls yet.</td></tr>"}</table>`;
  const runs = u.runs.filter((r) => r.calls > 0);
  $("#runsTable").innerHTML = `<table><tr><th>Run</th><th>Type</th><th>Target</th><th>Status</th><th class="n">Calls</th><th class="n">Input</th><th class="n">Cached</th><th class="n">Output</th><th class="n">Cost</th><th class="n">Secs</th></tr>
    ${runs.map((r) => `<tr><td>#${r.id}</td><td>${esc(r.kind.replace("_", " "))}</td><td>${esc(r.name || "-")}</td><td>${esc(r.status)}</td><td class="n">${r.calls}</td><td class="n">${fmtN(r.input)}</td><td class="n">${fmtN(r.cached)}</td><td class="n">${fmtN(r.output)}</td><td class="n">${fmt$(r.cost, 5)}</td><td class="n">${r.finished ? (r.finished - r.started).toFixed(0) : "-"}</td></tr>`).join("") || "<tr><td colspan=10 class='muted'>No runs yet.</td></tr>"}</table>`;
  const desk = runs.filter((r) => r.kind === "deal_desk" && r.status === "done"), strat = runs.filter((r) => r.kind === "strategy" && r.status === "done");
  const avg = (a) => (a.length ? a.reduce((s, r) => s + r.cost, 0) / a.length : 0);
  const scale = () => {
    const per = avg(desk) * +$("#runsPerUser").value + avg(strat) * +$("#stratPerUser").value;
    $("#scale").innerHTML = `<p class="small muted">Measured average: deal desk ${fmt$(avg(desk), 5)} (${desk.length} runs) · strategist ${fmt$(avg(strat), 5)} (${strat.length} runs) · ${fmt$(per, 3)} per user per month.</p>
      <table><tr><th>Users</th><th class="n">Per month</th><th class="n">Per year</th></tr>${[1, 100, 10000].map((n) => `<tr><td>${fmtN(n)}</td><td class="n">${fmt$(per * n, 2)}</td><td class="n">${fmt$(per * n * 12, 2)}</td></tr>`).join("")}</table>`;
  };
  $("#runsPerUser").oninput = scale; $("#stratPerUser").oninput = scale; scale();
  $("#capUsd").value = STATUS.daily_usd_cap; $("#capTok").value = STATUS.run_token_cap;
  const p = STATUS.prices[STATUS.model] || {};
  $("#priceNote").textContent = `Prices (USD per 1M tokens) for ${STATUS.model}: input $${p.input} · cached input $${p.cached} · output $${p.output}. Source: ${STATUS.price_source}. Per-run limits: ${STATUS.limits.max_scout_steps} Scout steps, ${STATUS.limits.max_pages} pages × ${fmtN(STATUS.limits.page_chars)} characters, ${STATUS.limits.max_facts} facts.`;
}
$("#testModel").onclick = async () => {
  $("#testModel").textContent = "Testing…";
  const r = await api("/api/test-model", {});
  $("#testModel").textContent = "Test model connection";
  alert(r.ok ? `✓ ${STATUS.model} replied: "${r.reply}" (${r.usage.input} in / ${r.usage.output} out tokens)` : `✗ ${r.error}`);
  loadCosts();
};
$("#saveCaps").onclick = async () => { await api("/api/settings", { daily_usd_cap: $("#capUsd").value, run_token_cap: $("#capTok").value }); loadCosts(); };

// ------------------------------------------------------------------ safety
const GUARDS = [["Prompt-injection filter", "Scraped pages are scanned; instruction-like lines are removed and the rest is wrapped as untrusted data."],
  ["Domain allow-list", "The Scout may only open pages on the target's own website - no other domains, IPs, localhost or file:// (stops exfiltration and SSRF)."],
  ["Quote verifier", "Every fact must quote its source verbatim; invented facts are rejected in code, so analysis is built only on verified evidence."],
  ["Budget kill-switch", "Daily USD cap and per-run token cap checked before every model call; Scout limited to 8 steps and 4 pages."],
  ["Human approval", "Outreach letters are drafts; the app has no email capability. Claims of 'sent' are rewritten as drafts."],
  ["Secret hygiene", "Keys load from .env (repo or parent folder), never reach the browser, and are redacted from errors and logs."]];
function loadSafety() {
  $("#guardCards").innerHTML = GUARDS.map(([h, p]) => `<div class="card" style="margin:0"><div class="eyebrow" style="color:#0e9f8e">Guard</div><h3 style="margin:4px 0 6px">${h}</h3><p class="small muted" style="margin:0;line-height:1.5">${p}</p></div>`).join("");
  $("#guardCards").style.marginBottom = "16px";
  loadSecurity();
}
$("#runTests").onclick = async () => {
  const r = await api("/api/safety-tests", { live: false });
  $("#testResults").innerHTML = `<div class="kpis" style="margin-bottom:8px"><div class="kpi hero"><div class="l">Guard tests passed</div><div class="v">${r.passed} / ${r.total}</div></div></div>` +
    r.results.map((t) => `<div class="test ${t.passed ? "pass" : "fail"}"><span class="ic">${t.passed ? "✓" : "✗"}</span><div><b>${esc(t.test)}</b><div class="d">${esc(t.detail)}</div></div></div>`).join("");
  loadSecurity();
};
$("#runLive").onclick = async () => {
  if (!STATUS.has_key) return alert("Add PORTKEY_API_KEY to .env first.");
  const r = await api("/api/safety-tests", { live: true });
  $("#testResults").innerHTML = `<div class="test pass"><span class="ic">✓</span><div><b>${r.passed}/${r.total} guard tests passed</b><div class="d">Now watch the real agents read the booby-trapped site (run #${r.live_run_id}).</div></div></div>`;
  await pollRun(r.live_run_id, "#liveTrace", () => { loadSecurity(); loadTargets(); });
};
async function loadSecurity() {
  const ev = await api("/api/security");
  $("#secLog").innerHTML = `<table><tr><th>Time</th><th>Guard</th><th>Run</th><th>Detail</th></tr>${ev.map((e) => `<tr><td class="small">${new Date(e.ts * 1000).toLocaleString()}</td><td><span class="sev high">${esc(e.kind.replace(/_/g, " "))}</span></td><td>${e.run_id ?? ""}</td><td class="small">${esc(e.detail)}</td></tr>`).join("") || "<tr><td colspan=4 class='muted'>No events yet.</td></tr>"}</table>`;
}

// ------------------------------------------------------------------ thesis
async function loadThesis() {
  const { markdown } = await api("/api/thesis");
  $("#thesis").innerHTML = esc(markdown).replace(/^# (.*)$/gm, "<h1>$1</h1>").replace(/^## (.*)$/gm, "<h2>$1</h2>")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>").replace(/^- (.*)$/gm, "<li>$1</li>").replace(/^\d+\. (.*)$/gm, "<li>$1</li>").replace(/\n\n/g, "<br>");
}

// ------------------------------------------------------------------ boot
initMap(); loadStatus(); loadTargets(); fillThesis();
async function fillThesis() {
  try {
    const o = await api("/api/opportunity");
    $("#op-cov").textContent = o.coverage_x;
    $("#op-inv").textContent = o.investable;
    $("#op-rev").textContent = fmtM(o.revenue_m);
    $("#op-eb").textContent = fmtM(o.ebitda_m);
    $("#op-src").innerHTML = `Source: ATLAS estimate from ${o.mapped} companies mapped from public sources (IWDC 2026 directory, EIGA, company sites, trade press; see Sources below) · ${o.excluded} excluded (owned by majors or roll-ups) · high-risk countries removed · revenue = branches × $4m`;
    const tc = ["#f0c56a", "#c99a3b", "#2bc2a9", "#3b5a7d"], tot = o.tiers.reduce((a, t) => a + t.revenue_m, 0) || 1;
    $("#op-stack").innerHTML = o.tiers.map((t, i) => `<i style="width:${(100 * t.revenue_m) / tot}%;background:${tc[i]}" title="${t.name}"></i>`).join("");
    $("#op-tiers").innerHTML = o.tiers.map((t, i) => `<div class="tier"><span class="sw" style="background:${tc[i]}"></span><span><b>${t.count}</b> ${t.name} <span style="color:#6f86a0">(${t.range})</span></span><b>${fmtM(t.revenue_m)}</b><span class="m">${t.multiple ? t.multiple + "x" : ""}</span></div>`).join("");
    const rc = { US: "#2bc2a9", Canada: "#f0c56a", Europe: "#7f9cff", Other: "#3b5a7d" }, rt = Object.values(o.region_revenue_m).reduce((a, b) => a + b, 0) || 1;
    const regs = ["US", "Canada", "Europe", "Other"].filter((k) => o.region_revenue_m[k]);
    $("#op-reg").innerHTML = regs.map((k) => `<i style="width:${(100 * o.region_revenue_m[k]) / rt}%;background:${rc[k]}"></i>`).join("");
    $("#op-regleg").innerHTML = regs.map((k) => `<span><i style="background:${rc[k]}"></i>${k === "US" ? "USA" : k} ${fmtM(o.region_revenue_m[k])}</span>`).join("");
    const q = (v, l, pct) => `<div class="qs"><div class="qv">${v}</div><div><div class="ql">${l}</div>${pct != null ? `<div class="qbar"><i style="width:${pct}%"></i></div>` : ""}</div></div>`;
    $("#op-q").innerHTML = q(o.low_risk_pct + "%", "in low-risk countries (US, Canada, W. & N. Europe)", o.low_risk_pct) +
      q(o.platforms, "platform-scale independents (31+ branches)") +
      q(o.fill_count, "with their own fill plant / production") +
      q(o.family_pct + "%", "show family or founder succession signals", o.family_pct) +
      q(o.sponsors, "PE-owned exit candidates (secondary buyouts)");
    $("#op-val").innerHTML = `Top 50 targets: <b>${fmtM(o.top50.revenue_m)}</b> revenue bought at ~<b>${o.top50.blended_multiple}x</b> EBITDA → worth <b>${o.exit_multiple}x</b> as a scaled platform: <b>${fmtM(o.top50.value_created_m)}</b> multiple-arbitrage value. ~${o.deals_to_goal} deals reach $1B.`;
  } catch (e) { /* thesis still renders */ }
}

setInterval(loadStatus, 15000);


// ------------------------------------------------------------------ target list (ranking)
const LS = { n: 20, risk: new Set(["low", "medium"]), regions: new Set(["US", "Canada", "Europe", "Latin America", "Middle East", "China & SEA"]) };
$$("#topChips button").forEach((b) => b.onclick = () => { LS.n = +b.dataset.n; $$("#topChips button").forEach((x) => x.classList.toggle("on", x === b)); loadList(); });
$$("#riskChips button").forEach((b) => b.onclick = () => { b.classList.toggle("on"); LS.risk.has(b.dataset.k) ? LS.risk.delete(b.dataset.k) : LS.risk.add(b.dataset.k); loadList(); });
$$("#lrChips button").forEach((b) => b.onclick = () => { b.classList.toggle("on"); LS.regions.has(b.dataset.r) ? LS.regions.delete(b.dataset.r) : LS.regions.add(b.dataset.r); loadList(); });
let RANK = null;
async function loadList() {
  const q = `/api/ranking?risk=${[...LS.risk].join(",")}&region=${encodeURIComponent([...LS.regions].join(","))}`;
  RANK = await api(q);
  const rows = LS.n ? RANK.rows.slice(0, LS.n) : RANK.rows, goal = RANK.goal_m;
  const tier = (k, lab) => { const t = RANK.tiers[k]; return `<div class="kpi ${k === (LS.n === 20 ? "top20" : LS.n === 50 ? "top50" : "") ? "hero" : ""}"><div class="l">${lab}</div><div class="v">${fmtM(t.revenue_m)}</div><div class="s">${t.n} companies · ${t.pct_of_goal}% of $1B · EBITDA ${fmtM(t.ebitda_m)}<br>Est. cost ${fmtM(t.ev_m)} at ${t.blended_multiple}x · value created ${fmtM(t.value_created_m)}</div></div>`; };
  $("#listKpis").innerHTML = tier("top20", "Top 20 · est. revenue") + tier("top50", "Top 50 · est. revenue") + tier("all", `All ${RANK.total} targets · est. revenue`) +
    `<div class="kpi"><div class="l">Deals to reach $1B</div><div class="v">${RANK.deals_to_goal ?? "–"}</div><div class="s">if the highest-ranked targets all transact (in rank order)</div></div>`;
  $("#listTitle").textContent = LS.n ? `Top ${LS.n} targets` : `All ${RANK.total} targets`;
  $("#listNote").textContent = `Est. revenue = branches × $${RANK.rev_per_location_m}m · EV = EBITDA × entry multiple · exit at ${RANK.exit_multiple}x — estimates, editable on Path to $1B`;
  let goalShown = false;
  $("#rankTable").innerHTML = `<div style="overflow-x:auto"><table><tr><th title="Tick up to 4 to compare">⇆</th><th>#</th><th>Company</th><th>Region</th><th>Risk</th><th class="n">Branches</th><th class="n">Est. revenue</th><th class="n">Est. EBITDA</th><th class="n">Entry multiple</th><th class="n">Est. EV</th><th class="n">Value created</th><th style="width:150px">Cumulative revenue</th><th class="n">Score</th><th>Why it ranks here</th><th></th></tr>
    ${rows.map((r) => { const g = !goalShown && r.cum_revenue_m >= goal; if (g) goalShown = true;
      return `<tr class="${g ? "goal-row" : ""}"><td><input type="checkbox" class="cmpchk" data-cmp="${esc(r.id)}" ${CMP.has(r.id) ? "checked" : ""}></td><td class="rk ${r.rank <= 20 ? "rk1" : ""}">${r.rank}</td>
      <td><b>${esc(r.name)}</b>${r.status === "sponsor" ? ' <span class="badge sponsor" style="font-size:10px;padding:1px 6px">PE-owned</span>' : ""}${r.deal_stage ? ` <span class="dstage s${STAGES.indexOf(r.deal_stage)}">${esc(r.deal_stage)}</span>` : ""}${r.fin_basis !== "estimated" ? ' <span class="rep" title="Uses your own reported figures">R</span>' : ""}${r.entry_role === "Platform candidate" ? ' <span class="role-b plat" title="Big enough to be the platform, small enough to buy first">Platform</span>' : r.entry_role === "Later stage" ? ' <span class="role-b late" title="A rival roll-up: a merger partner or exit buyer once you have scale, not a first deal">Later stage</span>' : r.entry_role === "Too large for entry" ? ' <span class="role-b big" title="EV above your max first-deal size (editable on Path to $1B)">Too large to start</span>' : ""}<div class="small muted">${esc(r.city)}${r.region_state ? ", " + esc(r.region_state) : ""} · ${esc(r.country)}</div></td>
      <td class="small">${esc(r.region_label)}</td><td><span class="risk-b ${r.risk}">${r.risk}</span></td>
      <td class="n">${r.locations ?? '<span class="muted">?</span>'}</td><td class="n">${fmtM(r.est_revenue_m)}</td><td class="n">${fmtM(r.est_ebitda_m)}</td>
      <td class="n" title="${esc(r.band + (r.adjustments.length ? " · " + r.adjustments.join(", ") : ""))}"><b>${r.entry_multiple}x</b><div class="small muted">${esc(r.band)}</div></td>
      <td class="n">${fmtM(r.est_ev_m)}</td><td class="n" style="color:var(--green)">+${fmtM(r.value_created_m)}<div class="small muted">${r.arbitrage_x > 0 ? "+" : ""}${r.arbitrage_x}x</div></td>
      <td><span class="small num">${fmtM(r.cum_revenue_m)}${g ? " ← $1B reached" : ""}</span><div class="small muted">capital ${fmtM(r.cum_ev_m)}</div><div class="cumbar"><i style="width:${Math.min(100, (100 * r.cum_revenue_m) / goal)}%"></i></div></td>
      <td class="n"><button class="score-btn" data-why="${esc(r.id)}" title="See how this score is built">${Math.round(r.score)}<i style="width:${r.score}%"></i></button>${r.agent_score != null ? `<div class="small muted">agent ${Math.round(r.agent_score)}</div>` : ""}</td>
      <td style="min-width:240px"><div class="whys">${r.why.slice(0, 5).map((w) => `<span>${esc(w)}</span>`).join("")}</div></td>
      <td style="white-space:nowrap"><button data-open="${esc(r.id)}" style="padding:4px 9px;font-size:11.5px">Open</button>${r.deal_stage ? "" : ` <button data-track="${esc(r.id)}" style="padding:4px 9px;font-size:11.5px" title="Add to your pipeline as Sourced">Track</button>`}</td></tr>`; }).join("")}</table></div>
    <p class="small muted">${esc(RANK.valuation_note)}</p><p class="small muted">${esc(RANK.risk_note)}</p>`;
  $$("[data-open]").forEach((b) => b.onclick = () => { goTab("map"); setTimeout(() => select(b.dataset.open, true), 250); });
  $$("[data-why]").forEach((b) => b.onclick = () => showWhy(RANK.rows.find((r) => r.id === b.dataset.why)));
  $$("[data-track]").forEach((b) => b.onclick = async () => { await api(`/api/targets/${b.dataset.track}/update`, { deal_stage: "Sourced" }); loadList(); });
  $$(".cmpchk").forEach((c) => c.onchange = () => { c.checked ? CMP.add(c.dataset.cmp) : CMP.delete(c.dataset.cmp); if (CMP.size > 10) { CMP.delete(c.dataset.cmp); c.checked = false; alert("Select up to 10 companies at a time."); } cmpBar(); });
  cmpBar();
  loadExclusions();
}
$("#toPlan").onclick = async () => {
  const n = LS.n || 50;
  const r = await api("/api/plan/top", { n, risk: [...LS.risk], regions: [...LS.regions] });
  await loadTargets(); goTab("plan");
  setTimeout(() => { $("#planSkipped").innerHTML = r.skipped && r.skipped.length ? skippedNote(r.skipped) : ""; }, 300);
};
async function loadExclusions() {
  const d = await api("/api/excluded");
  const all = d.on_map.map((x) => ({ name: x.name, owner: x.ownership, country: x.country }))
    .concat(d.excluded_research.filter((e) => !d.on_map.some((m) => m.name === e.name)).map((e) => ({ name: e.name, owner: e.reason || e.owner, country: e.country || "" })));
  const groups = {};
  all.forEach((x) => { const o = (x.owner || "Other").toLowerCase(); const k = /meritus/.test(o) ? "Meritus (AEA)" : /airgas|air liquide/.test(o) ? "Air Liquide / Airgas" : /linde|praxair|boc|afrox/.test(o) ? "Linde / Praxair" : /air products/.test(o) ? "Air Products" : /messer/.test(o) ? "Messer" : /nippon|matheson|taiyo/.test(o) ? "Nippon Sanso / Matheson" : /\bsol\b/.test(o) ? "SOL" : /american welding|awg/.test(o) ? "American Welding & Gas" : /holston/.test(o) ? "Holston" : /listed|tier-1|major/.test(o) ? "Tier-1 majors (HQ)" : "Other acquirers / merged"; (groups[k] = groups[k] || []).push(x); });
  $("#exclusions").innerHTML = `<p class="small muted">${all.length} companies are excluded because a Tier-1 major or a roll-up already owns them — buying them would mean buying from a strategic that is not a natural seller, at strategic prices. They stay on the map (grey) as competitive context.</p>
    <div class="ex-own">${Object.entries(groups).sort((a, b) => b[1].length - a[1].length).map(([k, v]) => `<div><b>${esc(k)}</b>${v.length} companies</div>`).join("")}</div>
    <details><summary class="small">Show all ${all.length} exclusions with reasons</summary><div style="overflow-x:auto;margin-top:8px"><table><tr><th>Company</th><th>Country</th><th>Why excluded</th></tr>
    ${all.map((x) => `<tr><td>${esc(x.name)}</td><td class="small">${esc(x.country)}</td><td class="small">${esc(x.owner)}</td></tr>`).join("")}</table></div></details>`;
}

// ------------------------------------------------------------------ outreach
let OB = "all";
$$("#obChips button").forEach((b) => b.onclick = () => { OB = b.dataset.o; $$("#obChips button").forEach((x) => x.classList.toggle("on", x === b)); loadOutreach(); });
async function loadOutreach() {
  if (typeof renderTpl === "function") renderTpl();
  const rows = await api("/api/outreach");
  const cnt = (s) => rows.filter((r) => r.outreach_status === s).length;
  $("#obKpis").innerHTML = [["Letters drafted", rows.length], ["Awaiting approval", cnt("draft")], ["Approved (not sent)", cnt("approved")], ["Rejected", cnt("rejected")]]
    .map(([l, v]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("");
  const sel = rows.filter((r) => OB === "all" || r.outreach_status === OB);
  $("#obList").innerHTML = sel.length ? sel.map((r) => { const a = JSON.parse(r.analysis_json || "{}");
    return `<div class="ob"><div><span class="stamp ${r.outreach_status === "approved" ? "ok" : ""}">${r.outreach_status === "approved" ? "APPROVED · NOT SENT" : r.outreach_status === "rejected" ? "REJECTED" : "DRAFT"}</span>
      <h3 style="margin-top:10px">${esc(r.name)}</h3><div class="small muted">${esc(r.city)}${r.region_state ? ", " + esc(r.region_state) : ""} · ${esc(r.country)}${r.score != null ? " · score " + Math.round(r.score) : ""}</div>
      <p class="small" style="line-height:1.5">${esc((a.investment_summary || "").slice(0, 220))}${(a.investment_summary || "").length > 220 ? "…" : ""}</p>
      <div style="display:flex;gap:6px;flex-wrap:wrap">${r.outreach_status !== "approved" ? `<button class="ok" data-ap="${esc(r.id)}">Approve</button>` : ""}${r.outreach_status !== "rejected" ? `<button class="danger" data-rj="${esc(r.id)}">Reject</button>` : ""}<button data-cp="${esc(r.id)}">Copy text</button><button data-open="${esc(r.id)}">Open target</button></div></div>
      <div class="letter" id="L-${esc(r.id)}">${esc(a.outreach_letter || "")}</div></div>`; }).join("")
    : `<div class="empty">No letters yet. Open a target on the Acquisition Map or Target List and click <b>Run deal desk</b> — the Analyst drafts a soft, conversation-first owner letter for your approval.</div>`;
  $$("[data-ap]").forEach((b) => b.onclick = async () => { await api(`/api/targets/${b.dataset.ap}/approve`, {}); loadOutreach(); });
  $$("[data-rj]").forEach((b) => b.onclick = async () => { await api(`/api/targets/${b.dataset.rj}/reject`, {}); loadOutreach(); });
  $$("[data-cp]").forEach((b) => b.onclick = () => { navigator.clipboard?.writeText($("#L-" + CSS.escape(b.dataset.cp)).innerText); b.textContent = "Copied ✓"; });
  $$("#obList [data-open]").forEach((b) => b.onclick = () => { goTab("map"); setTimeout(() => select(b.dataset.open, true), 250); });
}


// ------------------------------------------------------------------ strategy
async function loadStrategy() {
  const s = await api("/api/strategy");
  const R = Object.fromEntries(s.regions.map((r) => [r.region, r]));
  const us = R["US"], ca = R["Canada"], eu = R["Europe"];
  $("#stMethod").textContent = s.method;
  $("#stHero").innerHTML = `<div class="kpis">
    <div class="kpi hero"><div class="l">Priority markets</div><div class="v" style="font-size:19px">US · Canada · Europe</div><div class="s">${(us.investable + ca.investable + eu.investable)} investable targets · selective elsewhere</div></div>
    <div class="kpi"><div class="l">Canada entry multiple</div><div class="v">${ca.avg_multiple}x</div><div class="s">vs ${us.avg_multiple}x US · ${ca.taken_share_pct}% already consolidated · Meritus: ${ca.meritus}</div></div>
    <div class="kpi"><div class="l">US consolidation pressure</div><div class="v">${us.taken_share_pct}%</div><div class="s">${us.taken} taken out · ${us.meritus} by Meritus · ${us.recent_deals} deals 2024–26</div></div>
    <div class="kpi"><div class="l">PE-owned exit candidates</div><div class="v">${s.sponsors.length}</div><div class="s">secondary-buyout pipeline (Meritus/AEA ~5.8 yrs)</div></div></div>`;
  $("#stTable").innerHTML = `<div style="overflow-x:auto"><table><tr><th>Region</th><th>Attractiveness</th><th class="n">Investable targets</th><th class="n">Est. revenue</th><th class="n">Avg entry multiple</th><th class="n">Already consolidated</th><th class="n">Targets per rival</th><th class="n">Meritus cos</th><th class="n">Succession signals</th><th class="n">Market growth</th><th>Market size</th></tr>
    ${s.regions.filter((r) => r.region !== "Europe").map((r) => `<tr><td><b>${esc(r.label)}</b>${r.sub ? '<div class="small muted">Europe split</div>' : ""}</td><td><div style="display:flex;gap:8px;align-items:center"><div class="abar"><i style="width:${r.attractiveness}%"></i></div><b>${r.attractiveness}</b></div></td>
      <td class="n">${r.investable}</td><td class="n">${fmtM(r.est_revenue_m)}</td><td class="n"><b>${r.avg_multiple ?? "–"}x</b></td><td class="n">${r.taken_share_pct}%</td>
      <td class="n">${r.targets_per_rival}</td><td class="n">${r.meritus}</td><td class="n">${r.succession_pct}%</td><td class="n">${r.growth_cagr ? "+" + r.growth_cagr + "%" : "–"}</td><td class="small muted">${esc(r.market)}</td></tr>`).join("")}</table></div>
    <p class="small muted">Est. revenue uses branch counts where known (else ${s.assumptions.rev_per_location_m ? 3 : 3} branches) × $${s.assumptions.rev_per_location_m}m — Canada's total is inflated by many small companies with unknown branch counts. High-risk countries are excluded from "investable".</p>`;
  $("#stCanada").innerHTML = canadaHTML(s.canada);
  const pill = (pri, tag, title, body) => `<div class="card ${pri ? "pri" : ""}"><div class="tagp">${tag}</div><h3>${title}</h3>${body}</div>`;
  $("#stPillars").innerHTML = [
    pill(true, "Priority 1", "Canada: cheaper entry, no Meritus", `<p>Average entry ~<b>${ca.avg_multiple}x</b> EBITDA vs ~${us.avg_multiple}x in the US, <b>${ca.investable}</b> investable independents, <b>${ca.taken_share_pct}%</b> already consolidated and <b>no Meritus presence</b>. Fastest-growing North American market (+6.3% vs +6.2% US CAGR).</p>
      <ul><li>Platform: Innovair (Winnipeg, self-described largest independent) or Core Industrial Gases (ON).</li><li>Hub-and-spoke tuck-ins: Josef Gas, Lamarre, Nova Industrial, Western Gasco, CamCarb.</li><li>Risk: many are dealers of Air Liquide/Linde — secure supply and change-of-control terms first.</li></ul>`),
    pill(true, "Priority 2", "US core: scale where rivals are absent", `<p>Largest pool: <b>${us.investable}</b> investable targets (~${fmtM(us.est_revenue_m)} est. revenue), but <b>${us.meritus}</b> companies already went to Meritus and ${us.recent_deals} deals closed 2024–26.</p>
      <ul><li>Entry platform sized for a first cheque: Red Ball Oxygen (Gulf South, 23 br.) or Lampton (Plains, 17 br.). Gas and Supply and Norco (~$500–700m EV) are step-two combinations once you have scale.</li><li>AWG, Arc3 and Holston are rival roll-ups: later merger partners or exit buyers, not entry deals.</li><li>Go where Meritus is thin: Gulf South, Plains, Upper Midwest, New England.</li><li>Route density: cluster tuck-ins within 150 miles for +2–4 margin points.</li></ul>`),
    pill(false, "Pillar 3", "Succession wave", `<p>${us.succession_pct}% of US and ${eu.succession_pct}% of European targets show family/founder signals; multi-generation owners are flagged in the Target List.</p>
      <ul><li>Lead with legacy: keep the name, team and branches (the Meritus playbook).</li><li>Rollover equity + earn-outs + 12–24 month transition.</li><li>Proprietary outreach before owners hire bankers (Outreach tab).</li></ul>`),
    pill(false, "Pillar 4", "Secondary buyouts", `<p>${s.sponsors.length} PE-owned rivals, led by <b>Meritus (AEA, since Dec-2020)</b> — ~30 companies, 100+ locations; the CEO expects recapitalisations.</p>
      <ul><li>Option A: acquire / co-invest in a Meritus recap as a step-change to $1B.</li><li>Option B: buy sponsor-owned regionals at exit (B&amp;J / American Gas Group ~2027–28).</li><li>Expect ~+1x vs independents (auction premium).</li></ul>`),
    pill(false, "Pillar 5", "Supply of targets & window", `<p>Targets per rival: US <b>${us.targets_per_rival}</b>, Canada <b>${ca.targets_per_rival}</b>, Europe <b>${eu.targets_per_rival}</b>. The US window is closing as Meritus, AWG, Holston and Airgas keep buying; Europe and APAC are already ${eu.taken_share_pct}%/${R["China & SEA"].taken_share_pct}% consolidated.</p>
      <ul><li>Move first in Canada while competition is light.</li><li>Lock up 2–3 platforms in 12–18 months.</li></ul>`),
    pill(false, "Pillar 6", "Europe: selective, family mid-caps", `<p>${eu.investable} investable targets at ~${eu.avg_multiple}x; strong succession signals (${eu.succession_pct}%), but ${eu.taken_share_pct}% already consolidated by majors/SOL.</p>
      <ul><li>Nordics &amp; DACH family groups (Woikoski, BUSE, Tyczka), UK independents (Pro Gases).</li><li>Different regime (ADR, EIGA) — enter via a local platform partner.</li></ul>`),
  ].join("");
  const tot = s.path.reduce((a, p) => a + p.revenue_m, 0), cap = s.path.reduce((a, p) => a + p.ev_m, 0);
  const cols = ["#0b1726", "#c99a3b", "#0e9f8e"];
  $("#stPath").innerHTML = s.path.map((p, i) => `<div class="ph-row"><div><b>${esc(p.phase)}</b><div class="small muted">${p.deals} deals · e.g. ${esc(p.names.slice(0, 3).join(", "))}</div></div>
      <div class="ph-bar"><i style="width:${Math.min(100, (100 * p.revenue_m) / 1000)}%;background:${cols[i]}"></i></div>
      <div class="num"><b>${fmtM(p.revenue_m)}</b><div class="small muted">revenue</div></div><div class="num">${fmtM(p.ev_m)}<div class="small muted">est. cost</div></div><div class="num">${p.multiple ?? "–"}x</div></div>`).join("") +
    `<div class="ph-row" style="border:none"><div><b>Total</b></div><div class="ph-bar"><i style="width:${Math.min(100, tot / 10)}%;background:linear-gradient(90deg,#0b1726,#c99a3b,#0e9f8e)"></i></div><div class="num"><b>${fmtM(tot)}</b></div><div class="num"><b>${fmtM(cap)}</b></div><div class="num">${(cap / (tot * s.assumptions.ebitda_margin_pct / 100)).toFixed(1)}x</div></div>
    <p class="small muted">Accelerator: a secondary buyout of a scaled PE-owned roll-up could replace several US tuck-ins in one transaction, at a higher multiple. Load any combination into Path to $1B to model it.</p>`;
  $("#stIdeas").innerHTML = [
    pill(false, "Niche", "Medical & home oxygen", "<p>Ageing demographics; sticky, reimbursed volumes. Canada has many small home-oxygen providers — bolt onto a gas platform for density.</p>"),
    pill(false, "Niche", "Beverage CO₂ & dry ice", "<p>Recurring F&amp;B demand and periodic CO₂ shortages support pricing; own CO₂ supply is a moat.</p>"),
    pill(false, "Growth", "Specialty gases for AI / semis", "<p>Datacenter and semiconductor build-out lifts specialty and high-purity demand — the thesis's AI-infrastructure tailwind.</p>"),
    pill(false, "Lever", "Dealer conversion", "<p>Many independents are dealers for a major. As a scaled buyer, renegotiate or dual-source supply and capture the producer margin.</p>"),
    pill(false, "Lever", "Procurement & telemetry", "<p>IWDC co-op purchasing (~$4.5bn) plus telemetry-driven dispatch: lower gas/cylinder costs and fewer driver hours.</p>"),
    pill(false, "Risk", "Avoid high country risk", "<p>Turkey, Egypt, Nigeria, Kenya, Pakistan, Argentina, Ukraine are filtered out by default; Mexico/GCC/India only selectively, with local partners.</p>"),
  ].join("");
}

// ================================================================== day-to-day tools
var STAGES = ["Sourced", "Contacted", "Meeting held", "NDA signed", "IOI / LOI", "Diligence", "Closed", "Passed"];
var CMP = new Set();
const fmtX = (v) => (v == null ? "–" : Number(v).toFixed(1) + "x");
const pct = (v) => (v == null ? "–" : Number(v).toFixed(1) + "%");
function wideModal(html) { modal(html); $("#modalCard").classList.add("wide"); }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("#modalCard").classList.remove("wide"); });

// ---------- score breakdown
function showWhy(r) {
  if (!r) return;
  const parts = r.parts || [], max = Math.max(30, ...parts.map((p) => Math.abs(p.pts)));
  const raw = parts.reduce((a, p) => a + p.pts, 0);
  modal(`<div class="why-h"><div><div class="eyebrow">Why it ranks #${r.rank}</div><h3 style="margin:2px 0 0">${esc(r.name)}</h3></div><div class="why-sc">${Math.round(r.score)}<small>/100</small></div></div>
    <div class="why-list">${parts.map((p) => `<div class="why-row"><span class="f">${esc(p.factor)}</span><span class="l">${esc(p.label)}</span>
      <span class="bar ${p.pts < 0 ? "neg" : ""}"><i style="width:${(100 * Math.abs(p.pts)) / max}%"></i></span><b class="${p.pts < 0 ? "neg" : ""}">${p.pts > 0 ? "+" : ""}${Number(p.pts).toFixed(p.pts % 1 ? 1 : 0)}</b></div>`).join("")}</div>
    <div class="why-foot"><span>Pre-screen ${raw.toFixed(1)}${raw > 100 ? " → capped at 100" : ""}</span>${r.agent_score != null ? `<span>${r.agent_weight ? `Blended ${Math.round(100 - 100 * r.agent_weight)}/${Math.round(100 * r.agent_weight)} with the Screener agent's ${Math.round(r.agent_score)} (${r.verified_facts} verified facts)` : `Screener score ${Math.round(r.agent_score)} not blended in: no verified facts yet`} → <b>${Math.round(r.score)}</b></span>` : `<span class="muted">Run the deal desk to blend in the Screener agent's score</span>`}</div>
    <p class="small muted" style="margin:10px 0 0">Valuation: ${esc(r.band)} at ${r.entry_multiple}x${r.adjustments.length ? " (" + esc(r.adjustments.join(", ")) + ")" : ""}, EV ${fmtM(r.est_ev_m)} on ${r.fin_basis === "estimated" ? "estimated" : "<b>your</b>"} EBITDA of ${fmtM(r.est_ebitda_m)}.</p>
    <div style="display:flex;justify-content:flex-end;margin-top:14px"><button onclick="closeModal()">Close</button></div>`);
}

// ---------- compare
function cmpBar() {
  const bar = $("#cmpBar"); if (!bar) return;
  bar.classList.toggle("hidden", CMP.size === 0);
  $("#cmpN").textContent = `${CMP.size} selected${CMP.size > 4 ? " · compare shows up to 4" : CMP.size < 2 ? " · pick 2+ to compare" : ""}`;
  $("#cmpGo").disabled = CMP.size < 2 || CMP.size > 4;
  $("#cmpGo").title = CMP.size > 4 ? "Compare works with 2-4 companies; Research selected works with up to 10" : "";
}
$("#cmpClear").onclick = () => { CMP.clear(); $$(".cmpchk").forEach((c) => (c.checked = false)); cmpBar(); };
$("#cmpGo").onclick = async () => {
  const rows = [...CMP].map((id) => RANK.rows.find((r) => r.id === id)).filter(Boolean);
  const det = await Promise.all(rows.map((r) => api("/api/targets/" + r.id)));
  const scr = det.map((d) => (d.target.screen_json ? JSON.parse(d.target.screen_json) : null));
  const an = det.map((d) => (d.target.analysis_json ? JSON.parse(d.target.analysis_json) : null));
  const best = (vals, hi = true) => { const n = vals.filter((v) => v != null); if (n.length < 2 || new Set(n).size === 1) return -1; const b = hi ? Math.max(...n) : Math.min(...n); return vals.indexOf(b); };
  const row = (label, vals, fmt = (v) => v, hi = null) => { const b = hi === null ? -1 : best(vals, hi);
    return `<tr><th>${label}</th>${vals.map((v, i) => `<td class="${i === b ? "best" : ""}">${v == null || v === "" ? '<span class="muted">–</span>' : fmt(v)}</td>`).join("")}</tr>`; };
  const top = (r) => [...(r.parts || [])].sort((a, b) => b.pts - a.pts).slice(0, 4).map((p) => `<span class="chipd">${esc(p.factor)} +${Math.round(p.pts)}</span>`).join(" ");
  wideModal(`<div class="why-h"><div><div class="eyebrow">Side-by-side</div><h3 style="margin:2px 0 0">Compare targets</h3></div><button onclick="closeModal()">Close</button></div>
    <div style="overflow-x:auto"><table class="cmp"><tr><th></th>${rows.map((r) => `<td class="cmp-h"><b>${esc(r.name)}</b><div class="small muted">${esc(r.city)}${r.region_state ? ", " + esc(r.region_state) : ""} · ${esc(r.country)}</div></td>`).join("")}</tr>
    ${row("Rank", rows.map((r) => r.rank), (v) => "#" + v, false)}
    ${row("Score", rows.map((r) => Math.round(r.score)), (v) => `<b>${v}</b>`, true)}
    ${row("Score drivers", rows.map(top), (v) => v)}
    ${row("Type", rows.map((r) => (r.status === "sponsor" ? "PE-owned (secondary)" : r.status === "consolidator" ? "Independent consolidator" : "Independent")))}
    ${row("Ownership", rows.map((r) => esc(r.ownership)))}
    ${row("Country risk", rows.map((r) => `<span class="risk-b ${r.risk}">${r.risk}</span>`))}
    ${row("Branches", rows.map((r) => r.locations), (v) => v, true)}
    ${row("Revenue", rows.map((r) => r.est_revenue_m), fmtM, true)}
    ${row("EBITDA", rows.map((r) => r.est_ebitda_m), fmtM, true)}
    ${row("Financials", rows.map((r) => (r.fin_basis === "estimated" ? "estimate" : "<b>your figures</b>")))}
    ${row("Entry multiple", rows.map((r) => r.entry_multiple), fmtX, false)}
    ${row("Est. EV (cost)", rows.map((r) => r.est_ev_m), fmtM, false)}
    ${row("Value created at exit", rows.map((r) => r.value_created_m), fmtM, true)}
    ${row("Screener verdict", scr.map((x) => (x ? `<b>${Math.round(x.score)}</b> · ${esc(x.role_in_rollup || "")}<div class="small">${esc(x.headline || "")}</div>` : null)))}
    ${row("Top risks", an.map((a) => (a && a.risks ? a.risks.slice(0, 3).map((k) => `<div class="small">• ${esc(k.risk)} <span class="sev ${esc(k.severity)}">${esc(k.severity)}</span></div>`).join("") : null)))}
    ${row("Verified facts", det.map((d) => d.facts.filter((f) => f.verified).length), (v) => v, true)}
    ${row("Deal stage", rows.map((r) => r.deal_stage || null), (v) => esc(v))}
    </table></div><p class="small muted" style="margin:8px 0 0">Green = best in row. Screener verdict and risks appear once the deal desk has been run on a company.</p>`);
};

// ---------- deal tracking (drawer)
function dealPane(t) {
  const log = JSON.parse(t.deal_log || "[]").slice().reverse();
  return `<div class="deal-steps">${STAGES.slice(0, 7).map((s, i) => `<button data-stage="${s}" class="${t.deal_stage === s ? "on" : STAGES.indexOf(t.deal_stage) > i && t.deal_stage !== "Passed" ? "past" : ""}">${s}</button>`).join("")}</div>
    <div style="display:flex;gap:8px;margin:6px 0 14px"><button data-stage="Passed" class="${t.deal_stage === "Passed" ? "danger on" : "danger"}" style="font-size:11.5px">Pass</button>${t.deal_stage ? `<button data-stage="" class="ghost" style="font-size:11.5px">Stop tracking</button>` : ""}</div>
    <div class="assump">
      <label>Next step<input id="dNext" value="${esc(t.next_step)}" placeholder="e.g. Intro call with owner"></label>
      <label>Due date<input id="dDate" type="date" value="${esc(t.next_date)}"></label>
      <label>Contact (role)<input id="dRole" value="${esc(t.deal_contact_role)}" placeholder="e.g. Owner / CEO"></label>
      <label>Revenue $m (yours)<input id="dRev" type="number" step="any" value="${t.known_revenue_m ?? ""}" placeholder="from CIM / teaser"></label>
      <label>EBITDA $m (yours)<input id="dEb" type="number" step="any" value="${t.known_ebitda_m ?? ""}" placeholder="overrides the estimate"></label>
      <label>&nbsp;<button class="primary" id="dSave">Save</button></label>
    </div>
    <p class="small muted" style="margin:6px 0 0">Your revenue / EBITDA replace the branch-based estimate in the ranking, valuation and Path to $1B.</p>
    <div class="section-t">Deal log</div>
    <div style="display:flex;gap:6px"><input id="dNote" placeholder="Add a note: call summary, price expectations, next steps…"><button id="dAdd">Add</button></div>
    <div class="dlog">${log.length ? log.map((l) => `<div class="${l.auto ? "auto" : ""}"><span>${new Date(l.ts * 1000).toLocaleDateString()} ${new Date(l.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>${esc(l.text)}</div>`).join("") : '<div class="muted small">No notes yet.</div>'}</div>`;
}
function wireDeal(t) {
  const refresh = async () => { await select(t.id); loadTargets(); };
  $$("[data-stage]").forEach((b) => b.onclick = async () => { await api(`/api/targets/${t.id}/update`, { deal_stage: b.dataset.stage }); refresh(); });
  $("#dSave").onclick = async () => { await api(`/api/targets/${t.id}/update`, { next_step: $("#dNext").value, next_date: $("#dDate").value, deal_contact_role: $("#dRole").value, known_revenue_m: $("#dRev").value, known_ebitda_m: $("#dEb").value }); $("#dSave").textContent = "Saved ✓"; setTimeout(refresh, 400); };
  const add = async () => { const v = $("#dNote").value.trim(); if (!v) return; await api(`/api/targets/${t.id}/log`, { text: v }); refresh(); };
  $("#dAdd").onclick = add; $("#dNote").onkeydown = (e) => { if (e.key === "Enter") add(); };
}

// ---------- pipeline tab
async function loadPipeline() {
  const d = await api("/api/pipeline"), T = d.totals, today = new Date().toISOString().slice(0, 10);
  $("#pipeKpis").innerHTML = [
    ["Active deals", T.active, `${T.closed} closed`],
    ["Pipeline revenue", fmtM(T.revenue_m), `${Math.round((100 * T.revenue_m) / d.goal_m)}% of $1B if everything closes`],
    ["Probability-weighted", fmtM(T.weighted_revenue_m), `${Math.round((100 * T.weighted_revenue_m) / d.goal_m)}% of $1B · stage odds below`],
    ["Closed revenue", fmtM(T.closed_revenue_m), `weighted EV in play ${fmtM(T.weighted_ev_m)}`],
  ].map(([l, v, s], i) => `<div class="kpi ${i === 2 ? "hero" : ""}"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${esc(s)}</div></div>`).join("");
  $("#board").innerHTML = d.stages.map((st, i) => { const rs = d.rows.filter((r) => r.deal_stage === st);
    return `<div class="col s${i}"><div class="col-h"><b>${st}</b><span>${rs.length} · ${Math.round(d.prob[st] * 100)}%</span></div>
      ${rs.map((r) => `<div class="pc"><div class="pc-t" data-popen="${esc(r.id)}">${esc(r.name)}</div><div class="small muted">${esc(r.city)}${r.region_state ? ", " + esc(r.region_state) : ""} · ${fmtM(r.est_revenue_m)}${r.fin_basis !== "estimated" ? ' <span class="rep">R</span>' : ""}</div>
        ${r.next_step ? `<div class="pc-n ${r.next_date && r.next_date < today ? "late" : ""}">${esc(r.next_step)}${r.next_date ? " · " + esc(r.next_date) : ""}</div>` : ""}
        <select data-pmove="${esc(r.id)}">${d.stages.map((s) => `<option ${s === st ? "selected" : ""}>${s}</option>`).join("")}</select></div>`).join("") || '<div class="col-empty">–</div>'}</div>`; }).join("");
  const nx = d.rows.filter((r) => r.next_step && !["Closed", "Passed"].includes(r.deal_stage)).sort((a, b) => (a.next_date || "9999").localeCompare(b.next_date || "9999"));
  $("#nextSteps").innerHTML = nx.length ? nx.map((r) => `<div class="ns ${r.next_date && r.next_date < today ? "late" : ""}"><div class="d">${r.next_date ? esc(r.next_date) : "no date"}</div><div><b data-popen="${esc(r.id)}">${esc(r.name)}</b><div class="small">${esc(r.next_step)}</div><div class="small muted">${esc(r.deal_stage)}${r.deal_contact_role ? " · " + esc(r.deal_contact_role) : ""}</div></div></div>`).join("")
    : `<div class="empty">No next steps yet. Open a company → <b>Deal</b> tab → set a next step and due date.</div>`;
  if (!d.rows.length) $("#board").insertAdjacentHTML("beforebegin", `<div class="empty" id="pipeEmpty">Your pipeline is empty. In the <b>Target List</b>, click <b>Track</b> next to a company, or open any company and use its <b>Deal</b> tab.</div>`);
  else $("#pipeEmpty")?.remove();
  $$("[data-pmove]").forEach((s) => s.onchange = async () => { await api(`/api/targets/${s.dataset.pmove}/update`, { deal_stage: s.value }); loadPipeline(); });
  $$("[data-popen]").forEach((b) => b.onclick = () => { subtab = "deal"; goTab("map"); setTimeout(() => select(b.dataset.popen, true), 250); });
}
$("#exportPipe").onclick = () => { location.href = "/api/export/pipeline.csv"; };
$("#exportList").onclick = () => { location.href = `/api/export/targets.csv?risk=${[...LS.risk].join(",")}&region=${encodeURIComponent([...LS.regions].join(","))}`; };

// ---------- returns (Path to $1B)
function returnsHTML(p) {
  const R = p.returns, a = p.assumptions;
  if (!R) return `<div class="empty">Add deals to see sponsor returns.</div>`;
  const vb = R.value_bridge, tot = vb.ebitda_growth_m + vb.multiple_arbitrage_m + vb.debt_paydown_m + vb.fees_m;
  const seg = [["EBITDA growth", vb.ebitda_growth_m, "#0e9f8e"], ["Multiple arbitrage", vb.multiple_arbitrage_m, "#c99a3b"], ["Debt paydown", vb.debt_paydown_m, "#2f5d8a"]];
  const col = (m) => (m >= 3 ? "g3" : m >= 2.5 ? "g2" : m >= 2 ? "g1" : "g0");
  return `<div class="ret-top">
      <div class="ret-big"><div class="l">Gross IRR</div><div class="v">${R.irr_pct != null ? R.irr_pct.toFixed(0) + "%" : "–"}</div></div>
      <div class="ret-big"><div class="l">MOIC</div><div class="v">${R.moic != null ? R.moic.toFixed(1) + "x" : "–"}</div></div>
      <div class="ret-kv"><div><span>Equity in</span><b>${fmtM(R.equity_in_m)}</b></div><div><span>Acquisition debt</span><b>${fmtM(R.debt_m)}</b></div>
        <div><span>Exit EBITDA (yr ${a.hold_years})</span><b>${fmtM(R.exit_ebitda_m)}</b></div><div><span>Exit EV at ${a.exit_multiple}x</span><b>${fmtM(R.exit_ev_m)}</b></div>
        <div><span>Net debt at exit</span><b>${fmtM(R.net_debt_exit_m)}</b></div><div><span>Equity out</span><b>${fmtM(R.equity_out_m)}</b></div></div></div>
    <div class="section-t">Where the equity gain comes from · ${fmtM(tot)}</div>
    <div class="vb">${seg.map(([l, v, c]) => `<i style="flex:${Math.max(0.01, v)};background:${c}" title="${l}: ${fmtM(v)}"></i>`).join("")}</div>
    <div class="vb-l">${seg.map(([l, v, c]) => `<span><i style="background:${c}"></i>${l} <b>${fmtM(v)}</b> (${Math.round((100 * v) / tot)}%)</span>`).join("")}<span><i style="background:#d14b3d"></i>Fees <b>−${fmtM(Math.abs(vb.fees_m))}</b></span></div>
    <div class="section-t">Sensitivity · MOIC / IRR by exit multiple and organic growth</div>
    <table class="sens"><tr><th>Exit multiple ↓ · growth →</th>${R.growth_cols.map((g) => `<th>${g}%/yr</th>`).join("")}</tr>
      ${R.grid.map((row) => `<tr class="${row.exit_multiple === a.exit_multiple ? "base" : ""}"><th>${row.exit_multiple}x</th>${row.cells.map((c) => `<td class="${col(c.moic || 0)}">${c.moic != null ? c.moic.toFixed(1) + "x" : "–"}<span>${c.irr_pct != null ? c.irr_pct.toFixed(0) + "%" : ""}</span></td>`).join("")}</tr>`).join("")}</table>
    <p class="small muted">${esc(R.debt_note)} ${esc(R.note)} Most of the gain is multiple arbitrage: if competition pushes entry multiples up, use the Tuck-in multiple assumption to stress it.</p>`;
}

// ---------- Canada white space (Strategy)
function canadaHTML(c) {
  if (!c) return "";
  const mx = Math.max(...c.provinces.map((p) => Math.max(p.gdp_share_pct, p.supply_share_pct)));
  return `<div class="ca-grid"><div><table class="ca"><tr><th>Province</th><th style="width:34%">Demand (GDP share) vs supply of targets</th><th class="n">Targets</th><th class="n">Est. revenue</th><th class="n">Avg entry</th><th class="n">Dealer of a major</th><th>White space</th><th>Best names</th></tr>
    ${c.provinces.map((p) => `<tr><td><b>${esc(p.name)}</b></td>
      <td><div class="dual"><i class="d" style="width:${(100 * p.gdp_share_pct) / mx}%"></i></div><div class="dual"><i class="s" style="width:${(100 * p.supply_share_pct) / mx}%"></i></div><div class="small muted">${p.gdp_share_pct}% GDP · ${p.supply_share_pct}% of target revenue</div></td>
      <td class="n">${p.targets}</td><td class="n">${fmtM(p.est_revenue_m)}</td><td class="n">${fmtX(p.avg_multiple)}</td><td class="n">${p.dealer_share_pct == null ? "–" : p.dealer_share_pct + "%"}</td>
      <td><span class="ws ${p.white_space > 2 ? "hi" : p.white_space < -1 ? "lo" : ""}">${p.white_space > 2 ? "Under-supplied" : p.white_space < -1 ? "Rich in targets" : "Balanced"}</span></td>
      <td class="small ca-names">${p.top.slice(0, 3).map((x) => `<a href="#" data-copen="${esc(x.id)}">${esc(x.name.replace(/,?\s+(Ltd\.?|Inc\.?|Limited|Ltée|Corp\.?)$/i, "").replace(/\s*\(.*\)$/, ""))}</a>`).join("<br>") || "–"}</td></tr>`).join("")}</table>
    <div class="legend-s"><span><i class="d"></i>Share of Canadian GDP (demand proxy)</span><span><i class="s"></i>Share of investable target revenue (supply)</span></div></div>
    <div class="ca-read"><div class="section-t" style="margin-top:0">How to read it</div>
      <p><b>Ontario</b> is ~39% of the economy but only ~${c.provinces.find((p) => p.code === "ON")?.supply_share_pct}% of the targets we have found: the biggest prize, but you will need a platform there and more sourcing.</p>
      <p><b>Quebec and BC</b> are rich in independents relative to their economies: good tuck-in hunting grounds, but check dealer agreements (${c.provinces.find((p) => p.code === "QC")?.dealer_share_pct}% in Quebec mention a major).</p>
      <p><b>Alberta and Saskatchewan</b> are balanced; <b>Manitoba</b> is rich in targets, and Innovair (Winnipeg) is a natural western platform.</p>
      <p class="small muted">${esc(c.note)}</p></div></div>`;
}
document.addEventListener("click", (e) => { const a = e.target.closest("[data-copen]"); if (!a) return; e.preventDefault(); goTab("map"); setTimeout(() => select(a.dataset.copen, true), 250); });

// ---------- competitor coverage overlay (map)
let COV = null;
$("#covBtn").onclick = () => {
  const b = $("#covBtn");
  if (COV) { COV.remove(); COV = null; b.classList.remove("on"); return; }
  setView("map");
  COV = L.layerGroup(TARGETS.filter((t) => ["consolidated", "major", "consolidator", "sponsor"].includes(t.status))
    .map((t) => L.circle([t.lat, t.lon], { radius: 241000, stroke: false, fillColor: t.status === "sponsor" ? "#ff6b6b" : t.status === "consolidator" ? "#e0902a" : "#94a0ae", fillOpacity: 0.07, interactive: false }))).addTo(map);
  b.classList.add("on");
};


// ---------- batch research (selected targets)
$("#batchGo").onclick = async () => {
  if (!STATUS.has_key) return alert("Add PORTKEY_API_KEY to .env first.");
  const ids = [...CMP];
  const b = await api("/api/batch");
  const est = b.avg_cost_per_target ? `about $${(b.avg_cost_per_target * ids.length).toFixed(3)} (avg $${b.avg_cost_per_target.toFixed(4)} per company so far)` : "a few cents";
  if (!confirm(`Research ${ids.length} companies with the deal desk (Scout → Screener → Analyst)?\n\nEstimated cost: ${est}.\nSpent today: $${b.spend_today.toFixed(4)} of your $${b.daily_usd_cap.toFixed(2)} cap. The batch stops if the cap is reached.`)) return;
  await api("/api/batch/start", { ids });
  pollBatch();
};
let BATCH_T = null;
async function pollBatch() {
  clearTimeout(BATCH_T);
  const b = await api("/api/batch"), chip = $("#batchChip");
  if (!b.ids || !b.ids.length) return chip.classList.add("hidden");
  const name = (id) => (TARGETS.find((t) => t.id === id) || { name: id }).name;
  chip.classList.remove("hidden");
  if (b.status === "running") {
    chip.innerHTML = `<span class="spin"></span> Researching ${b.done.length + 1} of ${b.ids.length}: <b>${esc(name(b.current))}</b>`;
    BATCH_T = setTimeout(pollBatch, 2500); loadStatus();
  } else {
    const ok = b.done.filter((d) => d.status === "done").length;
    chip.innerHTML = `✓ Batch finished: ${ok} of ${b.ids.length} researched${b.note ? " · " + esc(b.note) : ""} <button id="batchX" class="ghost" style="color:#fff;padding:2px 8px">✕</button>`;
    $("#batchX").onclick = () => chip.classList.add("hidden");
    loadTargets(); if ($("#tab-list").classList.contains("on")) loadList();
  }
}
setTimeout(pollBatch, 1500);

// ---------- import your own targets (CSV)
function parseCSV(text) {
  const rows = []; let row = [], f = "", q = false;
  text = text.replace(/^\ufeff/, "");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c; }
    else if (c === '"') q = true;
    else if (c === "," || c === ";" || c === "\t") { row.push(f); f = ""; }
    else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(f); f = ""; if (row.some((x) => x.trim())) rows.push(row); row = []; }
    else f += c;
  }
  row.push(f); if (row.some((x) => x.trim())) rows.push(row);
  if (!rows.length) return [];
  const head = rows[0].map((h) => h.trim());
  return rows.slice(1).map((r) => Object.fromEntries(head.map((h, i) => [h, (r[i] || "").trim()])));
}
$("#importList").onclick = () => {
  modal(`<h3>Import your own targets</h3>
    <p class="small" style="line-height:1.55">Upload a CSV (save from Excel as <b>CSV</b>). The only required column is <b>Name</b>. Optional: <code>Website, City, State, Country, Branches, Ownership, Notes, Revenue, EBITDA, Stage, Lat, Lon</code>. Revenue/EBITDA in $m. Without Lat/Lon, companies are placed at their state/province or country centre. Names already on the map are skipped.</p>
    <input type="file" id="impFile" accept=".csv,text/csv">
    <div id="impPrev" class="small muted" style="margin-top:10px"></div>
    <div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end"><button id="impCancel">Cancel</button><button class="primary" id="impGo" disabled>Import</button></div>`);
  let ROWS = [];
  $("#impCancel").onclick = closeModal;
  $("#impFile").onchange = async () => {
    const f = $("#impFile").files[0]; if (!f) return;
    ROWS = parseCSV(await f.text());
    const cols = ROWS.length ? Object.keys(ROWS[0]) : [];
    const hasName = cols.some((c) => /^(name|company|company name|target)$/i.test(c));
    $("#impPrev").innerHTML = ROWS.length ? `${ROWS.length} rows · columns: ${cols.map(esc).join(", ")}${hasName ? "" : '<br><b style="color:var(--red)">No "Name" column found.</b>'}<br>First: <b>${esc(Object.values(ROWS[0])[0])}</b>` : "No rows found.";
    $("#impGo").disabled = !ROWS.length || !hasName;
  };
  $("#impGo").onclick = async () => {
    $("#impGo").disabled = true;
    const r = await api("/api/targets/import", { rows: ROWS });
    $("#impPrev").innerHTML = `<b style="color:var(--green)">Added ${r.added} companies.</b>${r.skipped_n ? ` Skipped ${r.skipped_n} (already on the map or no name).` : ""} They now appear on the map, in the Target List and can be researched with the deal desk.`;
    $("#impCancel").textContent = "Done";
    await loadTargets(); loadList();
  };
};


// ---------- house letter template (Outreach tab + company drawer)
const DEFAULT_LETTER = `Dear [Owner name],

I am an MBA student at Yale. Before that, I spent my career in private equity, most recently as a Director at Crescent Capital Group (~$50bn), and previously at Ardian and Shore Capital.

I am now building a long-term investment platform in industrial gas and welding supply distribution. [Company] stands out: [specific detail].

I would value 20 minutes to hear how you see the market and where you are taking the business, and I am happy to share what I am seeing across the industry in return.

Would you be open to a short call in the coming weeks?

Best regards,

Ade Thiruchandran
[Phone] · [Email]`;
let LETTER = DEFAULT_LETTER;
api("/api/letter-template").then((r) => { if (r.template) LETTER = r.template; renderTpl(); }).catch(() => {});
function tplDetail(t) {
  if (!t) return "";
  const where = [t.city, t.region_state].filter(Boolean).join(", ").replace(/\s*\(.*?\)/g, "");
  const gen = /(second|third|fourth|fifth|2nd|3rd|4th|5th)[- ]generation/i.exec(`${t.ownership} ${t.notes}`);
  const parts = [];
  if (t.locations) parts.push(`your ${t.locations} ${t.locations === 1 ? "location" : "locations"}${where ? " from your base in " + where : ""}`);
  else if (where) parts.push(`your business in ${where}`);
  if (gen) parts.push(`${gen[1].toLowerCase()}-generation family ownership`);
  return parts.length ? parts.join(" and ") + ", and your reputation with local customers" : "your reputation with local customers";
}
function fillLetter(tpl, t, owner, detail) {
  const co = t ? t.name.replace(/\s*\(.*?\)\s*/g, " ").trim() : "[Company]";
  return tpl.replaceAll("[Company]", co).replaceAll("[Owner name]", owner || "[Owner name]").replaceAll("[specific detail]", detail || "[specific detail]");
}
let TPL_T = null;
function renderTpl() {
  if (!$("#tplOut")) return;
  const dl = $("#tplList");
  if (dl && !dl.children.length && TARGETS.length) dl.innerHTML = TARGETS.filter((t) => ["target", "sponsor", "consolidator"].includes(t.status)).map((t) => `<option value="${esc(t.name)}">`).join("");
  $("#tplOut").textContent = fillLetter(LETTER, TPL_T, $("#tplOwner").value.trim(), $("#tplDetail").value.trim());
}
$("#tplCo").oninput = () => { TPL_T = TARGETS.find((t) => t.name === $("#tplCo").value) || null; if (TPL_T) $("#tplDetail").value = tplDetail(TPL_T); renderTpl(); };
$("#tplOwner").oninput = renderTpl; $("#tplDetail").oninput = renderTpl;
$("#tplCopy").onclick = () => { navigator.clipboard?.writeText($("#tplOut").textContent); $("#tplCopy").textContent = "Copied ✓"; setTimeout(() => ($("#tplCopy").textContent = "Copy letter"), 1500); };
$("#tplEdit").onclick = async () => {
  const ta = $("#tplText");
  if (ta.classList.contains("hidden")) { ta.value = LETTER; ta.classList.remove("hidden"); $("#tplOut").classList.add("hidden"); $("#tplEdit").textContent = "Save template"; }
  else { LETTER = ta.value; await api("/api/settings", { letter_template: LETTER }); ta.classList.add("hidden"); $("#tplOut").classList.remove("hidden"); $("#tplEdit").textContent = "Edit template"; renderTpl(); }
};
$("#tplReset").onclick = async () => { LETTER = DEFAULT_LETTER; await api("/api/settings", { letter_template: "" }); $("#tplText").classList.add("hidden"); $("#tplOut").classList.remove("hidden"); $("#tplEdit").textContent = "Edit template"; renderTpl(); };
