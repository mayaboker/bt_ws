# bt_gst Agent Rules

- All Click-specific CLI code must live in `bt_gst/cli.py`.
- Do not add `click` imports, Click decorators, or Click argument parsing to `bt_gst/main.py`.
- `cli.py` parses command-line input and returns typed command/action objects.
- `main.py` receives those command/action objects and dispatches runtime behavior.
