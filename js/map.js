/**
 * American CDL Incident Tracker — Map JS
 * Loads data/index.json first, then fetches per-year files on demand.
 * Avoids loading the full 94MB dataset at once.
 */

let allIncidents = [];
let filteredIncidents = [];
let loadedYears = new Set();
let indexData = null;
let map, markerLayer;

const FAULT_LABELS = {
  AT_FAULT:        "Trucker At Fault",
  NOT_AT_FAULT:    "Trucker Not At Fault",
  NO_FAULT_STATED: "Fault Not Stated",
};

const STATE_ABBR = {
  AL:"Alabama",AK:"Alaska",AZ:"Arizona",AR:"Arkansas",CA:"California",
  CO:"Colorado",CT:"Connecticut",DE:"Delaware",FL:"Florida",GA:"Georgia",
  HI:"Hawaii",ID:"Idaho",IL:"Illinois",IN:"Indiana",IA:"Iowa",KS:"Kansas",
  KY:"Kentucky",LA:"Louisiana",ME:"Maine",MD:"Maryland",MA:"Massachusetts",
  MI:"Michigan",MN:"Minnesota",MS:"Mississippi",MO:"Missouri",MT:"Montana",
  NE:"Nebraska",NV:"Nevada",NH:"New Hampshire",NJ:"New Jersey",NM:"New Mexico",
  NY:"New York",NC:"North Carolina",ND:"North Dakota",OH:"Ohio",OK:"Oklahoma",
  OR:"Oregon",PA:"Pennsylvania",RI:"Rhode Island",SC:"South Carolina",
  SD:"South Dakota",TN:"Tennessee",TX:"Texas",UT:"Utah",VT:"Vermont",
  VA:"Virginia",WA:"Washington",WV:"West Virginia",WI:"Wisconsin",WY:"Wyoming",
};

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
  initMap();
  showLoading("Loading index…");
  await loadIndex();
  populateFilters();
  handleUrlParams();
  // Load last 3 years by default for fast initial render
  await loadRecentYears(3);
  hideLoading();
  applyFilters();
  bindEvents();
});

// ── Loading UI ────────────────────────────────────────────────────────────────

function showLoading(msg) {
  let el = document.getElementById("loading-overlay");
  if (!el) {
    el = document.createElement("div");
    el.id = "loading-overlay";
    el.style.cssText = `
      position:fixed;top:0;left:0;right:0;bottom:0;
      background:rgba(13,15,18,0.85);
      display:flex;flex-direction:column;align-items:center;justify-content:center;
      z-index:9999;font-family:'Barlow Condensed',sans-serif;
    `;
    el.innerHTML = `
      <div style="color:#e8edf4;font-size:22px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:12px" id="loading-msg">${msg}</div>
      <div style="color:#5a6a80;font-size:13px" id="loading-sub">Please wait…</div>
    `;
    document.body.appendChild(el);
  } else {
    document.getElementById("loading-msg").textContent = msg;
  }
}

function updateLoadingMsg(msg) {
  const el = document.getElementById("loading-msg");
  if (el) el.textContent = msg;
}

function hideLoading() {
  const el = document.getElementById("loading-overlay");
  if (el) el.remove();
}

// ── Data Loading ──────────────────────────────────────────────────────────────

async function loadIndex() {
  try {
    const res = await fetch("data/index.json");
    indexData = await res.json();
    document.getElementById("incident-count").textContent =
      indexData.total_incidents.toLocaleString();
  } catch (e) {
    console.error("Failed to load index:", e);
    // Fallback: try loading full incidents.json
    try {
      showLoading("Loading full dataset…");
      const res = await fetch("data/incidents.json");
      allIncidents = await res.json();
      document.getElementById("incident-count").textContent =
        allIncidents.length.toLocaleString();
    } catch (e2) {
      console.error("Full load also failed:", e2);
    }
  }
}

async function loadYear(year) {
  if (loadedYears.has(year)) return;
  try {
    const res = await fetch(`data/by_year/${year}.json`);
    if (!res.ok) return;
    const incs = await res.json();
    allIncidents = allIncidents.concat(incs);
    loadedYears.add(year);
  } catch (e) {
    console.warn(`Failed to load year ${year}:`, e);
  }
}

async function loadRecentYears(n) {
  if (!indexData) return;
  const years = Object.keys(indexData.years).sort().reverse().slice(0, n);
  for (const year of years) {
    updateLoadingMsg(`Loading ${year}…`);
    await loadYear(year);
  }
}

