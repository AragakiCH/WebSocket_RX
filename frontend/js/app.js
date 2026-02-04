// --- refs UI ---
const btnConnect = document.getElementById("btnConnect");
const btnDisconnect = document.getElementById("btnDisconnect");
const statusDiv = document.getElementById("status");
const tbody = document.querySelector("#data-table tbody");

btnConnect.disabled = false;   // 👈 AQUI

// NUEVO
const btnExport = document.getElementById("btnExport");
const chkAll = document.getElementById("chkAll");

let ws = null;
let lastRender = 0;

// NUEVO: selección persistente por tag
const selectedTags = new Set();

console.log("WS script cargado (v3)");

// --- util: aplanar objetos anidados {A:{x:1}} -> {"A.x":1} ---
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

function setExportEnabled() {
  btnExport.disabled = selectedTags.size === 0;
}

function updateChkAllState(totalRows) {
  if (totalRows <= 0) {
    chkAll.checked = false;
    chkAll.indeterminate = false;
    return;
  }
  if (selectedTags.size === 0) {
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

// --- pinta la tabla (acepta dict plano o anidado) ---
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
    tdVal.textContent =
      typeof value === "object" ? JSON.stringify(value) : String(value);

    const tdChk = document.createElement("td");
    tdChk.className = "col-sel";

    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.checked = selectedTags.has(tag);

    chk.addEventListener("change", () => {
      if (chk.checked) selectedTags.add(tag);
      else selectedTags.delete(tag);

      setExportEnabled();
      updateChkAllState(entries.length);
    });

    tdChk.appendChild(chk);

    // ✅ orden: Tag | Valor | Checkbox
    tr.appendChild(tdTag);
    tr.appendChild(tdVal);
    tr.appendChild(tdChk);

    tbody.appendChild(tr);
  }

  setExportEnabled();
  updateChkAllState(entries.length);
}

// ✅ seleccionar todo / none
chkAll?.addEventListener("change", () => {
  const allChecks = tbody.querySelectorAll('input[type="checkbox"]');

  if (chkAll.checked) {
    allChecks.forEach((c) => {
      c.checked = true;
      const row = c.closest("tr");
      const tag = row?.children?.[0]?.textContent; // ✅ Tag está en col 0
      if (tag) selectedTags.add(tag); 
    });
  } else {
    allChecks.forEach((c) => (c.checked = false));
    selectedTags.clear();
  }

  setExportEnabled();
  updateChkAllState(allChecks.length);
});


// ✅ Exportar (CSV que Excel abre)
btnExport?.addEventListener("click", () => {
  if (selectedTags.size === 0) return;

  const rows = [];
  rows.push(["Tag", "Valor", "Timestamp"].join(","));

  const now = new Date().toISOString();

  const trs = tbody.querySelectorAll("tr");
  trs.forEach((tr) => {
    const tag = tr.children[0]?.textContent ?? "";
    const val = tr.children[1]?.textContent ?? "";
    if (!selectedTags.has(tag)) return;

    const safeTag = `"${String(tag).replaceAll('"', '""')}"`;
    const safeVal = `"${String(val).replaceAll('"', '""')}"`;
    rows.push([safeTag, safeVal, now].join(","));
  });

  const blob = new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = `ctrlx_export_${new Date().toISOString().replaceAll(":", "-")}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();

  URL.revokeObjectURL(url);
});


// --- conectar WebSocket ---
btnConnect.addEventListener("click", () => {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${location.host}/ws`;
  console.log("Conectando WS a:", url);

  ws = new WebSocket(url);

  ws.onopen = () => {
    console.log("WS abierto");
    statusDiv.textContent = "WebSocket conectado. Recibiendo datos…";
    btnConnect.disabled = true;
    btnDisconnect.disabled = false;
  };

  ws.onmessage = (evt) => {
    let parsed;
    try {
      parsed = JSON.parse(evt.data);
    } catch (e) {
      console.warn("No es JSON:", evt.data, e);
      return;
    }

    const nowMs = performance.now();
    if (nowMs - lastRender > 50) {
      updateTable(parsed);
      lastRender = nowMs;
      statusDiv.textContent = `Última actualización: ${new Date().toLocaleTimeString()}`;
    }
  };

  ws.onerror = (e) => console.error("WS error:", e);

  ws.onclose = () => {
    console.log("WS cerrado");
    statusDiv.textContent = "WebSocket desconectado.";
    btnConnect.disabled = false;
    btnDisconnect.disabled = true;
    ws = null;
  };
});

// --- desconectar WebSocket ---
btnDisconnect.addEventListener("click", () => {
  if (ws) {
    ws.close();
    ws = null;
  }
});
