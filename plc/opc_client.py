from opcua import Client, ua
import threading
import time
import os

class PLCReader:
    def __init__(self, url, user, password, buffer, buffer_size=100, on_sample=None):
        self.url, self.user, self.password = url, user, password
        self.buffer = buffer
        self.buffer_size = buffer_size
        self.on_sample = on_sample

        self._stop = False
        self._thr = None
        self._cli = None

        # Certs opcionales (solo si el endpoint exige seguridad y además requiere certificado de cliente)
        self.client_cert = os.getenv("OPCUA_CLIENT_CERT", "")  # ej: "certs/client_cert.der"
        self.client_key  = os.getenv("OPCUA_CLIENT_KEY", "")   # ej: "certs/client_key.pem"

        # timeouts
        self.timeout_connect = float(os.getenv("OPCUA_TIMEOUT_CONNECT", "5.0"))
        self.timeout_read    = float(os.getenv("OPCUA_TIMEOUT_READ", "3.0"))

    def stop(self):
        self._stop = True

    @staticmethod
    def _opc_host_port(url: str) -> tuple[str, str]:
        x = url.split("://", 1)[-1]
        hostport = x.split("/", 1)[0]
        if ":" in hostport:
            h, p = hostport.split(":", 1)
        else:
            h, p = hostport, "4840"
        return h, p

    @staticmethod
    def _replace_host(endpoint_url: str, new_host: str) -> str:
        old_host, _ = PLCReader._opc_host_port(endpoint_url)
        return endpoint_url.replace(old_host, new_host, 1)

    def read_value(self, node):
        try:
            val_node = node.get_child(["2:Value"])
            return val_node.get_value()
        except Exception:
            return node.get_value()

    def browse_by_names(self, root, *names):
        cur = root
        for n in names:
            found = None
            for ch in cur.get_children():
                if ch.get_browse_name().Name == n:
                    found = ch
                    break
            if not found:
                print("Por favor publique un proyecto desde la configuración de símbolos")
                return None
            cur = found
        return cur

    # -----------------------------
    # Helpers: elegir endpoint y armar security string
    # -----------------------------
    def _tokens_of(self, ep):
        return {t.TokenType.name for t in (ep.UserIdentityTokens or [])}

    def _score_ep(self, ep):
        tokens = self._tokens_of(ep)

        # si quiero UserName y no lo ofrece: descartado
        if self.user and "UserName" not in tokens:
            return -10_000

        # prioriza SecurityMode: None(0) < Sign(1) < SignAndEncrypt(2)
        mode = int(ep.SecurityMode)

        sp = (ep.SecurityPolicyUri or "").lower()
        sp_score = 0
        if "basic256sha256" in sp:
            sp_score = 30
        elif "basic256" in sp:
            sp_score = 20
        elif "none" in sp:
            sp_score = 0
        else:
            sp_score = 10  # otras policies

        return mode * 100 + sp_score

    def _policy_mode_from_ep(self, ep):
        # policy name
        uri = (ep.SecurityPolicyUri or "")
        uri_l = uri.lower()
        if uri_l.endswith("#none") or "none" in uri_l:
            policy = "None"
        elif "basic256sha256" in uri_l:
            policy = "Basic256Sha256"
        elif "basic256" in uri_l:
            policy = "Basic256"
        else:
            policy = "Basic256Sha256"  # fallback razonable

        # mode name
        mode_int = int(ep.SecurityMode)
        if mode_int == 2:
            mode = "SignAndEncrypt"
        elif mode_int == 1:
            mode = "Sign"
        else:
            mode = "None"

        return policy, mode

    # -----------------------------
    # Conexión robusta (sin doble connect/disconnect)
    # -----------------------------
    def _connect_with_best_endpoint(self) -> Client:
        """
        1) Conecta a self.url solo para pedir endpoints
        2) Elige endpoint compatible con UserName (si hay user)
        3) Reconecta al EndpointUrl elegido con seguridad correspondiente
        4) Devuelve cli ya conectado
        """
        # Paso A: conectar solo para listar endpoints (algunos servidores no permiten GetEndpoints sin sesión)
        probe = Client(self.url, timeout=self.timeout_connect)

        # si tu server NO acepta Anonymous, intenta con user/pass incluso para el probe
        if self.user:
            probe.set_user(self.user)
            probe.set_password(self.password)

        connected_probe = False
        try:
            probe.connect()
            connected_probe = True

            # obtiene endpoints (más estable que connect_and_get_server_endpoints)
            eps = probe.get_endpoints()  # devuelve lista de endpoints
        finally:
            if connected_probe:
                try:
                    probe.disconnect()
                except Exception:
                    pass

        if not eps:
            raise RuntimeError("No pude obtener endpoints del servidor OPC UA.")

        best = max(eps, key=self._score_ep, default=None)
        if not best or self._score_ep(best) < 0:
            raise RuntimeError("Servidor no ofrece endpoint compatible con UserName (o tus credenciales).")

        policy, mode = self._policy_mode_from_ep(best)
        endpoint_url = best.EndpointUrl or self.url

        base_host, _ = self._opc_host_port(self.url)
        endpoint_url = self._replace_host(endpoint_url, base_host)

        cli = Client(endpoint_url, timeout=self.timeout_connect)

        # Seguridad (solo si NO es None)
        if policy != "None" and mode != "None":
            sec = f"{policy},{mode}"
            cli.set_security_string(sec)

            # Si el servidor además exige certificado de cliente, necesitas ambos archivos
            # (si no los pones, algunos servidores igual te dejan entrar; otros no)
            if self.client_cert and self.client_key:
                cli.load_client_certificate(self.client_cert)
                cli.load_private_key(self.client_key)

        # Identidad (UserName)
        if self.user:
            cli.set_user(self.user)
            cli.set_password(self.password)

        # Conectar real
        cli.connect()
        return cli

    def plc_reader(self):
        type_name_map = {
            "Boolean":"BOOL","SByte":"SINT","Byte":"BYTE","Int16":"INT","UInt16":"UINT",
            "Int32":"DINT","UInt32":"UDINT","Int64":"LINT","UInt64":"ULINT",
            "Float":"REAL","Double":"LREAL","String":"STRING",
        }

        period_s = 0.02
        backoff = 1.0
        max_backoff = 30.0

        while not self._stop:
            cli = None
            connected = False
            try:
                cli = self._connect_with_best_endpoint()
                connected = True
                self._cli = cli
                backoff = 1.0

                root = cli.get_root_node()
                plc_prg = self.browse_by_names(
                    root, "Objects","Datalayer","plc","app","Application","sym","PLC_PRG"
                )
                if plc_prg is None:
                    time.sleep(min(backoff, max_backoff))
                    backoff = min(backoff * 2.0, max_backoff)
                    continue

                nodes = plc_prg.get_children()
                var_infos = []
                for ch in nodes:
                    name = ch.get_browse_name().Name
                    try:
                        vt = ua.VariantType(ch.get_data_type_as_variant_type()).name
                    except Exception:
                        vt = "UNKNOWN"
                    var_infos.append((name, type_name_map.get(vt, vt), ch))

                while not self._stop:
                    vars_by_type = {}
                    for name, plc_type_name, node in var_infos:
                        try:
                            val = self.read_value(node)
                            vars_by_type.setdefault(plc_type_name, {})[name] = val
                        except Exception as e:
                            vars_by_type.setdefault("Error", {})[name] = f"{e}"

                    vars_by_type["timestamp"] = time.time()

                    if len(self.buffer) >= self.buffer_size:
                        try:
                            self.buffer.pop(0)
                        except Exception:
                            pass

                    self.buffer.append(vars_by_type)
                    if self.on_sample:
                        try:
                            self.on_sample(dict(vars_by_type))
                        except Exception:
                            pass

                    time.sleep(period_s)

            except Exception as e:
                print(f"OPC UA FAIL {self.url} -> {e} | retry en {backoff:.1f}s")
                time.sleep(min(backoff, max_backoff))
                backoff = min(backoff * 2.0, max_backoff)

            finally:
                # ✅ SOLO desconectar si conectó
                if cli and connected:
                    try:
                        cli.disconnect()
                    except Exception:
                        pass
                self._cli = None

    def start(self):
        if self._thr and self._thr.is_alive():
            return
        self._stop = False
        self._thr = threading.Thread(target=self.plc_reader, daemon=True)
        self._thr.start()
