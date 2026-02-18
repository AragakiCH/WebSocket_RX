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
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    
def _probe_tcp_fast(host: str, port: int, timeout: float = 0.12) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def _tcp_ok_host_or_ip(host: str, port: int) -> tuple[bool, str | None]:
    ip = None
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        ip = None

    ok = _probe_tcp_fast(host, port)
    if not ok and ip:
        ok = _probe_tcp_fast(ip, port)
    return bool(ok), ip
    
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
def opcua_discover(request: Request, max_results: int = 20, deep: int = 0):
    port = 4840

    # 1) candidatos rápidos
    candidates: list[tuple[str, str]] = []  # (url, source)

    host_hdr = request.headers.get("host", "")
    host_only = host_hdr.split(":")[0].strip() if host_hdr else ""
    if host_only:
        candidates.append((f"opc.tcp://{host_only}:{port}", "ui-host"))

    # loopback
    candidates.append((f"opc.tcp://127.0.0.1:{port}", "loopback"))
    candidates.append((f"opc.tcp://localhost:{port}", "loopback"))

    # env (tu DEFAULT_URL_ENV ya tiene ctrlX-CORE / VirtualControl)
    for u in URLS_ENV:
        candidates.append((u, "env"))

    # hostnames típicos (rápido, sin red scan)
    for h in ["ctrlX-CORE", "ctrlx-core"] + [f"VirtualControl-{i}" for i in range(1, 9)]:
        candidates.append((f"opc.tcp://{h}:{port}", "known-hostname"))

    # vecinos ARP (rápido)
    # (usa tu discovery.py si quieres, pero ARP aquí también vale)
    try:
        import subprocess, re, sys
        ips = []
        if sys.platform.startswith("win"):
            out = subprocess.check_output(["arp","-a"], text=True, timeout=1.2, errors="ignore")
            ips += re.findall(r"\d+\.\d+\.\d+\.\d+", out)
        else:
            out = subprocess.check_output(["ip","neigh"], text=True, timeout=1.2, errors="ignore")
            ips += re.findall(r"\d+\.\d+\.\d+\.\d+", out)
        ips = [ip for ip in ips if not ip.startswith(("0.","127.","224.","255."))]
        for ip in ips[:60]:
            candidates.append((f"opc.tcp://{ip}:{port}", "arp"))
    except Exception:
        pass

    # deep=1 recién hace el discovery completo (incluye mDNS + scan subred)
    if deep:
        discovered = discover_opcua_urls(extra_candidates=[u for u,_ in candidates])
        for u in discovered:
            candidates.append((u, "deep-discovery"))

    # 2) dedupe por url
    seen = set()
    ordered: list[tuple[str,str]] = []
    for u, src in candidates:
        u = (u or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        ordered.append((u, src))

    # 3) probe TCP en paralelo (esto lo vuelve rápido)
    def split_host_port(url: str) -> tuple[str,int]:
        hp = url.split("://",1)[-1].split("/",1)[0]
        host = hp.split(":",1)[0]
        prt = int(hp.split(":",1)[1]) if ":" in hp else port
        return host, prt

    items = []
    with ThreadPoolExecutor(max_workers=24) as ex:
        futs = {}
        for url, src in ordered[:200]:  # límite duro, no te mates
            host, prt = split_host_port(url)
            futs[ex.submit(_tcp_ok_host_or_ip, host, prt)] = (url, host, prt, src)

        for fut in as_completed(futs):
            url, host, prt, src = futs[fut]
            try:
                ok, ip = fut.result()
            except Exception:
                ok, ip = False, None

            items.append({
                "url": url,
                "host": host,
                "ip": ip,
                "port": prt,
                "tcp_ok": bool(ok),
                "source": src,
            })

    # 4) ordenar: primero tcp_ok=True y luego por source
    prio = {"ui-host":0, "env":1, "known-hostname":2, "arp":3, "loopback":4, "deep-discovery":5}
    items.sort(key=lambda x: (not x["tcp_ok"], prio.get(x["source"], 99), x["host"]))

    return items[:max_results]

@app.post("/api/opcua/login")
def opcua_login(body: OpcuaLoginIn, request: Request):
    global CURRENT_OPCUA_USER, CURRENT_OPCUA_PASS, CURRENT_OPCUA_URL, plc

    u = body.user.strip()
    p = body.password
    if not u or not p:
        raise HTTPException(400, "Faltan credenciales")

    # ✅ MODO: el usuario eligió URL -> NO metas discovery / env / host_hdr
    if body.url and body.url.strip():
        chosen = body.url.strip()
        expanded = _unique([chosen, _normalize_to_ip(chosen)])

        winner = pick_first_alive_auth(u, p, expanded)
        if not winner:
            raise HTTPException(
                status_code=401,
                detail={"error": "No pude autenticar contra el endpoint elegido.", "tried": expanded},
            )

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

    # 👇 SOLO si NO eligió nada recién haces discovery/fallback
    candidates = []

    host_hdr = request.headers.get("host", "")
    host_only = host_hdr.split(":")[0].strip() if host_hdr else ""
    if host_only:
        candidates.append(f"opc.tcp://{host_only}:4840")

    candidates += URLS_ENV[:]
    discovered = discover_opcua_urls(extra_candidates=candidates)
    ordered = _unique(candidates + discovered)

    expanded = []
    for u0 in ordered:
        expanded.append(u0)
        u_ip = _normalize_to_ip(u0)
        if u_ip != u0:
            expanded.append(u_ip)
    expanded = _unique(expanded)

    winner = pick_first_alive_auth(u, p, expanded)
    if not winner:
        raise HTTPException(status_code=401, detail={"error": "No pude autenticar.", "tried": expanded[:30]})

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

APP_PREFIX = os.getenv("APP_PREFIX", "/api-websocket-rx")

BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
STATIC_DIR = (BASE_DIR / "frontend").resolve()

# Sirve UI dentro del prefijo del reverse proxy
app.mount(APP_PREFIX, StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")

# (Opcional) Mantén root para debug directo por :8000
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend-root")
