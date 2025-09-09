import sys, os, socket, time
from pathlib import Path
from PyQt6.QtCore import QProcess, QProcessEnvironment
from PyQt6.QtGui import QIcon

from PyQt6.QtWidgets import (
    QApplication, QMessageBox, QMainWindow, QLabel, QWidget, QFrame,
    QHBoxLayout, QVBoxLayout, QLineEdit, QPushButton, QComboBox,
    QDateEdit, QTableView, QSizePolicy
)
from PyQt6.QtCore import Qt, QDate, QSize
from PyQt6.QtGui import QIcon, QStandardItemModel, QStandardItem

# al inicio de tu app_desktop_threaded.py
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import app as fastapi_app


HOST = os.getenv("WS_HOST", "127.0.0.1")
PORT = int(os.getenv("WS_PORT", "8000"))

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
def build_styles() -> str:
    return """
    QMainWindow {
        background: #0F172A; /* slate-900 */
    }
    QLabel, QLineEdit, QComboBox, QDateEdit, QHeaderView::section {
        color: #E2E8F0; /* slate-200 */
        font-size: 14px;
    }
    /* Sidebar */
    QFrame#Sidebar {
        background: #0B1220; /* slightly darker */
        border-right: 1px solid #1F2937;
    }
    QPushButton#Nav {
        color: #CBD5E1;
        text-align: left;
        padding: 10px 14px;
        border: none;
        border-radius: 8px;
        background: transparent;
    }
    QPushButton#Nav:hover {
        background: #111827;
        color: #FFFFFF;
    }
    QPushButton#Nav[current="true"] {
        background: #1F2937;
        color: #FFFFFF;
        font-weight: 600;
    }

    /* Top actions */
    QPushButton#Primary {
        background: #3B82F6; /* blue-500 */
        color: white;
        border: none;
        border-radius: 10px;
        padding: 10px 16px;
        font-weight: 600;
    }
    QPushButton#Primary:hover {
        background: #2563EB; /* blue-600 */
    }
    QPushButton#Ghost {
        background: transparent;
        color: #93C5FD;
        border: 1px solid #1F2937;
        border-radius: 10px;
        padding: 8px 12px;
    }
    QPushButton#Ghost:hover {
        background: #111827;
    }

    /* Cards */
    QFrame.Card {
        background: #111827;
        border: 1px solid #1F2937;
        border-radius: 16px;
    }
    QLabel.CardTitle {
        color: #94A3B8; /* slate-400 */
        font-size: 12px;
        letter-spacing: 0.5px;
    }
    QLabel.CardValue {
        color: #F8FAFC;
        font-size: 24px;
        font-weight: 700;
    }

    /* Inputs */
    QLineEdit, QComboBox, QDateEdit {
        background: #0B1220;
        border: 1px solid #1F2937;
        border-radius: 10px;
        padding: 8px 10px;
        selection-background-color: #3B82F6;
    }

    /* Tabla */
    QTableView {
        background: #0B1220;
        color: #E5E7EB;
        gridline-color: #1F2937;
        border: 1px solid #1F2937;
        border-radius: 14px;
        selection-background-color: #1D4ED8;
        selection-color: white;
        alternate-background-color: #0F172A;
    }
    QHeaderView::section {
        background: #111827;
        color: #E5E7EB;
        border: none;
        padding: 10px;
        font-weight: 600;
    }
    """

class StatCard(QFrame):
    def __init__(self, title: str, value: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setProperty("class", "Card")
        self.setFixedHeight(100)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        t = QLabel(title); t.setObjectName("CardTitle"); t.setProperty("class", "CardTitle")
        v = QLabel(value); v.setObjectName("CardValue"); v.setProperty("class", "CardValue")
        lay.addWidget(t); lay.addStretch(1); lay.addWidget(v)

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

# ========== Reemplaza tu clase MainWindow por esta ==========
class MainWindow(QMainWindow):
    def __init__(self, server_proc, project_root: Path):
        super().__init__()
        self.server_proc = server_proc
        self.project_root = project_root
        self.setWindowTitle("LEXI 1.0 — Panel de Datos")
        self.resize(1200, 800)
        self.setMinimumSize(1000, 680)
        self.setStyleSheet(build_styles())

        # --- CENTRO ---
        root = QWidget(self)
        root_lay = QHBoxLayout(root); root_lay.setContentsMargins(0,0,0,0); root_lay.setSpacing(0)
        self.setCentralWidget(root)

        # ===== Sidebar =====
        sidebar = QFrame(); sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        sb_lay = QVBoxLayout(sidebar); sb_lay.setContentsMargins(16,16,16,16); sb_lay.setSpacing(8)

        logo = QLabel("⚙️  LEXI 1.0"); logo.setStyleSheet("color:#F8FAFC;font-weight:800;font-size:18px;")
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
        card1 = StatCard("Muestras (hoy)", "12,487")
        card2 = StatCard("Alarmas activas", "3")
        card3 = StatCard("Prom. Temperatura", "38.6 °C")
        card4 = StatCard("Última actualización", "hace 2 s")
        cards_lay.addWidget(card1); cards_lay.addWidget(card2); cards_lay.addWidget(card3); cards_lay.addWidget(card4)

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
        table.setModel(make_dummy_model())
        table.horizontalHeader().setDefaultSectionSize(170)
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

    def closeEvent(self, e):
        # NO toques: apaga el server cuando cierres
        try:
            if self.server_proc and self.server_proc.state() != QProcess.ProcessState.NotRunning:
                self.server_proc.terminate()
                if not self.server_proc.waitForFinished(1500):
                    self.server_proc.kill()
        finally:
            super().closeEvent(e)
# ========== fin MainWindow ==========
def main():
    here = Path(__file__).resolve().parent
    project_root = here.parent   # tú estás en .../WEBSOCKET_RX/frontend → raíz = padre

    # Detecta layout y arma el import-string correcto
    # Caso 1: main.py en la raíz (TU CASO)
    if (project_root / "main.py").exists():
        module_str = "main:app"
    # Caso 2: si algún día lo mueves a un paquete WebSocket_RX/main.py
    elif (project_root / "WebSocket_RX" / "main.py").exists():
        module_str = "WebSocket_RX.main:app"
    else:
        QMessageBox.critical(None, "Estructura no encontrada",
                             f"No encuentro main.py en {project_root} ni WebSocket_RX/main.py")
        sys.exit(1)

    # Crea logs/ si tu backend los usa
    (project_root / "logs").mkdir(parents=True, exist_ok=True)

    # Arranca el WS
    try:
        server_proc = start_ws_server(project_root, module_str)
    except Exception as e:
        QMessageBox.critical(None, "Error WebSocket", f"No se pudo iniciar el servidor:\n{e}")
        sys.exit(1)

    # Ventana
    win = MainWindow(server_proc, project_root)
    win.resize(1000, 700)
    win.show()
    return win

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = main()
    sys.exit(app.exec())
