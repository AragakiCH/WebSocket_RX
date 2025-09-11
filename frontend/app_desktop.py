import sys, os, socket, time
from pathlib import Path
from PyQt6.QtCore import QProcess, QProcessEnvironment
from PyQt6.QtGui import QIcon
from PyQt6.QtWebSockets import QWebSocket
from PyQt6.QtCore import QObject, pyqtSignal, QUrl, QTimer
import json
import traceback
from .login import LoginDialog


from PyQt6.QtWidgets import (
    QApplication, QMessageBox, QMainWindow, QLabel, QWidget, QFrame,
    QHBoxLayout, QVBoxLayout, QLineEdit, QPushButton, QComboBox,
    QDateEdit, QTableView, QSizePolicy
)
from PyQt6.QtCore import Qt, QDate, QSize
from PyQt6.QtGui import QIcon, QStandardItemModel, QStandardItem

# al inicio de tu app_desktop_threaded.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


HOST = os.getenv("WS_HOST", "127.0.0.1")
PORT = int(os.getenv("WS_PORT", "8090"))
WS_PATH = os.getenv("WS_PATH", "/ws")

#URL del OPC UA del ctrlX para validar usuarios
OPCUA_URL = os.getenv(
    "OPCUA_URL",
    "opc.tcp://VirtualControl-1:4840,opc.tcp://192.168.18.6:4840"
)

def is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False

def start_ws_server(project_root: Path, module_str: str) -> QProcess:
    proc = QProcess()
    proc.setProgram(sys.executable)
    proc.setArguments(["-m", "uvicorn", module_str, "--host", HOST, "--port", str(PORT), "--log-level", "info"])
    proc.setWorkingDirectory(str(project_root))

    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONUTF8", "1")
    proc.setProcessEnvironment(env)
    proc.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedChannels)

    proc.start()
    if not proc.waitForStarted(3000):
        raise RuntimeError("No se pudo iniciar uvicorn (timeout).")

    t0 = time.time()
    while time.time() - t0 < 6:
        if is_port_open(HOST, PORT):
            break
        time.sleep(0.1)

    if not is_port_open(HOST, PORT):
        try: proc.kill()
        except Exception: pass
        raise RuntimeError("Uvicorn no levantó el puerto. ¿8000 ocupado o import falló?")

    return proc

# ---------- helpers de UI ----------


class WSClient(QObject):
    data_received = pyqtSignal(dict)
    status_changed = pyqtSignal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.sock = QWebSocket()
        self.sock.connected.connect(self._on_connected)
        self.sock.disconnected.connect(self._on_disconnected)
        self.sock.textMessageReceived.connect(self._on_text)
        self.sock.binaryMessageReceived.connect(self._on_bin)
        self.sock.errorOccurred.connect(self._on_error)

        self._backoff_ms = 500
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self.connect)

    def connect(self):
        self.status_changed.emit(f"connecting → {self.url}")
        self.sock.open(QUrl(self.url))

    def close(self):
        self._reconnect_timer.stop()
        self.sock.close()

    def _on_connected(self):
        self.status_changed.emit("open")

    def _on_disconnected(self):
        self.status_changed.emit("closed")
        self._reconnect_timer.start(self._backoff_ms)
        self._backoff_ms = min(self._backoff_ms * 2, 5000)

    def _on_error(self, err):
        self.status_changed.emit(f"error: {self.sock.errorString()}")

    def _deliver(self, payload):
        # espera lista o dict; si lista, toma el último snapshot
        if isinstance(payload, list) and payload:
            snap = payload[-1]
        elif isinstance(payload, dict):
            snap = payload
        else:
            return
        self.data_received.emit(snap)
        self._backoff_ms = 500

    def _on_text(self, msg: str):
        try:
            self._deliver(json.loads(msg))
        except Exception:
            self.status_changed.emit(f"error: json(text)")
            traceback.print_exc()

    def _on_bin(self, data: bytes):
        try:
            self._deliver(json.loads(data.decode("utf-8", errors="ignore")))
        except Exception:
            self.status_changed.emit(f"error: json(bin)")
            traceback.print_exc()


