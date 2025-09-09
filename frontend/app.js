// --- refs UI ---
const btnConnect    = document.getElementById("btnConnect");
const btnDisconnect = document.getElementById("btnDisconnect");
const statusDiv     = document.getElementById("status");
const tbody         = document.querySelector("#data-table tbody");

let ws = null;
let lastRender = 0;

console.log("WS script cargado (v2)");

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

// --- pinta la tabla (acepta dict plano o anidado) ---
function updateTable(data) {
  // si viene array, toma el último (más reciente)
  const payload = Array.isArray(data) ? data[data.length - 1] : data;

  // si viene anidado por tipo, aplánalo
  const flat = flattenObject(payload);

  tbody.innerHTML = "";
  for (const [tag, value] of Object.entries(flat)) {
    const tr    = document.createElement("tr");
    const tdTag = document.createElement("td");
    const tdVal = document.createElement("td");
    tdTag.textContent = tag;
    tdVal.textContent =
      typeof value === "object" ? JSON.stringify(value) : String(value);
    tr.append(tdTag, tdVal);
    tbody.append(tr);
  }
}

// --- conectar WebSocket ---
btnConnect.addEventListener("click", () => {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = "ws://127.0.0.1:8010/ws";
  console.log("Conectando WS a:", url);
  ws = new WebSocket(url);

  ws.onopen = () => {
    console.log("WS abierto");
    statusDiv.textContent = "WebSocket conectado. Recibiendo datos…";
    btnConnect.disabled = true;
    btnDisconnect.disabled = false;
  };

  ws.onmessage = (evt) => {
    // logs para verificar que este archivo sí está cargado
    console.log("Mensaje bruto:", evt.data);

    let parsed;
    try {
      parsed = JSON.parse(evt.data);
    } catch (e) {
      console.warn("No es JSON:", evt.data, e);
      return;
    }

    console.log("Mensaje parseado:", parsed);

    const nowMs = performance.now();
    if (nowMs - lastRender > 50) { // ~20 fps
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
  if (ws) { ws.close(); ws = null; }
});