async function loadAllYears() {
  if (!indexData) return;
  const years = Object.keys(indexData.years).sort().reverse();
  showLoading("Loading all years…");
  for (const year of years) {
    updateLoadingMsg(`Loading ${year}…`);
    await loadYear(year);
  }
  hideLoading();
  applyFilters();
}

// ── Map Init ──────────────────────────────────────────────────────────────────

function initMap() {
  map = L.map("map", {
    center: [39.5, -98.35],
    zoom: 4,
    zoomControl: true,
    preferCanvas: true,
  });

  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(map);

  markerLayer = L.markerClusterGroup({
    maxClusterRadius: 40,
    showCoverageOnHover: false,
    iconCreateFunction: createClusterIcon,
  });
  map.addLayer(markerLayer);
}

function createClusterIcon(cluster) {
  const markers = cluster.getAllChildMarkers();
  const fatalCount   = markers.filter(m => m.options.incident?.severity?.fatalities > 0).length;
  const atFaultCount = markers.filter(m => m.options.incident?.fault === "AT_FAULT").length;
  const total = markers.length;

  let color = "#5a6a80";
  if (fatalCount > 0)                    color = "#d63030";
  else if (atFaultCount > total * 0.5)   color = "#e07020";

  const size = total > 100 ? 44 : total > 20 ? 36 : 28;
  return L.divIcon({
    html: `<div style="width:${size}px;height:${size}px;background:${color};border:2px solid rgba(255,255,255,0.5);border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:'Barlow Condensed',sans-serif;font-weight:700;font-size:${size>36?14:12}px;color:#fff">${total}</div>`,
    className: "",
    iconSize: [size, size],
    iconAnchor: [size/2, size/2],
  });
}

// ── Filters ───────────────────────────────────────────────────────────────────

function populateFilters() {
  // States — from index
  const stateSet = new Set();
  if (indexData) {
    // States will populate after data loads; re-call after loadAllYears
  }

  // Years — from index
  const yearSelect = document.getElementById("filter-year");
  if (indexData) {
    Object.keys(indexData.years).sort().reverse().forEach(y => {
      const opt = document.createElement("option");
      opt.value = y;
      opt.textContent = y;
      yearSelect.appendChild(opt);
    });
  }

  // Add "Load All Years" option
  const loadAllOpt = document.createElement("option");
  loadAllOpt.value = "_all";
  loadAllOpt.textContent = "All Years (load all data)";
  yearSelect.appendChild(loadAllOpt);
}

function populateStateFilter() {
  const stateSelect = document.getElementById("filter-state");
  // Clear existing options except first
  while (stateSelect.options.length > 1) stateSelect.remove(1);
  const states = [...new Set(allIncidents.map(i => i.state).filter(s => s && s !== "UNKNOWN"))].sort();
  states.forEach(s => {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = `${STATE_ABBR[s] || s} (${s})`;
    stateSelect.appendChild(opt);
  });
}

function getFilters() {
  return {
    state:    document.getElementById("filter-state").value,
    fault:    document.getElementById("filter-fault").value,
    year:     document.getElementById("filter-year").value,
    severity: document.getElementById("filter-severity").value,
    foreign:  document.getElementById("filter-foreign").value,
  };
}

function applyFilters() {
  const f = getFilters();

  // If a specific year is selected and not loaded yet, load it first
  if (f.year && f.year !== "_all" && !loadedYears.has(f.year)) {
    loadYear(f.year).then(() => {
      populateStateFilter();
      _doFilter(f);
    });
    return;
  }

  populateStateFilter();
  _doFilter(f);
}

function _doFilter(f) {
  filteredIncidents = allIncidents.filter(inc => {
    if (f.state    && inc.state !== f.state) return false;
    if (f.fault    && inc.fault !== f.fault) return false;
    if (f.year && f.year !== "_all" && inc.date?.slice(0,4) !== f.year) return false;
    if (f.severity) {
      if (f.severity === "fatal"  && !inc.severity?.fatalities) return false;
      if (f.severity === "injury" && (inc.severity?.fatalities > 0 || !inc.severity?.injuries)) return false;
      if (f.severity === "pdo"    && !inc.severity?.property_damage_only) return false;
    }
    if (f.foreign === "yes" && !inc.foreign_driver_flag) return false;
    if (f.foreign === "no"  &&  inc.foreign_driver_flag) return false;
    return true;
  });

  renderMarkers();
  updateStats();
}

// ── Markers ───────────────────────────────────────────────────────────────────

