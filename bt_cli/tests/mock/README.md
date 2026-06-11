# Mock Param Server

Run the mock ZMQ REP server:

```bash
venv/bin/python bt_cli/tests/mock/mock_param_server.py
```

In another terminal, point the CLI at it:

```bash
PYTHONPATH=bt_cli venv/bin/python -m bti_cli.main param list
PYTHONPATH=bt_cli venv/bin/python -m bti_cli.main param get camera.fps
PYTHONPATH=bt_cli venv/bin/python -m bti_cli.main param set controller.kp 2.5
PYTHONPATH=bt_cli venv/bin/python -m bti_cli.main param dump
```

Use a custom endpoint when needed:

```bash
venv/bin/python bt_cli/tests/mock/mock_param_server.py --endpoint tcp://127.0.0.1:5567
PYTHONPATH=bt_cli venv/bin/python -m bti_cli.main param list --endpoint tcp://127.0.0.1:5567
```
