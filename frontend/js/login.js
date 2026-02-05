// js/login.js
const HARD_USER = "admin";
const HARD_PASS = "1234";

// elementos del login overlay
const loginOverlay = document.getElementById("loginOverlay");
const loginForm = document.getElementById("loginForm");
const loginErr = document.getElementById("loginErr");
const userInput = document.getElementById("userInput");
const passInput = document.getElementById("passInput");
const btnTogglePass = document.getElementById("btnTogglePass");

// helper: ocultar/mostrar overlay
function showLogin() {
  loginOverlay?.classList.remove("hidden");
  if (loginErr) loginErr.hidden = true;
  userInput?.focus();
}

function hideLogin() {
  loginOverlay?.classList.add("hidden");
  if (loginErr) loginErr.hidden = true;

  // avisa a la app que ya estás logueado (para habilitar botones)
  window.dispatchEvent(new Event("auth:ok"));
}

// toggle pass
btnTogglePass?.addEventListener("click", () => {
  if (!passInput) return;
  const isPwd = passInput.type === "password";
  passInput.type = isPwd ? "text" : "password";
  btnTogglePass.textContent = isPwd ? "Ocultar" : "Mostrar";
});

const STORE = sessionStorage;

// 🔥 Si quieres que SIEMPRE pida login incluso al recargar, descomenta:
STORE.removeItem("auth_ok");
STORE.removeItem("auth_user");

// si ya estaba logueado en esta pestaña, no muestres modal
if (STORE.getItem("auth_ok") === "1") {
  hideLogin();
} else {
  showLogin();
}

// submit login
loginForm?.addEventListener("submit", (e) => {
  e.preventDefault();

  const u = (userInput?.value || "").trim();
  const p = passInput?.value || "";

  if (u === HARD_USER && p === HARD_PASS) {
    STORE.setItem("auth_ok", "1");
    STORE.setItem("auth_user", u);
    hideLogin();
    return;
  }

  if (loginErr) {
    loginErr.textContent = "Usuario o contraseña incorrectos.";
    loginErr.hidden = false;
  }
});
