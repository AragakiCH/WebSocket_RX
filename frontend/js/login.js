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
loginForm?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const u = (userInput?.value || "").trim();
  const p = passInput?.value || "";

  try {
    const r = await fetch("/api/opcua/login", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ user: u, password: p })
    });

    if (!r.ok) {
      const msg = await r.text();
      loginErr.textContent = msg || "No pude autenticar OPC UA.";
      loginErr.hidden = false;
      return;
    }

    // listo: backend ya tiene las credenciales en RAM
    STORE.setItem("auth_ok","1"); // solo para UI
    hideLogin();
  } catch {
    loginErr.textContent = "Servidor no responde.";
    loginErr.hidden = false;
  }
});


document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('loginForm');
    const ipSelect = document.getElementById('ipSelect');

    loginForm.addEventListener('submit', (e) => {
        e.preventDefault();
        
        // Obtenemos los valores
        const user = document.getElementById('userInput').value;
        const pass = document.getElementById('passInput').value;
        const selectedIp = ipSelect.value;

        if (!selectedIp) {
            alert("Causa, selecciona una IP pe'");
            return;
        }

        console.log("Intentando conectar a:", selectedIp);
        
        // Aquí seguiría tu lógica de login...
        // loginAuth(user, pass, selectedIp);
    });
});