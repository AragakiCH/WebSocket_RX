import sys, os, socket, time
from pathlib import Path
from PyQt6.QtCore import QProcess, QProcessEnvironment
from PyQt6.QtGui import QIcon
from PyQt6.QtWebSockets import QWebSocket
from PyQt6.QtCore import QObject, pyqtSignal, QUrl, QTimer
import json
import traceback
from .login import LoginDialog
import json, traceback, queue
from pathlib import Path
import os
from importlib.util import find_spec


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from utils.excel_logger import ExcelLogger
from PyQt6.QtWidgets import (
    QApplication, QMessageBox, QMainWindow, QLabel, QWidget, QFrame,
    QHBoxLayout, QVBoxLayout, QLineEdit, QPushButton, QComboBox,
    QDateEdit, QTableView, QSizePolicy, QFileDialog
)
from PyQt6.QtCore import Qt, QDate, QSize, QSettings  
from PyQt6.QtGui import QIcon, QStandardItemModel, QStandardItem
import tempfile, shutil
from datetime import datetime

# al inicio de tu app_desktop_threaded.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ===== Persistencia simple por máquina =====
if os.name == "nt":
    _BASE = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
else:
    _BASE = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share")))
APP_DATA_DIR = _BASE / "PSI-Dashboard"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
_CFG_PATH = APP_DATA_DIR / "config.json"

