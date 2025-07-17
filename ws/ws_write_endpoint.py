# ws/ws_write_endpoint.py
from fastapi import WebSocket
from opcua import Client, ua
from plc.opc_client import PLCReader  # Usa el mismo browse_by_names, etc.

# Debes reutilizar los mismos datos de conexión de main.py, así que puedes importarlos, o pasarlos como parámetro si lo refactorizas más

URL = "opc.tcp://192.168.18.60:4840"
USER = "psi_opc"
PASSWORD = "Saipem_2025_opc"

async def websocket_write_endpoint(websocket: WebSocket):
    await websocket.accept()
    # OPC UA client SOLO para este endpoint de escritura (puedes optimizar esto después)
    cli = Client(URL)
    cli.set_user(USER)
    cli.set_password(PASSWORD)
    cli.connect()
    try:
        # Reutiliza el método browse_by_names de tu clase
        reader = PLCReader(URL, USER, PASSWORD, [])
        root = cli.get_root_node()
        plc_prg = reader.browse_by_names(
            root, "Objects", "Datalayer", "plc", "app", "Application", "sym", "PLC_PRG"
        )
        while True:
            msg = await websocket.receive_json()
            var_name = msg.get("variable")
            value = msg.get("value")
            if not var_name:
                await websocket.send_json({"status": "error", "msg": "No variable name"})
                continue

            for ch in plc_prg.get_children():
                if ch.get_browse_name().Name == var_name:
                    # Aquí puedes usar VariantType según el tipo, ej: BOOL o REAL
                    if isinstance(value, bool):
                        ch.set_value(value, ua.VariantType.Boolean)
                    elif isinstance(value, float):
                        ch.set_value(value, ua.VariantType.Float)
                    elif isinstance(value, int):
                        ch.set_value(value, ua.VariantType.Int16)
                    else:
                        await websocket.send_json({"status": "error", "msg": "Tipo de valor no soportado"})
                        break
                    await websocket.send_json({"status": "ok", "msg": f"{var_name} actualizado"})
                    break
            else:
                await websocket.send_json({"status": "error", "msg": "Variable no encontrada"})
    except Exception as e:
        print("Error en escritura:", e)
    finally:
        cli.disconnect()
