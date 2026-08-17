You’re right: the Betaflight doc explicitly says to disable “Motor PWM speed separated from PID speed”. That setting is not the problem by itself.

  What the doc expects is still this UDP loop:

  - Betaflight sends normalized motor speed packets to Gazebo on UDP 9002.
  - Gazebo sends FDM state back to Betaflight on UDP 9003.

  The doc’s port map says 9002 is “SITL -> Gazebo Motor speeds [0.0 - 1.0]” and 9003 is “Gazebo -> SITL FDM state”. It also says to set ESC/Motor Protocol to PWM and
  disable “Motor PWM speed separated from PID speed”. Source: Betaflight Gazebo SITL doc, Architecture and Essential SITL Settings sections.
  https://betaflight.com/docs/development/autopilot/SITL_Autopilot_Testing_Gazebo

  So the correct interpretation is:

  - Disable separated motor PWM/PID speed in Betaflight.
  - Gazebo should still receive motor speed packets on 9002.
  - Gazebo should still send FDM packets on 9003.

  Your slowdown points to a plugin-side coupling bug or a packet-rate issue, not to the Betaflight setting being wrong.

  In this plugin, 9003 sending is gated behind betaflightOnline and happens only after ReceiveMotorCommand() returns:

  this->ReceiveMotorCommand();
  if (this->betaflightOnline)
  {
    this->ApplyMotorForces(dt, _ecm);
    this->SendState(_ecm);
  }

  When betaflightOnline == true, ReceiveMotorCommand() waits up to 1000 ms for a 9002 packet. If Betaflight sends 9002 slowly or stops sending it, the Gazebo update
  thread blocks, RTF drops, and 9003 also becomes slow.

  So I would change the plugin logic, not the Betaflight setting:

  this->ReceiveMotorCommandNonBlocking();

  if (this->betaflightOnline)
  {
    this->ApplyMotorForces(dt, _ecm);
  }

  this->SendState(_ecm);

  And make ReceiveMotorCommand() use a very small or zero timeout every tick. 9003 FDM output should not depend on receiving a fresh 9002 motor packet every update.

## Listen to bt-gst detector results

`bt_gst/scripts/listen_zmq.py` is a small diagnostic subscriber for the tracker
results published by `bt_gst`. It connects to the ZMQ PUB endpoint, decodes each
`bt_msgs.TrackerResultMessage`, and prints its detector frame ID and GStreamer
presentation timestamp.

Start the GStreamer pipeline in one terminal:

```bash
./bt_bringup/launch/run_gst.sh
```

From the workspace root, start the listener in another terminal:

```bash
bt_gst/.venv/bin/python bt_gst/scripts/listen_zmq.py
```

The default endpoint is `tcp://127.0.0.1:5556`. To connect to another endpoint:

```bash
bt_gst/.venv/bin/python bt_gst/scripts/listen_zmq.py \
  --endpoint tcp://127.0.0.1:6000
```

Example output:

```text
Listening for bt-gst tracker results on tcp://127.0.0.1:5556
frame_id=42 timestamp=123456789
frame_id=43 timestamp=156790122
```

`timestamp` is the video buffer's GStreamer PTS in nanoseconds. It is printed as
`None` when the source does not provide a valid PTS. Frame ID gaps are expected
when the publisher's rate limiter replaces an older pending result with a newer
one. Press Ctrl+C to stop the listener.
