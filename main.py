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
import threading
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
    log = logging.getLogger("uvicorn")
    env_urls = URLS_ENV[:] or ["opc.tcp://192.168.17.60:4840"]

    def supervisor():
        global plc  # ✅ CLAVE: vas a leer y asignar plc aquí

        backoff = 1.0
        max_backoff = 30.0

        while True:
            try:
                # 0) Si ya hay reader, vigila que siga vivo
                if plc is not None:
                    # Si tu PLCReader guarda el thread en self._thr (como tu versión),
                    # y se murió por alguna razón, lo soltamos para que reinicie.
                    try:
                        thr = getattr(plc, "_thr", None)
                        if thr is not None and not thr.is_alive():
                            log.warning("PLCReader thread murió. Reiniciando...")
                            try:
                                plc.stop()
                            except Exception:
                                pass
                            plc = None
                    except Exception:
                        pass

                    time.sleep(2.0)
                    continue

                # 1) intenta SOLO las URLs del ENV
                url, tried = pick_first_alive(user=USER, password=PASSWORD, ordered_urls=env_urls)

                # 2) fallback: discovery
                if not url:
                    log.warning("OPCUA_URL no respondió. Haré discovery. ENV=%s", env_urls)
                    ordered = discover_opcua_urls(extra_candidates=env_urls)
                    url, candidates = pick_first_alive(user=USER, password=PASSWORD, ordered_urls=ordered)

                if url:
                    log.info("OPC UA elegido: %s", url)

                    try:
                        _plc = PLCReader(
                            url, USER, PASSWORD, data_buffer,
                            buffer_size=100, on_sample=push_to_log
                        )
                        _plc.start()
                        plc = _plc  # ✅ ya no revienta (global plc)
                        log.info("PLCReader iniciado OK.")
                        backoff = 1.0  # reset backoff cuando conecta

                    except Exception as e:
                        log.exception("PLCReader no inició: %s", e)
                        push_to_log({"Error": {"plc_reader": str(e)}, "timestamp": time.time()})
                        time.sleep(backoff)
                        backoff = min(backoff * 2.0, max_backoff)

                else:
                    log.error("No se encontró OPC UA vivo todavía. Reintento en %.1fs", backoff)
                    push_to_log({"Error": {"opcua": "offline"}, "timestamp": time.time()})
                    time.sleep(backoff)
                    backoff = min(backoff * 2.0, max_backoff)

            except Exception as e:
                log.exception("Supervisor OPCUA reventó: %s", e)
                time.sleep(5.0)

    threading.Thread(target=supervisor, daemon=True).start()

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
