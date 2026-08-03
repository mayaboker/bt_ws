Yes—you can send Gazebo rangefinder data to Betaflight SITL, but sitl.c does not currently accept it through the Gazebo UDP state packet.

  The existing fdm_packet contains only timestamp, IMU, attitude, velocity, position, and pressure (src/platform/SIMULATOR/target/SITL/target.h:233). UDP port 9003 rejects packets
  unless their size exactly matches that structure (src/platform/SIMULATOR/sitl.c:527).

  The easiest route requires no sitl.c modification:

  1. Configure a SITL UART for LIDAR_TF.
  2. Configure rangefinder_hardware = TFMINI.
  3. Have your Gazebo plugin connect to that UART’s TCP port and send TFmini-compatible frames.

  SITL exposes UART1–UART8 as TCP ports 5761–5768 when configured/opened (src/main/drivers/serial_tcp.c:119). For example, configuring UART2 means Gazebo connects to 127.0.0.1:5762.

  Typical Betaflight CLI configuration:

  serial 1 32768 115200 57600 0 115200
  set rangefinder_hardware = TFMINI
  save

  Here serial 1 normally corresponds to UART2 and 32768 is FUNCTION_LIDAR_TF.

  Send a 9-byte TFmini frame at roughly 50–100 Hz:

  59 59 DL DH SL SH 00 00 CHECKSUM

  Where:

  - distance_cm = DL | (DH << 8)
  - strength = SL | (SH << 8); use a nonzero value such as 100
  - CHECKSUM is the unsigned 8-bit sum of the preceding eight bytes

  The parser and format are documented directly in src/main/drivers/rangefinder/rangefinder_lidartf.c:51. TFmini accepts 40–1200 cm in this implementation.

  For example, 150 cm:

  59 59 96 00 64 00 00 00 AC

  A native UDP implementation is also possible by adding a rangefinder_cm field to fdm_packet and a virtual rangefinder driver. However, that changes the port-9003 wire structure and
  requires matching changes to the Gazebo plugin and any SITL harness. The serial/TCP emulation is already supported and exercises Betaflight’s real rangefinder processing path, so it
  is the cleaner first choice.