class StatCard(QFrame):
    def __init__(self, title: str, value: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setProperty("class", "Card")
        self.setFixedHeight(100)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        self.t = QLabel(title); self.t.setObjectName("CardTitle"); self.t.setProperty("class", "CardTitle")
        self.v = QLabel(value); self.v.setObjectName("CardValue"); self.v.setProperty("class", "CardValue")
        lay.addWidget(self.t); lay.addStretch(1); lay.addWidget(self.v)

def make_dummy_model() -> QStandardItemModel:
    model = QStandardItemModel()
    model.setHorizontalHeaderLabels(["Timestamp", "Tag", "Valor", "Unidad", "Estado"])
    # datos de muestra (solo look)
    import datetime as _dt
    rows = []
    for i in range(25):
        ts = (_dt.datetime.now() - _dt.timedelta(seconds=5*i)).strftime("%Y-%m-%d %H:%M:%S")
        tag = ["vib_rms", "temp_head", "press_line", "flow_cmd"][i % 4]
        val = f"{round(10 + i*0.37, 2)}"
        unit = {"vib_rms":"mm/s", "temp_head":"°C", "press_line":"bar", "flow_cmd":"mL/min"}[tag]
        state = ["OK", "WARN", "OK", "ALARM"][i % 4]
        rows.append([ts, tag, val, unit, state])
    for r in rows:
        model.appendRow([QStandardItem(c) for c in r])
    return model


def flatten_snapshot(snap: dict) -> dict:
    out = {}
    for k, v in snap.items():
        if isinstance(v, dict):
            for sk, sv in v.items():
                out[f"{k}.{sk}"] = sv
        else:
            out[k] = v
    return out

_UNITS = {
    "REAL.vib_rms":"mm/s","REAL.vib_mean":"mm/s","REAL.vib_peak":"mm/s",
    "REAL.vib_crest":"","REAL.vib_g":"g","REAL.temp_C":"°C","REAL.pres_mA":"mA",
    "REAL.pres_lp":"bar","REAL.volt_V":"V","REAL.volt_lp":"V","REAL.volt_slope":"V/s",
}
def unit_for(tag: str) -> str:
    return _UNITS.get(tag, "")

# ========== Reemplaza tu clase MainWindow por esta ==========
class MainWindow(QMainWindow):
    def __init__(self, server_proc, project_root: Path):
        super().__init__()
        self.server_proc = server_proc
        self.project_root = project_root
        self.setWindowTitle("Dashboard")
        self.resize(1200, 800)
        self.setMinimumSize(1000, 680)
        #self.setStyleSheet(build_styles())

        # ====== WebSocket Client ======
        ws_url = f"ws://{HOST}:{PORT}{WS_PATH}"
        self.ws_client = WSClient(ws_url, self)
        self.ws_client.data_received.connect(self._on_snapshot)
        self.ws_client.status_changed.connect(self._on_ws_status)
        self.ws_client.connect()

        self._row_cap = 500
        self._samples_today = 0
        self._temp_avg = 0.0
        self._temp_n = 0

        # deja trazas claras en la barra de estado
        self.statusBar().showMessage(f"WS → {ws_url}")

        # --- CENTRO ---
        root = QWidget(self)
        root_lay = QHBoxLayout(root); root_lay.setContentsMargins(0,0,0,0); root_lay.setSpacing(0)
        self.setCentralWidget(root)

        # ===== Sidebar =====
        sidebar = QFrame(); sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        sb_lay = QVBoxLayout(sidebar); sb_lay.setContentsMargins(16,16,16,16); sb_lay.setSpacing(8)

        logo = QLabel("Dashboard"); logo.setStyleSheet("color:#F8FAFC;font-weight:800;font-size:18px;")
        sb_lay.addWidget(logo)

        def nav_btn(text, current=False):
            b = QPushButton(text); b.setObjectName("Nav")
            b.setProperty("current", "true" if current else "false")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(40)
            return b

        b_dashboard = nav_btn("Dashboard", True)
        b_data      = nav_btn("Datos")
        b_alarms    = nav_btn("Alarmas")
        b_settings  = nav_btn("Ajustes")

        for b in (b_dashboard, b_data, b_alarms, b_settings):
            sb_lay.addWidget(b)

        sb_lay.addStretch(1)
        ver = QLabel("v1.0"); ver.setStyleSheet("color:#64748B; font-size:11px;")
        sb_lay.addWidget(ver)

        # ===== Content =====
        content = QWidget()
        c_lay = QVBoxLayout(content); c_lay.setContentsMargins(18,18,18,18); c_lay.setSpacing(14)

        # --- Header ---
        header = QWidget()
        h_lay = QHBoxLayout(header); h_lay.setContentsMargins(0,0,0,0)
        title = QLabel("PSI · Panel de Datos")
        title.setStyleSheet("color:#F8FAFC; font-size:22px; font-weight:800;")
        subtitle = QLabel(f"http://{HOST}:{PORT}")
        subtitle.setStyleSheet("color:#94A3B8; font-size:12px;")
        title_box = QVBoxLayout(); title_box.setContentsMargins(0,0,0,0)
        w_title = QWidget(); w_title.setLayout(title_box)
        title_box.addWidget(title); title_box.addWidget(subtitle)

        h_lay.addWidget(w_title, 1)

        btn_refresh = QPushButton("Refrescar"); btn_refresh.setObjectName("Ghost")
        btn_export  = QPushButton("Exportar a Excel"); btn_export.setObjectName("Primary")
        btn_export.clicked.connect(self._export_placeholder)

        btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_export.setCursor(Qt.CursorShape.PointingHandCursor)

        h_lay.addWidget(btn_refresh, 0)
        h_lay.addWidget(btn_export, 0)

        # --- Cards métricas ---
        cards = QWidget()
        cards_lay = QHBoxLayout(cards); cards_lay.setSpacing(12); cards_lay.setContentsMargins(0,0,0,0)
        card1 = StatCard("Muestras (hoy)", "0")
        card2 = StatCard("Alarmas activas", "0")
        card3 = StatCard("Prom. Temperatura", "—")
        card4 = StatCard("Última actualización", "—")
        cards_lay.addWidget(card1); cards_lay.addWidget(card2); cards_lay.addWidget(card3); cards_lay.addWidget(card4)

        # <-- agrega esto:
        self._cards = {"samples": card1, "alarms": card2, "temp": card3, "last": card4}


        # --- Filtros ---
        filters = QWidget()
        f_lay = QHBoxLayout(filters); f_lay.setSpacing(8); f_lay.setContentsMargins(0,0,0,0)

        txt_search = QLineEdit(); txt_search.setPlaceholderText("Buscar tag / sensor…")
        txt_search.setClearButtonEnabled(True)
        txt_search.setMinimumWidth(220)

        cb_tipo = QComboBox()
        cb_tipo.addItems(["Todos", "Temperatura", "Presión", "Vibración", "Flujo"])

        de_from = QDateEdit(); de_from.setCalendarPopup(True); de_from.setDate(QDate.currentDate().addDays(-1))
        de_to   = QDateEdit(); de_to.setCalendarPopup(True); de_to.setDate(QDate.currentDate())

        btn_apply = QPushButton("Aplicar"); btn_apply.setObjectName("Ghost")
        btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)

        for w in (txt_search, cb_tipo, de_from, de_to, btn_apply):
            f_lay.addWidget(w)
        f_lay.addStretch(1)

        # --- Tabla ---
        table = QTableView()
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._model = QStandardItemModel()
        self._cells_by_tag = {}
        self._row_cap = 10000 
        self._model.setHorizontalHeaderLabels(["Timestamp", "Tag", "Valor", "Unidad", "Grupo"])
        table.setModel(self._model)
        table.horizontalHeader().resizeSection(2, 120)
        table.horizontalHeader().setHighlightSections(False)
        table.setMinimumHeight(400)

        # ensamblar content
        c_lay.addWidget(header)
        c_lay.addWidget(cards)
        c_lay.addWidget(filters)
        c_lay.addWidget(table, 1)

        # ensamblar root
        root_lay.addWidget(sidebar)
        root_lay.addWidget(content, 1)

        # --- Status bar ---
        self.statusBar().showMessage(f"WS listo en http://{HOST}:{PORT}")

        # (Opcional) icono de ventana
        icon_path = self.project_root / "frontend" / "app_icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # guardo referencias si luego quieres cablear señales
        self._widgets = {
            "btn_export": btn_export,
            "btn_refresh": btn_refresh,
            "txt_search": txt_search,
            "cb_tipo": cb_tipo,
            "de_from": de_from,
            "de_to": de_to,
            "table": table,
        }

    # Placeholder de export (solo UI)
    def _export_placeholder(self):
        QMessageBox.information(self, "Exportar a Excel",
                                "Esta acción exportará la tabla a Excel.\n\n"
                                "La UI ya está, el funcionamiento lo cableamos luego 😉")
        
    def _on_ws_status(self, status: str):
        self.statusBar().showMessage(f"WS {status}")

    def _append_row(self, ts_str: str, tag: str, val: str, unit: str, group: str):
        row = [
            QStandardItem(ts_str),
            QStandardItem(tag.split('.',1)[-1]),
            QStandardItem(val),
            QStandardItem(unit),
            QStandardItem(group.split('.',1)[0] if '.' in group else group),
        ]
        self._model.appendRow(row)
        if self._model.rowCount() > self._row_cap:
            self._model.removeRow(0)

    def _upsert_row(self, ts_str: str, tag: str, val: str, unit: str, group: str):
        """
        Mantiene una sola fila por variable (p.ej. REAL.vib_rms).
        Si existe, solo refresca Timestamp y Valor (y Unidad si cambiara).
        """
        rec = self._cells_by_tag.get(tag)
        if rec is None:
            it_ts   = QStandardItem(ts_str)
            it_tag  = QStandardItem(tag.split('.', 1)[-1])                 # muestra solo el subtag
            it_val  = QStandardItem(val)
            it_unit = QStandardItem(unit)
            it_grp  = QStandardItem(group.split('.', 1)[0] if '.' in group else group)

            # opcional: alinear valores a la derecha
            it_val.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self._model.appendRow([it_ts, it_tag, it_val, it_unit, it_grp])
            self._cells_by_tag[tag] = (it_ts, it_tag, it_val, it_unit, it_grp)

            # si activas ordenamiento:
            # self._widgets["table"].sortByColumn(1, Qt.SortOrder.AscendingOrder)
        else:
            it_ts, it_tag, it_val, it_unit, it_grp = rec
            it_ts.setText(ts_str)
            if it_val.text() != val:
                it_val.setText(val)
            if unit and it_unit.text() != unit:
                it_unit.setText(unit)


    def _on_snapshot(self, snap: dict):
        print("📥 snapshot:", json.dumps(snap)[:240], flush=True)
        flat = flatten_snapshot(snap)
        ts = flat.get("timestamp")
        from datetime import datetime
        ts_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if isinstance(ts,(int,float)) else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for k, v in flat.items():
            if k == "timestamp":
                continue
            if not any(k.startswith(p) for p in ("REAL.", "INT.", "LREAL.", "BOOL.")):
                continue

            if isinstance(v, float):
                val_str = f"{v:.6f}".rstrip('0').rstrip('.')
            else:
                val_str = str(v)

            self._upsert_row(ts_str, k, val_str, unit_for(k), k)

        # cards
        self._samples_today += 1
        self._cards["samples"].v.setText(f"{self._samples_today:,}".replace(",", "."))
        vib_rms = flat.get("REAL.vib_rms", 0.0)
        window_ready = flat.get("BOOL.window_ready", True)
        alarms = 1 if (not window_ready and isinstance(vib_rms,(int,float)) and vib_rms > 0.5) else 0
        self._cards["alarms"].v.setText(str(alarms))
        temp = flat.get("REAL.temp_C")
        if isinstance(temp,(int,float)):
            self._temp_n += 1
            self._temp_avg = ((self._temp_avg*(self._temp_n-1))+temp)/self._temp_n
            self._cards["temp"].v.setText(f"{self._temp_avg:.1f} °C")
        self._cards["last"].v.setText("ahora")
        self.statusBar().showMessage(f"WS open · último: {ts_str}")

    def closeEvent(self, e):
        try:
            if hasattr(self, "ws_client") and self.ws_client:
                self.ws_client.close()
            if self.server_proc and self.server_proc.state() != QProcess.ProcessState.NotRunning:
                self.server_proc.terminate()
                if not self.server_proc.waitForFinished(1500):
                    self.server_proc.kill()
        finally:
            super().closeEvent(e)
