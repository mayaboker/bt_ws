# SKILL: PyQt MVP with Service + Pure Model + Qt Bridge

## Purpose

Generate a PyQt application using a strict MVP architecture with:

* Pure Python Model (no Qt)
* Service layer (data producers, threads, ROS, IO)
* Python event system (no Qt in model)
* Presenter as the ONLY Qt bridge
* Thread-safe UI updates via Qt signals
* Dedicated package folders for models, services, views, presenters, and tests

---

## Architecture Overview

```
Service (thread)
    ↓
Model (pure Python)
    ↓
Python Event (callback)
    ↓
Presenter (bridge)
    ↓
Qt Signal
    ↓
Qt Slot (main thread)
    ↓
View (UI)
```

---

## Rules

### 0. Project Layout (REQUIRED)

Always create a dedicated folder for each architectural type:

```text
project_root/
  app_package/
    __init__.py
    app.py                  # composition root
    models/
      __init__.py           # Event class lives here
      x_model.py
    services/
      __init__.py
      x_service.py
    views/
      __init__.py
      x_view.py
    presenters/
      __init__.py
      x_presenter.py
  tests/
    __init__.py
    mock_data.py            # generated / mocked model data
    test_x_model.py
```

Rules:

* Do NOT place `model.py`, `service.py`, `view.py`, or `presenter.py` directly in the app package root.
* Use plural folder names: `models`, `services`, `views`, `presenters`.
* Keep `app.py` as the composition root that wires all objects together.
* Tests must be outside the runtime package in a top-level `tests/` folder.

### 1. Model (STRICT)

* Must NOT import Qt
* Must NOT use pyqtSignal / QObject
* Must use pure Python (dataclass preferred)
* Must expose events using a custom Event class
* Model files must live under `models/`
* Models import `Event` from their own package: `from . import Event`

Example:

```python
from dataclasses import dataclass, field

from . import Event


@dataclass
class Model:
    value: int = 0
    value_changed: Event = field(default_factory=Event)
```

---

### 2. Event System (REQUIRED)

Implement the shared Python callback system in `models/__init__.py`.

Example:

```python
from collections.abc import Callable
from threading import Lock
from typing import Generic, TypeVar


T = TypeVar("T")


class Event(Generic[T]):
    def __init__(self) -> None:
        self._subs: list[Callable[[T], None]] = []
        self._lock = Lock()

    def subscribe(self, cb: Callable[[T], None]) -> None:
        with self._lock:
            self._subs.append(cb)

    def emit(self, value: T) -> None:
        with self._lock:
            subscribers = tuple(self._subs)

        for cb in subscribers:
            cb(value)
```

Minimal form:

```python
class Event:
    def __init__(self):
        self._subs = []

    def subscribe(self, cb):
        self._subs.append(cb)

    def emit(self, value):
        for cb in self._subs:
            cb(value)
```

---

### 3. Service (STRICT)

* Must NOT import Qt
* Responsible for:

  * Threads / IO / ROS / external data
* Must update model only
* Must NOT touch View
* Must NOT emit Qt signals
* Service files must live under `services/`
* Services may provide deterministic helper methods such as `generate_once()` to support tests

Example:

```python
class Service:
    def __init__(self, model):
        self.model = model

    def run(self):
        self.model.set_value(new_value)
```

---

### 4. View (STRICT)

* Only Qt widgets
* No logic
* No model access
* Expose user actions via Qt signals
* View files must live under `views/`

Example:

```python
class View(QWidget):
    clicked = pyqtSignal()

    def set_value(self, v):
        self.label.setText(str(v))
```

---

### 5. Presenter (CRITICAL COMPONENT)

Responsibilities:

* Connect View ↔ Service
* Subscribe to Model events (Python callbacks)
* Convert Python callbacks → Qt signals
* Update View ONLY inside Qt slot
* Presenter files must live under `presenters/`

Pattern:

```python
class Presenter(QObject):
    model_signal = pyqtSignal(int)

    def __init__(self, model, service, view):
        super().__init__()

        self.model = model
        self.service = service
        self.view = view

        # Python callback
        self.model.value_changed.subscribe(self._on_model_changed)

        # Qt bridge
        self.model_signal.connect(self._on_model_changed_qt)

    def _on_model_changed(self, value):
        # MAY BE FROM ANY THREAD
        self.model_signal.emit(value)

    @pyqtSlot(int)
    def _on_model_changed_qt(self, value):
        # SAFE UI UPDATE
        self.view.set_value(value)
```

---

### 6. Thread Safety (MANDATORY RULE)

NEVER update UI from:

* service
* model
* python callback

ALWAYS use:

```
callback → pyqtSignal → pyqtSlot → UI
```

---

### 7. Composition Root

All objects must be created in one place:

```python
class App:
    def __init__(self):
        self.model = Model()
        self.service = Service(self.model)
        self.view = View()
        self.presenter = Presenter(self.model, self.service, self.view)
```

Rules:

* Keep references to presenters
* Do not create objects inside other classes implicitly
* Import models, services, views, and presenters from their dedicated packages

---

### 8. Data Flow Rules

* Service updates Model
* Model emits Python event
* Presenter listens
* Presenter emits Qt signal
* Presenter updates View

NO shortcuts allowed.

---

### 9. Forbidden Patterns

❌ Model inherits QObject
❌ Service uses Qt
❌ View accesses Model directly
❌ Presenter polls Model
❌ UI updated from background thread

---

### 10. Extensions

When generating advanced code, support:

* multiple services
* multiple presenters
* shared model
* background threads
* ROS / sockets / file IO

---

### 11. Tests + Mock Data (REQUIRED)

Every generated app must include a top-level `tests/` folder.

Required test files:

```text
tests/
  __init__.py
  mock_data.py
  test_x_model.py
```

Rules:

* `tests/mock_data.py` contains generated or mocked data for models.
* Model tests must verify that mocked data is stored correctly.
* Model tests must verify that model events emit mocked data.
* Test code must not import Qt unless it is specifically testing a view or presenter.
* Prefer pure model tests first because they are fast and do not require a display server.
* Use standard-library `unittest` unless the project already has a configured test runner.

Example:

```python
# tests/mock_data.py
MOCK_VALUES = ("one", "two", "three")


def make_values():
    return MOCK_VALUES
```

```python
import unittest

from app_package.models import XModel

from mock_data import make_values


class TestXModel(unittest.TestCase):
    def test_model_stores_mock_values(self):
        model = XModel()
        values = make_values()

        model.set_values(values)

        self.assertEqual(model.values(), values)
```

---

## Output Requirements

When generating code:

* Always include:

  * Event class
  * Model
  * Service
  * View
  * Presenter
  * Main / composition root
  * Tests folder
  * Mock model data
* Keep files modular using the required folder layout
* Use clear naming: `XModel`, `XService`, `XView`, `XPresenter`

---

## Goal

Produce scalable, thread-safe UI architecture suitable for:

* robotics dashboards
* streaming data visualization
* real-time monitoring systems
