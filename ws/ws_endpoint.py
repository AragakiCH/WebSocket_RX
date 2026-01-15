import asyncio, json, time, logging
from fastapi import WebSocket, WebSocketDisconnect
from plc.buffer import data_buffer

log = logging.getLogger("ws")

async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("[WS] cliente conectado")

    try:
        last_seq = None

        while True:
            sample = data_buffer.latest()
            if sample:
                seq = sample.get("__seq__")
                if seq != last_seq:
                    await websocket.send_json(sample)
                    last_seq = seq

            await asyncio.sleep(0.2)  # 5 Hz para UI

    except WebSocketDisconnect:
        print("[WS] cliente desconectado")
    except Exception as e:
        print("[WS] error:", e)
        try:
            await websocket.close()
        except:
            pass
