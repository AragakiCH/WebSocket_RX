// js/login.js
// Login modal + opcua discover dropdown + login POST (/api/opcua/login)
// Requiere en el HTML:
//  - #loginOverlay, #loginForm, #loginErr, #userInput, #passInput, #ipSelect
//  - (opcional) #btnTogglePass, #ipHint

// elementos del login overlay
const loginOverlay = document.getElementById("loginOverlay");
const loginForm = document.getElementById("loginForm");
const loginErr = document.getElementById("loginErr");
const userInput = document.getElementById("userInput");
const passInput = document.getElementById("passInput");
const ipSelect = document.getElementById("ipSelect");
const ipHint = document.getElementById("ipHint");
const btnTogglePass = document.getElementById("btnTogglePass");

const STORE = sessionStorage;

// 🔥 Si quieres que SIEMPRE pida login incluso al recargar, deja esto:
// (si quieres "recordar" sesión en la pestaña, comenta estas 2 líneas)
STORE.removeItem("auth_ok");
STORE.removeItem("auth_user");
STORE.removeItem("opcua_url");

function setError(msg) {
  if (!loginErr) return;
  loginErr.hidden = !msg;
  loginErr.textContent = msg || "";
}

// helper: ocultar/mostrar overlay
function showLogin() {
  loginOverlay?.classList.remove("hidden");
  setError("");
  userInput?.focus();
}

function hideLogin() {
  loginOverlay?.classList.add("hidden");
  setError("");

  // avisa a la app que ya estás logueado (para habilitar botones)
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

  // Opción AUTO (si no elige nada, backend intenta el primero que autentica)
  const optAuto = document.createElement("option");
  optAuto.value = "";
  optAuto.textContent = "Automático (recomendado)";
  ipSelect.appendChild(optAuto);

  const good = items.filter((x) => !!x.tcp_ok);
  const bad = items.filter((x) => !x.tcp_ok);

  // primero tcp_ok=true
  for (const it of [...good, ...bad]) {
    const opt = document.createElement("option");
    opt.value = it.url; // 👈 URL completa: "opc.tcp://x:4840"
    opt.textContent = labelFor(it);
    ipSelect.appendChild(opt);
  }

  // default: si hay tcp_ok=true, selecciona el primero; si no, deja "auto"
  if (good.length > 0) ipSelect.value = good[0].url;
  else ipSelect.value = "";

  if (ipHint) {
    ipHint.textContent = `Encontrados: ${items.length} · TCP OK: ${good.length}`;
  }
}

async function loadDiscover() {
  if (!ipSelect) return;

  try {
    setError("");

    ipSelect.disabled = true;
    ipSelect.innerHTML = `<option value="" disabled selected>Cargando endpoints…</option>`;

    const res = await fetch("/api/opcua/discover", { cache: "no-store" });
    if (!res.ok) throw new Error(await res.text());

    const items = await res.json();
    populateSelect(Array.isArray(items) ? items : []);
  } catch (e) {
    console.error("discover error:", e);
    setError("No pude listar endpoints OPC UA: " + (e?.message ?? e));
    ipSelect.innerHTML = `<option value="" disabled selected>Error cargando endpoints</option>`;
  } finally {
    ipSelect.disabled = false;
  }
}

// Si ya estaba logueado en esta pestaña, no muestres modal
if (STORE.getItem("auth_ok") === "1") {
  hideLogin();
} else {
  showLogin();
}

// Carga discover al iniciar (cuando el DOM ya existe)
document.addEventListener("DOMContentLoaded", () => {
  loadDiscover();
});

// submit login
loginForm?.addEventListener("submit", async (e) => {
  e.preventDefault();

  const u = (userInput?.value || "").trim();
  const p = passInput?.value || "";

  // puede ser "" (auto) o una URL opc.tcp://...
  const selectedUrl = (ipSelect?.value || "").trim();
  const urlToSend = selectedUrl ? selectedUrl : null;

  if (!u || !p) {
    setError("Faltan credenciales.");
    return;
  }

  try {
    setError("");

    const r = await fetch("/api/opcua/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // 👇 ahora mandamos url si el usuario eligió una
      body: JSON.stringify({ user: u, password: p, url: urlToSend }),
    });

    // intenta leer JSON, si falla cae a texto
    let data = null;
    try {
      data = await r.json();
    } catch {
      data = null;
    }

    if (!r.ok) {
      const msg =
        data?.detail?.error
          ? `${data.detail.error}\n\nTried:\n${(data.detail.tried || []).slice(0, 10).join("\n")}`
          : (data?.detail ? JSON.stringify(data.detail) : "No pude autenticar OPC UA.");

      setError(msg);
      return;
    }

    // OK: backend ya guardó user/pass/url en RAM
    STORE.setItem("auth_ok", "1");
    STORE.setItem("auth_user", u);
    if (data?.url) STORE.setItem("opcua_url", data.url);

    hideLogin();
  } catch (err) {
    console.error("login error:", err);
    setError("Servidor no responde.");
  }
});
