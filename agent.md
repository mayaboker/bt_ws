# Agent Instructions

This repository uses Python projects organized as separate packages.

When creating a new Python project:
- Create a new folder named after the package, for example `bt_example`.
- Add a `README.md`.
- Add Python source files under the package folder.
- Prefer small, focused modules.
- Add tests when behavior is non-trivial.
- Do not modify unrelated packages.

For simple packages, prefer:

```text
project_name/
├── README.md
├── pyproject.toml
├── src/
│   └── project_name/
│       └── __init__.py
└── tests/
    └── test_project_name.py