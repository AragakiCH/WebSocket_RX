import asyncio, json, time, logging
from fastapi import WebSocket, WebSocketDisconnect
from plc.buffer import data_buffer

log = logging.getLogger("ws")

async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    log.info("connection open")
    last_seq = None
    try:
        while True:
            batch = data_buffer.after(last_seq)
            if batch:
                for snap in batch:
                    await websocket.send_text(json.dumps(snap))
                last_seq = batch[-1]["__seq__"]
            await asyncio.sleep(0.01)  # ~100 Hz de “pull”; ajusta si quieres
    except WebSocketDisconnect:
        log.info("connection closed")
