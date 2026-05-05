// js/app.js
// Dashboard — usa SharedWS

// --- refs UI ---
const btnConnect = document.getElementById("btnConnect");
const btnDisconnect = document.getElementById("btnDisconnect");
const statusDiv = document.getElementById("status");
const tbody = document.querySelector("#data-table tbody");
const btnExport = document.getElementById("btnExport");
const exportCount = document.getElementById("exportCount");
const chkAll = document.getElementById("chkAll");
const connStatusBadge = document.getElementById("connStatusBadge");

// ============================
// URLs
// ============================
const parts = location.pathname.split("/").filter(Boolean);
window.APP_PREFIX = parts.length ? `/${parts[0]}` : "";
window.API_BASE = `${location.origin}${window.APP_PREFIX}`;

// --- state ---
let lastRender = 0;
let exporting = false;
let exportPoll = null;
const selectedTags = new Set();

// safety
if (btnConnect) btnConnect.disabled = true;
if (btnDisconnect) btnDisconnect.disabled = true;

// ============================
// Badge de conexión
// ============================
function setConnBadge(online) {
  if (!connStatusBadge) return;
  if (online) {
    connStatusBadge.className = "conn-badge online";
    connStatusBadge.innerHTML = `<i class="fa-solid fa-circle"></i> Conectado`;
  } else {
    connStatusBadge.className = "conn-badge offline";
    connStatusBadge.innerHTML = `<i class="fa-solid fa-circle"></i> Desconectado`;
  }
}

// ============================
// Auth gating
// ============================
function enableApp() {
  if (!btnConnect) return;
  btnConnect.disabled = false;
  setExportButtonUI();
}

window.__enableApp = enableApp;

if (sessionStorage.getItem("auth_ok") === "1") enableApp();
window.addEventListener("auth:ok", () => enableApp());
setTimeout(() => {
  if (sessionStorage.getItem("auth_ok") === "1") enableApp();
}, 0);

// ============================
// Utils
// ============================
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
  
  // 👇 Actualiza texto del botón según estado del export
  if (btnExport.querySelector("span")) {
    btnExport.querySelector("span").textContent = exporting
      ? "Detener y descargar"
      : "Iniciar export";
  }
}

// ============================
// Render table
// ============================
function onTagSelectionChanged(totalRows) {
  if (!exporting) {
    setExportButtonUI();
    updateChkAllState(totalRows);
  }
}

function updateTable(data) {
  if (!tbody) return;

  const payload = Array.isArray(data) ? data[data.length - 1] : data;
  const flat = flattenObject(payload);
  const entries = Object.entries(flat);

  tbody.innerHTML = "";

  for (const [tag, value] of entries) {
    const tr = document.createElement("tr");

    const tdTag = document.createElement("td");
    tdTag.textContent = tag;

    const tdVal = document.createElement("td");
    tdVal.textContent =
      typeof value === "object" ? JSON.stringify(value) : String(value);

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

// Seleccionar todo
chkAll?.addEventListener("change", () => {
  if (!tbody) return;
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

// ============================
// Export RT (sin cambios)
// ============================
async function fetchExportStatus() {
  const url = `${window.API_BASE}/api/export/status`;
  const res = await fetch(url, { cache: "no-store" });
  const raw = await res.text();
  if (!res.ok) throw new Error(raw.slice(0, 200));
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error("Status no-JSON: " + raw.slice(0, 120));
  }
}

async function pollExportStatus() {
  try {
    const st = await fetchExportStatus();
    exporting = !!st.active;
    if (exportCount) exportCount.textContent = String(st.rows_written ?? 0);
    if (tbody) {
      tbody
        .querySelectorAll('input[type="checkbox"]')
        .forEach((c) => (c.disabled = exporting));
    }
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
  const res = await fetch(`${window.API_BASE}/api/export/start`, {
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
  const res = await fetch(`${window.API_BASE}/api/export/stop`, {
    method: "POST",
  });
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
  const res = await fetch(`${window.API_BASE}/api/export/download`, {
    cache: "no-store",
  });
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

// ============================
// WebSocket compartido (SharedWS)
// ============================
btnConnect?.addEventListener("click", () => {
  window.SharedWS.connect();
});

btnDisconnect?.addEventListener("click", () => {
  window.SharedWS.disconnect();
});

// Suscribirse a eventos del WebSocket compartido
window.SharedWS.subscribe((event) => {
  if (event.type === "open") {
    if (statusDiv) statusDiv.querySelector("span").textContent = "Conectado. Recibiendo datos…";
    if (btnConnect) btnConnect.disabled = true;
    if (btnDisconnect) btnDisconnect.disabled = false;
    setConnBadge(true);
  } else if (event.type === "message") {
    const nowMs = performance.now();
    if (nowMs - lastRender > 50) {
      updateTable(event.data);
      lastRender = nowMs;
      if (statusDiv) {
        statusDiv.querySelector("span").textContent = `Última actualización: ${new Date().toLocaleTimeString()}`;
      }
    }
  } else if (event.type === "close") {
    if (statusDiv) statusDiv.querySelector("span").textContent = "WebSocket desconectado.";
    if (btnConnect) btnConnect.disabled = false;
    if (btnDisconnect) btnDisconnect.disabled = true;
    setConnBadge(false);
  } else if (event.type === "error") {
    console.error("WS error:", event.data);
  }
});

// Si ya está conectado al cargar, actualiza UI
if (window.SharedWS.isConnected) {
  if (btnConnect) btnConnect.disabled = true;
  if (btnDisconnect) btnDisconnect.disabled = false;
  setConnBadge(true);
}

// ============================
// Init
// ============================
setExportButtonUI();
pollExportStatus();

// ============================
// Logout
// ============================
// ============================
// Logout con modal personalizado
// ============================
const btnLogout = document.getElementById("btnLogout");
const logoutModal = document.getElementById("logoutModal");
const btnCancelLogout = document.getElementById("btnCancelLogout");
const btnConfirmLogout = document.getElementById("btnConfirmLogout");

function showLogoutModal() {
  if (logoutModal) {
    logoutModal.hidden = false;
    // Focus en el botón cancelar para accesibilidad
    btnCancelLogout?.focus();
  }
}

function hideLogoutModal() {
  if (logoutModal) {
    logoutModal.hidden = true;
  }
}

function doLogout() {
  hideLogoutModal();

  try {
    window.SharedWS.disconnect();
  } catch (e) {
    console.warn("Error cerrando WS en logout:", e);
  }

  // Limpiar trends
  sessionStorage.removeItem("trends_selected_tags");
  sessionStorage.removeItem("trends_series_data");

  sessionStorage.clear();

  const parts = location.pathname.split("/").filter(Boolean);
  const prefix = parts.length ? `/${parts[0]}` : "";
  window.location.replace(`${prefix}/login`);
}

// Click en botón logout del sidebar
btnLogout?.addEventListener("click", () => {
  showLogoutModal();
});

// Click en Cancelar
btnCancelLogout?.addEventListener("click", () => {
  hideLogoutModal();
});

// Click en Confirmar
btnConfirmLogout?.addEventListener("click", () => {
  doLogout();
});

// Click en el backdrop (fondo oscuro) también cierra el modal
logoutModal?.querySelector(".logout-modal-backdrop")?.addEventListener("click", () => {
  hideLogoutModal();
});

// ESC para cerrar el modal
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && logoutModal && !logoutModal.hidden) {
    hideLogoutModal();
  }
});