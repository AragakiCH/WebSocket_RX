# plc/buffer.py
import threading
from collections import deque

class DataBuffer:
    def __init__(self, maxlen=5000):
        self._lock = threading.Lock()
        self._dq = deque(maxlen=maxlen)
        self._seq = 0

    def append(self, sample: dict) -> int:
        with self._lock:
            self._seq += 1
            s = dict(sample)
            s["__seq__"] = self._seq
            self._dq.append(s)
            return self._seq

    def latest(self):
        with self._lock:
            return self._dq[-1] if self._dq else None

    def after(self, last_seq: int | None) -> list[dict]:
        with self._lock:
            if last_seq is None:
                return list(self._dq)
            return [s for s in self._dq if s.get("__seq__", 0) > last_seq]

    def __len__(self):
        with self._lock:
            return len(self._dq)

    def clear(self):
        with self._lock:
            self._dq.clear()

data_buffer = DataBuffer(maxlen=5000)
