# Tracker Controller Analysis — `TRK_VZ_KD=30`

Source: `tracker_controller.csv`  
Plot: [tracker_controller_analysis.svg](tracker_controller_analysis.svg)

![Tracker controller analysis](tracker_controller_analysis.svg)

## Executive summary

The gain increase from `TRK_VZ_KD=20` to `30` improved vertical-speed
tracking, but did not solve the vertical geometry. Average measured descent
increased from `-0.515` to `-0.616 m/s`, and mean setpoint error improved from
`-0.416` to `-0.326 m/s`. Proposed throttle became busier, but remains much
smoother than the old unbounded run 03.

This flight progressed farther than the previous bounded-speed run: depth
decreased from 15.56 to 6.67 m and the pitch approach profile began tapering.
It still exited with `target_lost_or_stale`. Late in the run the target moved
farther below the camera center (`dy=-0.867`) and its bounding box was clipped
by the image edge. The final loss is therefore consistent with inadequate
vertical alignment, not merely a controller timeout.

The next controlled change should be:

```text
TRK_VZ_MAX: 1.00 -> 1.25 m/s
```

Keep `TRK_VZ_KD=30`, `TRK_VZ_ACCEL=0.75`, and `TRK_THR_KP=100` unchanged.
This tests whether the slant approach needs a faster bounded descent without
mixing another gain or acceleration change into the experiment.

## Run overview

| Metric | Result |
| --- | ---: |
| Samples | 636 |
| Duration | 12.700 s |
| Controller rate | 50.000 Hz |
| 95th-percentile loop interval | 20.034 ms |
| Maximum loop interval | 20.172 ms |
| Valid control rows | 635 |
| Unique camera frames | 351 |
| Approximate camera rate | 27.6 Hz |
| Initial / final depth | 15.56 / 6.67 m |
| Initial / final slant range | 17.82 / 7.96 m |
| Exit reason | `target_lost_or_stale` |

Loop timing is stable and is not causing the control behavior.

## Effect of increasing `TRK_VZ_KD`

| Metric | Previous bounded run (`KD=20`) | Current run (`KD=30`) |
| --- | ---: | ---: |
| Mean measured vertical speed | -0.515 m/s | -0.616 m/s |
| Mean vertical-speed error | -0.416 m/s | -0.326 m/s |
| Final vertical-speed error | -0.580 m/s | -0.350 m/s |
| Minimum measured vertical speed | -0.96 m/s | -1.25 m/s |
| Mean throttle correction | -8.31 RC | -9.79 RC |
| Final depth | 10.04 m | 6.67 m |
| Duration before loss | 10.08 s | 12.70 s |

The result supports the gain change: the vehicle follows the requested descent
more closely and the approach continues farther. There is some overshoot—the
measured rate reaches `-1.25 m/s` while the setpoint is `-1.0 m/s`—but it is
brief rather than a sustained unstable oscillation. Increasing `TRK_VZ_KD`
again is therefore not the best next experiment.

## Vertical-loop behavior

Logged settings:

```text
TRK_THR_KP   = 100
TRK_VZ_KD    = 30
TRK_VZ_MAX   = 1.0 m/s
TRK_VZ_ACCEL = 0.75 m/s^2
```

| Vertical quantity | Minimum | Maximum | Mean | Final |
| --- | ---: | ---: | ---: | ---: |
| Raw requested speed | -2.789 | -1.747 | -2.040 | -2.789 m/s |
| Capped target | -1.000 | -1.000 | -1.000 | -1.000 m/s |
| Slewed setpoint | -1.000 | 0.000 | -0.942 | -1.000 m/s |
| Measured speed | -1.250 | 0.000 | -0.616 | -0.650 m/s |
| Speed error | -0.825 | +0.250 | -0.326 | -0.350 m/s |
| Throttle correction | -24.75 | +7.50 | -9.79 | -10.50 RC |

The setpoint reaches `-1.0 m/s` at 1.42 s. The raw request remains more
negative than the cap throughout the run, so `TRK_THR_KP` is not limiting the
response. Vertical telemetry is continuously valid; its 95th-percentile age is
0.159 s and maximum age is 0.198 s, both below the 0.30 s rejection threshold.

The controller alternates between under-speed and occasional over-speed. For
example, measured speed is about `-1.23 m/s` near 3 s, then only `-0.32 m/s`
near 5 s. Some of this step-like behavior is expected because the flight
controller supplies vertical speed at approximately 10 Hz while the control
loop runs at 50 Hz. More inner gain would amplify those telemetry steps.