def _cfg_read() -> dict:
    try:
        with open(_CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _cfg_write(d: dict):
    try:
        with open(_CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass

# --- puertos (reemplazar lo que tienes) ---
def _port_in_use(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False

def _pick_free_port(host: str) -> int:
    # Pide un puerto al SO (aleatorio libre)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((host, 0))
    port = s.getsockname()[1]
    s.close()
    return port

def choose_persistent_ws_port(host: str = "127.0.0.1") -> int:
    # 1) si viene por env, respétalo
    env_p = os.getenv("WS_PORT")
    if env_p and env_p.isdigit():
        return int(env_p)

    # 2) si ya tenías uno guardado y está libre → úsalo
    cfg = _cfg_read()
    saved = int(cfg.get("ws_port", 0) or 0)
    if saved and not _port_in_use(host, saved):
        return saved

    # 3) pide uno aleatorio al SO y persiste
    p = _pick_free_port(host)
    cfg["ws_port"] = p
    _cfg_write(cfg)
    return p

def update_persisted_port(host: str, port: int):
    # Si el guardado está ocupado, toma otro aleatorio y persiste
    if _port_in_use(host, port):
        p = _pick_free_port(host)
        cfg = _cfg_read(); cfg["ws_port"] = p; _cfg_write(cfg)
        return p
    return port


HOST = os.getenv("WS_HOST", "127.0.0.1")
PORT = choose_persistent_ws_port(HOST)
WS_PATH = os.getenv("WS_PATH", "/ws")

#URL del OPC UA del ctrlX para validar usuarios
OPCUA_URL = os.getenv("OPCUA_URL", "")

if os.name == "nt":
    _BASE = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
else:
    _BASE = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share")))

APP_DATA_DIR = _BASE / "PSI-Dashboard"
DEFAULT_EXPORT_DIR = APP_DATA_DIR / "exports"
DEFAULT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

def is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False

def start_ws_server(project_root: Path, module_str: str, opcua_url: str, opcua_user: str, opcua_pwd: str) -> QProcess:

    global PORT
    PORT = update_persisted_port(HOST, PORT)

    proc = QProcess()
    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONUTF8", "1")
    env.insert("OPCUA_URL", opcua_url)
    env.insert("OPCUA_USER", opcua_user)
    env.insert("OPCUA_PASSWORD", opcua_pwd)
    env.insert("UVICORN_MODULE", module_str)
    env.insert("WS_HOST", HOST)
    env.insert("WS_PORT", str(PORT)) 
    proc.setProcessEnvironment(env)
    proc.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedChannels)

    if getattr(sys, "frozen", False):
        from pathlib import Path as _P
        proc.setWorkingDirectory(str(_P(sys.executable).parent))
        proc.setProgram(sys.executable)
        proc.setArguments(["--run-server"])
    else:
        proc.setWorkingDirectory(str(project_root))
        proc.setProgram(sys.executable)
        proc.setArguments(["-m", "uvicorn", module_str, "--host", HOST, "--port", str(PORT), "--log-level", "info"])

    proc.start()
    if not proc.waitForStarted(5000):
        raise RuntimeError("No se pudo iniciar uvicorn (timeout).")

    deadline = time.time() + 25.0
    wait = 0.1
    while time.time() < deadline:
        if is_port_open(HOST, PORT):
            return proc
        time.sleep(wait)
        wait = min(wait * 1.5, 1.2)

    if not is_port_open(HOST, PORT):
        try: proc.kill()
        except Exception: pass
        raise RuntimeError("Uvicorn no levantó el puerto.")

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
        try:
            self.sock.sendTextMessage('{"op":"subscribe"}')
        except Exception:
            pass

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

ALLOWED_PREFIXES = ("REAL.", "INT.", "LREAL.", "BOOL.", "UDINT.")

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
        self._settings = QSettings("WebSocketRX", "PSI-Dashboard")
        self._last_export_dir = str(DEFAULT_EXPORT_DIR.resolve())
        #self.setStyleSheet(build_styles())

        # ====== WebSocket Client ======
        ws_url = f"ws://{HOST}:{PORT}{WS_PATH}"
        self.statusBar().showMessage(f"WS → {ws_url}")
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
        btn_export.clicked.connect(self._toggle_export)

        btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_export.setCursor(Qt.CursorShape.PointingHandCursor)

        h_lay.addWidget(btn_refresh, 0)
        h_lay.addWidget(btn_export, 0)

        # --- Cards métricas ---
        cards = QWidget()
        cards_lay = QHBoxLayout(cards); cards_lay.setSpacing(12); cards_lay.setContentsMargins(0,0,0,0)
        card1 = StatCard("Muestras (hoy)", "0")
        card4 = StatCard("Última actualización", "—")
        cards_lay.addWidget(card1); cards_lay.addWidget(card4)

        # <-- agrega esto:
        self._cards = {"samples": card1, "last": card4}


        # --- Filtros ---
        filters = QWidget()
        f_lay = QHBoxLayout(filters); f_lay.setSpacing(8); f_lay.setContentsMargins(0,0,0,0)

        txt_search = QLineEdit(); txt_search.setPlaceholderText("Buscar tag / sensor…")
        txt_search.setClearButtonEnabled(True)
        txt_search.setMinimumWidth(220)


        btn_apply = QPushButton("Aplicar"); btn_apply.setObjectName("Ghost")
        btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)

        for w in (txt_search, btn_apply):
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
        self._model.setHorizontalHeaderLabels(["Timestamp", "Tag", "Valor", "Unidad", "Grupo", ""])

        table.setModel(self._model)
        # ancho del Tag y del checkbox (última columna)
        table.horizontalHeader().resizeSection(1, 160)  # Tag
        table.setColumnWidth(5, 36)                      # Checkbox



        table.setModel(self._model)
        self._selected_tags = set()
        self._model.itemChanged.connect(self._on_item_changed)

        # NUEVO: estado de exportación
        self._exporting = False
        self._export_queue = None
        self._export_logger = None
        self._export_path_tpl = None
        self._export_session_dir = None 

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
            "table": table,
        }

    # Placeholder de export (solo UI)
    def _toggle_export(self):
        if not self._exporting:
            if not self._selected_tags:
                QMessageBox.warning(
                    self, "Exportar a Excel",
                    "Por favor selecciona al menos 1 dato (checkbox en la columna Tag)."
                )
                return

            # === NO PREGUNTAMOS NADA: arrancamos YA en una carpeta temporal de sesión ===
            sess_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_tmp = Path(tempfile.gettempdir()) / "wsrx_export" / sess_id
            base_tmp.mkdir(parents=True, exist_ok=True)
            self._export_session_dir = base_tmp
            self._export_path_tpl = str(base_tmp / "rt_{date}.xlsx")

            self._export_queue = queue.Queue(maxsize=50000)
            self._drops = 0
            self._export_logger = ExcelLogger(
                q=self._export_queue,
                path_template=self._export_path_tpl,
                flush_every=50,
                flush_interval=0.2,
                sheet_name="rt",
                pretty_headers=True,
                long_format=False,
                with_table=True,
                autosize=True,
                save_checkpoint_s=2.0
            )
            self._export_logger.start()
            self._exporting = True
            self._widgets["btn_export"].setText("Detener exportación")
            self.statusBar().showMessage(
                f"Exportando → {self._export_session_dir} (temporal)."
            )
            QMessageBox.information(
                self, "Exportación iniciada",
                f"Exportando en tiempo real.\nArchivo temporal: {self._export_path_tpl}\n"
                f"Al detener, te pediré dónde guardarlo."
            )
            return

        # ====== Estabas exportando → vas a detener y elegir destino ======
        try:
            if self._export_logger:
                self._export_logger.stop()   # espera a que cierre/flush
                self._export_logger = None
            self._export_queue = None
        finally:
            self._exporting = False
            self._widgets["btn_export"].setText("Exportar a Excel")

        # Junta los .xlsx generados en la sesión
        files = sorted(Path(self._export_session_dir).glob("*.xlsx")) if self._export_session_dir else []
        if not files:
            QMessageBox.information(self, "Exportación detenida",
                                    "No se generó ningún archivo durante la sesión.")
            self._export_session_dir = None
            return

        # Si hay un solo archivo → Save As; si hay varios → elige carpeta y movemos todos
        last_dir = self._settings.value("export/dir", str(DEFAULT_EXPORT_DIR.resolve()))

        if len(files) == 1:
            default_name = files[0].name  # ej. rt_2025-09-11.xlsx
            dest_path, _ = QFileDialog.getSaveFileName(
                self,
                "Guardar Excel como…",
                str(Path(last_dir) / default_name),
                "Excel (*.xlsx)"
            )
            if not dest_path:
                # si cancela, deja el archivo en temporal y avisa dónde quedó
                QMessageBox.information(
                    self, "Exportación detenida",
                    f"Archivo quedó en temporal:\n{files[0]}"
                )
                return
            self._settings.setValue("export/dir", str(Path(dest_path).parent))
            try:
                shutil.move(str(files[0]), dest_path)
                QMessageBox.information(self, "Exportación guardada",
                                        f"Guardado en:\n{dest_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error al mover archivo",
                                    f"No se pudo guardar:\n{e}\n\nOrigen:\n{files[0]}")
        else:
            # Múltiples archivos (rotación _02, _03, o varios días)
            dest_dir = QFileDialog.getExistingDirectory(
                self, "Selecciona carpeta destino para los Excel",
                last_dir, QFileDialog.Option.ShowDirsOnly
            )
            if not dest_dir:
                QMessageBox.information(
                    self, "Exportación detenida",
                    f"Archivos quedaron en temporal:\n{self._export_session_dir}"
                )
                return
            self._settings.setValue("export/dir", dest_dir)
            moved = 0
            errors = []
            for f in files:
                try:
                    shutil.move(str(f), str(Path(dest_dir) / f.name))
                    moved += 1
                except Exception as e:
                    errors.append((f, e))
            msg = f"Movidos {moved}/{len(files)} archivos a:\n{dest_dir}"
            if errors:
                msg += "\n\nErrores:\n" + "\n".join(f"- {p}: {err}" for p, err in errors)
            QMessageBox.information(self, "Exportación guardada", msg)

        # Limpia la carpeta temporal (si quedó vacía)
        try:
            if self._export_session_dir and self._export_session_dir.exists():
                # intenta borrar la subcarpeta de sesión; ignora si no está vacía
                if not any(self._export_session_dir.iterdir()):
                    self._export_session_dir.rmdir()
        except Exception:
            pass
        finally:
            self._export_session_dir = None
        
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
        for it in row:
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            self._model.appendRow(row)
            
        self._model.appendRow(row)
        if self._model.rowCount() > self._row_cap:
            self._model.removeRow(0)

    def _upsert_row(self, ts_str: str, tag: str, val: str, unit: str, group: str):
        """
        Mantiene una sola fila por variable.
        Orden de columnas: 0=Timestamp, 1=Tag, 2=Valor, 3=Unidad, 4=Grupo, 5=Checkbox
        """
        rec = self._cells_by_tag.get(tag)
        if rec is None:
            # --- crea items ---
            it_ts   = QStandardItem(ts_str)
            it_tag  = QStandardItem(tag.split('.', 1)[-1])
            it_val  = QStandardItem(val)
            it_unit = QStandardItem(unit)
            it_grp  = QStandardItem(group.split('.', 1)[0] if '.' in group else group)

            # Guarda el tag completo en el item Tag (para exportación/lookup),
            # pero SIN hacerlo checkable.
            it_tag.setCheckable(False)
            it_tag.setData(tag, Qt.ItemDataRole.UserRole)

            for it in (it_ts, it_tag, it_val, it_unit, it_grp):
                it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

            # Checkbox SOLO en la última columna
            it_chk = QStandardItem()
            it_chk.setEditable(False)
            it_chk.setSelectable(False)
            it_chk.setCheckable(True)
            it_chk.setCheckState(Qt.CheckState.Unchecked)
            it_chk.setText("")
            it_chk.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

            # Inserta la fila
            self._model.appendRow([it_ts, it_tag, it_val, it_unit, it_grp, it_chk])

            # Guarda referencias
            self._cells_by_tag[tag] = (it_ts, it_tag, it_val, it_unit, it_grp, it_chk)
        else:
            it_ts, it_tag, it_val, it_unit, it_grp, it_chk = rec
            it_ts.setText(ts_str)
            if it_val.text() != val:
                it_val.setText(val)
            if unit and it_unit.text() != unit:
                it_unit.setText(unit)
            # opcional: si el grupo pudiera cambiar
            # new_grp = group.split('.',1)[0] if '.' in group else group
            # if it_grp.text() != new_grp:
            #     it_grp.setText(new_grp)




    def _on_snapshot(self, snap: dict):
        print("📥 snapshot:", json.dumps(snap)[:240], flush=True)
        flat = flatten_snapshot(snap)
        ts = flat.get("timestamp")
        from datetime import datetime
        ts_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if isinstance(ts,(int,float)) else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for k, v in flat.items():
            if k == "timestamp":
                continue
            if not any(k.startswith(p) for p in ALLOWED_PREFIXES):
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
        temp = flat.get("REAL.temp_C")
        if isinstance(temp,(int,float)):
            self._temp_n += 1
            self._temp_avg = ((self._temp_avg*(self._temp_n-1))+temp)/self._temp_n
            self._cards["temp"].v.setText(f"{self._temp_avg:.1f} °C")
        self._cards["last"].v.setText("ahora")
        self.statusBar().showMessage(f"WS open · último: {ts_str}")

        # ===== Exportación en tiempo real
        if self._exporting and self._export_queue is not None and self._selected_tags:
            ts_epoch = flat.get("timestamp")
            if not isinstance(ts_epoch, (int, float)):
                import time as _t
                ts_epoch = _t.time()
            sample = {"timestamp": ts_epoch}
            for tag in sorted(self._selected_tags):
                sample[tag] = flat.get(tag, None)
            try:
                self._export_queue.put_nowait(sample)
            except queue.Full:
                # no bloquees la UI; cuenta la caída
                self._drops = getattr(self, "_drops", 0) + 1

        # status rico con progreso
        rows = getattr(self._export_logger, "rows_written", 0) if self._export_logger else 0
        drops = getattr(self, "_drops", 0)
        self.statusBar().showMessage(f"WS open · último: {ts_str} · filas escritas: {rows} · drops: {drops}")

    def _on_item_changed(self, item: QStandardItem):
        # Solo reaccionar al checkbox (columna 5)
        if item.column() != 5:
            return

        row = item.row()
        it_tag = self._model.item(row, 1)  # columna Tag
        tag_full = it_tag.data(Qt.ItemDataRole.UserRole) if it_tag else None

        if not tag_full:
            # Fallback: Grupo (col 4) + nombre de Tag (col 1)
            grp_item = self._model.item(row, 4)
            grp = grp_item.text() if grp_item else ""
            tag_name = it_tag.text() if it_tag else ""
            tag_full = f"{grp}.{tag_name}" if grp else tag_name

        if item.checkState() == Qt.CheckState.Checked:
            self._selected_tags.add(tag_full)
        else:
            self._selected_tags.discard(tag_full)


    def closeEvent(self, e):
        try:
            if hasattr(self, "ws_client") and self.ws_client:
                self.ws_client.close()
            if self.server_proc and self.server_proc.state() != QProcess.ProcessState.NotRunning:
                self.server_proc.terminate()
                if not self.server_proc.waitForFinished(1500):
                    self.server_proc.kill()
            if getattr(self, "_exporting", False):
                try:
                    if self._export_logger:
                        self._export_logger.stop()
                except Exception:
                    pass

        finally:
            super().closeEvent(e)
            


