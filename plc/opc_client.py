from opcua import Client, ua
import threading
import time

class PLCReader:
    def __init__(self, url, user, password, buffer, buffer_size=100, on_sample=None):
        self.url, self.user, self.password = url, user, password
        self.buffer = buffer
        self.buffer_size = buffer_size
        self.on_sample = on_sample

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
                    found = ch; break
            if not found:
                print("Por favor publique un proyecto desde la configuración de símbolos")
                return None
            cur = found
        return cur

    def plc_reader(self):
        type_name_map = {
            "Boolean":"BOOL","SByte":"SINT","Byte":"BYTE","Int16":"INT","UInt16":"UINT",
            "Int32":"DINT","UInt32":"UDINT","Int64":"LINT","UInt64":"ULINT",
            "Float":"REAL","Double":"LREAL","String":"STRING",
        }

        cli = Client(self.url, timeout=3.0)
        if self.user: cli.set_user(self.user); cli.set_password(self.password)
        cli.connect()
        try:
            root = cli.get_root_node()
            plc_prg = self.browse_by_names(
                root, "Objects","Datalayer","plc","app","Application","sym","PLC_PRG"
            )
            if plc_prg is None:
                return

            # 🔥 Cachea nodos, nombres y tipos (una vez)
            nodes = plc_prg.get_children()
            var_infos = []
            for ch in nodes:
                name = ch.get_browse_name().Name
                try:
                    vt = ua.VariantType(ch.get_data_type_as_variant_type()).name
                except Exception:
                    vt = "UNKNOWN"
                var_infos.append((name, type_name_map.get(vt, vt), ch))

            period_s = 0.02  # 50 Hz; pon 0.01 si quieres 100 Hz
            while True:
                vars_by_type = {}
                for name, plc_type_name, node in var_infos:
                    try:
                        val = self.read_value(node)
                        bucket = vars_by_type.setdefault(plc_type_name, {})
                        bucket[name] = val
                    except Exception as e:
                        vars_by_type.setdefault("Error", {})[name] = f"⛔ {e}"

                vars_by_type["timestamp"] = time.time()

                # poda por tamaño propio (por compat)
                if len(self.buffer) >= self.buffer_size:
                    try: self.buffer.pop(0)
                    except Exception: pass

                self.buffer.append(vars_by_type)   # ahora añade __seq__
                if self.on_sample:
                    try: self.on_sample(dict(vars_by_type))
                    except Exception: pass

                time.sleep(period_s)
        finally:
            cli.disconnect()

    def start(self):
        threading.Thread(target=self.plc_reader, daemon=True).start()
