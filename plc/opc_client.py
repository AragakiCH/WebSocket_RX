from opcua import Client, ua
import threading
import time

class PLCReader:
    def __init__(self, url, user, password, buffer, buffer_size=100):
        self.url = url
        self.user = user
        self.password = password
        self.buffer = buffer
        self.buffer_size = buffer_size

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
                vars = {}
                for ch in plc_prg.get_children():
                    name = ch.get_browse_name().Name
                    try:
                        vars[name] = self.read_value(ch)
                    except Exception as e:
                        vars[name] = f"⛔ {e}"
                vars["timestamp"] = time.time()

                if len(self.buffer) >= self.buffer_size:
                    self.buffer.pop(0)
                self.buffer.append(vars)

                time.sleep(0.02)

        finally:
            cli.disconnect()

    def start(self):
        threading.Thread(target=self.plc_reader, daemon=True).start()
