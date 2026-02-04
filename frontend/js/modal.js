(function () {
  const overlay = document.getElementById("setupOverlay");
  const ipInput = document.getElementById("ipInput");
  const archSelect = document.getElementById("archSelect");
  const btnContinue = document.getElementById("btnContinue");

  const btnConnect = document.getElementById("btnConnect");

  // carga valores previos (si existieran)
  try {
    const saved = JSON.parse(localStorage.getItem("ctrlxConfig") || "null");
    if (saved?.ip) ipInput.value = saved.ip;
    if (saved?.arch) archSelect.value = saved.arch;
  } catch {}

  // bloquea scroll mientras el modal está activo
  // document.body.classList.add("modal-open");

  function persistConfig(cfg) {
    window.ctrlxConfig = cfg;
    try { localStorage.setItem("ctrlxConfig", JSON.stringify(cfg)); } catch {}
  }

  btnContinue.addEventListener("click", () => {
    const ip = (ipInput.value || "").trim() || "192.168.1.10";
    const arch = archSelect.value;

    persistConfig({ ip, arch });

    // cierra modal
    // cierre con animación
    overlay.classList.add("closing");
    setTimeout(() => {
      overlay.classList.add("hidden");
      overlay.classList.remove("closing");
    }, 220);

    document.body.classList.remove("modal-open");

    // habilita el botón principal (recién aquí)
    btnConnect.disabled = false;

    // status opcional
    const status = document.getElementById("status");
    status.textContent = `Listo. Config: ${ip} (${arch}). Presiona "Obtener Datos del PLC".`;
  });

  // Enter para continuar
  ipInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") btnContinue.click();
  });
})();
