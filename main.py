# main.py
import os, sys, queue, socket
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from ws.ws_endpoint import websocket_endpoint
from ws.ws_write_endpoint import websocket_write_endpoint
from plc.opc_client import PLCReader
from plc.buffer import data_buffer
from plc.discovery import discover_opcua_urls, pick_first_alive_auth, pick_first_alive_any, _probe_tcp_host
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
    seen = set(); out = []
    for x in seq:
        x = (x or "").strip()
        if not x: 
            continue
        if x not in seen:
            seen.add(x); out.append(x)
    return out

def _url_host(url: str) -> str:
    hp = url.split("://",1)[-1].split("/",1)[0]
    host = hp.split(":",1)[0]
    return host.strip()

def _url_port(url: str) -> int:
    hp = url.split("://",1)[-1].split("/",1)[0]
    if ":" in hp:
        try: return int(hp.split(":",1)[1])
        except Exception: return 4840
    return 4840

def _normalize_to_ip(url: str) -> str:
    # opc.tcp://host:4840 -> opc.tcp://ip:4840 (si resuelve)
    host = _url_host(url)
    port = _url_port(url)
    try:
        ip = socket.gethostbyname(host)
        # si ya es ip, gethostbyname lo devuelve igual
        return f"opc.tcp://{ip}:{port}"
    except Exception:
        return url
    
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
URL_FALLBACK = URLS_ENV[0] if URLS_ENV else "opc.tcp://127.0.0.1:4840"

class OpcuaLoginIn(BaseModel):
    user: str
    password: str
    url: str | None = None


class OpcuaDiscoverItem(BaseModel):
    url: str
    host: str
    ip: str | None = None
    port: int
    tcp_ok: bool
    source: str

plc = None
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



@app.on_event("startup")
def _startup():
    def supervisor():
        global plc, CURRENT_OPCUA_USER, CURRENT_OPCUA_PASS, CURRENT_OPCUA_URL
        import logging
        log = logging.getLogger("uvicorn")
        backoff = 1.0
        max_backoff = 30.0

        while True:
            try:
                if plc is not None:
                    thr = getattr(plc, "_thr", None)
                    if thr is not None and not thr.is_alive():
                        try: plc.stop()
                        except Exception: pass
                        plc = None
                    time.sleep(2.0)
                    continue

                user = (CURRENT_OPCUA_USER or "").strip()
                password = CURRENT_OPCUA_PASS or ""
                if not user or not password:
                    time.sleep(1.0)
                    continue

                env_urls = [CURRENT_OPCUA_URL] if CURRENT_OPCUA_URL else URLS_ENV[:]
                if not env_urls:
                    env_urls = [URL_FALLBACK]

                url = pick_first_alive_any(env_urls)
                if not url:
                    ordered = discover_opcua_urls(extra_candidates=env_urls)
                    url = pick_first_alive_any(ordered)

                if url:
                    log.info("OPC UA elegido: %s", url)
                    _plc = PLCReader(url, user, password, data_buffer, buffer_size=100)
                    _plc.start()
                    plc = _plc
                    backoff = 1.0
                else:
                    log.error("No OPC UA vivo. Reintento en %.1fs", backoff)
                    time.sleep(backoff)
                    backoff = min(backoff*2.0, max_backoff)

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


@app.get("/api/opcua/discover", response_model=list[OpcuaDiscoverItem])
def opcua_discover(request: Request, max_results: int = 20):
    # 1) arma candidatos “inteligentes”
    candidates = []

    # host desde donde entras a la UI (si entras por 192.168.1.1:8000 => prueba 192.168.1.1:4840)
    host_hdr = request.headers.get("host", "")
    host_only = host_hdr.split(":")[0].strip() if host_hdr else ""
    if host_only:
        candidates.append(f"opc.tcp://{host_only}:4840")

    candidates += URLS_ENV[:]

    # 2) discovery “fuerte”
    discovered = discover_opcua_urls(extra_candidates=candidates)
    ordered = _unique(candidates + discovered)

    # 3) prepara items con info (y TCP test rápido)
    items = []
    for u in ordered:
        host = _url_host(u)
        port = _url_port(u)

        ip = None
        try:
            ip = socket.gethostbyname(host)
        except Exception:
            ip = None

        tcp_ok = _probe_tcp_host(host, port=port) or (ip and _probe_tcp_host(ip, port=port))

        # source heurístico
        source = "env/discovery"
        if host in ("127.0.0.1", "localhost"):
            source = "loopback"
        elif host_only and host == host_only:
            source = "ui-host"
        elif "VirtualControl" in host or "virtualcontrol" in host:
            source = "virtualcontrol"
        elif "ctrlx" in host.lower():
            source = "ctrlx-core"

        items.append({
            "url": u,
            "host": host,
            "ip": ip,
            "port": port,
            "tcp_ok": tcp_ok,
            "source": source,
        })

    # 4) filtra y limita: primero tcp_ok=True
    items.sort(key=lambda x: (not x["tcp_ok"], x["source"]))

    # quita duplicados por url final
    out = []
    seen = set()
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        out.append(it)
        if len(out) >= max_results:
            break

    return out

@app.post("/api/opcua/login")
def opcua_login(body: OpcuaLoginIn, request: Request):
    global CURRENT_OPCUA_USER, CURRENT_OPCUA_PASS, CURRENT_OPCUA_URL, plc

    u = body.user.strip()
    p = body.password
    if not u or not p:
        raise HTTPException(400, "Faltan credenciales")

    # 1) lista de candidatos
    candidates = []
    if body.url and body.url.strip():
        candidates.append(body.url.strip())

    # host de UI también (por si el user no escogió nada)
    host_hdr = request.headers.get("host", "")
    host_only = host_hdr.split(":")[0].strip() if host_hdr else ""
    if host_only:
        candidates.append(f"opc.tcp://{host_only}:4840")

    candidates += URLS_ENV[:]
    discovered = discover_opcua_urls(extra_candidates=candidates)

    ordered = _unique(candidates + discovered)

    # 2) prueba: si URL trae hostname, prueba también su versión por IP
    expanded = []
    for u0 in ordered:
        expanded.append(u0)
        u_ip = _normalize_to_ip(u0)
        if u_ip != u0:
            expanded.append(u_ip)
    expanded = _unique(expanded)

    # 3) elige el primero que autentique
    winner = pick_first_alive_auth(u, p, expanded)
    if not winner:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "No pude autenticar contra ningún endpoint.",
                "hint": "Revisa usuario/clave OPC UA y security/token del server.",
                "tried": expanded[:30],
            },
        )

    # 4) guarda
    CURRENT_OPCUA_USER = u
    CURRENT_OPCUA_PASS = p
    CURRENT_OPCUA_URL  = winner

    # 5) reinicia reader (tu supervisor lo levantará)
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

    target = (url or CURRENT_OPCUA_URL or URL_FALLBACK).strip()

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
