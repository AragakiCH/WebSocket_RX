// js/login.js
// Login + OPC UA discover (endpoints) + discover programs + login final
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
      loginForm: document.getElementById("loginForm"),
      loginErr: document.getElementById("loginErr"),
      userInput: document.getElementById("userInput"),
      passInput: document.getElementById("passInput"),
      ipSelect: document.getElementById("ipSelect"),
      ipHint: document.getElementById("ipHint"),
      programSelect: document.getElementById("programSelect"),
      programHint: document.getElementById("programHint"),
      btnDiscoverPrograms: document.getElementById("btnDiscoverPrograms"),
      btnLogin: document.getElementById("btnLogin"),
    };
  }

  function setError(msg) {
    const { loginErr } = getEls();
    if (!loginErr) return;
    loginErr.hidden = !msg;
    loginErr.textContent = msg || "";
  }

  function setProgramHint(msg, isError = false) {
    const { programHint } = getEls();
    if (!programHint) return;
    programHint.textContent = msg || "";
    programHint.style.color = isError
      ? "rgba(239, 68, 68, 0.9)"
      : "rgba(234, 240, 255, 0.55)";
  }

  function hideLogin() {
    window.location.replace(`${APP_PREFIX}/dashboard`);
  }

  // =========================================================
  // Discover endpoints OPC UA (lo que ya tenías)
  // =========================================================
  function labelFor(item) {
    const ok = item.tcp_ok ? "✅" : "⛔";
    const src = item.source ? ` · ${item.source}` : "";
    const ip = item.ip && item.ip !== item.host ? ` (${item.ip})` : "";
    return `${ok} ${item.host}${ip}:${item.port}${src}`;
  }

  function populateEndpoints(items) {
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

    if (ipHint)
      ipHint.textContent = `Encontrados: ${items.length} · TCP OK: ${good.length}`;
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
      const res = await fetch(url, { cache: "no-store" });
      const raw = await res.text();

      if (!res.ok) throw new Error(`HTTP ${res.status}: ${raw.slice(0, 200)}`);

      let items;
      try {
        items = JSON.parse(raw);
      } catch {
        throw new Error(`Respuesta no JSON: ${raw.slice(0, 140)}`);
      }

      populateEndpoints(Array.isArray(items) ? items : []);
    } catch (e) {
      console.error("discover error:", e);
      setError("No pude listar endpoints OPC UA: " + (e?.message ?? e));
      const { ipSelect } = getEls();
      if (ipSelect) {
        ipSelect.innerHTML = `<option value="" disabled selected>Error cargando endpoints</option>`;
      }
      discoverLoaded = false;
    } finally {
      const { ipSelect } = getEls();
      if (ipSelect) ipSelect.disabled = false;
    }
  }

  // =========================================================
  // 🔍 Discover programs (botón lupa)
  // =========================================================
  function populatePrograms(programs) {
    const { programSelect } = getEls();
    if (!programSelect) return;

    programSelect.innerHTML = "";

    if (!programs || programs.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.disabled = true;
      opt.selected = true;
      opt.textContent = "Sin programas disponibles";
      programSelect.appendChild(opt);
      return;
    }

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.disabled = true;
    placeholder.textContent = "Selecciona un programa…";
    programSelect.appendChild(placeholder);

    for (const prog of programs) {
      const opt = document.createElement("option");
      opt.value = prog;
      opt.textContent = prog;
      programSelect.appendChild(opt);
    }

    // Si solo hay uno, lo selecciona automáticamente
    if (programs.length === 1) {
      programSelect.value = programs[0];
    }
  }

  async function discoverPrograms() {
    const {
      userInput,
      passInput,
      ipSelect,
      btnDiscoverPrograms,
      programSelect,
    } = getEls();

    const u = (userInput?.value || "").trim();
    const p = passInput?.value || "";
    const url = (ipSelect?.value || "").trim();

    if (!u || !p) {
      setError("Primero ingresa usuario y contraseña.");
      return;
    }
    if (!url) {
      setError("Selecciona un endpoint OPC UA primero.");
      return;
    }

    setError("");
    setProgramHint("Buscando programas en el PLC…");

    if (btnDiscoverPrograms) btnDiscoverPrograms.disabled = true;
    if (programSelect) {
      programSelect.disabled = true;
      programSelect.innerHTML = `<option value="" disabled selected>Buscando…</option>`;
    }
    // 👇 AGREGA SOLO ESTAS 2 LÍNEAS
    console.log("🔍 Endpoint:", `${API_BASE}/api/opcua/discover-programs`);
    console.log("🔍 Body:", { user: u, password: p, url });

    try {
      const r = await fetch(`${API_BASE}/api/opcua/discover-programs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user: u, password: p, url }),
      });

      const raw = await r.text();
      let data = null;
      try {
        data = JSON.parse(raw);
      } catch {}

      if (!r.ok) {
        const msg =
          data?.detail?.error ||
          (data?.detail ? JSON.stringify(data.detail) : raw.slice(0, 200)) ||
          "No pude listar programas.";
        throw new Error(msg);
      }

      const programs = Array.isArray(data?.programs) ? data.programs : [];
      populatePrograms(programs);
      setProgramHint(`Encontrados: ${programs.length} programa(s)`);
    } catch (err) {
      console.error("discover-programs error:", err);
      setError("Error listando programas: " + (err?.message ?? err));
      setProgramHint("Falló la búsqueda. Revisa credenciales/URL.", true);
      if (programSelect) {
        programSelect.innerHTML = `<option value="" disabled selected>Error al buscar</option>`;
      }
    } finally {
      if (btnDiscoverPrograms) btnDiscoverPrograms.disabled = false;
      if (programSelect) programSelect.disabled = false;
    }
  }

  // =========================================================
  // Eventos + submit final
  // =========================================================
  function bindEvents() {
    const { loginForm, btnDiscoverPrograms } = getEls();

    btnDiscoverPrograms?.addEventListener("click", discoverPrograms);

    loginForm?.addEventListener("submit", async (e) => {
      e.preventDefault();

      const { userInput, passInput, ipSelect, programSelect } = getEls();

      const u = (userInput?.value || "").trim();
      const p = passInput?.value || "";
      const selectedUrl = (ipSelect?.value || "").trim();
      const program = (programSelect?.value || "").trim();
      const urlToSend = selectedUrl || null;

      if (!u || !p) return setError("Faltan credenciales.");
      if (!program)
        return setError("Selecciona un programa (pulsa 🔍 para listarlos).");

      try {
        setError("");

        const r = await fetch(`${API_BASE}/api/opcua/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user: u,
            password: p,
            url: urlToSend,
            program, // 👈 ahora también se manda
          }),
        });

        const raw = await r.text();
        let data = null;
        try {
          data = JSON.parse(raw);
        } catch {}

        if (!r.ok) {
          const msg = data?.detail?.error
            ? `${data.detail.error}\n\nTried:\n${(data.detail.tried || []).slice(0, 10).join("\n")}`
            : data?.detail
              ? JSON.stringify(data.detail)
              : raw.slice(0, 200) || "No pude autenticar OPC UA.";
          return setError(msg);
        }

        STORE.setItem("auth_ok", "1");
        STORE.setItem("auth_user", u);
        if (data?.url) STORE.setItem("opcua_url", data.url);
        STORE.setItem("opcua_program", program);

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

    if (STORE.getItem("auth_ok") === "1") {
      window.location.replace(`${APP_PREFIX}/dashboard`);
      return;
    }

    const { userInput } = getEls();
    userInput?.focus();

    loadDiscover();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLogin, { once: true });
  } else {
    initLogin();
  }
})();