## Camera centering and loss

| Error metric | `dx` | `dy` |
| --- | ---: | ---: |
| Mean absolute error | 0.0184 | 0.6419 |
| RMS error | 0.0209 | 0.6473 |
| Time inside +/-0.03 deadband | 83.3% | 0.0% |
| Range | +0.0094 to +0.0406 | -0.867 to -0.554 |

Yaw centering remains good. Vertical centering improves from `dy=-0.746` at
startup to approximately `-0.554` around 3-6 s, but then reverses. After the
pitch-taper boundary, mean `dy` is about `-0.781`; at the last held estimate it
is `-0.867`, very near the image edge.

Invalid observations occur in 10 episodes:

- 44 rows report `width/height depth disagreement`.
- 5 rows report `bounding box clipped by image edge`.
- The first clipped observation occurs at 12.620 s.
- The estimate is held until its age reaches 0.256 s, just beyond the configured
  0.25 s timeout, and the controller safely exits.

The timeout behaves correctly. Increasing `TRK_TIMEOUT_S` would only keep
flying longer with an off-screen target and is not recommended.

## Pitch profile

The initial depth produces a nominal taper boundary of 9.33 m. Because the
quintic profile has zero slope at its boundary, the first visible change away
from `-10 degrees` occurs at 10.62 s and 9.06 m. Pitch then smoothly relaxes to
`-9.23 degrees` by the last valid command at 6.67 m.

This confirms that the approach profile is active and continuous. However, its
activation coincides with worsening vertical image error. That does not prove
the pitch taper is the cause—the descent was already slower than its setpoint—
but it is a relationship to watch in the next run.

## Command smoothness

| Proposed-throttle metric | `KD=20` run | Current `KD=30` run | Old run 03 |
| --- | ---: | ---: | ---: |
| Mean absolute 20 ms step | 0.141 RC | 0.297 RC | 0.638 RC |
| 95th-percentile step | 1 RC | 2 RC | 4 RC |
| Maximum step | 3 RC | 6 RC | 15 RC |
| Total variation | 7.06 RC/s | 14.83 RC/s | 31.9 RC/s |

The increased gain roughly doubles command activity, as expected, but the
output remains much smoother than run 03. Proposed throttle stays between
1639 and 1678, leaving ample correction headroom around the 1660 baseline.

## Recommended next experiment

Change one parameter only:

```text
TRK_VZ_MAX = 1.25
```

This recommendation was subsequently applied to the canonical parameter
default in `bt_app/parameters.yaml`.

Why this is the next useful change:

1. The raw visual request is between `-1.75` and `-2.79 m/s`, so a 1.25 m/s
   cap will remain an actual cap throughout this type of run.
2. The current loop now demonstrates useful response to a bounded setpoint.
3. Late vertical error worsens while the target moves toward the lower image
   edge, indicating the current descent trajectory is insufficient for the
   forward approach.
4. A 1.25 m/s cap is a conservative 25% increase, not a return to the
   multi-metre-per-second behavior seen in run 03.

Keep these unchanged for clean comparison:

```text
TRK_VZ_KD    = 30
TRK_VZ_ACCEL = 0.75
TRK_THR_KP   = 100
TRK_TIMEOUT_S = 0.25
```

For the next log, success should mean more than reaching a smaller depth:

- `dy` should stop becoming more negative after the taper boundary.
- The bounding box should remain inside the image.
- Measured vertical speed should follow the 1.25 m/s setpoint without repeated
  large overshoot.
- Throttle maximum steps should remain near or below the current 6 RC.

If `dy` still worsens despite tracking the 1.25 m/s setpoint, do not continue
raising speed blindly. The next investigation should correlate camera mounting
angle and the pitch-taper profile with `dy`, and consider a distance-dependent
vertical-speed limit or a slower/shorter pitch taper. Also add raw bounding-box
width, height, individual width/height depth estimates, and image-edge margins
to the CSV so estimator disagreement and clipping can be diagnosed directly.

## Conclusion

`TRK_VZ_KD=30` is an improvement and should be retained. It reduces vertical
speed error and allows the approach to progress farther, at an acceptable cost
in command smoothness. The remaining failure is vertical alignment: the
bounded `-1.0 m/s` target is insufficient late in this slanted approach and the
target exits the image. Test `TRK_VZ_MAX=1.25` next, with every other vertical
parameter unchanged.
