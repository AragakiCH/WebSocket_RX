# frontend/login.py
import sys, os
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame
)
from opcua import Client
from plc.discovery import discover_opcua_urls, pick_first_alive
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


# === Hilo de discovery (no bloquea la UI) ===
class _DiscoveryWorker(QThread):
    # emite: lista de candidatos y la mejor URL (o "")
    done = pyqtSignal(list, str)

    def __init__(self, env_urls: str, parent=None):
        super().__init__(parent)
        self.env_urls = env_urls

    @staticmethod
    def _tcp_alive(host: str, port: int = 4840, timeout: float = 0.3) -> bool:
        import socket
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def run(self):
        import socket
        from opcua import Client

        def _parse(url: str):
            after = url.split("://", 1)[-1]
            parts = after.split(":")
            host = parts[0]; port = int(parts[1]) if len(parts) > 1 else 4840
            return host, port

        def _valid_host(h: str) -> bool:
            if h in ("0.0.0.0", "255.255.255.255"): return False
            if h.startswith(("224.", "239.")) or h.endswith(".255"): return False
            return True

        # base + lo que venga por env
        env_list  = [u.strip() for u in (self.env_urls or "").split(",") if u.strip()]
        candidates = discover_opcua_urls(extra_candidates=env_list)

        # un barrido corto por la /24 local para encontrar el CORE físico
        try:
            addrs = socket.gethostbyname_ex(socket.gethostname())[2]
            lan = next((ip for ip in addrs if ip.count(".")==3 and not ip.startswith(("127.","169.254."))), None)
            if lan:
                pref = ".".join(lan.split(".")[:3])
                # primero “típicos”, luego algunos más
                quick = [".60", ".1", ".2", ".32", ".6"]
                sweep = [f"{pref}{sfx}" for sfx in quick] + [f"{pref}.{i}" for i in range(3,255,7)]
                for h in sweep:
                    candidates.append(f"opc.tcp://{h}:4840")
        except Exception:
            pass

        # de-dup
        candidates = list(dict.fromkeys(candidates))

        meta = {}   # url -> (app_name, product_uri, is_virtual, has_meta)
        alive = []
        for url in candidates:
            host, port = _parse(url)
            if not _valid_host(host):
                continue
            if not self._tcp_alive(host, port, 0.25):
                continue
            app = prod = ""; is_virtual = False; has_meta = False
            try:
                c = Client(url, timeout=1.2)
                eps = c.connect_and_get_server_endpoints()
                if eps:
                    has_meta = True
                    app  = (eps[0].Server.ApplicationName.Text or "").lower()
                    prod = (eps[0].Server.ProductUri or "").lower()
                    is_virtual = ("virtual" in app) or ("virtual" in prod)
            except Exception:
                pass
            finally:
                try: c.disconnect()
                except Exception: pass
            meta[url] = (app, prod, is_virtual, has_meta)
            alive.append(url)

        # ranking: primero los que tienen metadatos, luego físicos, luego no-loopback
        def _rank(url: str):
            host, _ = _parse(url)
            app, prod, is_virtual, has_meta = meta.get(url, ("","",False,False))
            is_loop = host in ("127.0.0.1", "localhost")
            return (
                0 if has_meta else 1,     # preferir con meta
                1 if is_virtual else 0,   # preferir físico
                1 if is_loop else 0,      # no loopback
                host                      # estable por host
            )

        ordered = sorted(alive, key=_rank)
        best = ordered[0] if ordered else ""

        self.done.emit(ordered, best)


