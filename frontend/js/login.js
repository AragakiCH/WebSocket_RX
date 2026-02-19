// js/login.js
// Login modal + OPC UA discover dropdown + login POST (/api/opcua/login)
// - Soporta reverse-proxy (/api-websocket-rx) sin hardcodear rutas
// - Evita “Unexpected token '<'” leyendo response como texto y validando content-type
// - No “rompe” el gating: al loguear llama window.__enableApp() y además emite auth:ok
//
// Requiere en el HTML:
//  - #loginOverlay, #loginForm, #loginErr, #userInput, #passInput, #ipSelect
//  - (opcional) #btnTogglePass, #ipHint

const loginOverlay = document.getElementById("loginOverlay");
const loginForm = document.getElementById("loginForm");
const loginErr = document.getElementById("loginErr");
const userInput = document.getElementById("userInput");
const passInput = document.getElementById("passInput");
const ipSelect = document.getElementById("ipSelect");
const ipHint = document.getElementById("ipHint");
const btnTogglePass = document.getElementById("btnTogglePass");

const STORE = sessionStorage;

// ===============================
// URL base robusta para ctrlX reverse proxy
// ===============================
function computePrefix() {
  // Ej: baseURI = https://192.168.17.60/api-websocket-rx/
  // new URL(".", baseURI).pathname => "/api-websocket-rx/"
  const dir = new URL(".", document.baseURI).pathname;
  return dir.endsWith("/") ? dir.slice(0, -1) : dir; // "/api-websocket-rx"
}

const APP_PREFIX = computePrefix(); // "" o "/api-websocket-rx"
const API_BASE = `${location.origin}${APP_PREFIX}`;
const WS_BASE = `${location.origin.replace(/^http/, "ws")}${APP_PREFIX}`; // por si lo usas luego

// ===============================
// Config de sesión
// ===============================
// 👇 OJO: si dejas esto, SIEMPRE te fuerza login al recargar.
// Si quieres “recordar” en la pestaña, comenta estas 3 líneas.
STORE.removeItem("auth_ok");
STORE.removeItem("auth_user");
STORE.removeItem("opcua_url");

// ===============================
// UI helpers
// ===============================
function setError(msg) {
  if (!loginErr) return;
  loginErr.hidden = !msg;
  loginErr.textContent = msg || "";
}

function showLogin() {
  loginOverlay?.classList.remove("hidden");
  setError("");
  userInput?.focus();
}

function hideLogin() {
  loginOverlay?.classList.add("hidden");
  setError("");

  // 1) habilita la app incluso si el evento se pierde
  if (typeof window.__enableApp === "function") window.__enableApp();

  // 2) compat con tu app.js (listener auth:ok)
  window.dispatchEvent(new Event("auth:ok"));
}

// toggle pass (opcional)
btnTogglePass?.addEventListener("click", () => {
  if (!passInput) return;
  const isPwd = passInput.type === "password";
  passInput.type = isPwd ? "text" : "password";
  btnTogglePass.textContent = isPwd ? "Ocultar" : "Mostrar";
});

function labelFor(item) {
  // item: { url, host, ip, port, tcp_ok, source }
  const ok = item.tcp_ok ? "✅" : "⛔";
  const src = item.source ? ` · ${item.source}` : "";
  const ip = item.ip && item.ip !== item.host ? ` (${item.ip})` : "";
  return `${ok} ${item.host}${ip}:${item.port}${src}`;
}

function populateSelect(items) {
  if (!ipSelect) return;

  ipSelect.innerHTML = "";

  const optAuto = document.createElement("option");
  optAuto.value = "";
  optAuto.textContent = "Automático (recomendado)";
  ipSelect.appendChild(optAuto);

  const good = items.filter((x) => !!x.tcp_ok);
  const bad = items.filter((x) => !x.tcp_ok);

  for (const it of [...good, ...bad]) {
    const opt = document.createElement("option");
    opt.value = it.url; // opc.tcp://x:4840
    opt.textContent = labelFor(it);
    ipSelect.appendChild(opt);
  }

  ipSelect.value = good.length > 0 ? good[0].url : "";

  if (ipHint) {
    ipHint.textContent = `Encontrados: ${items.length} · TCP OK: ${good.length}`;
  }
}

// ===============================
// Discover (anti “Unexpected token '<'”)
// ===============================
let discoverLoaded = false;

async function loadDiscover() {
  if (!ipSelect || discoverLoaded) return; // evita spam
  discoverLoaded = true;

  try {
    setError("");

    ipSelect.disabled = true;
    ipSelect.innerHTML =
      `<option value="" disabled selected>Cargando endpoints…</option>`;

    const url = `${API_BASE}/api/opcua/discover`;
    console.log("DISCOVER URL =>", url);

    const res = await fetch(url, { cache: "no-store" });
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    const raw = await res.text();

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${raw.slice(0, 200)}`);
    }

    // Si ctrlX te devolvió HTML (proxy/ruta), lo cazamos aquí
    if (!ct.includes("application/json")) {
      const head = raw.slice(0, 140).replace(/\s+/g, " ");
      throw new Error(`Respuesta no-JSON (CT=${ct || "?"}): ${head}`);
    }

    const items = JSON.parse(raw);
    populateSelect(Array.isArray(items) ? items : []);
  } catch (e) {
    console.error("discover error:", e);
    setError("No pude listar endpoints OPC UA: " + (e?.message ?? e));
    if (ipSelect) {
      ipSelect.innerHTML =
        `<option value="" disabled selected>Error cargando endpoints</option>`;
    }
  } finally {
    if (ipSelect) ipSelect.disabled = false;
  }
}

// ===============================
// Boot
// ===============================
if (STORE.getItem("auth_ok") === "1") {
  hideLogin();
} else {
  showLogin();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", loadDiscover, { once: true });
} else {
  loadDiscover();
}

// ===============================
// Submit login
// ===============================
loginForm?.addEventListener("submit", async (e) => {
  e.preventDefault();

  const u = (userInput?.value || "").trim();
  const p = passInput?.value || "";

  const selectedUrl = (ipSelect?.value || "").trim();
  const urlToSend = selectedUrl ? selectedUrl : null;

  if (!u || !p) {
    setError("Faltan credenciales.");
    return;
  }

  try {
    setError("");

    const r = await fetch(`${API_BASE}/api/opcua/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user: u, password: p, url: urlToSend }),
    });

    const raw = await r.text();
    let data = null;
    try {
      data = JSON.parse(raw);
    } catch {
      data = null;
    }

    if (!r.ok) {
      const msg =
        data?.detail?.error
          ? `${data.detail.error}\n\nTried:\n${(data.detail.tried || []).slice(0, 10).join("\n")}`
          : (data?.detail ? JSON.stringify(data.detail) : raw.slice(0, 200) || "No pude autenticar OPC UA.");
      setError(msg);
      return;
    }

    STORE.setItem("auth_ok", "1");
    STORE.setItem("auth_user", u);
    if (data?.url) STORE.setItem("opcua_url", data.url);

    hideLogin();
  } catch (err) {
    console.error("login error:", err);
    setError("Servidor no responde.");
  }
});
