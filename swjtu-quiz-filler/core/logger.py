import threading
from datetime import datetime
from typing import Callable


class AppLogger:
    def __init__(self, on_log: Callable[[str], None]):
        self._on_log = on_log
        self._lock = threading.Lock()

    def info(self, message: str) -> None:
        self._emit('INFO', message)

    def warn(self, message: str) -> None:
        self._emit('WARN', message)

    def error(self, message: str) -> None:
        self._emit('ERROR', message)

    def _emit(self, level: str, message: str) -> None:
        with self._lock:
            ts = datetime.now().strftime('%H:%M:%S')
            self._on_log(f'[{ts}] [{level}] {message}')
