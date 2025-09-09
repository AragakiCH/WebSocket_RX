import sys
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QWidget
)
from PyQt6.QtGui import QIcon

VALID_USER = "rexroth"
VALID_PASS = "rexroth"

class LoginDialog(QDialog):
    login_ok = pyqtSignal(str)  # emite el usuario válido

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LEXI 1.0 — Iniciar sesión")
        self.setModal(True)
        self.setObjectName("LoginDialog")
        self.setMinimumSize(420, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        # ---- Layout raíz (centro con tarjeta) ----
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        card = QFrame(self)
        card.setObjectName("LoginCard")
        card.setProperty("class", "Card")
        card.setMinimumWidth(360)
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(24, 24, 24, 24)
        card_l.setSpacing(16)

        # Branding
        title = QLabel("⚙️  LEXI 1.0")
        title.setObjectName("LoginTitle")
        subtitle = QLabel("Panel de datos · ctrlX")
        subtitle.setObjectName("LoginSubtitle")

        card_l.addWidget(title)
        card_l.addWidget(subtitle)

        # Inputs
        self.txt_user = QLineEdit()
        self.txt_user.setPlaceholderText("Usuario")
        self.txt_user.setObjectName("LoginInput")

        self.txt_pass = QLineEdit()
        self.txt_pass.setPlaceholderText("Contraseña")
        self.txt_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_pass.setObjectName("LoginInput")

        # Toggle ver/ocultar
        toggle = QPushButton("👁 Mostrar")
        toggle.setObjectName("Ghost")
        toggle.setCheckable(True)
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        def _toggle():
            self.txt_pass.setEchoMode(
                QLineEdit.EchoMode.Normal if toggle.isChecked() else QLineEdit.EchoMode.Password
            )
            toggle.setText("🙈 Ocultar" if toggle.isChecked() else "👁 Mostrar")
        toggle.clicked.connect(_toggle)

        pass_row = QHBoxLayout()
        pass_row.addWidget(self.txt_pass, 1)
        pass_row.addWidget(toggle, 0)

        card_l.addWidget(self.txt_user)
        card_l.addLayout(pass_row)

        # Error label
        self.lbl_err = QLabel("")
        self.lbl_err.setObjectName("LoginError")
        self.lbl_err.setVisible(False)
        card_l.addWidget(self.lbl_err)

        # Botones
        btn_login = QPushButton("Ingresar")
        btn_login.setObjectName("Primary")
        btn_login.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_login.clicked.connect(self._do_login)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(btn_login)
        card_l.addLayout(btn_row)

        # Footer mini
        foot = QLabel("© PSI · Mechatronics")
        foot.setObjectName("LoginFoot")
        foot.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # Centering
        root.addStretch(1)
        root.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(foot)
        root.addStretch(1)

        # UX: enter = login
        self.txt_user.returnPressed.connect(self._do_login)
        self.txt_pass.returnPressed.connect(self._do_login)

        # Auto-focus
        self.txt_user.setFocus()

    def _show_error(self, msg: str):
        self.lbl_err.setText(msg)
        self.lbl_err.setVisible(True)

    def _do_login(self):
        u = self.txt_user.text().strip()
        p = self.txt_pass.text()
        if u == VALID_USER and p == VALID_PASS:
            self.lbl_err.setVisible(False)
            self.login_ok.emit(u)
            self.accept()
        else:
            self._show_error("Credenciales inválidas. Intenta de nuevo.")
