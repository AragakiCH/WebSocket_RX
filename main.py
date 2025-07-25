from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from ws.ws_endpoint import websocket_endpoint
from ws.ws_write_endpoint import websocket_write_endpoint
from plc.opc_client import PLCReader
from plc.buffer import data_buffer

# --- CONFIG ---
URL      = "opc.tcp://192.168.100.31:4840"
USER     = "boschrexroth"
PASSWORD = "boschrexroth"

# --- APP ---
app = FastAPI()

# (Opcional) si vas a servir el frontend desde otro origen, habilita CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],            # o ["http://localhost:5500"] si lo limitas
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Monta la carpeta `frontend/` en la raíz “/”


# --- Iniciar PLC Thread ---
plc = PLCReader(URL, USER, PASSWORD, data_buffer, buffer_size=100)
plc.start()

# --- WebSocket routes ---
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket_endpoint(websocket)

@app.websocket("/ws_write")
async def ws_write(websocket: WebSocket):
    await websocket_write_endpoint(websocket)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