# ========== fin MainWindow ==========

def _resolve_uvicorn_module() -> str:
    # si ya viene desde el env (cuando relanzamos con --run-server), respétalo
    mod = os.getenv("UVICORN_MODULE")
    if mod:
        return mod

    # empaquetado: el módulo está dentro del exe
    if getattr(sys, "frozen", False):
        return "main:app"

    # desarrollo: prueba imports reales
    if find_spec("main"):
        return "main:app"
    if find_spec("WebSocket_RX.main"):
        return "WebSocket_RX.main:app"

    raise RuntimeError("No se encontró el módulo FastAPI (main:app).")


def main(after_user: str | None = None, creds: dict | None = None):
    project_root = Path(__file__).resolve().parent.parent

    # Detecta layout y arma el import-string correcto
    module_str = _resolve_uvicorn_module()

    (project_root / "logs").mkdir(parents=True, exist_ok=True)

    # Arranca el WS
    try:
        url = creds.get("url") if creds else OPCUA_URL
        usr = creds.get("user") if creds else ""
        pwd = creds.get("pwd")  if creds else ""
        server_proc = start_ws_server(project_root, module_str, url, usr, pwd)
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

def start_gui():
    app = QApplication(sys.argv)

    # Rutas / estilos (tu mismo código actual)
    here = Path(__file__).resolve().parent
    project_root = here.parent
    qss_app   = project_root / "frontend" / "styles" / "app.qss"
    qss_login = project_root / "frontend" / "styles" / "login.qss"

    css_parts = []
    for path in (qss_app, qss_login):
        try:
            with open(path, "r", encoding="utf-8") as f:
                css_parts.append(f.read())
        except Exception as e:
            print(f"[WARN] No se pudo cargar stylesheet {path}: {e}")
    if css_parts:
        app.setStyleSheet("\n\n".join(css_parts))

    # ======= Login =======
    login = LoginDialog(opcua_url=OPCUA_URL)
    if login.exec() == LoginDialog.DialogCode.Accepted:
        user = login.last_user or "usuario"
        creds = {
            "user": getattr(login, "last_user", "") or "",
            "pwd":  getattr(login, "last_pwd",  "") or "",
            "url":  getattr(login, "good_url", OPCUA_URL) or OPCUA_URL,
        }
        win = main(after_user=user, creds=creds)
        sys.exit(app.exec())
    else:
        sys.exit(0)

if __name__ == "__main__":
    start_gui()


