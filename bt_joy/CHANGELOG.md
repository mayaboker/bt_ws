# Changelog

All notable changes to `bt-joy` will be documented in this file.

The format follows the spirit of Keep a Changelog, and this project uses
semantic versioning while it evolves.

## [0.0.6] - 2026-05-18

### Added

- Added UDP keepalive request and response packets between client and server.
- Added client-side keepalive timeout/error logging for failed, malformed, late, or missing responses.
- Added startup Betaflight MSP version probing before joystick forwarding begins.
- Added `MSP_STATUS_EX` parsing with Betaflight arming disable flag names.
- Added Debian-native packaging files, systemd units, service YAML examples, and man pages.
- Added YAML configuration support for the MSP server command.
- Added tests for keepalive protocol, MSP version/status parsing, and keepalive timeout logging.

### Changed

- Switched periodic MSP status reads from legacy `MSP_STATUS` to `MSP_STATUS_EX`.
- Status logs now include raw arming disable flags and decoded names.
- Joystick RC packet logs are debug-level while status/keepalive logs remain visible at info/error levels.
