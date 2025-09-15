import asyncio, json, time, logging
from fastapi import WebSocket, WebSocketDisconnect
from plc.buffer import data_buffer

log = logging.getLogger("ws")

async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    log.info("connection open")
    last_ts = None
    try:
        while True:
            snap = data_buffer.latest()  # <- véase buffer abajo
            if snap:
                ts = snap.get("timestamp") or time.time()
                if ts != last_ts:
                    await websocket.send_text(json.dumps(snap))
                    last_ts = ts
            await asyncio.sleep(0.2)  # 5 Hz
    except WebSocketDisconnect:
        log.info("connection closed")
