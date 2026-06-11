from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from bt_gui.models import RandomDataModel
from bt_gui.services import RandomDataService
from bt_gui.views import MainView


class MainPresenter(QObject):
    values_changed = pyqtSignal(object)

    def __init__(self, model: RandomDataModel, service: RandomDataService, view: MainView) -> None:
        super().__init__()
        self._model = model
        self._service = service
        self._view = view

        self._model.values_changed.subscribe(self._on_model_values_changed)
        self.values_changed.connect(self._on_model_values_changed_qt)
        self._view.closing.connect(self.stop)

    def start(self) -> None:
        self._service.start()

    @pyqtSlot()
    def stop(self) -> None:
        self._service.stop()

    def _on_model_values_changed(self, values: tuple[str, str, str]) -> None:
        self.values_changed.emit(values)

    @pyqtSlot(object)
    def _on_model_values_changed_qt(self, values: tuple[str, str, str]) -> None:
        self._view.set_values(values)

