# main.py
import os, sys, queue
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from ws.ws_endpoint import websocket_endpoint
from ws.ws_write_endpoint import websocket_write_endpoint
from plc.opc_client import PLCReader
from plc.buffer import data_buffer
from plc.discovery import discover_opcua_urls, pick_first_alive
import logging
try:
    from utils.excel_logger import ExcelLogger
except ImportError:
    ExcelLogger = None
import time

LOG_TO_EXCEL = os.getenv("LOG_TO_EXCEL", "true").lower() == "false"


def _parse_opcua_urls(val: str) -> list[str]:
    if not val:
        return []
    return [u.strip() for u in val.split(",") if u.strip()]

URL_ENV  = os.getenv("OPCUA_URL", "opc.tcp://192.168.17.60:4840")  # admite varias separadas por coma
URLS_ENV = _parse_opcua_urls(URL_ENV)
URLS    = _parse_opcua_urls(URL_ENV)
URL     = URLS[0] if URLS else "opc.tcp://192.168.17.60:4840"  # ← hotfix: toma la 1ª

USER     = os.getenv("OPCUA_USER", "boschrexroth")
PASSWORD = os.getenv("OPCUA_PASSWORD", "boschrexroth")

log = logging.getLogger("psi.main")
log.info("PLC URL=%s  USER set=%s", URL_ENV, bool(USER))


app = FastAPI()
log_queue: queue.Queue = queue.Queue(maxsize=10000)
excel_logger = None
plc = None  # <- no arrancar aquí

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True,
)

if ExcelLogger and LOG_TO_EXCEL:
    excel_logger = ExcelLogger(q=log_queue, path_template="logs/ws_{date}.xlsx",
                               flush_every=20, flush_interval=0.5)
    excel_logger.start()

def push_to_log(sample: dict):
    try:
        log_queue.put_nowait(sample)  # tu logger a Excel
    except queue.Full:
        pass
    # <- añade esto SÍ o SÍ:
    try:
        data_buffer.append(sample)
    except Exception:
        pass

@app.on_event("startup")
def _startup():
    global plc

    log = logging.getLogger("uvicorn")

    # 0) URLS directas del ENV (prioridad absoluta)
    env_urls = URLS_ENV[:]  # ya parseadas
    if not env_urls:
        env_urls = ["opc.tcp://192.168.17.60:4840"]

    # 1) Primero intenta SOLO las del ENV (sin escanear nada)
    url, tried = pick_first_alive(user=USER, password=PASSWORD, ordered_urls=env_urls)
    if not url:
        log.warning("OPCUA_URL no respondió. Haré discovery. ENV=%s", env_urls)

        # 2) Fallback: discovery + las del ENV adelante
        ordered = discover_opcua_urls(extra_candidates=env_urls)

        url, candidates = pick_first_alive(user=USER, password=PASSWORD, ordered_urls=ordered)
        if not url:
            log.error("No se encontró OPC UA vivo. Candidatos: %s", candidates)
            # deja rastro visible en UI
            push_to_log({"Error": {"opcua": "offline"}, "timestamp": time.time()})
            return

    log.info("OPC UA elegido: %s", url)

    try:
        plc = PLCReader(url, USER, PASSWORD, data_buffer,
                        buffer_size=100, on_sample=push_to_log)
        plc.start()
        log.info("PLCReader iniciado OK.")
    except Exception as e:
        log.exception("PLCReader no inició: %s", e)
        push_to_log({"Error": {"plc_reader": str(e)}, "timestamp": time.time()})

@app.on_event("shutdown")
def _shutdown():
    try:
        if excel_logger:
            excel_logger.stop()
    except Exception:
        pass
    try:
        if plc:
            plc.stop()  # si tu clase tiene stop(); si no, ignora
    except Exception:
        pass

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket_endpoint(websocket)

@app.websocket("/ws_write")
async def ws_write(websocket: WebSocket):
    await websocket_write_endpoint(websocket)

# StaticFiles compatible con PyInstaller
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
STATIC_DIR = (BASE_DIR / "frontend").resolve()
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")
