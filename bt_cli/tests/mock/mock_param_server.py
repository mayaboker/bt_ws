from __future__ import annotations

import argparse
import json
from typing import Any

import zmq


PARAMS: dict[str, Any] = {
    "camera.fps": 30,
    "camera.width": 1280,
    "camera.height": 720,
    "controller.kp": 1.0,
    "controller.ki": 0.0,
    "controller.kd": 0.1,
}


def parse_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def handle_param_request(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action == "list":
        return {"ok": True, "result": sorted(PARAMS)}

    if action == "dump":
        return {"ok": True, "result": PARAMS}

    if action == "get":
        name = params.get("name")
        if name not in PARAMS:
            return {"ok": False, "error": f"Unknown parameter: {name}"}
        return {"ok": True, "result": PARAMS[name]}

    if action == "set":
        name = params.get("name")
        value = params.get("value")
        if not name:
            return {"ok": False, "error": "Missing parameter name"}

        PARAMS[name] = parse_value(value)
        return {"ok": True, "result": {"name": name, "value": PARAMS[name]}}

    return {"ok": False, "error": f"Unsupported param action: {action}"}


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    namespace = request.get("namespace")
    action = request.get("action")
    params = request.get("params") or {}

    if namespace != "param":
        return {"ok": False, "error": f"Unsupported namespace: {namespace}"}

    if not isinstance(params, dict):
        return {"ok": False, "error": "Request params must be an object"}

    return handle_param_request(str(action), params)


def serve(endpoint: str) -> None:
    context = zmq.Context.instance()
    socket = context.socket(zmq.REP)
    socket.bind(endpoint)

    print(f"Mock param server listening on {endpoint}", flush=True)

    try:
        while True:
            request = socket.recv_json()
            print(f"request: {request}", flush=True)
            response = handle_request(request)
            print(f"response: {response}", flush=True)
            socket.send_json(response)
    except KeyboardInterrupt:
        print("\nMock param server stopped", flush=True)
    finally:
        socket.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock BTI param ZMQ server")
    parser.add_argument(
        "--endpoint",
        default="tcp://127.0.0.1:5555",
        help="ZMQ REP bind endpoint",
    )
    args = parser.parse_args()

    serve(args.endpoint)


if __name__ == "__main__":
    main()
