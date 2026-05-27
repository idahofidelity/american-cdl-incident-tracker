/**
 * American CDL Incident Tracker — Map JS
 * Loads incidents.json, renders Leaflet map with clustering,
 * handles all filters, stats, and the side panel.
 */

// ── State ─────────────────────────────────────────────────────────────────

let allIncidents = [];
let filteredIncidents = [];
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

// ── Init ──────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
  initMap();
  await loadData();
  populateFilters();
  applyFilters();
  bindEvents();
  handleUrlParams();
});

// ── Map Init ──────────────────────────────────────────────────────────────

function initMap() {
  map = L.map("map", {
    center: [39.5, -98.35],
    zoom: 4,
    zoomControl: true,
    preferCanvas: true,
  });

  // Dark tile layer
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
  const fatalCount = markers.filter(m => m.options.incident?.severity?.fatalities > 0).length;
  const atFaultCount = markers.filter(m => m.options.incident?.fault === "AT_FAULT").length;
  const total = markers.length;

  let color = "#5a6a80";
  if (fatalCount > 0) color = "#d63030";
  else if (atFaultCount > total * 0.5) color = "#e07020";

  const size = total > 100 ? 44 : total > 20 ? 36 : 28;

  return L.divIcon({
    html: `<div style="
      width:${size}px;height:${size}px;
      background:${color};
      border:2px solid rgba(255,255,255,0.5);
      border-radius:50%;
      display:flex;align-items:center;justify-content:center;
      font-family:'Barlow Condensed',sans-serif;
      font-weight:700;font-size:${size > 36 ? 14 : 12}px;
      color:#fff;
    ">${total}</div>`,
    className: "",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

// ── Data Loading ──────────────────────────────────────────────────────────

async function loadData() {
  try {
    const res = await fetch("data/incidents.json");
    allIncidents = await res.json();
    document.getElementById("incident-count").textContent =
      allIncidents.length.toLocaleString();
  } catch (e) {
    console.error("Failed to load incidents:", e);
    allIncidents = [];
  }
}

// ── Filters ───────────────────────────────────────────────────────────────

function populateFilters() {
  // States
  const stateSelect = document.getElementById("filter-state");
  const states = [...new Set(allIncidents.map(i => i.state).filter(Boolean))].sort();
  states.forEach(s => {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = `${STATE_ABBR[s] || s} (${s})`;
    stateSelect.appendChild(opt);
  });

  // Years
  const yearSelect = document.getElementById("filter-year");
  const years = [...new Set(allIncidents.map(i => i.date?.slice(0, 4)).filter(Boolean))].sort().reverse();
  years.forEach(y => {
    const opt = document.createElement("option");
    opt.value = y;
    opt.textContent = y;
    yearSelect.appendChild(opt);
  });
}

function getFilters() {
  return {
    state:   document.getElementById("filter-state").value,
    fault:   document.getElementById("filter-fault").value,
    year:    document.getElementById("filter-year").value,
    severity: document.getElementById("filter-severity").value,
    foreign: document.getElementById("filter-foreign").value,
  };
}

function applyFilters() {
  const f = getFilters();

  filteredIncidents = allIncidents.filter(inc => {
    if (f.state && inc.state !== f.state) return false;
    if (f.fault && inc.fault !== f.fault) return false;
    if (f.year && inc.date?.slice(0, 4) !== f.year) return false;
    if (f.severity) {
      if (f.severity === "fatal"  && inc.severity?.fatalities < 1) return false;
      if (f.severity === "injury" && (inc.severity?.fatalities > 0 || inc.severity?.injuries < 1)) return false;
      if (f.severity === "pdo"    && !inc.severity?.property_damage_only) return false;
    }
    if (f.foreign === "yes" && !inc.foreign_driver_flag) return false;
    if (f.foreign === "no"  &&  inc.foreign_driver_flag) return false;
    return true;
  });

  renderMarkers();
  updateStats();
}

// ── Markers ───────────────────────────────────────────────────────────────

function renderMarkers() {
  markerLayer.clearLayers();

  const viewMode = document.getElementById("map-view").value;
  if (viewMode === "heatmap") {
    renderHeatmap();
    return;
  }

  filteredIncidents.forEach(inc => {
    if (!inc.lat || !inc.lng) return;

    const fatal   = inc.severity?.fatalities > 0;
    const injury  = !fatal && inc.severity?.injuries > 0;
    const size    = fatal ? "sz-fatal" : injury ? "sz-injury" : "sz-pdo";
    const fault   = inc.fault || "NO_FAULT_STATED";
    const foreign = inc.foreign_driver_flag ? " cdl-foreign" : "";

    const icon = L.divIcon({
      className: `cdl-marker fault-${fault} ${size}${foreign}`,
      iconSize: null,
      iconAnchor: fatal ? [8, 8] : injury ? [5.5, 5.5] : [3.5, 3.5],
    });

    const marker = L.marker([inc.lat, inc.lng], { icon, incident: inc });

    marker.bindPopup(buildPopupHtml(inc), {
      maxWidth: 340,
      className: "cdl-popup",
    });

    marker.on("click", () => openPanel(inc));
    markerLayer.addLayer(marker);
  });
}

function renderHeatmap() {
  // Simple heatmap using circle markers with opacity
  filteredIncidents.forEach(inc => {
    if (!inc.lat || !inc.lng) return;
    const fatal = inc.severity?.fatalities > 0;
    L.circleMarker([inc.lat, inc.lng], {
      radius: fatal ? 12 : 6,
      fillColor: fatal ? "#d63030" : "#e07020",
      fillOpacity: 0.25,
      stroke: false,
    }).addTo(markerLayer);
  });
}

// ── Popup HTML ────────────────────────────────────────────────────────────

function buildPopupHtml(inc) {
  const fatal   = inc.severity?.fatalities || 0;
  const injured = inc.severity?.injuries || 0;
  const fault   = inc.fault || "NO_FAULT_STATED";
  const faultLabel = FAULT_LABELS[fault] || fault;
  const faultColor = fault === "AT_FAULT" ? "#d63030"
                   : fault === "NOT_AT_FAULT" ? "#2e9e58" : "#5a6a80";

  return `
    <div class="popup-header">${inc.state || "?"} — ${formatDate(inc.date)}</div>
    <div class="popup-row"><strong style="color:${faultColor}">${faultLabel}</strong></div>
    ${inc.foreign_driver_flag ? `<div class="popup-row" style="color:#d4a820">⚠ Foreign driver flagged</div>` : ""}
    ${fatal ? `<div class="popup-row"><strong class="severity-fatal">${fatal} fatali${fatal === 1 ? "ty" : "ties"}</strong></div>` : ""}
    ${injured ? `<div class="popup-row"><strong class="severity-injury">${injured} injured</strong></div>` : ""}
    <div class="popup-row">${inc.description?.slice(0, 120) || ""}${inc.description?.length > 120 ? "…" : ""}</div>
    <button class="popup-open-btn" onclick="openPanelById('${inc.id}')">View Full Record →</button>
  `;
}

// ── Side Panel ────────────────────────────────────────────────────────────

function openPanelById(id) {
  const inc = allIncidents.find(i => i.id === id);
  if (inc) openPanel(inc);
}

function openPanel(inc) {
  const panel = document.getElementById("incident-panel");
  const content = document.getElementById("panel-content");
  content.innerHTML = buildPanelHtml(inc);
  panel.classList.remove("hidden");
}

function closePanel() {
  document.getElementById("incident-panel").classList.add("hidden");
}

function buildPanelHtml(inc) {
  const fault   = inc.fault || "NO_FAULT_STATED";
  const fatal   = inc.severity?.fatalities || 0;
  const injured = inc.severity?.injuries || 0;
  const statedCost = inc.cost?.stated_usd;
  const estCost    = inc.cost?.estimated_usd;

  const faultBadge = `<span class="fault-badge ${fault}">${FAULT_LABELS[fault] || fault}</span>`;
  const foreignBadge = inc.foreign_driver_flag
    ? `<span class="foreign-badge">⚠ Foreign Driver Flagged</span>` : "";

  const victimSection = inc.victims?.length ? `
    <div class="panel-section">
      <div class="panel-section-title">Victims</div>
      ${inc.victims.map(v => `
        <div class="panel-row">
          <span class="panel-row-label">${v.name}${v.age ? `, age ${v.age}` : ""}${v.hometown ? ` — ${v.hometown}` : ""}</span>
        </div>
      `).join("")}
    </div>` : "";

  const sources = (inc.sources || []).map(s =>
    `<a class="source-link" href="${s}" target="_blank" rel="noopener">${s}</a>`
  ).join("");

  return `
    <div class="panel-id">${inc.id}</div>
    <div class="panel-date">${formatDate(inc.date)} · ${inc.state || "Unknown State"}${inc.highway ? ` · ${inc.highway}` : ""}${inc.county ? `, ${inc.county}` : ""}</div>
    ${faultBadge}${foreignBadge}
    <div class="panel-desc">${inc.description || "No description available."}</div>

    ${inc.foreign_driver_note ? `
    <div class="panel-section">
      <div class="panel-section-title">Foreign Driver Note</div>
      <div style="font-size:12px;color:var(--yellow)">${inc.foreign_driver_note}</div>
    </div>` : ""}

    <div class="panel-section">
      <div class="panel-section-title">Severity</div>
      <div class="panel-row">
        <span class="panel-row-label">Fatalities</span>
        <span class="panel-row-value ${fatal > 0 ? "severity-fatal" : ""}">${fatal}</span>
      </div>
      <div class="panel-row">
        <span class="panel-row-label">Injured</span>
        <span class="panel-row-value ${injured > 0 ? "severity-injury" : ""}">${injured}</span>
      </div>
      <div class="panel-row">
        <span class="panel-row-label">Property Damage Only</span>
        <span class="panel-row-value">${inc.severity?.property_damage_only ? "Yes" : "No"}</span>
      </div>
    </div>

    <div class="panel-section">
      <div class="panel-section-title">Carrier / Driver</div>
      <div class="panel-row">
        <span class="panel-row-label">Carrier</span>
        <span class="panel-row-value">${inc.carrier_name || "Not identified"}</span>
      </div>
      ${inc.carrier_usdot ? `<div class="panel-row">
        <span class="panel-row-label">USDOT #</span>
        <span class="panel-row-value">
          <a href="https://safer.fmcsa.dot.gov/query.asp?searchtype=ANY&query_type=queryCarrierSnapshot&query_param=USDOT&query_string=${inc.carrier_usdot}" target="_blank">${inc.carrier_usdot}</a>
        </span>
      </div>` : ""}
      <div class="panel-row">
        <span class="panel-row-label">At-Fault Driver</span>
        <span class="panel-row-value" style="color:${fault === "AT_FAULT" ? "var(--red-light)" : "inherit"}">${inc.at_fault_driver || (fault === "AT_FAULT" ? "At fault — name not available" : "N/A")}</span>
      </div>
      <div class="panel-row">
        <span class="panel-row-label">Vehicle Type</span>
        <span class="panel-row-value">${inc.vehicle_type || "Not specified"}</span>
      </div>
    </div>

    <div class="panel-section">
      <div class="panel-section-title">Cost</div>
      <div class="panel-row">
        <span class="panel-row-label">Stated (reported)</span>
        <span class="panel-row-value cost-stated">${statedCost ? "$" + statedCost.toLocaleString() : "Not reported"}</span>
      </div>
      <div class="panel-row">
        <span class="panel-row-label">Estimated</span>
        <span class="panel-row-value cost-est">${estCost ? "$" + estCost.toLocaleString() : "N/A"}</span>
      </div>
      ${estCost ? `<div class="cost-note">${inc.cost?.estimated_basis || "FHWA cost model"}</div>` : ""}
    </div>

    ${victimSection}

    <div class="panel-section">
      <div class="panel-section-title">Sources</div>
      ${sources || '<span style="color:var(--text-muted);font-size:12px">No sources on file</span>'}
    </div>
  `;
}

// ── Stats ──────────────────────────────────────────────────────────────────

function updateStats() {
  const total     = filteredIncidents.length;
  const fatal     = filteredIncidents.reduce((s, i) => s + (i.severity?.fatalities || 0), 0);
  const injured   = filteredIncidents.reduce((s, i) => s + (i.severity?.injuries || 0), 0);
  const atFault   = filteredIncidents.filter(i => i.fault === "AT_FAULT").length;
  const notFault  = filteredIncidents.filter(i => i.fault === "NOT_AT_FAULT").length;
  const foreign   = filteredIncidents.filter(i => i.foreign_driver_flag).length;
  const totalCost = filteredIncidents.reduce((s, i) => s + (i.cost?.estimated_usd || 0), 0);

  document.getElementById("stat-total").textContent    = total.toLocaleString();
  document.getElementById("stat-fatal").textContent    = fatal.toLocaleString();
  document.getElementById("stat-injured").textContent  = injured.toLocaleString();
  document.getElementById("stat-at-fault").textContent = atFault.toLocaleString();
  document.getElementById("stat-not-fault").textContent= notFault.toLocaleString();
  document.getElementById("stat-foreign").textContent  = foreign.toLocaleString();
  document.getElementById("stat-cost").textContent     = formatCost(totalCost);
}

// ── Events ─────────────────────────────────────────────────────────────────

function bindEvents() {
  ["filter-state","filter-fault","filter-year","filter-severity","filter-foreign","map-view"]
    .forEach(id => document.getElementById(id).addEventListener("change", applyFilters));

  document.getElementById("btn-reset").addEventListener("click", () => {
    ["filter-state","filter-fault","filter-year","filter-severity","filter-foreign"]
      .forEach(id => { document.getElementById(id).value = ""; });
    document.getElementById("map-view").value = "incidents";
    applyFilters();
  });

  document.getElementById("panel-close").addEventListener("click", closePanel);
}

// ── URL Params ─────────────────────────────────────────────────────────────

function handleUrlParams() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("state")) {
    document.getElementById("filter-state").value = params.get("state");
  }
  if (params.get("fault")) {
    document.getElementById("filter-fault").value = params.get("fault");
  }
  if (params.get("id")) {
    const inc = allIncidents.find(i => i.id === params.get("id"));
    if (inc) openPanel(inc);
  }
  applyFilters();
}

// ── Helpers ────────────────────────────────────────────────────────────────

function formatDate(dateStr) {
  if (!dateStr) return "Date unknown";
  const [y, m, d] = dateStr.split("-");
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${months[parseInt(m) - 1]} ${parseInt(d)}, ${y}`;
}

function formatCost(n) {
  if (!n) return "—";
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000)     return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)         return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toLocaleString()}`;
}

// Expose for popup onclick
window.openPanelById = openPanelById;
