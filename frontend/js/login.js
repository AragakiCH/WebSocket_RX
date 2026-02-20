// js/login.js
// Login modal + OPC UA discover dropdown + login POST (/api/opcua/login)
(() => {

const STORE = sessionStorage;

function computePrefix() {
  const dir = new URL(".", document.baseURI).pathname;
  return dir.endsWith("/") ? dir.slice(0, -1) : dir;
}

const APP_PREFIX = window.APP_PREFIX || computePrefix();
const API_BASE = window.API_BASE || `${location.origin}${APP_PREFIX}`;

let discoverLoaded = false;

function getEls() {
  return {
    loginOverlay: document.getElementById("loginOverlay"),
    loginForm: document.getElementById("loginForm"),
    loginErr: document.getElementById("loginErr"),
    userInput: document.getElementById("userInput"),
    passInput: document.getElementById("passInput"),
    ipSelect: document.getElementById("ipSelect"),
    ipHint: document.getElementById("ipHint"),
    btnTogglePass: document.getElementById("btnTogglePass"),
  };
}

function setError(msg) {
  const { loginErr } = getEls();
  if (!loginErr) return;
  loginErr.hidden = !msg;
  loginErr.textContent = msg || "";
}

function showLogin() {
  const { loginOverlay, userInput } = getEls();
  if (!loginOverlay) return;
  loginOverlay.classList.remove("hidden");
  setError("");
  userInput?.focus();
}

function hideLogin() {
  const { loginOverlay } = getEls();
  if (!loginOverlay) return;
  loginOverlay.classList.add("hidden");
  setError("");

  const btn = document.getElementById("btnConnect");
  if (btn) btn.disabled = false;

  if (typeof window.__enableApp === "function") window.__enableApp();
  window.dispatchEvent(new Event("auth:ok"));
}

function labelFor(item) {
  const ok = item.tcp_ok ? "✅" : "⛔";
  const src = item.source ? ` · ${item.source}` : "";
  const ip = item.ip && item.ip !== item.host ? ` (${item.ip})` : "";
  return `${ok} ${item.host}${ip}:${item.port}${src}`;
}

function populateSelect(items) {
  const { ipSelect, ipHint } = getEls();
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

async function loadDiscover() {
  const { ipSelect } = getEls();
  if (!ipSelect || discoverLoaded) return;
  discoverLoaded = true;

  try {
    setError("");
    ipSelect.disabled = true;
    ipSelect.innerHTML = `<option value="" disabled selected>Cargando endpoints…</option>`;

    const url = `${API_BASE}/api/opcua/discover`;
    console.log("[discover] GET", url);

    const res = await fetch(url, { cache: "no-store" });

    const ct = (res.headers.get("content-type") || "").toLowerCase();
    const raw = await res.text();

    console.log("[discover] status:", res.status, "ct:", ct, "raw:", raw.slice(0, 200));

    if (!res.ok) throw new Error(`HTTP ${res.status}: ${raw.slice(0, 200)}`);

    // FastAPI normalmente devuelve "application/json; charset=utf-8"
    // pero si por alguna razón viene distinto, igual intentamos parsear.
    let items;
    try {
      items = JSON.parse(raw);
    } catch {
      const head = raw.slice(0, 140).replace(/\s+/g, " ");
      throw new Error(`Respuesta no JSON (CT=${ct || "?"}): ${head}`);
    }

    populateSelect(Array.isArray(items) ? items : []);
  } catch (e) {
    console.error("discover error:", e);
    setError("No pude listar endpoints OPC UA: " + (e?.message ?? e));

    const { ipSelect } = getEls();
    if (ipSelect) {
      ipSelect.innerHTML = `<option value="" disabled selected>Error cargando endpoints</option>`;
    }

    // permite reintentar
    discoverLoaded = false;
  } finally {
    const { ipSelect } = getEls();
    if (ipSelect) ipSelect.disabled = false;
  }
}

function bindEvents() {
  const { btnTogglePass, passInput, loginForm, userInput, ipSelect } = getEls();

  btnTogglePass?.addEventListener("click", () => {
    if (!passInput) return;
    const isPwd = passInput.type === "password";
    passInput.type = isPwd ? "text" : "password";
    btnTogglePass.textContent = isPwd ? "Ocultar" : "Mostrar";
  });

  loginForm?.addEventListener("submit", async (e) => {
    e.preventDefault();

    const { userInput, passInput, ipSelect } = getEls();

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
}

function initLogin() {
  console.log("[login] APP_PREFIX:", APP_PREFIX, "API_BASE:", API_BASE);

  bindEvents();

  //if (STORE.getItem("auth_ok") === "1") hideLogin();
  //else showLogin();

  showLogin();

  loadDiscover();
}

// Boot (garantiza DOM listo)
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initLogin, { once: true });
} else {
  initLogin();
}

})();