# === OPC UA check en un hilo (sin discovery) ===
class _OpcuaCheckWorker(QThread):
    result = pyqtSignal(bool, str, str)  # ok, message

    def __init__(self, url: str, user: str, pwd: str, parent=None):
        super().__init__(parent)
        self.url  = url            # puede ser 1 o varias URLs separadas por coma
        self.user = user
        self.pwd  = pwd

    @staticmethod
    def _ensure_cert_pair(cert_path: str, key_path: str):
        if os.path.exists(cert_path) and os.path.exists(key_path):
            return
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime
        Path(os.path.dirname(cert_path)).mkdir(parents=True, exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"PE"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"PSI"),
            x509.NameAttribute(NameOID.COMMON_NAME, u"PSI-Dashboard"),
        ])
        cert = (x509.CertificateBuilder()
                .subject_name(subject).issuer_name(subject)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.utcnow() - datetime.timedelta(days=1))
                .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
                .sign(key, hashes.SHA256()))
        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption()))
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

    def _probe(self, url: str):
        from opcua import Client
        # RUTA ABSOLUTA estable para no regenerar cada vez
        if os.name == "nt":
            base = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "PSI-Dashboard" / "opcua"
        else:
            base = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "psi-dashboard" / "opcua"
        cert_path = str(base / "client_cert.pem")
        key_path  = str(base / "client_key.pem")

        self._ensure_cert_pair(cert_path, key_path)

        attempts = [
            ("Basic256Sha256", "SignAndEncrypt"),
            ("Basic256Sha256", "Sign"),
            ("Basic256",       "SignAndEncrypt"),
            ("None",           "None"),  # solo diagnóstico
        ]

        last_err = None
        for pol, mode in attempts:
            try:
                c = Client(url, timeout=8.0)
                c.application_name = "PSI Dashboard"
                c.application_uri  = "urn:psi:dashboard"   # estable
                if pol != "None":
                    c.set_security_string(f"{pol},{mode},{cert_path},{key_path}")
                if self.user:
                    c.set_user(self.user); c.set_password(self.pwd)
                c.connect()
                try:
                    c.get_root_node().get_child(["0:Objects"])
                finally:
                    c.disconnect()
                return
            except Exception as e:
                last_err = e
                print(f"[OPC UA] intento {pol}/{mode} -> {type(e).__name__}: {e}", flush=True)

        raise last_err or RuntimeError("No se pudo establecer sesión segura")

    def run(self):
        urls = [u.strip() for u in (self.url or "").split(",") if u.strip()]
        if not urls:
            self.result.emit(False, "Sin candidatos OPC UA", "")
            return
        last_err = "No endpoints probados"
        for url in urls:
            try:
                self._probe(url)
                self.result.emit(True, "OK", url)
                return
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
        self.result.emit(False, last_err, "")


class LoginDialog(QDialog):
    login_ok = pyqtSignal(str)  # emite el usuario válido

    def __init__(self, opcua_url: str, parent=None):
        super().__init__(parent)
        self.opcua_url = opcua_url  # ej: "opc.tcp://VirtualControl-1:4840,opc.tcp://192.168.18.6:4840"
        self._last_user = None
        self._last_pwd  = None
        self._good_url  = None

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
        self.lbl_detect = QLabel("Detectando PLC…")
        self.lbl_detect.setObjectName("DetectInfo")
        self.lbl_detect.setStyleSheet("color:#64748B; font-size:12px;")
        card_l.addWidget(self.lbl_detect)
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

                # ⬇️ arranca discovery INMEDIATO
        self._start_discovery()

    # --------- DISCOVERY ----------
    def _start_discovery(self):
        self._disc_worker = _DiscoveryWorker(self.opcua_url, self)
        self._disc_worker.done.connect(self._on_discovery_done)
        self._disc_worker.start()

    def _on_discovery_done(self, candidates: list, best_url: str):
        self._candidates = candidates or []
        if best_url:
            self._good_url = best_url
            urls = [best_url] + [u for u in self._candidates if u != best_url]
            self.opcua_url = ",".join(urls)

            # --- obtener nombre del servidor y si es virtual
            label = "ctrlX CORE"
            try:
                c = Client(best_url, timeout=1.2)
                eps = c.connect_and_get_server_endpoints()
                if eps:
                    app = (eps[0].Server.ApplicationName.Text or "")
                    prod = (eps[0].Server.ProductUri or "")
                    is_virtual = ("virtual" in app.lower()) or ("virtual" in prod.lower())
                    label = "ctrlX COREvirtual" if is_virtual else "ctrlX CORE"
            except Exception:
                # si no hay meta y es loopback, lo tratamos como virtual
                host = best_url.split("://",1)[-1].split(":")[0]
                if host in ("127.0.0.1", "localhost"):
                    label = "ctrlX COREvirtual"
            finally:
                try: c.disconnect()
                except Exception: pass

            self.lbl_detect.setText(f"Detectado: {best_url} ({label})")
        else:
            msg = "Sin PLC detectado automáticamente."
            if self._candidates:
                msg += f" ({len(self._candidates)} candidatos)"
                print("[DISCOVERY] candidates:", self._candidates, flush=True)
            self.lbl_detect.setText(msg)

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
        # usa la lista reordenada por discovery (si ya terminó); si no, usa lo que haya
        urls = self.opcua_url or ""
        self._worker = _OpcuaCheckWorker(urls, u, p, self)
        self._worker.result.connect(self._on_check_result)
        self._worker.start()

    def _on_check_result(self, ok: bool, message: str, good_url: str):
        self._set_busy(False)
        if ok:
            self._last_user = self.txt_user.text().strip()
            self._last_pwd  = self.txt_pass.text()
            self._good_url  = good_url or self.opcua_url  # fallback
            self.login_ok.emit(self._last_user)
            self.accept()
        else:
            self._show_error("Credenciales inválidas o sin permisos OPC UA.\n" + message)

    @property
    def last_user(self) -> str | None:
        return self._last_user

    @property
    def last_pwd(self) -> str | None:
        return self._last_pwd

    @property
    def good_url(self) -> str | None:
        return self._good_url
