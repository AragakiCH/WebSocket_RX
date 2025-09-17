# plc/discovery.py
from __future__ import annotations
import os, re, socket, ipaddress, logging, subprocess, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, List, Tuple

log = logging.getLogger("psi.discovery")

PORT = int(os.getenv("DISCOVERY_PORT", "4840"))
TMO  = float(os.getenv("DISCOVERY_TIMEOUT_S", "0.25"))
MAX_PER_NET = int(os.getenv("DISCOVERY_MAX_HOSTS_PER_NET", "256"))

def _unique(seq: Iterable[str]) -> List[str]:
    seen = set(); out = []
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

def _probe_tcp(host: str, port: int = PORT, timeout: float = TMO) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            return True
    except Exception:
        return False

def _probe_opcua(url: str, user: str = "", password: str = "", timeout: float = 2.0) -> Tuple[bool, str]:
    host = url.split("://", 1)[-1].split(":")[0]
    try:
        from opcua import Client
    except Exception:
        return (_probe_tcp(host, PORT, timeout), "")
    try:
        c = Client(url, timeout=timeout)
        if user:
            c.set_user(user); c.set_password(password)
        c.connect()
        app_name = ""
        try:
            eps = c.get_endpoints() or []
            if eps and getattr(eps[0].Server.ApplicationName, "Text", ""):
                app_name = eps[0].Server.ApplicationName.Text
        finally:
            c.disconnect()
        return (True, app_name)
    except Exception:
        return (False, "")

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
    try:
        import psutil
        for _, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and a.address and a.netmask:
                    try:
                        iface = ipaddress.IPv4Interface(f"{a.address}/{a.netmask}")
                        nets.add(iface.network)
                    except Exception:
                        pass
    except Exception:
        # Sin psutil no adivinamos redes; que el usuario use DISCOVERY_CIDRS
        pass
    nets.update(_cidrs_from_env())
    return list(nets)

def _neighbors_arp() -> List[str]:
    """IPs vecinas vistas en ARP (rápido)."""
    ips: List[str] = []
    try:
        if sys.platform.startswith("win"):
            out = subprocess.check_output(["arp","-a"], text=True, timeout=1.5, errors="ignore")
            ips += re.findall(r"\d+\.\d+\.\d+\.\d+", out)
        else:
            # Linux/macOS
            for cmd in (["ip","neigh"], ["arp","-an"]):
                try:
                    out = subprocess.check_output(cmd, text=True, timeout=1.5, errors="ignore")
                    ips += re.findall(r"\d+\.\d+\.\d+\.\d+", out)
                    break
                except Exception:
                    continue
    except Exception:
        pass
    # filtra locales
    ips = [ip for ip in ips if not ip.startswith(("0.","127.","224.","255."))]
    return _unique(ips)

def _mdns_discover(timeout: float = 1.5) -> List[str]:
    urls: List[str] = []
    try:
        from zeroconf import Zeroconf, ServiceBrowser
    except Exception:
        return urls
    class _L:
        def __init__(self): self.urls=[]
        def add_service(self, zc, type_, name):
            try:
                info = zc.get_service_info(type_, name)
                if not info: return
                addrs = [socket.inet_ntoa(a) for a in info.addresses]
                for a in addrs:
                    urls.append(f"opc.tcp://{a}:{info.port}")
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
    """Devuelve hasta MAX_PER_NET hosts del net (espaciados si la red es grande)."""
    total = net.num_addresses - 2 if net.prefixlen <= 30 else max(0, net.num_addresses)
    if total <= 0:
        return []
    step = max(1, total // MAX_PER_NET)
    i = 0
    for host in net.hosts():
        if i % step == 0:
            yield str(host)
        i += 1

def discover_opcua_urls(extra_candidates: Iterable[str] = ()) -> List[str]:
    candidates: List[str] = []

    # Siempre probamos localhost primero (COREvirtual)
    candidates += [f"opc.tcp://127.0.0.1:{PORT}", f"opc.tcp://localhost:{PORT}"]

    # 1) Candidatos del usuario (ENV) tienen prioridad absoluta
    for x in extra_candidates:
        if x.strip():
            candidates.append(x.strip())

    # 2) mDNS (si existe)
    candidates += _mdns_discover()

    # 3) Vecinos ARP (muy rápido)
    arp_ips = _neighbors_arp()
    candidates += [f"opc.tcp://{ip}:{PORT}" for ip in arp_ips]

    # 4) Subredes locales (psutil + ENV), limitando hosts para no morir en /16 o /12
    nets = _local_networks()
    pool = ThreadPoolExecutor(max_workers=256)
    futures = { pool.submit(_probe_tcp, ip, PORT, TMO): ip
                for net in nets for ip in _limit_hosts(net) }
    hits = []
    for fut in as_completed(futures):
        try:
            ok = fut.result()
            if ok:
                hits.append(futures[fut])
        except Exception:
            pass
    pool.shutdown(wait=True)
    candidates += [f"opc.tcp://{ip}:{PORT}" for ip in hits]

    return _unique(candidates)

def pick_first_alive(user: str = "", password: str = "", ordered_urls: Iterable[str] = ()) -> Tuple[str|None, List[str]]:
    urls = list(ordered_urls)
    for url in urls:
        ok, app = _probe_opcua(url, user, password, timeout=2.0)
        log.info("Probe %s -> %s %s", url, "OK" if ok else "FAIL", f"({app})" if app else "")
        if ok:
            return url, urls
    return None, urls
