#!/usr/bin/env python3
import socket
import struct
import time


PORT = 9004
RATE_HZ = 50
DT = 1.0 / RATE_HZ

ROLL = 0
PITCH = 1
THROTTLE = 2
YAW = 3
ARM = 4
AUTOPILOT = 5

RC_MIN = 1000
RC_MID = 1500
RC_MAX = 2000

THROTTLE_TAKEOFF = 1650
THROTTLE_LAND = 1050
PITCH_FORWARD = 1600


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send_rc(channels):
    # little-endian: double + 16 uint16
    pkt = struct.pack("<d16H", time.time(), *channels)
    sock.sendto(pkt, ("127.0.0.1", PORT))


def channels(throttle=RC_MIN, pitch=RC_MID, armed=False):
    ch = [RC_MID] * 16
    ch[ROLL] = RC_MID
    ch[PITCH] = pitch
    ch[THROTTLE] = throttle
    ch[YAW] = RC_MID
    ch[ARM] = RC_MAX if armed else RC_MIN
    ch[AUTOPILOT] = RC_MAX
    return ch


def hold(duration, throttle=RC_MIN, pitch=RC_MID, armed=False):
    end_time = time.monotonic() + duration
    ch = channels(throttle=throttle, pitch=pitch, armed=armed)

    while time.monotonic() < end_time:
        send_rc(ch)
        time.sleep(DT)


def step(message, duration, throttle=RC_MIN, pitch=RC_MID, armed=False):
    print(f"{time.strftime('%H:%M:%S')} - {message}", flush=True)
    hold(duration, throttle=throttle, pitch=pitch, armed=armed)


def main():
    try:
        step("Send neutral RC with throttle low", 1.0, throttle=RC_MIN, armed=False)

        step("Arm with throttle low", 1.0, throttle=RC_MIN, armed=True)

        step("Take off", 4.0, throttle=THROTTLE_TAKEOFF, armed=True)

        step("Hold hover throttle", 3.0, throttle=RC_MID, armed=True)

        step("Land by lowering throttle", 3.0, throttle=THROTTLE_LAND, armed=True)
        step("Disarm", 1.0, throttle=RC_MIN, armed=False)
    except KeyboardInterrupt:
        print(f"{time.strftime('%H:%M:%S')} - Interrupted", flush=True)
    finally:
        step("Send final disarmed low-throttle command", 0.5, throttle=RC_MIN, armed=False)


if __name__ == "__main__":
    main()