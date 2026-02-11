# plc/discovery.py
from __future__ import annotations
import os, re, socket, ipaddress, logging, subprocess, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, List, Tuple, Literal

log = logging.getLogger("psi.discovery")

PORT = int(os.getenv("DISCOVERY_PORT", "4840"))
TMO  = float(os.getenv("DISCOVERY_TIMEOUT_S", "0.25"))
MAX_PER_NET = int(os.getenv("DISCOVERY_MAX_HOSTS_PER_NET", "256"))
ProbeStatus = Literal["OK", "AUTH_INVALID", "DOWN"]

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


def _probe_opcua(url: str, user="", password="", timeout=2.0) -> Tuple[ProbeStatus, str]:
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
        if "BadIdentityTokenInvalid" in msg:
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

def _local_hostnames() -> list[str]:
    names = set()
    try:
        names.add(socket.gethostname())
    except Exception:
        pass
    try:
        names.add(socket.getfqdn())
    except Exception:
        pass
    # los típicos de ctrlX
    names.update(["ctrlX-CORE"])
    for i in range(1, 9):
        names.add(f"VirtualControl-{i}")
    # filtra basura
    out = []
    for n in names:
        n = (n or "").strip()
        if n and n.lower() not in ("localhost",):
            out.append(n)
    return _unique(out)

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

def _hostname_candidates() -> List[str]:
    # Hostnames típicos
    names = ["ctrlX-CORE"]
    # VirtualControl-1..4 (ajusta el rango si quieres)
    for i in range(1, 5):
        names.append(f"VirtualControl-{i}")
        names.append(f"VirtualControl {i}")  # por si alguien lo escribe así (lo normal es con guion)
    # limpia espacios (porque "VirtualControl 1" en URL es inválido sin encode)
    out = []
    for n in names:
        n2 = n.replace(" ", "-")  # IMPORTANT: en URL no metas espacios
        out.append(n2)
    return _unique(out)

def discover_opcua_urls(extra_candidates: Iterable[str] = ()) -> List[str]:
    candidates: List[str] = []

    # 0) lo que venga de afuera (prioridad alta)
    for x in extra_candidates:
        x = (x or "").strip()
        if x:
            candidates.append(x)

    # 1) hostnames conocidos + hostname real del equipo
    for h in _local_hostnames():   # aquí incluye ctrlX-CORE, VirtualControl-1..N, hostname, fqdn
        candidates.append(f"opc.tcp://{h}:{PORT}")

    # 2) loopback
    candidates += [f"opc.tcp://127.0.0.1:{PORT}", f"opc.tcp://localhost:{PORT}"]

    # 3) mDNS
    candidates += _mdns_discover()

    # 4) ARP neighbors
    candidates += [f"opc.tcp://{ip}:{PORT}" for ip in _neighbors_arp()]

    # 5) subredes
    for net in _local_networks():
        for host in _limit_hosts(net):
            candidates.append(f"opc.tcp://{host}:{PORT}")

    return _unique(candidates)


def pick_first_alive_any(ordered_urls):
    for url in ordered_urls:
        host, port = _parse_host_port_from_opcua_url(url)
        if not _probe_tcp(host, port):
            continue
        st, _ = _probe_opcua(url, user="", password="")
        if st in ("OK", "AUTH_INVALID"):
            return url
    return None

def _parse_host_port_from_opcua_url(url: str) -> Tuple[str, int]:
    x = url.split("://", 1)[-1]
    hostport = x.split("/", 1)[0]
    if ":" in hostport:
        h, p = hostport.split(":", 1)
        return h, int(p)
    return hostport, PORT

def pick_first_alive_auth(user, password, ordered_urls):
    for url in ordered_urls:
        st, info = _probe_opcua(url, user=user, password=password)
        if st == "OK":
            return url
    return None