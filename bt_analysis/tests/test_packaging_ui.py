from pathlib import Path

import tomllib

import bt_analysis


def test_package_declares_cli_and_static_assets():
    project_root = Path(__file__).parents[1]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text())

    assert pyproject["project"]["name"] == "bt-analysis"
    assert pyproject["project"]["scripts"]["bt-analysis"] == "bt_analysis.main:main"
    assert pyproject["tool"]["setuptools"]["package-data"]["bt_analysis"] == [
        "static/*.html",
        "static/*.css",
        "static/*.js",
    ]
    assert bt_analysis.__version__ == "0.1.0"


def test_dashboard_assets_include_interactive_graph_controls():
    static = Path(bt_analysis.__file__).with_name("static")
    html = (static / "index.html").read_text()
    javascript = (static / "app.js").read_text()

    assert 'id="chart"' in html
    assert 'id="chart-legend"' in html
    assert 'id="chart-tooltip"' in html
    assert 'id="reset-zoom"' in html
    assert 'id="data-scope"' in html
    assert 'value="through-track"' in html
    assert 'addEventListener("pointermove"' in javascript
    assert 'addEventListener("pointerdown"' in javascript
    assert 'addEventListener("pointerup"' in javascript
    assert "stateColors" in javascript
    assert "renderStateLegend" in javascript
    assert "filteredVelocityStatistics" in javascript
    assert 'state === "TRACK"' in javascript
