from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from .models import RandomDataModel
from .presenters import MainPresenter
from .services import RandomDataService
from .views import MainView


class App:
    def __init__(self) -> None:
        self.qt_app = QApplication(sys.argv)
        self.model = RandomDataModel()
        self.service = RandomDataService(self.model)
        self.view = MainView()
        self.presenter = MainPresenter(self.model, self.service, self.view)
        self.qt_app.aboutToQuit.connect(self.presenter.stop)

    def run(self) -> int:
        self.view.show()
        self.presenter.start()
        return self.qt_app.exec()
