import asyncio
from fastapi import WebSocket
from plc.buffer import data_buffer

async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            if data_buffer:
                await websocket.send_json([data_buffer[-1]])
            await asyncio.sleep(0.1)
    except Exception as e:
        print("Cliente desconectado o error:", e)
