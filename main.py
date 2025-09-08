from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import queue

try:
    from utils.excel_logger import ExcelLogger
except ImportError:
    ExcelLogger = None


from ws.ws_endpoint import websocket_endpoint
from ws.ws_write_endpoint import websocket_write_endpoint
from plc.opc_client import PLCReader
from plc.buffer import data_buffer

# --- CONFIG ---
URL      = "opc.tcp://192.168.18.32:4840"
USER     = "boschrexroth"
PASSWORD = "boschrexroth"

# --- APP ---
app = FastAPI()

log_queue: queue.Queue = queue.Queue(maxsize=10000)


# (Opcional) si vas a servir el frontend desde otro origen, habilita CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# crea y arranca el logger (antes de iniciar el PLCReader)
excel_logger = None
if ExcelLogger:
    excel_logger = ExcelLogger(
        q=log_queue,
        path_template="logs/ws_{date}.xlsx",
        flush_every=20,
        flush_interval=0.5,
    )
    excel_logger.start()




def push_to_log(sample: dict):
    try:
        log_queue.put_nowait(sample)
    except queue.Full:
        # mejor perder una muestra que bloquear el hilo OPC
        pass


# --- Iniciar PLC Thread ---
plc = PLCReader(URL, USER, PASSWORD, data_buffer, buffer_size=100, on_sample=push_to_log)
plc.start()

# --- WebSocket routes ---
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket_endpoint(websocket)

@app.websocket("/ws_write")
async def ws_write(websocket: WebSocket):
    await websocket_write_endpoint(websocket)

@app.on_event("shutdown")
def _shutdown():
    # cierra limpio
    try:
        excel_logger.stop()
    except Exception:
        pass

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
