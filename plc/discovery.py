from __future__ import annotations
import os, re, socket, ipaddress, logging, subprocess, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, List, Tuple, Literal

log = logging.getLogger("psi.discovery")

PORT = int(os.getenv("DISCOVERY_PORT", "4840"))
TCP_TMO  = float(os.getenv("DISCOVERY_TCP_TIMEOUT_S", "0.25"))
OPC_TMO  = float(os.getenv("DISCOVERY_OPC_TIMEOUT_S", "2.5"))
MAX_PER_NET = int(os.getenv("DISCOVERY_MAX_HOSTS_PER_NET", "256"))

ProbeStatus = Literal["OK", "AUTH_INVALID", "DOWN"]

def _unique(seq: Iterable[str]) -> List[str]:
    seen = set(); out = []
    for x in seq:
        x = (x or "").strip()
        if not x: 
            continue
        if x not in seen:
            seen.add(x); out.append(x)
    return out

def _probe_tcp_host(host: str, port: int = PORT, timeout: float = TCP_TMO) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def _probe_opcua(url: str, user="", password="", timeout=OPC_TMO) -> Tuple[ProbeStatus, str]:
    from opcua import Client
    try:
        c = Client(url, timeout=timeout)
        if user:
            c.set_user(user)
            c.set_password(password)
        c.connect()
        c.disconnect()
        return "OK", ""
    except Exception as e:
        msg = repr(e)
        if "BadIdentityTokenInvalid" in msg or "BadUserAccessDenied" in msg:
            return "AUTH_INVALID", msg
        return "DOWN", msg

def _cidrs_from_env() -> List[ipaddress.IPv4Network]:
    out = []
    raw = os.getenv("DISCOVERY_CIDRS", "")
    for part in [p.strip() for p in raw.split(",") if p.strip()]:
        try:
            out.append(ipaddress.IPv4Network(part, strict=False))
        except Exception:
            log.warning("CIDR inválido ignorado: %s", part)
    return out

def _local_networks() -> List[ipaddress.IPv4Network]:
    nets = set()
    # intenta via psutil
    try:
        import psutil
        for _, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and a.address and a.netmask:
                    try:
                        iface = ipaddress.IPv4Interface(f"{a.address}/{a.netmask}")
                        # evita loopback
                        if str(iface.ip).startswith("127."):
                            continue
                        nets.add(iface.network)
                    except Exception:
                        pass
    except Exception:
        pass

    nets.update(_cidrs_from_env())
    # si no encontró nada, fallback a /24 “típico” de tu IP (si existe)
    return list(nets)

def _neighbors_arp() -> List[str]:
    ips: List[str] = []
    try:
        if sys.platform.startswith("win"):
            out = subprocess.check_output(["arp","-a"], text=True, timeout=2.0, errors="ignore")
            ips += re.findall(r"\d+\.\d+\.\d+\.\d+", out)
        else:
            for cmd in (["ip","neigh"], ["arp","-an"]):
                try:
                    out = subprocess.check_output(cmd, text=True, timeout=2.0, errors="ignore")
                    ips += re.findall(r"\d+\.\d+\.\d+\.\d+", out)
                    break
                except Exception:
                    continue
    except Exception:
        pass
    ips = [ip for ip in ips if not ip.startswith(("0.","127.","224.","255."))]
    return _unique(ips)

def _mdns_discover(timeout: float = 1.5) -> List[str]:
    urls: List[str] = []
    try:
        from zeroconf import Zeroconf, ServiceBrowser
    except Exception:
        return urls

    class _L:
        def __init__(self): pass
        def add_service(self, zc, type_, name):
            try:
                info = zc.get_service_info(type_, name)
                if not info: return
                port = info.port or PORT
                addrs = [socket.inet_ntoa(a) for a in (info.addresses or [])]
                # algunos anuncian hostname en server
                if info.server:
                    hn = info.server.rstrip(".")
                    urls.append(f"opc.tcp://{hn}:{port}")
                for a in addrs:
                    urls.append(f"opc.tcp://{a}:{port}")
            except Exception:
                pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, "_opcua-tcp._tcp.local.", _L())
        import time; time.sleep(timeout)
    finally:
        zc.close()
    return _unique(urls)

def _limit_hosts(net: ipaddress.IPv4Network) -> Iterable[str]:
    # samplea como máximo MAX_PER_NET hosts
    hosts = list(net.hosts())
    if not hosts:
        return []
    if len(hosts) <= MAX_PER_NET:
        return (str(h) for h in hosts)
    step = max(1, len(hosts) // MAX_PER_NET)
    return (str(hosts[i]) for i in range(0, len(hosts), step))

def _hostname_candidates() -> List[str]:
    # “comunes”, pero no dependes de ellos
    max_vc = int(os.getenv("DISCOVERY_VIRTUALCONTROL_MAX", "8"))
    out = ["ctrlX-CORE", "ctrlx-core", "localhost"]
    out += [f"VirtualControl-{i}" for i in range(1, max_vc+1)]
    out += [f"VirtualControl-{i}".lower() for i in range(1, max_vc+1)]
    return _unique(out)

def discover_opcua_urls(extra_candidates: Iterable[str] = ()) -> List[str]:
    candidates: List[str] = []

    # 0) los que te pasen
    for x in extra_candidates:
        if x and x.strip():
            candidates.append(x.strip())

    # 1) hostnames comunes
    for h in _hostname_candidates():
        candidates.append(f"opc.tcp://{h}:{PORT}")

    # 2) loopback
    candidates += [f"opc.tcp://127.0.0.1:{PORT}", f"opc.tcp://localhost:{PORT}"]

    # 3) mDNS
    candidates += _mdns_discover()

    # 4) vecinos ARP (rápido)
    for ip in _neighbors_arp():
        candidates.append(f"opc.tcp://{ip}:{PORT}")

    # 5) scan subredes locales, pero limitado
    for net in _local_networks():
        for host in _limit_hosts(net):
            candidates.append(f"opc.tcp://{host}:{PORT}")

    return _unique(candidates)

def pick_first_alive_any(urls: Iterable[str]) -> str | None:
    urls = list(_unique(urls))
    # filtro TCP rápido
    fast = []
    for u in urls:
        host = u.split("://",1)[-1].split(":",1)[0].split("/",1)[0]
        if _probe_tcp_host(host):
            fast.append(u)
    # prueba OPC UA sin auth (acepta AUTH_INVALID como “vive”)
    for u in fast:
        st, _ = _probe_opcua(u)
        if st in ("OK", "AUTH_INVALID"):
            return u
    return None

def pick_first_alive_auth(user: str, password: str, urls: Iterable[str]) -> str | None:
    urls = list(_unique(urls))
    # filtro TCP rápido
    fast = []
    for u in urls:
        host = u.split("://",1)[-1].split(":",1)[0].split("/",1)[0]
        if _probe_tcp_host(host):
            fast.append(u)
    for u in fast:
        st, _ = _probe_opcua(u, user=user, password=password)
        if st == "OK":
            return u
    return None
