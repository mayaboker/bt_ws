#!/usr/bin/env python3
from __future__ import annotations

import argparse
import keyword
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "bt_app" / "config" / "parameters.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "bt_app" / "bt_app" / "parameters" / "generated"

TYPE_MAP = {
    "bool": "bool",
    "float": "float",
    "int": "int",
    "str": "str",
}


def load_parameters(path: Path) -> dict[str, dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    raw_parameters = config.get("parameters", config)
    if not isinstance(raw_parameters, dict):
        raise ValueError("Parameter YAML must contain a mapping")

    parameters: dict[str, dict[str, Any]] = {}
    for name, definition in raw_parameters.items():
        if not isinstance(name, str):
            raise ValueError(f"Parameter name must be a string: {name!r}")
        if not isinstance(definition, dict):
            raise ValueError(f"Parameter {name!r} definition must be a mapping")
        if "type" not in definition:
            raise ValueError(f"Parameter {name!r} is missing type")
        if "default" not in definition:
            raise ValueError(f"Parameter {name!r} is missing default")
        parameters[name] = definition

    return parameters


def constant_name(parameter_name: str) -> str:
    name = re.sub(r"[^0-9A-Za-z]+", "_", parameter_name).strip("_").upper()
    if not name:
        raise ValueError(f"Cannot build constant name for parameter {parameter_name!r}")
    if name[0].isdigit():
        name = f"PARAM_{name}"
    return name


def attribute_name(parameter_name: str) -> str:
    name = re.sub(r"[^0-9A-Za-z]+", "_", parameter_name).strip("_").lower()
    if not name:
        raise ValueError(f"Cannot build attribute name for parameter {parameter_name!r}")
    if name[0].isdigit():
        name = f"param_{name}"
    if keyword.iskeyword(name):
        name = f"{name}_"
    return name


def python_type(parameter_name: str, definition: dict[str, Any]) -> str:
    configured_type = definition["type"]
    if configured_type not in TYPE_MAP:
        supported = ", ".join(sorted(TYPE_MAP))
        raise ValueError(
            f"{parameter_name!r} has unsupported type {configured_type!r}. "
            f"Supported types: {supported}"
        )

    limits = definition.get("limits")
    options = limits.get("options") if isinstance(limits, dict) else None
    if configured_type == "str" and isinstance(options, list) and options:
        literal_values = ", ".join(repr(str(option)) for option in options)
        return f"Literal[{literal_values}]"

    return TYPE_MAP[configured_type]


def check_unique_names(parameters: dict[str, dict[str, Any]]) -> None:
    constants: dict[str, str] = {}
    attributes: dict[str, str] = {}
    for parameter_name in parameters:
        const = constant_name(parameter_name)
        attr = attribute_name(parameter_name)
        if const in constants:
            raise ValueError(
                f"Constant name collision: {constants[const]!r} and "
                f"{parameter_name!r} both become {const}"
            )
        if attr in attributes:
            raise ValueError(
                f"Attribute name collision: {attributes[attr]!r} and "
                f"{parameter_name!r} both become {attr}"
            )
        constants[const] = parameter_name
        attributes[attr] = parameter_name


def render_keys(parameters: dict[str, dict[str, Any]], source: Path) -> str:
    lines = [
        '"""Auto-generated parameter key constants."""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Final, Literal",
        "",
        "",
        "class ParameterKey:",
        f"    \"\"\"Parameter keys generated from {source.as_posix()}.\"\"\"",
    ]

    for name in sorted(parameters):
        const = constant_name(name)
        lines.append(f"    {const}: Final[Literal[{name!r}]] = {name!r}")

    lines.append("")
    lines.append("")
    lines.append("ALL_PARAMETER_KEYS: Final[tuple[str, ...]] = (")
    for name in sorted(parameters):
        lines.append(f"    {name!r},")
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


def render_typed(parameters: dict[str, dict[str, Any]], source: Path) -> str:
    lines = [
        '"""Auto-generated typed parameter accessors."""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any, Literal, Protocol, cast",
        "",
        "from bt_app.parameters.generated.keys import ParameterKey",
        "",
        "",
        "class SupportsParameterGet(Protocol):",
        "    def get(self, name: str) -> Any:",
        "        ...",
        "",
        "",
        "class TypedParameters:",
        f"    \"\"\"Typed parameter accessors generated from {source.as_posix()}.\"\"\"",
        "",
        "    def __init__(self, parameters: SupportsParameterGet) -> None:",
        "        self._parameters = parameters",
    ]

    for name in sorted(parameters):
        attr = attribute_name(name)
        const = constant_name(name)
        typ = python_type(name, parameters[name])
        lines.extend(
            [
                "",
                "    @property",
                f"    def {attr}(self) -> {typ}:",
                f"        return cast({typ}, self._parameters.get(ParameterKey.{const}))",
            ]
        )

    lines.append("")
    return "\n".join(lines)


def render_init() -> str:
    return "\n".join(
        [
            '"""Generated parameter typing helpers."""',
            "",
            "from bt_app.parameters.generated.keys import ALL_PARAMETER_KEYS, ParameterKey",
            "from bt_app.parameters.generated.typed import TypedParameters",
            "",
            "__all__ = [",
            '    "ALL_PARAMETER_KEYS",',
            '    "ParameterKey",',
            '    "TypedParameters",',
            "]",
            "",
        ]
    )


def write_if_changed(path: Path, content: str) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def generate(input_path: Path, output_dir: Path) -> list[Path]:
    parameters = load_parameters(input_path)
    check_unique_names(parameters)

    generated = {
        output_dir / "__init__.py": render_init(),
        output_dir / "keys.py": render_keys(parameters, input_path.relative_to(ROOT)),
        output_dir / "typed.py": render_typed(parameters, input_path.relative_to(ROOT)),
    }

    changed: list[Path] = []
    for path, content in generated.items():
        if write_if_changed(path, content):
            changed.append(path)

    return changed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate typed parameter helpers")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    changed = generate(args.input, args.output_dir)
    if changed:
        for path in changed:
            print(f"generated {path.relative_to(ROOT)}")
    else:
        print("parameter generated files are up to date")


if __name__ == "__main__":
    main()
