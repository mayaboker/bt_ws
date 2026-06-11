import socket
import json
import time
import math

HOST = "127.0.0.1"
PORT = 9870

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.connect((HOST, PORT))

t0 = time.time()

while True:
    t = time.time() - t0

    msg = {
        "timestamp": t,
        "drone": {
            "attitude": {
                "roll": 0.1 * math.sin(t),
                "pitch": 0.2 * math.sin(t),
                "yaw": 0.3 * math.sin(t),
            },
            "position": {
                "x": 1.0 * t,
                "y": 0.2 * math.sin(t),
                "z": 5.0,
            },
            "velocity": {
                "x": 1.0,
                "y": 0.0,
                "z": 0.0,
            },
        },
        "motors": {
            "m1": 0.50,
            "m2": 0.52,
            "m3": 0.49,
            "m4": 0.51,
        },
        "controller": {
            "target": {
                "altitude": 5.0,
                "pitch_rc": 1470,
            },
            "error": {
                "altitude": 0.12,
            },
        },
    }

    sock.send((json.dumps(msg) + "\n").encode("utf-8"))
    time.sleep(0.02)
