// js/ws-shared.js
// WebSocket compartido entre Dashboard y Trends
// - Un solo WS que persiste entre cambios de vista
// - Eventos para suscribirse a los datos

(() => {
  const parts = location.pathname.split("/").filter(Boolean);
  const APP_PREFIX = parts.length ? `/${parts[0]}` : "";
  const WS_BASE = `${location.origin.replace(/^http/, "ws")}${APP_PREFIX}`;

  // Estado del WebSocket
  let ws = null;
  let isConnected = false;
  let lastData = null;

  // Suscriptores (callbacks que reciben los datos)
  const subscribers = new Set();

  // ============================
  // API pública
  // ============================
  window.SharedWS = {
    // Estado
    get isConnected() {
      return isConnected;
    },

    get lastData() {
      return lastData;
    },

    // Conectar (idempotente: si ya está conectado, no hace nada)
    connect() {
      if (ws && isConnected) {
        console.log("[SharedWS] Ya conectado, reutilizando");
        return;
      }

      if (ws && ws.readyState === WebSocket.CONNECTING) {
        console.log("[SharedWS] Conexión en progreso...");
        return;
      }

      const url = `${WS_BASE}/ws`;
      console.log("[SharedWS] Conectando a:", url);

      ws = new WebSocket(url);

      ws.onopen = () => {
        console.log("[SharedWS] ✅ Conectado");
        isConnected = true;
        notifyAll("open");
      };

      ws.onmessage = (evt) => {
        let parsed;
        try {
          parsed = JSON.parse(evt.data);
        } catch {
          return;
        }

        lastData = parsed;
        notifyAll("message", parsed);
      };

      ws.onerror = (err) => {
        console.error("[SharedWS] ❌ Error:", err);
        notifyAll("error", err);
      };

      ws.onclose = () => {
        console.log("[SharedWS] 🔌 Desconectado");
        isConnected = false;
        ws = null;
        notifyAll("close");
      };
    },

    // Desconectar
    disconnect() {
      if (ws) {
        console.log("[SharedWS] Cerrando conexión...");
        ws.close();
        ws = null;
      }
      isConnected = false;
    },

    // Suscribirse a eventos: "open", "message", "close", "error"
    subscribe(callback) {
      subscribers.add(callback);

      // Si ya está conectado, notifica inmediatamente
      if (isConnected) {
        callback({ type: "open" });
        if (lastData) {
          callback({ type: "message", data: lastData });
        }
      }

      // Retorna función para desuscribirse
      return () => subscribers.delete(callback);
    },
  };

  // Notifica a todos los suscriptores
  function notifyAll(type, data) {
    const event = { type, data };
    subscribers.forEach((cb) => {
      try {
        cb(event);
      } catch (e) {
        console.error("[SharedWS] Error en suscriptor:", e);
      }
    });
  }

  // Auto-conectar si ya había sesión activa
  if (sessionStorage.getItem("auth_ok") === "1") {
    // Pequeño delay para que las vistas se monten primero
    setTimeout(() => {
      const wasConnected = sessionStorage.getItem("ws_was_connected") === "1";
      if (wasConnected) {
        console.log("[SharedWS] Auto-reconectando...");
        window.SharedWS.connect();
      }
    }, 100);
  }

  // Guardar estado al cerrar página
  window.addEventListener("beforeunload", () => {
    if (isConnected) {
      sessionStorage.setItem("ws_was_connected", "1");
    } else {
      sessionStorage.removeItem("ws_was_connected");
    }
  });
})();