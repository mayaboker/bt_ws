from __future__ import annotations

import random
import threading

from bt_gui.models import RandomDataModel


class RandomDataService:
    def __init__(self, model: RandomDataModel, interval_sec: float = 1.0) -> None:
        self._model = model
        self._interval_sec = interval_sec
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="random-data-service", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def generate_once(self) -> tuple[str, str, str]:
        values = (
            f"Altitude: {random.uniform(0.0, 120.0):06.2f} m",
            f"Speed: {random.uniform(0.0, 35.0):05.2f} m/s",
            f"Battery: {random.randint(0, 100):03d} %",
        )
        self._model.set_values(values)
        return values

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.generate_once()
            self._stop_event.wait(self._interval_sec)

