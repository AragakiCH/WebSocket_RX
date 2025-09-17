# launcher.py
import os, sys, copy, logging
from pathlib import Path
from frontend.app_desktop import start_gui

def _log_file() -> Path:
    base = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    log_dir = base / "PSI-Dashboard" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "server.log"

def _bootstrap_basic_logging():
    """Log de arranque ANTES de uvicorn para ver envs y errores tempranos."""
    lf = _log_file()
    logging.basicConfig(
        filename=str(lf),
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return lf

def _safe_uvicorn_log_config():
    """Tu config original, pero usando el mismo archivo de log."""
    from uvicorn.config import LOGGING_CONFIG as DEFAULT_LOGGING
    cfg = copy.deepcopy(DEFAULT_LOGGING)

    # sin colores → evitamos isatty()
    cfg["formatters"]["default"]["use_colors"] = False
    cfg["formatters"]["access"]["use_colors"]  = False

    lf = str(_log_file())
    cfg["handlers"]["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "formatter": "default",
        "filename": lf,
        "maxBytes": 1_048_576,
        "backupCount": 3,
        "encoding": "utf-8",
    }
    # manda TODOS los logs de uvicorn al archivo
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        cfg["loggers"].setdefault(name, {"handlers": ["file"], "level": "INFO", "propagate": False})
        cfg["loggers"][name]["handlers"] = ["file"]
        cfg["loggers"][name]["level"] = "INFO"
        cfg["loggers"][name]["propagate"] = False
    return cfg


def _resolve_asgi_app():
    # Si te forzaron un módulo por env, úsalo tal cual (string tipo "pkg.module:app")
    mod = os.getenv("UVICORN_MODULE")
    if mod:
        return mod

    # 1) Proyecto clásico: main.py junto a launcher.py
    try:
        from main import app as _app
        return _app
    except Exception:
        pass

    # 2) (opcional) otro layout que a veces usabas
    try:
        from main import app as _app
        return _app
    except Exception as e:
        logging.getLogger("launcher").exception("No pude importar FastAPI app", exc_info=e)
        raise

def run_server():
    import uvicorn

    lf = _bootstrap_basic_logging()
    log = logging.getLogger("launcher")

    # Dump de entorno para diagnosticar cuándo corre empaquetado
    log.info("=== PSI-Dashboard server arrancando ===")
    log.info("server.log → %s", lf)
    log.info("UVICORN_MODULE=%s", os.getenv("UVICORN_MODULE"))
    log.info("WS_HOST=%s  WS_PORT=%s", os.getenv("WS_HOST"), os.getenv("WS_PORT"))
    log.info("OPCUA_URL=%s", os.getenv("OPCUA_URL"))
    log.info("OPCUA_USER set=%s", bool(os.getenv("OPCUA_USER")))

    module = os.getenv("UVICORN_MODULE", "main:app")
    host   = os.getenv("WS_HOST", "127.0.0.1")
    port   = int(os.getenv("WS_PORT"))

    app_target = _resolve_asgi_app()

    # Arranca uvicorn con logging seguro a archivo
    uvicorn.run(
        app_target, 
        host=host,
        port=port,
        log_level="info",
        log_config=_safe_uvicorn_log_config(),
    )

def run_gui():
    start_gui()


if __name__ == "__main__":
    if "--run-server" in sys.argv:
        run_server()
    else:
        run_gui()