# ========== fin MainWindow ==========
def main(after_user: str | None = None):
    here = Path(__file__).resolve().parent
    project_root = here.parent

    # Detecta layout y arma el import-string correcto
    if (project_root / "main.py").exists():
        module_str = "main:app"
    elif (project_root / "WebSocket_RX" / "main.py").exists():
        module_str = "WebSocket_RX.main:app"
    else:
        QMessageBox.critical(None, "Estructura no encontrada",
                             f"No encuentro main.py en {project_root} ni WebSocket_RX/main.py")
        sys.exit(1)

    (project_root / "logs").mkdir(parents=True, exist_ok=True)

    # Arranca el WS
    try:
        server_proc = start_ws_server(project_root, module_str)
    except Exception as e:
        QMessageBox.critical(None, "Error WebSocket", f"No se pudo iniciar el servidor:\n{e}")
        sys.exit(1)

    # Ventana principal (dashboard)
    win = MainWindow(server_proc, project_root)
    if after_user:
        win.statusBar().showMessage(f"Bienvenido, {after_user} · WS listo en http://{HOST}:{PORT}")
    win.resize(1000, 700)
    win.show()
    return win

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Rutas
    here = Path(__file__).resolve().parent
    project_root = here.parent
    qss_app   = project_root / "frontend" / "styles" / "app.qss"
    qss_login = project_root / "frontend" / "styles" / "login.qss"

    # Cargar y unir estilos (primero dashboard, luego login; lo último gana)
    css_parts = []
    for path in (qss_app, qss_login):
        try:
            with open(path, "r", encoding="utf-8") as f:
                css_parts.append(f.read())
        except Exception as e:
            print(f"[WARN] No se pudo cargar stylesheet {path}: {e}")

    if css_parts:
        app.setStyleSheet("\n\n".join(css_parts))

    # ======= Primero mostrar login =======

    login = LoginDialog(opcua_url=OPCUA_URL)
    if login.exec() == LoginDialog.DialogCode.Accepted:
        user = login.last_user or "usuario"
        win = main(after_user=user)
        sys.exit(app.exec())
    else:
        sys.exit(0)


