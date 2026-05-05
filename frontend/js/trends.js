// js/trends.js
// Vista Trends — reutiliza el WebSocket compartido
// - Persiste selección de tags en sessionStorage

(() => {
  const tagsList = document.getElementById("tagsList");
  const activeCount = document.getElementById("activeCount");
  const canvas = document.getElementById("trendsChart");
  const btnClearChart = document.getElementById("btnClearChart");
  const connStatusBadge = document.getElementById("connStatusBadge");

  const MAX_POINTS = 500;
  let lastRender = 0;
  let currentTags = {};
  const selectedTags = new Set();
  const seriesData = {};
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
  // Persistencia de selección
  // ============================
  const STORAGE_KEY_SELECTED = "trends_selected_tags";
  const STORAGE_KEY_SERIES = "trends_series_data";

  function saveSelection() {
    try {
      sessionStorage.setItem(STORAGE_KEY_SELECTED, JSON.stringify([...selectedTags]));
    } catch (e) {
      console.warn("No pude guardar selección:", e);
    }
  }

  function loadSelection() {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY_SELECTED);
      if (saved) {
        const tags = JSON.parse(saved);
        tags.forEach((tag) => selectedTags.add(tag));
        console.log("[Trends] Selección restaurada:", tags);
      }
    } catch (e) {
      console.warn("No pude cargar selección:", e);
    }
  }

  function saveSeriesData() {
    try {
      // Solo guardar los últimos 100 puntos por serie para no llenar sessionStorage
      const compressed = {};
      for (const [tag, points] of Object.entries(seriesData)) {
        compressed[tag] = points.slice(-100);
      }
      sessionStorage.setItem(STORAGE_KEY_SERIES, JSON.stringify(compressed));
    } catch (e) {
      console.warn("No pude guardar series:", e);
    }
  }

  function loadSeriesData() {
    try {
      const saved = sessionStorage.getItem(STORAGE_KEY_SERIES);
      if (saved) {
        const compressed = JSON.parse(saved);
        for (const [tag, points] of Object.entries(compressed)) {
          seriesData[tag] = points;
        }
        console.log("[Trends] Series restauradas:", Object.keys(seriesData));
      }
    } catch (e) {
      console.warn("No pude cargar series:", e);
    }
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
          labels: {
            color: "#2B2F33",
            font: { size: 12, weight: "600" },
            padding: 12,
            usePointStyle: true,
            pointStyle: "circle",
          },
        },
        tooltip: {
          backgroundColor: "rgba(255, 255, 255, 0.98)",
          titleColor: "#2B2F33",
          bodyColor: "#525F6B",
          borderColor: "#007BC0",
          borderWidth: 2,
          padding: 12,
          boxPadding: 6,
          usePointStyle: true,
        },
      },
      scales: {
        x: {
          type: "linear",
          ticks: {
            color: "#525F6B",
            font: { size: 11 },
            callback: (v) => new Date(v).toLocaleTimeString(),
          },
          grid: { color: "#DFE3E6", lineWidth: 1 },
          border: { color: "#C5CDD3", width: 2 },
        },
        y: {
          ticks: { color: "#525F6B", font: { size: 11 } },
          grid: { color: "#DFE3E6", lineWidth: 1 },
          border: { color: "#C5CDD3", width: 2 },
        },
      },
    },
  });

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

  function renderTagsList() {
    if (!tagsList) return;

    const entries = Object.entries(currentTags);
    if (entries.length === 0) {
      tagsList.innerHTML = `
        <div class="empty-state">
          <i class="fa-solid fa-plug-circle-xmark"></i>
          <p>Esperando datos del WebSocket...</p>
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
          saveSelection(); // 👈 NUEVO: guarda al cambiar
        });

        tagsList.appendChild(row);
      }
    }

    for (const [tag, val] of entries) {
      const row = tagsList.querySelector(`.tag-row[data-tag="${CSS.escape(tag)}"]`);
      if (row) {
        const span = row.querySelector("[data-val]");
        if (span) {
          span.textContent = typeof val === "object" ? JSON.stringify(val) : String(val);
        }
      }
    }
  }

  function updateActiveCount() {
    if (activeCount) activeCount.textContent = String(selectedTags.size);
  }

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

  function pushFrame(flat) {
    const ts = Date.now();
    for (const tag of selectedTags) {
      const raw = flat[tag];
      if (raw === undefined) continue;
      if (!isNumeric(raw)) continue;

      const arr = seriesData[tag] || (seriesData[tag] = []);
      arr.push({ x: ts, y: toNumber(raw) });

      while (arr.length > MAX_POINTS) arr.shift();
    }
  }

  // ============================
  // Init: restaurar selección guardada
  // ============================
  loadSelection();
  loadSeriesData();

  // Restaurar datasets en la gráfica si hay tags seleccionados
  for (const tag of selectedTags) {
    ensureDataset(tag);
  }
  updateActiveCount();
  chart.update("none");

  // ============================
  // Suscripción al WebSocket compartido
  // ============================
  window.SharedWS.subscribe((event) => {
    if (event.type === "open") {
      setConnBadge(true);
    } else if (event.type === "message") {
      const payload = Array.isArray(event.data)
        ? event.data[event.data.length - 1]
        : event.data;
      const flat = flattenObject(payload);
      currentTags = flat;

      const nowMs = performance.now();
      pushFrame(flat);

      if (nowMs - lastRender > 100) {
        lastRender = nowMs;
        renderTagsList();
        if (selectedTags.size > 0) {
          chart.update("none");
          saveSeriesData(); // 👈 NUEVO: guarda los datos periódicamente
        }
      }
    } else if (event.type === "close") {
      setConnBadge(false);
    }
  });

  // Si ya hay datos disponibles al cargar
  if (window.SharedWS.lastData) {
    const payload = Array.isArray(window.SharedWS.lastData)
      ? window.SharedWS.lastData[window.SharedWS.lastData.length - 1]
      : window.SharedWS.lastData;
    const flat = flattenObject(payload);
    currentTags = flat;
    renderTagsList();
  }

  // Si ya está conectado
  if (window.SharedWS.isConnected) {
    setConnBadge(true);
  }

  btnClearChart?.addEventListener("click", () => {
    for (const tag of Object.keys(seriesData)) seriesData[tag] = [];
    chart.data.datasets.forEach((d) => {
      d.data = seriesData[d.label] || [];
    });
    chart.update("none");
    
    // 👇 NUEVO: limpiar también el storage
    sessionStorage.removeItem(STORAGE_KEY_SERIES);
  });

  // ============================
  // Guardar al salir de la página
  // ============================
  window.addEventListener("beforeunload", () => {
    saveSelection();
    saveSeriesData();
  });
})();