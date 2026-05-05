// js/trends.js
// Vista Trends — gráfica en tiempo real con Chart.js
// - WebSocket propio (no depende del dashboard)
// - Selecciona tags por checkbox para graficar/desgraficar
// - Mantiene un historial circular de N puntos por serie

(() => {
  // ============================
  // Refs UI
  // ============================
  const btnConnect = document.getElementById("btnConnect");
  const btnDisconnect = document.getElementById("btnDisconnect");
  const btnClearChart = document.getElementById("btnClearChart");
  const statusDiv = document.getElementById("status");
  const tagsList = document.getElementById("tagsList");
  const activeCount = document.getElementById("activeCount");
  const canvas = document.getElementById("trendsChart");

  // ============================
  // Config
  // ============================
  const MAX_POINTS = 500; // 👈 puntos por serie en memoria (fijo)

  // ============================
  // URLs (mismo cálculo que en app.js)
  // ============================
  const parts = location.pathname.split("/").filter(Boolean);
  const APP_PREFIX = parts.length ? `/${parts[0]}` : "";
  const WS_BASE = `${location.origin.replace(/^http/, "ws")}${APP_PREFIX}`;

  // ============================
  // State
  // ============================
  let ws = null;
  let lastRender = 0;

  // tags actualmente disponibles (último frame del WS)
  let currentTags = {};

  // tags seleccionados para graficar
  const selectedTags = new Set();

  // historial: { "Tag.Path": [{x: ts, y: val}, ...] }
  const seriesData = {};

  // colores asignados a cada tag (consistentes)
  const seriesColors = {};
  const COLOR_PALETTE = [
    "#58C7FF", "#A78BFA", "#22C55E", "#EF4444", "#F59E0B",
    "#EC4899", "#14B8A6", "#F97316", "#84CC16", "#06B6D4",
    "#8B5CF6", "#FB7185", "#10B981", "#FBBF24", "#3B82F6",
  ];
  let colorIdx = 0;
  function colorFor(tag) {
    if (!seriesColors[tag]) {
      seriesColors[tag] = COLOR_PALETTE[colorIdx % COLOR_PALETTE.length];
      colorIdx++;
    }
    return seriesColors[tag];
  }

  // ============================
  // Chart.js setup
  // ============================
  const chart = new Chart(canvas, {
    type: "line",
    data: { datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      parsing: false,
      plugins: {
        legend: {
          labels: { color: "#EAF0FF", font: { size: 12 } },
        },
        tooltip: {
          backgroundColor: "rgba(15, 20, 40, 0.95)",
          titleColor: "#EAF0FF",
          bodyColor: "#EAF0FF",
          borderColor: "rgba(88,199,255,0.4)",
          borderWidth: 1,
        },
      },
      scales: {
        x: {
          type: "linear",
          ticks: {
            color: "rgba(234,240,255,0.65)",
            callback: (v) => {
              const d = new Date(v);
              return d.toLocaleTimeString();
            },
          },
          grid: { color: "rgba(255,255,255,0.06)" },
        },
        y: {
          ticks: { color: "rgba(234,240,255,0.65)" },
          grid: { color: "rgba(255,255,255,0.06)" },
        },
      },
    },
  });

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

  function isNumeric(v) {
    if (typeof v === "number") return Number.isFinite(v);
    if (typeof v === "boolean") return true;
    if (typeof v === "string") {
      const n = Number(v);
      return v.trim() !== "" && Number.isFinite(n);
    }
    return false;
  }

  function toNumber(v) {
    if (typeof v === "boolean") return v ? 1 : 0;
    return Number(v);
  }

  // ============================
  // Render lista de tags (panel izquierdo)
  // ============================
  function renderTagsList() {
    if (!tagsList) return;

    const entries = Object.entries(currentTags);
    if (entries.length === 0) {
      tagsList.innerHTML = `
        <div class="empty-state">
          Conéctate al PLC para ver los tags disponibles.
        </div>`;
      return;
    }

    const existingTags = new Set(
      Array.from(tagsList.querySelectorAll(".tag-row")).map((r) => r.dataset.tag)
    );
    const incomingTags = new Set(entries.map(([t]) => t));

    const sameSet =
      existingTags.size === incomingTags.size &&
      [...existingTags].every((t) => incomingTags.has(t));

    if (!sameSet) {
      tagsList.innerHTML = "";
      for (const [tag] of entries) {
        const row = document.createElement("div");
        row.className = "tag-row";
        row.dataset.tag = tag;
        if (selectedTags.has(tag)) row.classList.add("active");

        row.innerHTML = `
          <label>
            <input type="checkbox" ${selectedTags.has(tag) ? "checked" : ""} />
            <span>${tag}</span>
          </label>
          <span class="tag-value" data-val></span>
        `;

        const chk = row.querySelector('input[type="checkbox"]');
        chk.addEventListener("change", () => {
          if (chk.checked) {
            selectedTags.add(tag);
            row.classList.add("active");
            ensureDataset(tag);
          } else {
            selectedTags.delete(tag);
            row.classList.remove("active");
            removeDataset(tag);
          }
          updateActiveCount();
        });

        tagsList.appendChild(row);
      }
    }

    for (const [tag, val] of entries) {
      const row = tagsList.querySelector(`.tag-row[data-tag="${CSS.escape(tag)}"]`);
      if (row) {
        const span = row.querySelector("[data-val]");
        if (span) {
          span.textContent =
            typeof val === "object" ? JSON.stringify(val) : String(val);
        }
      }
    }
  }

  function updateActiveCount() {
    if (activeCount) activeCount.textContent = String(selectedTags.size);
  }

  // ============================
  // Datasets de la gráfica
  // ============================
  function ensureDataset(tag) {
    if (!seriesData[tag]) seriesData[tag] = [];

    const exists = chart.data.datasets.some((d) => d.label === tag);
    if (exists) return;

    const color = colorFor(tag);
    chart.data.datasets.push({
      label: tag,
      data: seriesData[tag],
      borderColor: color,
      backgroundColor: color + "33",
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.2,
      spanGaps: true,
    });
    chart.update("none");
  }

  function removeDataset(tag) {
    chart.data.datasets = chart.data.datasets.filter((d) => d.label !== tag);
    chart.update("none");
  }

  // ============================
  // Push de un nuevo frame al historial
  // ============================
  function pushFrame(flat) {
    const ts = Date.now();

    for (const tag of selectedTags) {
      const raw = flat[tag];
      if (raw === undefined) continue;
      if (!isNumeric(raw)) continue;

      const arr = seriesData[tag] || (seriesData[tag] = []);
      arr.push({ x: ts, y: toNumber(raw) });

      // ventana circular fija
      while (arr.length > MAX_POINTS) arr.shift();
    }
  }

  // ============================
  // WebSocket
  // ============================
  function setStatus(text) {
    if (statusDiv) statusDiv.textContent = text;
  }

  function connect() {
    const url = `${WS_BASE}/ws`;
    console.log("[trends] WS →", url);

    ws = new WebSocket(url);

    ws.onopen = () => {
      setStatus("WebSocket conectado. Recibiendo datos…");
      btnConnect.disabled = true;
      btnDisconnect.disabled = false;
    };

    ws.onmessage = (evt) => {
      let parsed;
      try {
        parsed = JSON.parse(evt.data);
      } catch {
        return;
      }

      const payload = Array.isArray(parsed) ? parsed[parsed.length - 1] : parsed;
      const flat = flattenObject(payload);
      currentTags = flat;

      const nowMs = performance.now();
      pushFrame(flat);

      if (nowMs - lastRender > 100) {
        lastRender = nowMs;
        renderTagsList();
        if (selectedTags.size > 0) chart.update("none");
        setStatus(`Última actualización: ${new Date().toLocaleTimeString()}`);
      }
    };

    ws.onerror = (e) => console.error("[trends] WS error:", e);

    ws.onclose = () => {
      setStatus("WebSocket desconectado.");
      btnConnect.disabled = false;
      btnDisconnect.disabled = true;
      ws = null;
    };
  }

  function disconnect() {
    if (ws) ws.close();
    ws = null;
  }

  // ============================
  // Eventos UI
  // ============================
  btnConnect?.addEventListener("click", connect);
  btnDisconnect?.addEventListener("click", disconnect);

  btnClearChart?.addEventListener("click", () => {
    for (const tag of Object.keys(seriesData)) seriesData[tag] = [];
    chart.data.datasets.forEach((d) => {
      d.data = seriesData[d.label] || [];
    });
    chart.update("none");
  });

  window.addEventListener("beforeunload", () => {
    if (ws) ws.close();
  });
})();