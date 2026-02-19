// js/login.js
// Login modal + OPC UA discover dropdown + login POST (/api/opcua/login)

const loginOverlay = document.getElementById("loginOverlay");
const loginForm = document.getElementById("loginForm");
const loginErr = document.getElementById("loginErr");
const userInput = document.getElementById("userInput");
const passInput = document.getElementById("passInput");
const ipSelect = document.getElementById("ipSelect");
const ipHint = document.getElementById("ipHint");
const btnTogglePass = document.getElementById("btnTogglePass");

const STORE = sessionStorage;

function computePrefix() {
  const dir = new URL(".", document.baseURI).pathname; // "/api-websocket-rx/"
  return dir.endsWith("/") ? dir.slice(0, -1) : dir;   // "/api-websocket-rx"
}

const APP_PREFIX = computePrefix();
const API_BASE = `${location.origin}${APP_PREFIX}`;

function setError(msg) {
  if (!loginErr) return;
  loginErr.hidden = !msg;
  loginErr.textContent = msg || "";
}

function showLogin() {
  if (!loginOverlay) return;
  loginOverlay.classList.remove("hidden");
  setError("");
  userInput?.focus();
}

function hideLogin() {
  if (!loginOverlay) return;
  loginOverlay.classList.add("hidden");
  setError("");

  // habilita la app sí o sí
  if (typeof window.__enableApp === "function") window.__enableApp();
  window.dispatchEvent(new Event("auth:ok"));
}

btnTogglePass?.addEventListener("click", () => {
  if (!passInput) return;
  const isPwd = passInput.type === "password";
  passInput.type = isPwd ? "text" : "password";
  btnTogglePass.textContent = isPwd ? "Ocultar" : "Mostrar";
});

function labelFor(item) {
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
    opt.value = it.url;
    opt.textContent = labelFor(it);
    ipSelect.appendChild(opt);
  }

  ipSelect.value = good.length > 0 ? good[0].url : "";

  if (ipHint) ipHint.textContent = `Encontrados: ${items.length} · TCP OK: ${good.length}`;
}

let discoverLoaded = false;
async function loadDiscover() {
  if (!ipSelect || discoverLoaded) return;
  discoverLoaded = true;

  try {
    setError("");
    ipSelect.disabled = true;
    ipSelect.innerHTML = `<option value="" disabled selected>Cargando endpoints…</option>`;

    const url = `${API_BASE}/api/opcua/discover`;
    const res = await fetch(url, { cache: "no-store" });

    const ct = (res.headers.get("content-type") || "").toLowerCase();
    const raw = await res.text();

    if (!res.ok) throw new Error(`HTTP ${res.status}: ${raw.slice(0, 200)}`);
    if (!ct.includes("application/json")) {
      const head = raw.slice(0, 140).replace(/\s+/g, " ");
      throw new Error(`Respuesta no-JSON (CT=${ct || "?"}): ${head}`);
    }

    const items = JSON.parse(raw);
    populateSelect(Array.isArray(items) ? items : []);
  } catch (e) {
    console.error("discover error:", e);
    setError("No pude listar endpoints OPC UA: " + (e?.message ?? e));
    if (ipSelect) ipSelect.innerHTML = `<option value="" disabled selected>Error cargando endpoints</option>`;
  } finally {
    if (ipSelect) ipSelect.disabled = false;
  }
}

// Boot
if (STORE.getItem("auth_ok") === "1") hideLogin();
else showLogin();

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", loadDiscover, { once: true });
} else {
  loadDiscover();
}

// Submit login
loginForm?.addEventListener("submit", async (e) => {
  e.preventDefault();

  const u = (userInput?.value || "").trim();
  const p = passInput?.value || "";

  const selectedUrl = (ipSelect?.value || "").trim();
  const urlToSend = selectedUrl ? selectedUrl : null;

  if (!u || !p) return setError("Faltan credenciales.");

  try {
    setError("");

    const r = await fetch(`${API_BASE}/api/opcua/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user: u, password: p, url: urlToSend }),
    });

    const raw = await r.text();
    let data = null;
    try { data = JSON.parse(raw); } catch {}

    if (!r.ok) {
      const msg =
        data?.detail?.error
          ? `${data.detail.error}\n\nTried:\n${(data.detail.tried || []).slice(0, 10).join("\n")}`
          : (data?.detail ? JSON.stringify(data.detail) : raw.slice(0, 200) || "No pude autenticar OPC UA.");
      return setError(msg);
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
