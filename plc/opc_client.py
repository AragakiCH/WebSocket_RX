from opcua import Client, ua
import threading
import time

class PLCReader:
    def __init__(self, url, user, password, buffer, buffer_size=100, on_sample=None):
        self.url = url
        self.user = user
        self.password = password
        self.buffer = buffer
        self.buffer_size = buffer_size
        self.on_sample = on_sample

    def read_value(self, node):
        try:
            val_node = node.get_child(["2:Value"])
            return val_node.get_value()
        except Exception:
            return node.get_value()

    def children_all(self, node):
        refs = [
            ua.ObjectIds.HasComponent,
            ua.ObjectIds.Organizes,
            ua.ObjectIds.HasProperty
        ]
        kids = []
        for r in refs:
            kids += node.get_children(
                refs=r,
                nodeclassmask=ua.NodeClass.Variable | ua.NodeClass.Object
            )
        uniq = {k.nodeid.to_string(): k for k in kids}
        return node.get_children()

    def browse_by_names(self, root, *names):
        cur = root
        for n in names:
            for ch in self.children_all(cur):
                if ch.get_browse_name().Name == n:
                    cur = ch
                    break
            else:
                # ← aquí ya no se lanza excepción, solo se imprime
                print("Por favor publique un proyecto desde la configuración de símbolos")
                return None
        return cur

    def plc_reader(self):
        # Diccionario para traducir tipos OPC UA a nombres PLC comunes
        type_name_map = {
            "Boolean": "BOOL",
            "SByte": "SINT",
            "Byte": "BYTE",
            "Int16": "INT",
            "UInt16": "UINT",
            "Int32": "DINT",
            "UInt32": "UDINT",
            "Int64": "LINT",
            "UInt64": "ULINT",
            "Float": "REAL",
            "Double": "LREAL",
            "String": "STRING",
            # Agrega más si tu PLC maneja otros tipos (DateTime, Guid, etc)
        }

        cli = Client(self.url, timeout=2)
        cli.set_user(self.user)
        cli.set_password(self.password)
        cli.connect()
        try:
            root = cli.get_root_node()
            plc_prg = self.browse_by_names(
                root, "Objects", "Datalayer", "plc", "app",
                "Application", "sym", "PLC_PRG"
            )
            if plc_prg is None:
                print("Por favor publique un proyecto desde la configuración de símbolos")
                return

            while True:
                vars_by_type = {}
                for ch in plc_prg.get_children():
                    name = ch.get_browse_name().Name
                    try:
                        val = self.read_value(ch)
                        data_type = ch.get_data_type_as_variant_type()
                        type_name = ua.VariantType(data_type).name
                        plc_type_name = type_name_map.get(type_name, type_name)  # Si no está mapeado, usa el nombre OPC UA

                        if plc_type_name not in vars_by_type:
                            vars_by_type[plc_type_name] = {}
                        vars_by_type[plc_type_name][name] = val

                    except Exception as e:
                        if "Error" not in vars_by_type:
                            vars_by_type["Error"] = {}
                        vars_by_type["Error"][name] = f"⛔ {e}"

                vars_by_type["timestamp"] = time.time()

                if len(self.buffer) >= self.buffer_size:
                    self.buffer.pop(0)
                self.buffer.append(vars_by_type)

                if self.on_sample:
                    try:
                        self.on_sample(dict(vars_by_type))  # copia superficial
                    except Exception as e:
                        # no frenes el hilo por el logger
                        print(f"[Excel log warn] {e}")

                time.sleep(0.02)
        finally:
            cli.disconnect()

    def start(self):
        threading.Thread(target=self.plc_reader, daemon=True).start()
