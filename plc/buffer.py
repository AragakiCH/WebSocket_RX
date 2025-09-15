# plc/buffer.py
import threading
from collections import deque

class DataBuffer:
    """
    Buffer thread-safe compatible con el uso típico de lista:
      - append(sample)
      - len(buffer)
      - pop(0)  (para podar el más viejo)
    Y además:
      - latest()  -> último sample (o None)
      - clear(), iteración segura
    """
    def __init__(self, maxlen=None):
        self._lock = threading.Lock()
        self._dq = deque(maxlen=maxlen)  # maxlen opcional; si None, sin límite

    def append(self, sample: dict):
        with self._lock:
            self._dq.append(sample)

    def latest(self):
        with self._lock:
            return self._dq[-1] if self._dq else None

    def __len__(self):
        with self._lock:
            return len(self._dq)

    def pop(self, idx=-1):
        """Soporta pop() y pop(0). Para otros índices, simula removiendo ese elemento."""
        with self._lock:
            if not self._dq:
                raise IndexError("pop from an empty buffer")
            if idx == -1:
                return self._dq.pop()
            if idx == 0:
                return self._dq.popleft()
            # pop(index) genérico
            n = len(self._dq)
            if idx < 0:
                idx += n
            if idx < 0 or idx >= n:
                raise IndexError("pop index out of range")
            self._dq.rotate(-idx)
            item = self._dq.popleft()
            self._dq.rotate(idx)
            return item

    def clear(self):
        with self._lock:
            self._dq.clear()

    def __iter__(self):
        # devuelve una copia segura para iterar
        with self._lock:
            return iter(list(self._dq))

# instancia global
data_buffer = DataBuffer()
