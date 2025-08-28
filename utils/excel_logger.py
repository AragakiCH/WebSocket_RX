# utils/excel_logger.py
import os, json, time, queue, threading
from datetime import datetime
from openpyxl import Workbook, load_workbook

def _flatten(obj, prefix="", out=None):
    if out is None: out = {}
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            _flatten(v, key, out)
        else:
            out[key] = v
    return out

class ExcelLogger(threading.Thread):
    """
    Consume muestras desde una Queue y las guarda en Excel:
      - raw:  [timestamp, json]
      - flat: columnas dinámicas (aplanadas)
    """
    def __init__(self, q: queue.Queue,
                 path_template: str = "logs/ws_{date}.xlsx",
                 flush_every: int = 20,         # cuántas muestras por flush
                 flush_interval: float = 0.5):  # o cada X segundos
        super().__init__(daemon=True)
        self.q = q
        self.path_template = path_template
        self.flush_every = flush_every
        self.flush_interval = flush_interval
        self._stop = threading.Event()
        self._wb = None
        self._path = None
        self._header = []  # header de la hoja flat (orden de columnas)

    def stop(self):
        self._stop.set()

    def run(self):
        batch = []
        last = time.time()
        while not self._stop.is_set():
            try:
                item = self.q.get(timeout=0.25)
                batch.append(item)
                if len(batch) >= self.flush_every or (time.time() - last) >= self.flush_interval:
                    self._flush(batch)
                    batch.clear()
                    last = time.time()
            except queue.Empty:
                if batch and (time.time() - last) >= self.flush_interval:
                    self._flush(batch)
                    batch.clear()
                    last = time.time()
        # flush final
        if batch:
            self._flush(batch)
        if self._wb:
            self._wb.save(self._path)

    # --- internos ---
    def _ensure_workbook(self):
        date = datetime.now().strftime("%Y-%m-%d")
        path = self.path_template.format(date=date)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        if self._wb is None or self._path != path:
            # rotación diaria
            if self._wb:
                self._wb.save(self._path)

            if os.path.exists(path):
                self._wb = load_workbook(path)
                # header de flat desde la primera fila
                if "flat" in self._wb.sheetnames and self._wb["flat"].max_row >= 1:
                    self._header = [c.value for c in self._wb["flat"][1]]
            else:
                self._wb = Workbook()
                ws_raw = self._wb.active
                ws_raw.title = "raw"
                ws_raw.append(["timestamp", "json"])
                ws_flat = self._wb.create_sheet("flat")
                self._header = ["timestamp"]
                ws_flat.append(self._header)

            self._path = path

        # asegúrate de que existan las hojas
        if "raw" not in self._wb.sheetnames:
            self._wb.create_sheet("raw")
            self._wb["raw"].append(["timestamp", "json"])
        if "flat" not in self._wb.sheetnames:
            self._wb.create_sheet("flat")
            self._header = ["timestamp"]
            self._wb["flat"].append(self._header)

    def _flush(self, batch):
        self._ensure_workbook()
        ws_raw = self._wb["raw"]
        ws_flat = self._wb["flat"]

        # si abrimos un archivo existente y no tenemos header en memoria
        if not self._header and ws_flat.max_row >= 1:
            self._header = [c.value for c in ws_flat[1]]
            if not self._header:
                self._header = ["timestamp"]

        header_changed = False

        for sample in batch:
            ts = sample.get("timestamp", time.time())
            # 1) RAW
            ws_raw.append([ts, json.dumps(sample, ensure_ascii=False, separators=(",", ":"))])

            # 2) FLAT
            flat = _flatten(sample)
            if "timestamp" not in flat:
                flat["timestamp"] = ts

            # agrega nuevas columnas si aparecen
            for key in flat.keys():
                if key not in self._header:
                    self._header.append(key)
                    header_changed = True

            if header_changed:
                # reescribe header (fila 1)
                for idx, key in enumerate(self._header, start=1):
                    ws_flat.cell(row=1, column=idx, value=key)
                header_changed = False

            row = [flat.get(col, None) for col in self._header]
            ws_flat.append(row)

        self._wb.save(self._path)