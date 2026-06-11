# bt_joy

Joystick input utilities for the BT workspace.

See [CHANGELOG.md](CHANGELOG.md) for version history.

## Development

Install the project in editable mode:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Run the command-line entry point with the packaged example mapping:

```bash
bt-joy
```

Override the joystick device, UDP target, or polling rate:

```bash
bt-joy --device /dev/input/js0 --host 127.0.0.1 --port 9000 --poll-hz 100
```

Send keepalive packets once per second and log server delay responses:

```bash
bt-joy --keepalive-interval 1.0 --keepalive-timeout 1.0
```

The client YAML can also tune repeated high round-trip warnings:

```yaml
keepalive_rtt_warning:
  enabled: true
  threshold_ms: 100.0
  window_s: 10.0
  count: 3
  cooldown_s: 10.0
```

Disable keepalive packets:

```bash
bt-joy --keepalive-interval 0
```

Log the local mapping without needing the mock server:

```bash
bt-joy --log-mapping --log-level INFO
```

Use an external client configuration:

```bash
bt-joy --config client.yaml
```

The client configuration can point at a separate channel mapping file:

```yaml
mapping: mapping.yaml
```

Override that mapping from the command line:

```bash
bt-joy --config client.yaml --mapping xbox.yaml
```

Run the UDP mock server in another terminal to inspect packets:

```bash
bt-joy-mock-server --host 127.0.0.1 --port 9000
```

For a one-shot check, use a timeout:

```bash
bt-joy-mock-server --host 127.0.0.1 --port 9000 --timeout 5
```

Forward joystick UDP packets to Betaflight MSP `MSP_SET_RAW_RC` over TCP:

```bash
bt-joy-msp-server --listen-host 127.0.0.1 --listen-port 9000 --output tcp --tcp-host 127.0.0.1 --tcp-port 5761
```

Forward to MSP over serial:

```bash
bt-joy-msp-server --listen-port 9000 --output serial --serial-device /dev/ttyUSB0 --baudrate 115200
```

```bash title="rpi"
bt-joy-msp-server --listen-port 9000 --output serial --serial-device /dev/ttyAMA0 --baudrate 115200
```

Read and log MSP status, including Betaflight arming disable flags, at a fixed interval:

```bash
bt-joy-msp-server --output tcp --tcp-host 127.0.0.1 --tcp-port 5761 --status-interval 1.0
```

Use a YAML config file for the MSP server:

```bash
bt-joy-msp-server --config /etc/bt-joy/server.yaml
```

## Debian Package

This project includes Debian-native packaging in `debian/`.

Build the package from the project root:

```bash
dpkg-buildpackage -us -uc
```

The package installs:

```text
/usr/bin/bt-joy
/usr/bin/bt-joy-msp-server
/etc/bt-joy/client.yaml
/etc/bt-joy/mapping.yaml
/etc/bt-joy/server.yaml
/lib/systemd/system/bt-joy-client.service
/lib/systemd/system/bt-joy-server.service
```

Enable and inspect services:

```bash
sudo systemctl enable --now bt-joy-server.service
sudo systemctl enable --now bt-joy-client.service
journalctl -u bt-joy-server.service -f
```

Manual pages are installed for the commands, service units, and YAML files.

## Packet Format

Each UDP datagram contains:

```text
magic        4 bytes   "BTJY"
version      uint8     1
sequence     uint32    increments every packet
timestamp_us uint64    wall-clock send time in microseconds
count        uint8     number of channels
channels     uint16[]  mapped channel values
crc32        uint32    CRC over all previous bytes
```

Keepalive request datagrams contain:

```text
magic        4 bytes   "BTKA"
version      uint8     1
sequence     uint32    increments every keepalive packet
timestamp_us uint64    client send time in microseconds
crc32        uint32    CRC over all previous bytes
```

Keepalive response datagrams contain:

```text
magic                 4 bytes   "BTKR"
version               uint8     1
sequence              uint32    matching keepalive sequence
client_timestamp_us   uint64    original client send time
server_received_us    uint64    server receive time
server_delay_us       uint64    server_received_us - client_timestamp_us
crc32                 uint32    CRC over all previous bytes
```

---