function renderMarkers() {
  markerLayer.clearLayers();

  // Only render incidents with coordinates
  const withCoords = filteredIncidents.filter(i => i.lat && i.lng);

  withCoords.forEach(inc => {
    const fatal  = inc.severity?.fatalities > 0;
    const injury = !fatal && inc.severity?.injuries > 0;
    const size   = fatal ? "sz-fatal" : injury ? "sz-injury" : "sz-pdo";
    const fault  = inc.fault || "NO_FAULT_STATED";

    const icon = L.divIcon({
      className: `cdl-marker fault-${fault} ${size}`,
      iconSize: null,
      iconAnchor: fatal ? [8,8] : injury ? [5.5,5.5] : [3.5,3.5],
    });

    const marker = L.marker([inc.lat, inc.lng], { icon, incident: inc });
    marker.bindPopup(buildPopupHtml(inc), { maxWidth: 340 });
    marker.on("click", () => openPanel(inc));
    markerLayer.addLayer(marker);
  });
}

// ── Popup & Panel ─────────────────────────────────────────────────────────────

function buildPopupHtml(inc) {
  const fault = inc.fault || "NO_FAULT_STATED";
  const faultColor = fault === "AT_FAULT" ? "#d63030" : fault === "NOT_AT_FAULT" ? "#2e9e58" : "#5a6a80";
  const fatal   = inc.severity?.fatalities || 0;
  const injured = inc.severity?.injuries   || 0;
  return `
    <div class="popup-header">${inc.state || "?"} — ${formatDate(inc.date)}</div>
    <div class="popup-row"><strong style="color:${faultColor}">${FAULT_LABELS[fault]||fault}</strong></div>
    ${inc.foreign_driver_flag ? `<div class="popup-row" style="color:#d4a820">⚠ Foreign driver flagged</div>` : ""}
    ${fatal   ? `<div class="popup-row"><strong class="severity-fatal">${fatal} fatalit${fatal===1?"y":"ies"}</strong></div>` : ""}
    ${injured ? `<div class="popup-row"><strong class="severity-injury">${injured} injured</strong></div>` : ""}
    <div class="popup-row">${(inc.description||"").slice(0,120)}${(inc.description||"").length>120?"…":""}</div>
    <button class="popup-open-btn" onclick="openPanelById('${inc.id}')">View Full Record →</button>
  `;
}

function openPanelById(id) {
  const inc = allIncidents.find(i => i.id === id);
  if (inc) openPanel(inc);
}

function openPanel(inc) {
  const panel = document.getElementById("incident-panel");
  document.getElementById("panel-content").innerHTML = buildPanelHtml(inc);
  panel.classList.remove("hidden");
}

