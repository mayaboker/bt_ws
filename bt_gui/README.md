# BT GUI

PyQt6 MVP application with three vertically stacked text boxes. A background service generates random data and updates the UI through a pure model plus Qt presenter bridge.

Package layout:

```text
bt_gui/
  bt_gui/
    models/
    services/
    views/
    presenters/
  tests/
```

Run from the workspace root:

```bash
venv/bin/python bt_gui/main.py
```

Run tests:

```bash
PYTHONPATH=bt_gui venv/bin/python -m unittest discover -s bt_gui/tests
```
