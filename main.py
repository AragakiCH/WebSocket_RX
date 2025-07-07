from fastapi import FastAPI, WebSocket
from ws.ws_endpoint import websocket_endpoint
from ws.ws_write_endpoint import websocket_write_endpoint
from plc.opc_client import PLCReader
from plc.buffer import data_buffer

# --- CONFIG ---
URL = "opc.tcp://192.168.18.60:4840"
USER = "psi_opc"
PASSWORD = "Saipem_2025_opc"

# --- APP ---
app = FastAPI()

# --- Iniciar PLC Thread ---
plc = PLCReader(URL, USER, PASSWORD, data_buffer, buffer_size=100)
plc.start()

# --- WebSocket route ---
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket_endpoint(websocket)


@app.websocket("/ws_write")
async def ws_write(websocket: WebSocket):
    await websocket_write_endpoint(websocket)
