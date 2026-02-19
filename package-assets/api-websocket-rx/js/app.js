// js/app.js
// ctrlX WebSocket UI + RT Export (Python backend)

// --- refs UI ---
const btnConnect    = document.getElementById("btnConnect");
const btnDisconnect = document.getElementById("btnDisconnect");
const statusDiv     = document.getElementById("status");
const tbody         = document.querySelector("#data-table tbody");

const btnExport   = document.getElementById("btnExport");
const exportCount = document.getElementById("exportCount");
const chkAll      = document.getElementById("chkAll");

// ===============================
// URL base robusta para ctrlX reverse proxy
// ===============================
const parts = location.pathname.split("/").filter(Boolean);
const APP_PREFIX = parts.length ? `/${parts[0]}` : "";
const API_BASE = `${location.origin}${APP_PREFIX}`;
const WS_BASE  = `${location.origin.replace("http", "ws")}${APP_PREFIX}`;

// --- state ---
let ws = null;
let lastRender = 0;

let exporting = false;
let exportPoll = null;

const selectedTags = new Set();

btnConnect.disabled = true;
btnDisconnect.disabled = true;

// =====================================
// Auth gating
// =====================================
function enableApp() {
  btnConnect.disabled = false;
  setExportButtonUI();
}

if (sessionStorage.getItem("auth_ok") === "1") enableApp();
window.addEventListener("auth:ok", () => enableApp());

// =====================================
// Utils
// =====================================
function flattenObject(obj, prefix = "", out = {}) {
  if (!obj || typeof obj !== "object") return out;
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      flattenObject(v, key, out);
    } else {
      out[key] = v;
    }
  }
  return out;
}

function updateChkAllState(totalRows) {
  if (!chkAll) return;

  if (totalRows <= 0 || selectedTags.size === 0) {
    chkAll.checked = false;
    chkAll.indeterminate = false;
    return;
  }
  if (selectedTags.size === totalRows) {
    chkAll.checked = true;
    chkAll.indeterminate = false;
    return;
  }
  chkAll.checked = false;
  chkAll.indeterminate = true;
}

function setExportButtonUI() {
  if (!btnExport) return;

  const logged = sessionStorage.getItem("auth_ok") === "1";
  const hasTags = selectedTags.size > 0;

  btnExport.disabled = !logged || !hasTags;
  btnExport.textContent = exporting ? "Detener y descargar" : "Iniciar export";
}

// =====================================
// Render table
// =====================================
function onTagSelectionChanged(totalRows) {
  if (!exporting) {
    setExportButtonUI();
    updateChkAllState(totalRows);
  }
}

function updateTable(data) {
  const payload = Array.isArray(data) ? data[data.length - 1] : data;
  const flat = flattenObject(payload);
  const entries = Object.entries(flat);

  tbody.innerHTML = "";

  for (const [tag, value] of entries) {
    const tr = document.createElement("tr");

    const tdTag = document.createElement("td");
    tdTag.textContent = tag;

    const tdVal = document.createElement("td");
    tdVal.textContent = typeof value === "object" ? JSON.stringify(value) : String(value);

    const tdChk = document.createElement("td");
    tdChk.className = "col-sel";

    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.checked = selectedTags.has(tag);
    chk.disabled = exporting;

    chk.addEventListener("change", () => {
      if (chk.checked) selectedTags.add(tag);
      else selectedTags.delete(tag);
      onTagSelectionChanged(entries.length);
    });

    tdChk.appendChild(chk);

    tr.appendChild(tdTag);
    tr.appendChild(tdVal);
    tr.appendChild(tdChk);

    tbody.appendChild(tr);
  }

  onTagSelectionChanged(entries.length);
}

chkAll?.addEventListener("change", () => {
  const allChecks = tbody.querySelectorAll('input[type="checkbox"]');

  if (exporting) {
    chkAll.checked = !chkAll.checked;
    return;
  }

  if (chkAll.checked) {
    allChecks.forEach((c) => {
      c.checked = true;
      const row = c.closest("tr");
      const tag = row?.children?.[0]?.textContent;
      if (tag) selectedTags.add(tag);
    });
  } else {
    allChecks.forEach((c) => (c.checked = false));
    selectedTags.clear();
  }

  onTagSelectionChanged(allChecks.length);
});

