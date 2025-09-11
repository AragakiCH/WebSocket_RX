# frontend/login.py
import sys, os
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame
)

# === OPC UA check en un hilo (sin discovery) ===
class _OpcuaCheckWorker(QThread):
    result = pyqtSignal(bool, str)  # ok, message

    def __init__(self, url: str, user: str, pwd: str, parent=None):
        super().__init__(parent)
        self.url  = url            # puede ser 1 o varias URLs separadas por coma
        self.user = user
        self.pwd  = pwd

    def _probe(self, url: str):
        from opcua import Client
        c = Client(url, timeout=8.0)     # directo al endpoint, sin discovery
        c.set_user(self.user)
        c.set_password(self.pwd)
        c.connect()
        try:
            # ping mínimo para confirmar sesión válida
            c.get_root_node().get_child(["0:Objects"])
        finally:
            c.disconnect()

    def run(self):
        # Permito múltiples endpoints separados por coma, e intento en orden
        urls = [u.strip() for u in self.url.split(",") if u.strip()] or [self.url]
        last_err = "No endpoints probados"
        for url in urls:
            try:
                self._probe(url)
                self.result.emit(True, "OK")
                return
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
        self.result.emit(False, last_err)


class LoginDialog(QDialog):
    login_ok = pyqtSignal(str)  # emite el usuario válido

    def __init__(self, opcua_url: str, parent=None):
        super().__init__(parent)
        self.opcua_url = opcua_url  # ej: "opc.tcp://VirtualControl-1:4840,opc.tcp://192.168.18.6:4840"
        self._last_user = None

        self.setWindowTitle("Iniciar sesión")
        self.setModal(True)
        self.setObjectName("LoginDialog")
        self.setMinimumSize(420, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        root = QVBoxLayout(self); root.setContentsMargins(24,24,24,24); root.setSpacing(12)

        card = QFrame(self); card.setObjectName("LoginCard"); card.setProperty("class","Card"); card.setMinimumWidth(360)
        card_l = QVBoxLayout(card); card_l.setContentsMargins(24,24,24,24); card_l.setSpacing(16)

        title = QLabel("Iniciar Sesión"); title.setObjectName("LoginTitle")
        subtitle = QLabel("Panel de datos · ctrlX"); subtitle.setObjectName("LoginSubtitle")
        card_l.addWidget(title); card_l.addWidget(subtitle)

        self.txt_user = QLineEdit(); self.txt_user.setPlaceholderText("Usuario"); self.txt_user.setObjectName("LoginInput")
        self.txt_pass = QLineEdit(); self.txt_pass.setPlaceholderText("Contraseña"); self.txt_pass.setEchoMode(QLineEdit.EchoMode.Password); self.txt_pass.setObjectName("LoginInput")
        toggle = QPushButton("Mostrar"); toggle.setObjectName("Ghost"); toggle.setCheckable(True)
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        def _toggle():
            self.txt_pass.setEchoMode(QLineEdit.EchoMode.Normal if toggle.isChecked() else QLineEdit.EchoMode.Password)
            toggle.setText("Ocultar" if toggle.isChecked() else "Mostrar")
        toggle.clicked.connect(_toggle)

        pass_row = QHBoxLayout(); pass_row.addWidget(self.txt_pass, 1); pass_row.addWidget(toggle, 0)
        card_l.addWidget(self.txt_user); card_l.addLayout(pass_row)

        self.lbl_err = QLabel(""); self.lbl_err.setObjectName("LoginError"); self.lbl_err.setVisible(False)
        card_l.addWidget(self.lbl_err)

        self.btn_login = QPushButton("Ingresar"); self.btn_login.setObjectName("Primary")
        self.btn_login.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_login.clicked.connect(self._do_login)

        btn_row = QHBoxLayout(); btn_row.addStretch(1); btn_row.addWidget(self.btn_login)
        card_l.addLayout(btn_row)

        foot = QLabel("© PSI 2025"); foot.setObjectName("LoginFoot"); foot.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        root.addStretch(1); root.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter); root.addWidget(foot); root.addStretch(1)

        self.txt_user.returnPressed.connect(self._do_login)
        self.txt_pass.returnPressed.connect(self._do_login)
        self.txt_user.setFocus()

        self._worker = None

    def _set_busy(self, busy: bool):
        self.btn_login.setEnabled(not busy)
        self.txt_user.setEnabled(not busy)
        self.txt_pass.setEnabled(not busy)
        self.setCursor(Qt.CursorShape.BusyCursor if busy else Qt.CursorShape.ArrowCursor)

    def _show_error(self, msg: str):
        self.lbl_err.setText(msg)
        self.lbl_err.setVisible(True)

    def _do_login(self):
        u = self.txt_user.text().strip()
        p = self.txt_pass.text()
        if not u or not p:
            self._show_error("Completa usuario y contraseña.")
            return

        self.lbl_err.setVisible(False)
        self._set_busy(True)
        self._worker = _OpcuaCheckWorker(self.opcua_url, u, p, self)
        self._worker.result.connect(self._on_check_result)
        self._worker.start()

    def _on_check_result(self, ok: bool, message: str):
        self._set_busy(False)
        if ok:
            self._last_user = self.txt_user.text().strip()
            self.login_ok.emit(self._last_user)
            self.accept()
        else:
            self._show_error("Credenciales inválidas o sin permisos OPC UA.\n" + message)

    @property
    def last_user(self) -> str | None:
        return self._last_user
