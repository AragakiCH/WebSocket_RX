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
from plc.discovery import discover_opcua_urls, pick_first_alive_auth, pick_first_alive_any
import logging
from pydantic import BaseModel
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi import Body
from utils.rt_export_manager import RtExportManager
import os
from fastapi import Request
from opcua import Client
import threading
try:
    from utils.excel_logger import ExcelLogger
except ImportError:
    ExcelLogger = None
import time
import traceback

LOG_TO_EXCEL = os.getenv("LOG_TO_EXCEL", "true").lower() == "false"
export_mgr = RtExportManager(out_dir="exports", checkpoint_s=1.5)

def _parse_opcua_urls(val: str) -> list[str]:
    if not val:
        return []
    return [u.strip() for u in val.split(",") if u.strip()]

def _unique(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

IS_EMBEDDED = os.getenv("PSI_EMBEDDED", "false").lower() == "true"

# URL_ENV = os.getenv(
#     "OPCUA_URL",
#     "opc.tcp://127.0.0.1:4840,opc.tcp://localhost:4840, opc.tcp://192.168.17.60:4840"
# )

DEFAULT_URL_ENV = ",".join([
    "opc.tcp://127.0.0.1:4840",
    "opc.tcp://localhost:4840",
    "opc.tcp://ctrlX-CORE:4840",
    "opc.tcp://VirtualControl-1:4840",
    "opc.tcp://VirtualControl-2:4840",
    "opc.tcp://VirtualControl-3:4840",
    "opc.tcp://VirtualControl-4:4840",
])

URL_ENV = os.getenv("OPCUA_URL", DEFAULT_URL_ENV)
URLS_ENV = _parse_opcua_urls(URL_ENV)
URL = URLS_ENV[0] if URLS_ENV else "opc.tcp://127.0.0.1:4840"

class OpcuaLoginIn(BaseModel):
    user: str
    password: str
    url: str | None = None  # opcional si quieres elegir URL también

CURRENT_OPCUA_USER = None
CURRENT_OPCUA_PASS = None
CURRENT_OPCUA_URL  = None

#USER     = os.getenv("OPCUA_USER", "boschrexroth")
#PASSWORD = os.getenv("OPCUA_PASSWORD", "boschrexroth")

#log = logging.getLogger("psi.main")
#log.info("PLC URL=%s  USER set=%s", URL_ENV, bool(USER))


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
        log_queue.put_nowait(sample)
    except queue.Full:
        pass

    try:
        data_buffer.append(sample)
    except Exception:
        pass

    # ✅ NUEVO: si está exportando, mete fila
    try:
        export_mgr.ingest(sample)
    except Exception:
        pass

@app.on_event("startup")
def _startup():
    log = logging.getLogger("uvicorn")
    env_urls = URLS_ENV[:] #or ["opc.tcp://192.168.17.60:4840"]

    def supervisor():
        global plc, CURRENT_OPCUA_USER, CURRENT_OPCUA_PASS, CURRENT_OPCUA_URL

        backoff = 1.0
        max_backoff = 30.0

        while True:
            try:
                # 0) si ya hay reader, vigila que siga vivo
                if plc is not None:
                    thr = getattr(plc, "_thr", None)
                    if thr is not None and not thr.is_alive():
                        try:
                            plc.stop()
                        except Exception:
                            pass
                        plc = None
                    time.sleep(2.0)
                    continue

                # 1) no spamees conexiones si aún no hay login
                user = (CURRENT_OPCUA_USER or "").strip()
                password = CURRENT_OPCUA_PASS or ""
                if not user or not password:
                    time.sleep(1.0)
                    continue

                # 2) URLs candidatas (si el login mandó url, úsala primero)
                env_urls = [CURRENT_OPCUA_URL] if CURRENT_OPCUA_URL else URLS_ENV[:]
                if not env_urls:
                    env_urls = [URL]  # fallback

                # 3) elige una URL "viva" (sin validar auth aquí)
                url = pick_first_alive_any(env_urls)

                # 4) fallback discovery
                if not url:
                    log.warning("OPCUA_URL no respondió. Haré discovery. ENV=%s", env_urls)
                    ordered = discover_opcua_urls(extra_candidates=env_urls)
                    url = pick_first_alive_any(ordered)

                # 5) si hay url viva, arranca PLCReader con credenciales actuales
                if url:
                    log.info("OPC UA elegido: %s", url)
                    _plc = PLCReader(
                        url, user, password, data_buffer,
                        buffer_size=100, on_sample=push_to_log
                    )
                    _plc.start()
                    plc = _plc
                    log.info("PLCReader iniciado OK.")
                    backoff = 1.0
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

@app.post("/api/opcua/login")
def opcua_login(body: OpcuaLoginIn, request: Request):
    global CURRENT_OPCUA_USER, CURRENT_OPCUA_PASS, CURRENT_OPCUA_URL, plc

    u = body.user.strip()
    p = body.password
    if not u or not p:
        raise HTTPException(400, "Faltan credenciales")

    candidates = []
    if body.url and body.url.strip():
        candidates.append(body.url.strip())

    # host por donde estás entrando a la UI (IP o nombre)
    host_hdr = request.headers.get("host", "")
    host_only = host_hdr.split(":")[0].strip() if host_hdr else ""
    if host_only:
        candidates.append(f"opc.tcp://{host_only}:4840")

    # env + discovery
    candidates += URLS_ENV[:]
    discovered = discover_opcua_urls(extra_candidates=candidates)
    ordered = _unique(candidates + discovered)

    winner = pick_first_alive_auth(u, p, ordered)
    if not winner:
        raise HTTPException(401, detail={"error":"No pude autenticar", "tried": ordered[:30]})

    CURRENT_OPCUA_USER = u
    CURRENT_OPCUA_PASS = p
    CURRENT_OPCUA_URL  = winner

    try:
        if plc:
            plc.stop()
            plc = None
    except Exception:
        pass

    return {"ok": True, "url": winner}

@app.get("/api/opcua/endpoints")
def opcua_endpoints(url: str | None = None):
    u = (CURRENT_OPCUA_USER or "").strip()
    p = CURRENT_OPCUA_PASS or ""
    if not u or not p:
        raise HTTPException(400, "Primero haz login en /api/opcua/login")

    target = (url or CURRENT_OPCUA_URL or URL).strip()

    # probamos 2 caminos:
    # A) conectar + get_endpoints()
    # B) connect_and_get_server_endpoints()
    try:    
        c = Client(target, timeout=5.0)
        c.set_user(u)
        c.set_password(p)

        c.connect()
        try:
            eps = c.get_endpoints()
        finally:
            try:
                c.disconnect()
            except Exception:
                pass

        out = []
        for e in eps or []:
            out.append({
                "EndpointUrl": getattr(e, "EndpointUrl", None),
                "SecurityPolicyUri": getattr(e, "SecurityPolicyUri", None),
                "SecurityMode": str(getattr(e, "SecurityMode", None)),
                "UserTokens": [t.TokenType.name for t in (getattr(e, "UserIdentityTokens", None) or [])],
            })
        return out

    except Exception as ex_a:
        # fallback B
        try:
            c = Client(target, timeout=5.0)
            c.set_user(u)
            c.set_password(p)
            eps = c.connect_and_get_server_endpoints()
            try:
                c.disconnect()
            except Exception:
                pass

            out = []
            for e in eps or []:
                out.append({
                    "EndpointUrl": getattr(e, "EndpointUrl", None),
                    "SecurityPolicyUri": getattr(e, "SecurityPolicyUri", None),
                    "SecurityMode": str(getattr(e, "SecurityMode", None)),
                    "UserTokens": [t.TokenType.name for t in (getattr(e, "UserIdentityTokens", None) or [])],
                })
            return out

        except Exception as ex_b:
            # ✅ devuelve el error real (no “500 pelado”)
            return JSONResponse(
                status_code=500,
                content={
                    "target": target,
                    "phaseA_error": repr(ex_a),
                    "phaseB_error": repr(ex_b),
                    "traceA": traceback.format_exc(),
                },
            )

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket_endpoint(websocket)

@app.websocket("/ws_write")
async def ws_write(websocket: WebSocket):
    await websocket_write_endpoint(websocket)

@app.post("/api/export/start")
def export_start(payload: dict = Body(...)):
    tags = payload.get("tags") or []
    try:
        st = export_mgr.start(tags)
        return {"ok": True, "status": st}
    except Exception as e:
        raise HTTPException(400, f"No pude iniciar export: {e}")

@app.post("/api/export/stop")
def export_stop():
    st = export_mgr.stop()
    return {"ok": True, "status": st}

@app.get("/api/export/status")
def export_status():
    return export_mgr.status()

@app.get("/api/export/download")
def export_download():
    st = export_mgr.status()
    path = st.get("path")
    if not path or not os.path.exists(path):
        raise HTTPException(404, "No hay archivo para descargar todavía.")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=os.path.basename(path),
    )

# StaticFiles compatible con PyInstaller
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
STATIC_DIR = (BASE_DIR / "frontend").resolve()
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")