// =====================================
// Export RT
// =====================================
async function fetchExportStatus() {
  const res = await fetch(`${API_BASE}/api/export/status`, { cache: "no-store" });
  console.log("EXPORT STATUS URL =>", `${API_BASE}/api/export/status`);
  const raw = await res.text();
  if (!res.ok) throw new Error(raw.slice(0, 200));

  try { return JSON.parse(raw); }
  catch { throw new Error("Status no-JSON: " + raw.slice(0, 120)); }
}

async function pollExportStatus() {
  try {
    const st = await fetchExportStatus();
    exporting = !!st.active;

    if (exportCount) exportCount.textContent = String(st.rows_written ?? 0);

    tbody.querySelectorAll('input[type="checkbox"]').forEach((c) => (c.disabled = exporting));
    if (chkAll) chkAll.disabled = exporting;

    setExportButtonUI();
    return st;
  } catch (e) {
    console.warn("pollExportStatus error:", e);
  }
}

async function startExport() {
  if (selectedTags.size === 0) return;

  const tags = Array.from(selectedTags);

  const res = await fetch(`${API_BASE}/api/export/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tags }),
  });

  const raw = await res.text();
  if (!res.ok) throw new Error(raw.slice(0, 200));

  exporting = true;
  setExportButtonUI();

  if (exportPoll) clearInterval(exportPoll);
  exportPoll = setInterval(pollExportStatus, 500);

  await pollExportStatus();
}

async function stopExport() {
  const res = await fetch(`${API_BASE}/api/export/stop`, { method: "POST" });
  const raw = await res.text();
  if (!res.ok) throw new Error(raw.slice(0, 200));

  exporting = false;

  if (exportPoll) {
    clearInterval(exportPoll);
    exportPoll = null;
  }

  await pollExportStatus();
}

async function downloadExportXlsx() {
  const res = await fetch(`${API_BASE}/api/export/download`, { cache: "no-store" });
  if (!res.ok) throw new Error((await res.text()).slice(0, 200));

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = `rt_export_${new Date().toISOString().replaceAll(":", "-")}.xlsx`;
  document.body.appendChild(a);
  a.click();
  a.remove();

  URL.revokeObjectURL(url);
}

btnExport?.addEventListener("click", async () => {
  try {
    const st = await fetchExportStatus().catch(() => null);
    if (st) exporting = !!st.active;

    if (!exporting) {
      await startExport();
    } else {
      await stopExport();
      await downloadExportXlsx();
    }
  } catch (e) {
    console.error(e);
    alert("Export falló: " + (e?.message ?? e));
  }
});

// =====================================
// WebSocket connect/disconnect
// =====================================
btnConnect.addEventListener("click", () => {
  const url = `${WS_BASE}/ws`;
  console.log("Conectando WS a:", url);

  ws = new WebSocket(url);

  ws.onopen = () => {
    statusDiv.textContent = "WebSocket conectado. Recibiendo datos…";
    btnConnect.disabled = true;
    btnDisconnect.disabled = false;
  };

  ws.onmessage = (evt) => {
    let parsed;
    try { parsed = JSON.parse(evt.data); }
    catch { return; }

    const nowMs = performance.now();
    if (nowMs - lastRender > 50) {
      updateTable(parsed);
      lastRender = nowMs;
      statusDiv.textContent = `Última actualización: ${new Date().toLocaleTimeString()}`;
    }
  };

  ws.onerror = (e) => console.error("WS error:", e);

  ws.onclose = () => {
    statusDiv.textContent = "WebSocket desconectado.";
    btnConnect.disabled = false;
    btnDisconnect.disabled = true;
    ws = null;
  };
});

btnDisconnect.addEventListener("click", () => {
  if (ws) ws.close();
  ws = null;
});

// =====================================
// Init
// =====================================
setExportButtonUI();
pollExportStatus();
