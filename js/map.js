/**
 * American CDL Incident Tracker — Map JS
 * - Lazy loads by year
 * - Pie-chart cluster icons (at-fault vs not-at-fault)
 * - Proper source URL handling
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

// ── Loading UI ────────────────────────────────────────────────────────────────

function showLoading(msg, sub) {
  let el = document.getElementById("loading-overlay");
  if (!el) {
    el = document.createElement("div");
    el.id = "loading-overlay";
    el.style.cssText = "position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(13,15,18,0.88);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:9999;font-family:'Barlow Condensed',sans-serif;";
    el.innerHTML = `
      <div style="color:#e8edf4;font-size:22px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;margin-bottom:10px" id="load-msg"></div>
      <div style="color:#5a6a80;font-size:13px" id="load-sub"></div>
      <div style="margin-top:18px;width:240px;height:4px;background:#252b36;border-radius:2px"><div id="load-bar" style="height:4px;background:#2970c8;border-radius:2px;width:0%;transition:width .3s"></div></div>`;
    document.body.appendChild(el);
  }
  document.getElementById("load-msg").textContent = msg || "Loading…";
  document.getElementById("load-sub").textContent = sub || "";
}

function updateLoading(msg, pct) {
  const m = document.getElementById("load-msg");
  const b = document.getElementById("load-bar");
  if (m) m.textContent = msg;
  if (b && pct !== undefined) b.style.width = pct + "%";
}

function hideLoading() {
  const el = document.getElementById("loading-overlay");
  if (el) el.remove();
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
  initMap();
  showLoading("Loading index…");
  await loadIndex();
  populateFilters();
  handleUrlParams();
  await loadRecentYears(3);
  hideLoading();
  applyFilters();
  bindEvents();
});

// ── Data Loading ──────────────────────────────────────────────────────────────

async function loadIndex() {
  try {
    const res = await fetch("data/index.json");
    indexData = await res.json();
    document.getElementById("incident-count").textContent =
      indexData.total_incidents.toLocaleString();
  } catch (e) {
    console.error("Index load failed:", e);
  }
}

async function loadYear(year) {
  if (loadedYears.has(String(year))) return 0;
  try {
    const res = await fetch(`data/by_year/${year}.json`);
    if (!res.ok) return 0;
    const incs = await res.json();
    allIncidents = allIncidents.concat(incs);
    loadedYears.add(String(year));
    return incs.length;
  } catch (e) {
    console.warn(`Failed to load ${year}:`, e);
    return 0;
  }
}

async function loadRecentYears(n) {
  if (!indexData) return;
  const years = Object.keys(indexData.years).sort().reverse().slice(0, n);
  const total = years.length;
  for (let i = 0; i < years.length; i++) {
    updateLoading(`Loading ${years[i]}…`, Math.round((i / total) * 100));
    await loadYear(years[i]);
  }
}

async function loadAllYears() {
  if (!indexData) return;
  const years = Object.keys(indexData.years).sort().reverse();
  const total = years.length;
  showLoading("Loading all years…", "This may take 30–60 seconds");
  for (let i = 0; i < years.length; i++) {
    updateLoading(`Loading ${years[i]}… (${i+1}/${total})`, Math.round((i / total) * 100));
    await loadYear(years[i]);
    // Yield to browser every 3 years to prevent freeze
    if (i % 3 === 2) await new Promise(r => setTimeout(r, 0));
  }
  hideLoading();
  populateStateFilter();
  applyFilters();
}

// ── Map Init ──────────────────────────────────────────────────────────────────

function initMap() {
  map = L.map("map", {
    center: [39.5, -98.35], zoom: 4,
    zoomControl: true, preferCanvas: true,
  });

  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: "abcd", maxZoom: 19,
  }).addTo(map);

  markerLayer = L.markerClusterGroup({
    maxClusterRadius: 50,
    showCoverageOnHover: false,
    iconCreateFunction: createPieClusterIcon,
  });
  map.addLayer(markerLayer);
}

// ── Pie Chart Cluster Icon ────────────────────────────────────────────────────

function createPieClusterIcon(cluster) {
  const markers = cluster.getAllChildMarkers();
  const total     = markers.length;
  const atFault   = markers.filter(m => m.options.fault === "AT_FAULT").length;
  const notFault  = markers.filter(m => m.options.fault === "NOT_AT_FAULT").length;
  const noStated  = total - atFault - notFault;
  const hasFatal  = markers.some(m => m.options.fatal);

  const size = total > 200 ? 48 : total > 50 ? 40 : total > 10 ? 32 : 26;
  const r    = size / 2;
  const cx   = r, cy = r;

  // Build SVG pie slices
  const slices = [
    { count: atFault,  color: "#d63030" },
    { count: notFault, color: "#2e9e58" },
    { count: noStated, color: "#5a6a80" },
  ].filter(s => s.count > 0);

  let svgPie = "";
  if (slices.length === 1) {
    // Single color — simple circle
    svgPie = `<circle cx="${cx}" cy="${cy}" r="${r-1}" fill="${slices[0].color}" />`;
  } else {
    let startAngle = -Math.PI / 2;
    slices.forEach(slice => {
      const angle = (slice.count / total) * 2 * Math.PI;
      const endAngle = startAngle + angle;
      const x1 = cx + (r-1) * Math.cos(startAngle);
      const y1 = cy + (r-1) * Math.sin(startAngle);
      const x2 = cx + (r-1) * Math.cos(endAngle);
      const y2 = cy + (r-1) * Math.sin(endAngle);
      const large = angle > Math.PI ? 1 : 0;
      svgPie += `<path d="M${cx},${cy} L${x1},${y1} A${r-1},${r-1} 0 ${large},1 ${x2},${y2} Z" fill="${slice.color}" />`;
      startAngle = endAngle;
    });
  }

  // Fatal ring
  const ring = hasFatal
    ? `<circle cx="${cx}" cy="${cy}" r="${r-1}" fill="none" stroke="#ff6060" stroke-width="2" opacity="0.8"/>`
    : `<circle cx="${cx}" cy="${cy}" r="${r-1}" fill="none" stroke="rgba(255,255,255,0.3)" stroke-width="1"/>`;

  const fontSize = size > 38 ? 13 : size > 28 ? 11 : 9;
  const label = `<text x="${cx}" y="${cy+fontSize*0.38}" text-anchor="middle" font-family="Barlow Condensed,sans-serif" font-weight="700" font-size="${fontSize}" fill="white" style="text-shadow:0 1px 3px rgba(0,0,0,.8)">${total > 999 ? Math.round(total/1000)+"k" : total}</text>`;

  const svg = `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" xmlns="http://www.w3.org/2000/svg">${svgPie}${ring}${label}</svg>`;

  return L.divIcon({
    html: svg,
    className: "",
    iconSize: [size, size],
    iconAnchor: [size/2, size/2],
  });
}

// ── Filters ───────────────────────────────────────────────────────────────────

function populateFilters() {
  if (!indexData) return;
  const yearSelect = document.getElementById("filter-year");
  yearSelect.innerHTML = "";
  Object.keys(indexData.years).sort().reverse().forEach(y => {
    const opt = document.createElement("option");
    opt.value = y;
    const cnt = indexData.years[y].count.toLocaleString();
    opt.textContent = `${y} (${cnt})`;
    yearSelect.appendChild(opt);
  });
}

function populateStateFilter() {
  const sel = document.getElementById("filter-state");
  const cur = sel.value;
  while (sel.options.length > 1) sel.remove(1);
  const states = [...new Set(allIncidents.map(i => i.state).filter(s => s && s !== "UNKNOWN"))].sort();
  states.forEach(s => {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = `${STATE_ABBR[s]||s} (${s})`;
    sel.appendChild(opt);
  });
  sel.value = cur;
}

function getFilters() {
  const yearSel = document.getElementById("filter-year");
  const selectedYears = new Set([...yearSel.selectedOptions].map(o => o.value));
  return {
    state:    document.getElementById("filter-state").value,
    fault:    document.getElementById("filter-fault").value,
    years:    selectedYears,
    severity: document.getElementById("filter-severity").value,
    foreign:  document.getElementById("filter-foreign").value,
  };
}

async function applyFilters() {
  const f = getFilters();
  // Load any selected years not yet loaded
  for (const y of f.years) {
    if (!loadedYears.has(y)) {
      showLoading(`Loading ${y}…`);
      await loadYear(y);
    }
  }
  hideLoading();
  populateStateFilter();
  _doFilter(f);
}

async function loadSelectedYears() {
  const yearSel = document.getElementById("filter-year");
  const years = [...yearSel.selectedOptions].map(o => o.value);
  if (!years.length) { alert("Hold Ctrl and click one or more years first."); return; }
  showLoading(`Loading ${years.length} year(s)…`);
  for (let i = 0; i < years.length; i++) {
    updateLoading(`Loading ${years[i]}… (${i+1}/${years.length})`, Math.round(i/years.length*100));
    await loadYear(years[i]);
  }
  hideLoading();
  populateStateFilter();
  _doFilter(getFilters());
}

function _doFilter(f) {
  filteredIncidents = allIncidents.filter(inc => {
    if (f.state    && inc.state !== f.state) return false;
    if (f.fault    && inc.fault !== f.fault) return false;
    if (f.years.size > 0 && !f.years.has(inc.date?.slice(0,4))) return false;
    if (f.severity) {
      if (f.severity === "fatal"  && !(inc.severity?.fatalities > 0)) return false;
      if (f.severity === "injury" && (inc.severity?.fatalities > 0 || !(inc.severity?.injuries > 0))) return false;
      if (f.severity === "pdo"    && !inc.severity?.property_damage_only) return false;
    }
    if (f.foreign === "foreign_confirmed" && !inc.foreign_driver_confirmed) return false;
    if (f.foreign === "foreign_probable"  && !inc.foreign_driver_probable)  return false;
    if (f.foreign === "foreign_possible"  && !inc.foreign_driver_possible)  return false;
    if (f.foreign === "any_foreign"       && !inc.foreign_driver_flag)      return false;
    if (f.foreign === "american"          && !inc.american_driver_flag)     return false;
    return true;
  });

  renderMarkers();
  updateStats();
}

// ── Markers ───────────────────────────────────────────────────────────────────

function renderMarkers() {
  markerLayer.clearLayers();
  const withCoords = filteredIncidents.filter(i => i.lat && i.lng);

  // Show notice when filter returns records but none have coordinates
  const notice = document.getElementById("no-coords-notice");
  if (notice) notice.remove();
  if (filteredIncidents.length > 0 && withCoords.length === 0) {
    const div = document.createElement("div");
    div.id = "no-coords-notice";
    div.style.cssText = "position:absolute;bottom:calc(var(--footer-h)+60px);left:50%;transform:translateX(-50%);background:var(--steel);border:1px solid var(--border);padding:10px 18px;border-radius:4px;font-size:13px;color:var(--text-secondary);z-index:500;text-align:center";
    div.innerHTML = `<strong style="color:var(--text-primary)">${filteredIncidents.length.toLocaleString()} records match</strong> — none have map coordinates.<br><small>News-sourced incidents are shown in the Incidents table but cannot be pinned without geocoding.</small>`;
    document.body.appendChild(div);
  }

  withCoords.forEach(inc => {
    const fatal  = (inc.severity?.fatalities || 0) > 0;
    const injury = !fatal && (inc.severity?.injuries || 0) > 0;
    const size   = fatal ? "sz-fatal" : injury ? "sz-injury" : "sz-pdo";
    const fault  = inc.fault || "NO_FAULT_STATED";

    const icon = L.divIcon({
      className: `cdl-marker fault-${fault} ${size}`,
      iconSize: null,
      iconAnchor: fatal ? [8,8] : injury ? [5.5,5.5] : [3.5,3.5],
    });

    const marker = L.marker([inc.lat, inc.lng], {
      icon,
      incident: inc,
      fault: fault,
      fatal: fatal,
    });
    marker.bindPopup(buildPopupHtml(inc), { maxWidth: 340 });
    marker.on("click", () => openPanel(inc));
    markerLayer.addLayer(marker);
  });
}

// ── Source URL Resolver ───────────────────────────────────────────────────────

function formatSourceUrl(url) {
  if (!url) return null;
  // Google News redirect URLs — show as Google News search link instead
  if (url.includes("news.google.com/rss/articles/")) {
    return { display: "Google News (cached)", href: null, isGnews: true };
  }
  // FARS — direct reference string, not a clickable URL
  if (url.startsWith("NHTSA FARS")) {
    return { display: url, href: "https://www.nhtsa.gov/research-data/fatality-analysis-reporting-system-fars", isRef: true };
  }
  return { display: url.replace(/^https?:\/\//, "").slice(0, 80), href: url };
}

// ── Popup & Panel ─────────────────────────────────────────────────────────────

function buildPopupHtml(inc) {
  const fault = inc.fault || "NO_FAULT_STATED";
  const faultColor = fault==="AT_FAULT" ? "#d63030" : fault==="NOT_AT_FAULT" ? "#2e9e58" : "#5a6a80";
  const fatal   = inc.severity?.fatalities || 0;
  const injured = inc.severity?.injuries   || 0;
  return `
    <div class="popup-header">${inc.state||"?"} — ${formatDate(inc.date)}</div>
    <div class="popup-row"><strong style="color:${faultColor}">${FAULT_LABELS[fault]||fault}</strong></div>
    ${inc.foreign_driver_flag ? `<div class="popup-row" style="color:#d4a820">⚠ Foreign driver flagged</div>` : ""}
    ${fatal   ? `<div class="popup-row"><strong style="color:#d63030">${fatal} fatalit${fatal===1?"y":"ies"}</strong></div>` : ""}
    ${injured ? `<div class="popup-row"><strong style="color:#e07020">${injured} injured</strong></div>` : ""}
    <div class="popup-row">${(inc.description||"").slice(0,120)}${(inc.description||"").length>120?"…":""}</div>
    <button class="popup-open-btn" onclick="openPanelById('${inc.id}')">View Full Record →</button>`;
}

function openPanelById(id) {
  const inc = allIncidents.find(i => i.id === id);
  if (inc) openPanel(inc);
}

function openPanel(inc) {
  document.getElementById("panel-content").innerHTML = buildPanelHtml2(inc);
  document.getElementById("incident-panel").classList.remove("hidden");
}

function buildPanelHtml2(inc) {
  const fault      = inc.fault || "NO_FAULT_STATED";
  const fatal      = inc.severity?.fatalities || 0;
  const injured    = inc.severity?.injuries   || 0;
  const statedCost = inc.cost?.stated_usd;
  const estCost    = inc.cost?.estimated_usd;
  const driver     = inc.at_fault_driver;

  // Driver origin badge — four tiers
  let foreignBadge = "";
  if (inc.foreign_driver_confirmed) {
    foreignBadge = `<span class="foreign-badge" style="background:var(--red);color:#fff">🚨 Foreign Driver — Confirmed</span>`;
  } else if (inc.foreign_driver_probable) {
    foreignBadge = `<span class="foreign-badge" style="background:var(--orange);color:#fff">⚠ Foreign Driver — Probable (No Name Given)</span>`;
  } else if (inc.foreign_driver_possible) {
    foreignBadge = `<span class="foreign-badge" style="background:var(--yellow);color:#111">? Foreign Driver — Possible (verify)</span>`;
  } else if (inc.american_driver_flag) {
    foreignBadge = `<span class="foreign-badge" style="background:#1a3a6b;color:#fff;border:1px solid #2970c8">🇺🇸 American-Origin Name — Possible (verify)</span>`;
  } else if (inc.foreign_driver_flag) {
    foreignBadge = `<span class="foreign-badge">⚠ Foreign Driver Flagged</span>`;
  }

  // Source links
  const sourceLinks = (inc.sources || []).map(s => {
    const parsed = formatSourceUrl(s);
    if (!parsed) return "";
    if (parsed.isGnews) return `<span class="source-link" style="color:var(--text-muted)">Google News article — search title in browser</span>`;
    if (parsed.isRef)   return `<a class="source-link" href="${parsed.href}" target="_blank" rel="noopener">NHTSA FARS Database ↗</a>`;
    return `<a class="source-link" href="${parsed.href}" target="_blank" rel="noopener">${parsed.display}</a>`;
  }).join("");

  return `
    <div class="panel-id">${inc.id}</div>
    <div class="panel-date">${formatDate(inc.date)} · ${inc.state||"?"}${inc.highway?" · "+inc.highway:""}${inc.county?", "+inc.county:""}</div>

    ${driver ? `
    <div style="background:var(--steel-mid);border-left:3px solid ${fault==="AT_FAULT"?"var(--red)":"var(--border)"};padding:10px 12px;margin:10px 0;border-radius:0 3px 3px 0">
      <div style="font-family:var(--font-head);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--text-muted);margin-bottom:3px">${fault==="AT_FAULT"?"At-Fault Driver":"Driver"}</div>
      <div style="font-family:var(--font-head);font-weight:900;font-size:20px;color:${fault==="AT_FAULT"?"var(--red-light)":"var(--text-primary)"};letter-spacing:.03em">${driver}</div>
    </div>` : fault==="AT_FAULT" ? `
    <div style="background:var(--steel-mid);border-left:3px solid var(--red);padding:10px 12px;margin:10px 0;border-radius:0 3px 3px 0">
      <div style="font-family:var(--font-head);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--text-muted);margin-bottom:3px">At-Fault Driver</div>
      <div style="font-size:13px;color:var(--text-muted);font-style:italic">Name not available in source</div>
    </div>` : ""}

    <span class="fault-badge ${fault}">${FAULT_LABELS[fault]||fault}</span>
    ${foreignBadge}

    <div class="panel-desc" style="margin-top:10px">${inc.description||"No description available."}</div>

    ${inc.foreign_driver_note ? `
    <div class="panel-section">
      <div class="panel-section-title">Foreign Driver Note</div>
      <div style="font-size:12px;color:var(--yellow);line-height:1.5">${inc.foreign_driver_note}</div>
    </div>` : ""}

    <div class="panel-section">
      <div class="panel-section-title">Severity</div>
      <div class="panel-row"><span class="panel-row-label">Fatalities</span><span class="panel-row-value ${fatal>0?"severity-fatal":""}">${fatal}</span></div>
      <div class="panel-row"><span class="panel-row-label">Injured</span><span class="panel-row-value ${injured>0?"severity-injury":""}">${injured}</span></div>
      <div class="panel-row"><span class="panel-row-label">Vehicle Type</span><span class="panel-row-value">${inc.vehicle_type||"Large Truck"}</span></div>
    </div>

    <div class="panel-section">
      <div class="panel-section-title">Carrier</div>
      <div class="panel-row"><span class="panel-row-label">Name</span><span class="panel-row-value">${inc.carrier_name||"Not identified"}</span></div>
      ${inc.carrier_usdot ? `<div class="panel-row"><span class="panel-row-label">USDOT #</span><span class="panel-row-value"><a href="https://safer.fmcsa.dot.gov/query.asp?searchtype=ANY&query_type=queryCarrierSnapshot&query_param=USDOT&query_string=${inc.carrier_usdot}" target="_blank">${inc.carrier_usdot} ↗</a></span></div>` : ""}
    </div>

    <div class="panel-section">
      <div class="panel-section-title">Cost</div>
      <div class="panel-row"><span class="panel-row-label">Stated (reported)</span><span class="panel-row-value cost-stated">${statedCost?"$"+statedCost.toLocaleString():"Not reported"}</span></div>
      <div class="panel-row"><span class="panel-row-label">Estimated</span><span class="panel-row-value cost-est">${estCost?"$"+estCost.toLocaleString():"N/A"}</span></div>
      ${estCost?`<div class="cost-note">${inc.cost?.estimated_basis||"FHWA cost model"}</div>`:""}
    </div>

    <div class="panel-section">
      <div class="panel-section-title">Sources</div>
      ${sourceLinks||`<span style="color:var(--text-muted);font-size:12px">No sources on file</span>`}
    </div>`;
}

// ── Stats ──────────────────────────────────────────────────────────────────────

function updateStats() {
  const total   = filteredIncidents.length;
  const fatal   = filteredIncidents.reduce((s,i)=>s+(i.severity?.fatalities||0),0);
  const injured = filteredIncidents.reduce((s,i)=>s+(i.severity?.injuries||0),0);
  const atFault = filteredIncidents.filter(i=>i.fault==="AT_FAULT").length;
  const notFault= filteredIncidents.filter(i=>i.fault==="NOT_AT_FAULT").length;
  const foreign = filteredIncidents.filter(i=>i.foreign_driver_flag).length;
  const cost    = filteredIncidents.reduce((s,i)=>s+(i.cost?.estimated_usd||0),0);

  document.getElementById("stat-total").textContent     = total.toLocaleString();
  document.getElementById("stat-fatal").textContent     = fatal.toLocaleString();
  document.getElementById("stat-injured").textContent   = injured.toLocaleString();
  document.getElementById("stat-at-fault").textContent  = atFault.toLocaleString();
  document.getElementById("stat-not-fault").textContent = notFault.toLocaleString();
  document.getElementById("stat-foreign").textContent   = foreign.toLocaleString();
  // american stat not in bar currently — tracked in data only
  document.getElementById("stat-cost").textContent      = formatCost(cost);
}

// ── Events ────────────────────────────────────────────────────────────────────

function bindEvents() {
  document.getElementById("btn-load-years").addEventListener("click", loadSelectedYears);
  document.getElementById("btn-load-all-years").addEventListener("click", loadAllYears);
  ["filter-state","filter-fault","filter-severity","filter-foreign","map-view"]
    .forEach(id => document.getElementById(id).addEventListener("change", applyFilters));

  document.getElementById("btn-reset").addEventListener("click", () => {
    ["filter-state","filter-fault","filter-severity","filter-foreign"]
      .forEach(id => { document.getElementById(id).value = ""; });
    // Deselect all year options
    [...document.getElementById("filter-year").options].forEach(o => o.selected = false);
    document.getElementById("map-view").value = "incidents";
    applyFilters();
  });

  document.getElementById("panel-close").addEventListener("click", () => {
    document.getElementById("incident-panel").classList.add("hidden");
  });
}

// ── URL Params ────────────────────────────────────────────────────────────────

function handleUrlParams() {
  const p = new URLSearchParams(window.location.search);
  if (p.get("state")) document.getElementById("filter-state").value = p.get("state");
  if (p.get("fault")) document.getElementById("filter-fault").value = p.get("fault");
  if (p.get("year"))  document.getElementById("filter-year").value  = p.get("year");
}

// ── Helpers ───────────────────────────────────────────────────────────────────

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
