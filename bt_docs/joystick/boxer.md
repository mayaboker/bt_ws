# Boxer

![alt text](images/boxer.png)


| Switch | MAVLink channel | Purpose |
| ------ | --------------- | ------- |
| SA     | 6 | Manual (`1000`) / altitude hold (`2000`) |
| SB     | 8 | Tracker disabled (`1000`) / tracker1 (`1500`) / tracker2 (`2000`) |
| SD     | 7 | Auto takeoff |
| SE     | 5 | Disarmed / armed |
| SF     | 9 | Tracking entry, momentary (`1000` to `2000`) |

Tracker1 and tracker2 both select the same controller in the current POC. The
application only recognizes an SF rising edge after first observing SF low.
The edge enters tracking only when the application is armed in `ALT_HOLD` and
the target has already acquired a valid lock. An early press is ignored. Moving
SB to disabled cancels acquisition and immediately exits tracking.