function buildPanelHtml(inc) {
  const fault = inc.fault || "NO_FAULT_STATED";
  const fatal   = inc.severity?.fatalities || 0;
  const injured = inc.severity?.injuries   || 0;
  const statedCost = inc.cost?.stated_usd;
  const estCost    = inc.cost?.estimated_usd;

  return `
    <div class="panel-id">${inc.id}</div>
    <div class="panel-date">${formatDate(inc.date)} · ${inc.state||"?"}${inc.highway ? " · "+inc.highway : ""}${inc.county ? ", "+inc.county : ""}</div>
    <span class="fault-badge ${fault}">${FAULT_LABELS[fault]||fault}</span>
    ${inc.foreign_driver_flag ? `<span class="foreign-badge">⚠ Foreign Driver Flagged</span>` : ""}
    <div class="panel-desc">${inc.description||"No description available."}</div>
    ${inc.foreign_driver_note ? `<div class="panel-section"><div class="panel-section-title">Foreign Driver Note</div><div style="font-size:12px;color:var(--yellow)">${inc.foreign_driver_note}</div></div>` : ""}
    <div class="panel-section">
      <div class="panel-section-title">Severity</div>
      <div class="panel-row"><span class="panel-row-label">Fatalities</span><span class="panel-row-value ${fatal>0?"severity-fatal":""}">${fatal}</span></div>
      <div class="panel-row"><span class="panel-row-label">Injured</span><span class="panel-row-value ${injured>0?"severity-injury":""}">${injured}</span></div>
    </div>
    <div class="panel-section">
      <div class="panel-section-title">Carrier / Driver</div>
      <div class="panel-row"><span class="panel-row-label">Carrier</span><span class="panel-row-value">${inc.carrier_name||"Not identified"}</span></div>
      ${inc.carrier_usdot ? `<div class="panel-row"><span class="panel-row-label">USDOT #</span><span class="panel-row-value"><a href="https://safer.fmcsa.dot.gov/query.asp?searchtype=ANY&query_type=queryCarrierSnapshot&query_param=USDOT&query_string=${inc.carrier_usdot}" target="_blank">${inc.carrier_usdot}</a></span></div>` : ""}
      <div class="panel-row"><span class="panel-row-label">At-Fault Driver</span><span class="panel-row-value" style="color:${fault==="AT_FAULT"?"var(--red-light)":"inherit"}">${inc.at_fault_driver||(fault==="AT_FAULT"?"At fault — name not available":"N/A")}</span></div>
    </div>
    <div class="panel-section">
      <div class="panel-section-title">Cost</div>
      <div class="panel-row"><span class="panel-row-label">Stated</span><span class="panel-row-value cost-stated">${statedCost?"$"+statedCost.toLocaleString():"Not reported"}</span></div>
      <div class="panel-row"><span class="panel-row-label">Estimated</span><span class="panel-row-value cost-est">${estCost?"$"+estCost.toLocaleString():"N/A"}</span></div>
      ${estCost?`<div class="cost-note">${inc.cost?.estimated_basis||"FHWA cost model"}</div>`:""}
    </div>
    <div class="panel-section">
      <div class="panel-section-title">Sources</div>
      ${(inc.sources||[]).map(s=>`<a class="source-link" href="${s}" target="_blank" rel="noopener">${s}</a>`).join("")||"<span style='color:var(--text-muted);font-size:12px'>No sources on file</span>"}
    </div>
  `;
}

// ── Stats ──────────────────────────────────────────────────────────────────────

function updateStats() {
  const total    = filteredIncidents.length;
  const fatal    = filteredIncidents.reduce((s,i) => s+(i.severity?.fatalities||0), 0);
  const injured  = filteredIncidents.reduce((s,i) => s+(i.severity?.injuries||0), 0);
  const atFault  = filteredIncidents.filter(i => i.fault==="AT_FAULT").length;
  const notFault = filteredIncidents.filter(i => i.fault==="NOT_AT_FAULT").length;
  const foreign  = filteredIncidents.filter(i => i.foreign_driver_flag).length;
  const cost     = filteredIncidents.reduce((s,i) => s+(i.cost?.estimated_usd||0), 0);

  document.getElementById("stat-total").textContent    = total.toLocaleString();
  document.getElementById("stat-fatal").textContent    = fatal.toLocaleString();
  document.getElementById("stat-injured").textContent  = injured.toLocaleString();
  document.getElementById("stat-at-fault").textContent = atFault.toLocaleString();
  document.getElementById("stat-not-fault").textContent= notFault.toLocaleString();
  document.getElementById("stat-foreign").textContent  = foreign.toLocaleString();
  document.getElementById("stat-cost").textContent     = formatCost(cost);
}

// ── Events ─────────────────────────────────────────────────────────────────────

function bindEvents() {
  document.getElementById("filter-year").addEventListener("change", async e => {
    if (e.target.value === "_all") {
      await loadAllYears();
      e.target.value = "";
    }
    applyFilters();
  });

  ["filter-state","filter-fault","filter-severity","filter-foreign","map-view"]
    .forEach(id => document.getElementById(id).addEventListener("change", applyFilters));

  document.getElementById("btn-reset").addEventListener("click", () => {
    ["filter-state","filter-fault","filter-year","filter-severity","filter-foreign"]
      .forEach(id => { document.getElementById(id).value = ""; });
    document.getElementById("map-view").value = "incidents";
    applyFilters();
  });

  document.getElementById("panel-close").addEventListener("click", () => {
    document.getElementById("incident-panel").classList.add("hidden");
  });
}

// ── URL Params ─────────────────────────────────────────────────────────────────

function handleUrlParams() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("state")) document.getElementById("filter-state").value = params.get("state");
  if (params.get("fault")) document.getElementById("filter-fault").value = params.get("fault");
  if (params.get("year"))  document.getElementById("filter-year").value  = params.get("year");
  if (params.get("id")) {
    const inc = allIncidents.find(i => i.id === params.get("id"));
    if (inc) openPanel(inc);
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function formatDate(d) {
  if (!d) return "Date unknown";
  const [y,m,day] = d.split("-");
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${months[parseInt(m)-1]} ${parseInt(day)}, ${y}`;
}

function formatCost(n) {
  if (!n) return "—";
  if (n >= 1e12) return `$${(n/1e12).toFixed(1)}T`;
  if (n >= 1e9)  return `$${(n/1e9).toFixed(1)}B`;
  if (n >= 1e6)  return `$${(n/1e6).toFixed(1)}M`;
  if (n >= 1e3)  return `$${(n/1e3).toFixed(0)}K`;
  return `$${n.toLocaleString()}`;
}

window.openPanelById = openPanelById;
