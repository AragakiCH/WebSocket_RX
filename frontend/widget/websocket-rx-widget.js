// frontend/widget/websocket-rx-widget.js
(() => {
  const scriptUrl = document.currentScript?.src || "";
  const widgetDir = scriptUrl ? new URL(".", scriptUrl).pathname.replace(/\/$/, "") : "/api-websocket-rx/widget";
  const APP_PREFIX = widgetDir.replace(/\/widget$/, "");
  const API_BASE = `${location.origin}${APP_PREFIX}`;
  const WS_BASE = `${location.origin.replace(/^http/, "ws")}${APP_PREFIX}`;
  const CSS_HREF = `${API_BASE}/widget/websocket-rx-widget.css`;

  class WebsocketRxWidget extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });

      this.ws = null;
      this.lastRender = 0;
      this.exporting = false;
      this.exportPoll = null;
      this.selectedTags = new Set();
      this.discoverLoaded = false;

      this.storageKey = `wsrx-widget-auth-${this.instanceId}`;
    }

    get instanceId() {
      if (!this._instanceId) {
        this._instanceId =
          this.getAttribute("instance-id") ||
          `wsrx-${Math.random().toString(36).slice(2, 10)}`;
      }
      return this._instanceId;
    }

    connectedCallback() {
      this.render();
      this.cacheEls();
      this.bindEvents();
      this.restoreSession();
      this.setExportButtonUI();
      this.pollExportStatus();

      if (this.isLogged()) {
        this.hideLogin();
      } else {
        this.showLogin();
        this.loadDiscover();
      }
    }

    disconnectedCallback() {
      if (this.ws) {
        try { this.ws.close(); } catch {}
        this.ws = null;
      }
      if (this.exportPoll) {
        clearInterval(this.exportPoll);
        this.exportPoll = null;
      }
    }

    render() {
      this.shadowRoot.innerHTML = `
        <link rel="stylesheet" href="${CSS_HREF}">
        <div class="widget-shell">
          <div id="loginOverlay" class="modal-overlay hidden">
            <div class="modal" role="dialog" aria-modal="true" aria-labelledby="loginTitle">
              <div class="modal-header">
                <h2 id="loginTitle">Iniciar sesión</h2>
                <div class="modal-sub">Panel de datos · ctrlX</div>
              </div>

              <form id="loginForm" class="modal-body">
                <div class="field">
                  <label for="userInput">Usuario</label>
                  <input
                    id="userInput"
                    type="text"
                    placeholder="Ej: admin"
                    autocomplete="username"
                    required
                  />
                </div>

                <div class="field">
                  <label for="passInput">Contraseña</label>
                  <div class="pass-row">
                    <input
                      id="passInput"
                      type="password"
                      placeholder="Ej: 1234"
                      autocomplete="current-password"
                      required
                    />
                  </div>
                </div>

                <div class="field">
                  <label for="ipSelect">Endpoint OPC UA</label>
                  <select id="ipSelect" required>
                    <option value="" disabled selected>Cargando endpoints…</option>
                  </select>
                  <small id="ipHint" class="muted"></small>
                </div>

                <div id="loginErr" class="login-error hidden"></div>

                <div class="modal-footer">
                  <button id="btnLogin" class="btn" type="submit">Ingresar</button>
                </div>
              </form>
            </div>
          </div>

          <header class="widget-header">
            <div class="title-wrap">
              <h1>ctrlX WebSocket Demo</h1>
              <div class="subline">Widget Dashboard</div>
            </div>
            <div class="header-actions">
              <button id="btnConnect" class="btn" disabled>Obtener Datos del PLC</button>
              <button id="btnDisconnect" class="btn" disabled>Desconectar</button>
            </div>
          </header>

          <main class="widget-main">
            <div class="toolbar">
              <div id="status" class="status">WebSocket desconectado.</div>

              <div class="export-actions">
                <button id="btnExport" class="btn btn-secondary" disabled>Iniciar export</button>
                <span id="exportCount" class="export-badge">0</span>
              </div>
            </div>

            <div class="table-wrap">
              <table id="data-table">
                <thead>
                  <tr>
                    <th>Tag</th>
                    <th>Valor</th>
                    <th class="col-sel">
                      <input type="checkbox" id="chkAll" title="Seleccionar todo" />
                    </th>
                  </tr>
                </thead>
                <tbody></tbody>
              </table>
            </div>
          </main>
        </div>
      `;
    }

    cacheEls() {
      const $ = (sel) => this.shadowRoot.querySelector(sel);

      this.els = {
        loginOverlay: $("#loginOverlay"),
        loginForm: $("#loginForm"),
        loginErr: $("#loginErr"),
        userInput: $("#userInput"),
        passInput: $("#passInput"),
        ipSelect: $("#ipSelect"),
        ipHint: $("#ipHint"),
        btnLogin: $("#btnLogin"),

        btnConnect: $("#btnConnect"),
        btnDisconnect: $("#btnDisconnect"),
        statusDiv: $("#status"),
        tbody: this.shadowRoot.querySelector("#data-table tbody"),
        btnExport: $("#btnExport"),
        exportCount: $("#exportCount"),
        chkAll: $("#chkAll"),
      };
    }

    bindEvents() {
      this.els.loginForm?.addEventListener("submit", (e) => this.onLoginSubmit(e));
      this.els.btnConnect?.addEventListener("click", () => this.connectWs());
      this.els.btnDisconnect?.addEventListener("click", () => this.disconnectWs());
      this.els.btnExport?.addEventListener("click", () => this.onExportClick());
      this.els.chkAll?.addEventListener("change", () => this.onToggleAll());
    }

    // =========================
    // Session
    // =========================
    saveSession(data) {
      try {
        sessionStorage.setItem(this.storageKey, JSON.stringify(data));
      } catch {}
    }

    restoreSession() {
      try {
        const raw = sessionStorage.getItem(this.storageKey);
        if (!raw) return;
        const data = JSON.parse(raw);
        if (data?.auth_ok === "1") {
          this._session = data;
        }
      } catch {}
    }

    get session() {
      return this._session || { auth_ok: "0" };
    }

    isLogged() {
      return this.session?.auth_ok === "1";
    }

    setLogged(user, opcuaUrl) {
      this._session = {
        auth_ok: "1",
        auth_user: user || "",
        opcua_url: opcuaUrl || "",
      };
      this.saveSession(this._session);
    }

    clearSession() {
      this._session = { auth_ok: "0" };
      try { sessionStorage.removeItem(this.storageKey); } catch {}
    }

    // =========================
    // UI helpers
    // =========================
    setError(msg) {
      const el = this.els.loginErr;
      if (!el) return;
      if (!msg) {
        el.classList.add("hidden");
        el.textContent = "";
        return;
      }
      el.classList.remove("hidden");
      el.textContent = msg;
    }

    showLogin() {
      this.els.loginOverlay?.classList.remove("hidden");
      this.setError("");
      this.els.userInput?.focus();
      if (this.els.btnConnect) this.els.btnConnect.disabled = true;
    }

    hideLogin() {
      this.els.loginOverlay?.classList.add("hidden");
      this.setError("");
      if (this.els.btnConnect) this.els.btnConnect.disabled = false;
      this.setExportButtonUI();
    }

    flattenObject(obj, prefix = "", out = {}) {
      if (!obj || typeof obj !== "object") return out;
      for (const [k, v] of Object.entries(obj)) {
        const key = prefix ? `${prefix}.${k}` : k;
        if (v !== null && typeof v === "object" && !Array.isArray(v)) {
          this.flattenObject(v, key, out);
        } else {
          out[key] = v;
        }
      }
      return out;
    }

    labelFor(item) {
      const ok = item.tcp_ok ? "✅" : "⛔";
      const src = item.source ? ` · ${item.source}` : "";
      const ip = item.ip && item.ip !== item.host ? ` (${item.ip})` : "";
      return `${ok} ${item.host}${ip}:${item.port}${src}`;
    }

    populateSelect(items) {
      const { ipSelect, ipHint } = this.els;
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
        opt.textContent = this.labelFor(it);
        ipSelect.appendChild(opt);
      }

      ipSelect.value = good.length > 0 ? good[0].url : "";
      if (ipHint) ipHint.textContent = `Encontrados: ${items.length} · TCP OK: ${good.length}`;
    }

    updateChkAllState(totalRows) {
      const { chkAll } = this.els;
      if (!chkAll) return;

      if (totalRows <= 0 || this.selectedTags.size === 0) {
        chkAll.checked = false;
        chkAll.indeterminate = false;
        return;
      }
      if (this.selectedTags.size === totalRows) {
        chkAll.checked = true;
        chkAll.indeterminate = false;
        return;
      }
      chkAll.checked = false;
      chkAll.indeterminate = true;
    }

    setExportButtonUI() {
      const { btnExport } = this.els;
      if (!btnExport) return;

      const logged = this.isLogged();
      const hasTags = this.selectedTags.size > 0;

      btnExport.disabled = !logged || !hasTags;
      btnExport.textContent = this.exporting ? "Detener y descargar" : "Iniciar export";
    }

    onTagSelectionChanged(totalRows) {
      if (!this.exporting) {
        this.setExportButtonUI();
        this.updateChkAllState(totalRows);
      }
    }

    updateTable(data) {
      const { tbody } = this.els;
      if (!tbody) return;

      const payload = Array.isArray(data) ? data[data.length - 1] : data;
      const flat = this.flattenObject(payload);
      const entries = Object.entries(flat);

      tbody.innerHTML = "";

      for (const [tag, value] of entries) {
        const tr = document.createElement("tr");

        const tdTag = document.createElement("td");
        tdTag.textContent = tag;

        const tdVal = document.createElement("td");
        tdVal.textContent =
          typeof value === "object" ? JSON.stringify(value) : String(value);

        const tdChk = document.createElement("td");
        tdChk.className = "col-sel";

        const chk = document.createElement("input");
        chk.type = "checkbox";
        chk.checked = this.selectedTags.has(tag);
        chk.disabled = this.exporting;

        chk.addEventListener("change", () => {
          if (chk.checked) this.selectedTags.add(tag);
          else this.selectedTags.delete(tag);
          this.onTagSelectionChanged(entries.length);
        });

        tdChk.appendChild(chk);
        tr.appendChild(tdTag);
        tr.appendChild(tdVal);
        tr.appendChild(tdChk);
        tbody.appendChild(tr);
      }

      this.onTagSelectionChanged(entries.length);
    }

    onToggleAll() {
      const { tbody, chkAll } = this.els;
      if (!tbody || !chkAll) return;

      const allChecks = tbody.querySelectorAll('input[type="checkbox"]');

      if (this.exporting) {
        chkAll.checked = !chkAll.checked;
        return;
      }

      if (chkAll.checked) {
        allChecks.forEach((c) => {
          c.checked = true;
          const row = c.closest("tr");
          const tag = row?.children?.[0]?.textContent;
          if (tag) this.selectedTags.add(tag);
        });
      } else {
        allChecks.forEach((c) => (c.checked = false));
        this.selectedTags.clear();
      }

      this.onTagSelectionChanged(allChecks.length);
    }

    // =========================
    // Discover / Login
    // =========================
    async loadDiscover() {
      const { ipSelect } = this.els;
      if (!ipSelect || this.discoverLoaded) return;
      this.discoverLoaded = true;

      try {
        this.setError("");
        ipSelect.disabled = true;
        ipSelect.innerHTML = `<option value="" disabled selected>Cargando endpoints…</option>`;

        const res = await fetch(`${API_BASE}/api/opcua/discover`, { cache: "no-store" });
        const raw = await res.text();

        if (!res.ok) throw new Error(`HTTP ${res.status}: ${raw.slice(0, 200)}`);

        let items;
        try {
          items = JSON.parse(raw);
        } catch {
          throw new Error(`Respuesta no JSON: ${raw.slice(0, 140)}`);
        }

        this.populateSelect(Array.isArray(items) ? items : []);
      } catch (e) {
        console.error("discover error:", e);
        this.setError("No pude listar endpoints OPC UA: " + (e?.message ?? e));
        if (ipSelect) {
          ipSelect.innerHTML = `<option value="" disabled selected>Error cargando endpoints</option>`;
        }
        this.discoverLoaded = false;
      } finally {
        if (ipSelect) ipSelect.disabled = false;
      }
    }

    async onLoginSubmit(e) {
      e.preventDefault();

      const u = (this.els.userInput?.value || "").trim();
      const p = this.els.passInput?.value || "";
      const selectedUrl = (this.els.ipSelect?.value || "").trim();
      const urlToSend = selectedUrl ? selectedUrl : null;

      if (!u || !p) {
        this.setError("Faltan credenciales.");
        return;
      }

      try {
        this.setError("");

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
          this.setError(msg);
          return;
        }

        this.setLogged(u, data?.url || "");
        this.hideLogin();
      } catch (err) {
        console.error("login error:", err);
        this.setError("Servidor no responde.");
      }
    }

    // =========================
    // Export
    // =========================
    async fetchExportStatus() {
      const res = await fetch(`${API_BASE}/api/export/status`, { cache: "no-store" });
      const raw = await res.text();
      if (!res.ok) throw new Error(raw.slice(0, 200));

      try {
        return JSON.parse(raw);
      } catch {
        throw new Error("Status no-JSON: " + raw.slice(0, 120));
      }
    }

    async pollExportStatus() {
      try {
        const st = await this.fetchExportStatus();
        this.exporting = !!st.active;

        if (this.els.exportCount) {
          this.els.exportCount.textContent = String(st.rows_written ?? 0);
        }

        if (this.els.tbody) {
          this.els.tbody
            .querySelectorAll('input[type="checkbox"]')
            .forEach((c) => (c.disabled = this.exporting));
        }

        if (this.els.chkAll) this.els.chkAll.disabled = this.exporting;
        this.setExportButtonUI();
        return st;
      } catch (e) {
        console.warn("pollExportStatus error:", e);
      }
    }

    async startExport() {
      if (this.selectedTags.size === 0) return;

      const tags = Array.from(this.selectedTags);

      const res = await fetch(`${API_BASE}/api/export/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tags }),
      });

      const raw = await res.text();
      if (!res.ok) throw new Error(raw.slice(0, 200));

      this.exporting = true;
      this.setExportButtonUI();

      if (this.exportPoll) clearInterval(this.exportPoll);
      this.exportPoll = setInterval(() => this.pollExportStatus(), 500);

      await this.pollExportStatus();
    }

    async stopExport() {
      const res = await fetch(`${API_BASE}/api/export/stop`, { method: "POST" });
      const raw = await res.text();
      if (!res.ok) throw new Error(raw.slice(0, 200));

      this.exporting = false;

      if (this.exportPoll) {
        clearInterval(this.exportPoll);
        this.exportPoll = null;
      }

      await this.pollExportStatus();
    }

    async downloadExportXlsx() {
      const res = await fetch(`${API_BASE}/api/export/download`, { cache: "no-store" });
      if (!res.ok) throw new Error((await res.text()).slice(0, 200));

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);

      const a = document.createElement("a");
      a.href = url;
      a.download = `rt_export_${new Date().toISOString().replaceAll(":", "-")}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();

      URL.revokeObjectURL(url);
    }

    async onExportClick() {
      try {
        const st = await this.fetchExportStatus().catch(() => null);
        if (st) this.exporting = !!st.active;

        if (!this.exporting) {
          await this.startExport();
        } else {
          await this.stopExport();
          await this.downloadExportXlsx();
        }
      } catch (e) {
        console.error(e);
        alert("Export falló: " + (e?.message ?? e));
      }
    }

    // =========================
    // WebSocket
    // =========================
    connectWs() {
      const url = `${WS_BASE}/ws`;
      console.log("Conectando WS a:", url);

      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        if (this.els.statusDiv) this.els.statusDiv.textContent = "WebSocket conectado. Recibiendo datos…";
        if (this.els.btnConnect) this.els.btnConnect.disabled = true;
        if (this.els.btnDisconnect) this.els.btnDisconnect.disabled = false;
      };

      this.ws.onmessage = (evt) => {
        let parsed;
        try {
          parsed = JSON.parse(evt.data);
        } catch {
          return;
        }

        const nowMs = performance.now();
        if (nowMs - this.lastRender > 50) {
          this.updateTable(parsed);
          this.lastRender = nowMs;
          if (this.els.statusDiv) {
            this.els.statusDiv.textContent = `Última actualización: ${new Date().toLocaleTimeString()}`;
          }
        }
      };

      this.ws.onerror = (e) => console.error("WS error:", e);

      this.ws.onclose = () => {
        if (this.els.statusDiv) this.els.statusDiv.textContent = "WebSocket desconectado.";
        if (this.els.btnConnect) this.els.btnConnect.disabled = false;
        if (this.els.btnDisconnect) this.els.btnDisconnect.disabled = true;
        this.ws = null;
      };
    }

    disconnectWs() {
      if (this.ws) this.ws.close();
      this.ws = null;
    }
  }

  if (!customElements.get("websocket-rx-widget")) {
    customElements.define("websocket-rx-widget", WebsocketRxWidget);
  }
})();