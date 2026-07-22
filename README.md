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