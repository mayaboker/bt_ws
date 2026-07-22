# Betaflight SITL + Gazebo "slow SITL" bug — full report and fix

- **Date:** 2026-07-22
- **Machine:** `dev1` (Ubuntu, 16 cores, host uptime ~3.15 days at diagnosis time)
- **Stack:** Gazebo Harmonic + `bt_gazebo/plugins/BetaflightPlugin.cc` (betaloop-style, world `betaloop_iris_betaflight_demo_harmonic.sdf`, 4 ms physics step / 250 Hz) ↔ `betaflight_2025.12.2_SITL` (prebuilt, run from `~/projects/bt_ws`)
- **Fix location:** git worktree `~/projects/bf_2025_simrate_fix`, branch `my_bt_2025_simrate_fix` (based on `origin/2025.12-maintenance`), changes in `src/platform/SIMULATOR/sitl.c` (uncommitted at the time of writing)

---

## 1. Symptom

The simulation ran extremely slowly even after applying the well-known configurator fix
(ESC/Motor Protocol = **PWM**, **disable** "Motor PWM speed separated from PID speed",
i.e. `use_unsynced_pwm = OFF`). The craft was unresponsive, the configurator felt dead or
laggy, and the Gazebo world advanced in visible ~1 second jerks.

**Important negative result:** the configurator setting was *verified applied and working*
on the live FC via MSP:

```
MSP_ADVANCED_CONFIG: pid_process_denom = 16, use_unsynced_pwm = 0,
                     motorProtocol = PWM, motorPwmRate = 480
MSP_STATUS:          pid cycleTime ≈ 2000 us  (≈ 500 Hz PID loop)
```

So the PID loop was correctly clamped to ~500 Hz. The slowness had a different cause.

## 2. Measured evidence

### 2.1 The wire (tcpdump on `lo`, UDP 9003 = FDM in, 9002 = servo out)

Wedged state — the lockstep collapsed to ~1 Hz with a fixed 1005 ms period:

```
FDM  (296 B, gz→sitl)      ← after 1004.5 ms silence
SRV  ( 16 B, sitl→gz)      ← +0.4 ms   (SITL's emergency reply)
FDM  (296 B, gz→sitl)      ← +0.5 ms   (plugin steps once, sends state)
[ ~1004.5 ms of silence — SITL never answers this second FDM ]
... repeats; every ~10 s a 4–5 s gap (plugin's 5-strike offline reset)
```

The 1005 ms period is exactly the plugin's behavior: when it believes Betaflight is
online, `ReceiveMotorCommand()` blocks the physics `PreUpdate` for up to **1000 ms**
waiting for a 16-byte servo packet, so a silent SITL freezes the whole Gazebo world.

### 2.2 The SITL process

- **91% of one core** consumed while functionally dead (main thread trapped in a
  spin-wait, see §3).
- MSP: first request answered after seconds, subsequent ones **>30 s** (dead).
- Every FDM answered *only* by the UDP thread's ">500 ms silence" emergency branch —
  never by the PID loop.

### 2.3 Control measurement (after fix)

Same machine, same Gazebo session, same eeprom:

| Metric | Wedged | Fixed |
|---|---|---|
| Lockstep rate (both directions) | 1–2 Hz, 1005 ms stalls | **240 Hz sustained, p50 gap 4.00 ms** |
| MSP round-trip | seconds → >30 s | **10–30 ms** |
| SITL CPU | 91% of a core | **~0%** |
| Gazebo real-time factor | collapsed | **1.00** |

## 3. Root cause

A lockstep-clock feedback bug in `src/platform/SIMULATOR/sitl.c`, `updateState()`
(the FDM receive path), amplified by the SITL clock scaling and the scheduler's
spin-wait. Chain of events:

1. **`last_ts` is never initialized**, and the ">500 ms since last FDM" timeout branch
   **returns early without updating it**:

   ```c
   if (realtime_now > last_realtime + 500*1e3) { // 500ms timeout
       last_timestamp = pkt->timestamp;
       last_realtime = realtime_now;
       sendMotorUpdate();
       return;                      // <-- last_ts and simRate untouched
   }
   ```

2. The **first FDM after boot always lands in that branch**, because the
   BetaflightPlugin only starts sending FDM once it has seen a servo packet
   ("online" detection), and SITL's init takes longer than 500 ms. The *second*
   FDM (one 4 ms sim step later) then takes the normal path and computes:

   ```c
   simRate = deltaSim / (now_ts - last_ts);
   //       = 0.004 s / (CLOCK_MONOTONIC now - 0)   ≈ 0.004 / 272000 s
   //       ≈ 1.5e-8        (denominator = HOST UPTIME, ~3.15 days)
   ```

3. **The virtual clock stops entirely.** `micros64()` accumulates
   `out += (now - last) * simRate` in integer nanosecond units and advances
   `last` on every call; with simRate ≈ 1.5e-8 each per-call increment is far
   below 1 ns, truncates to zero, and is *lost* — sim time does not merely slow
   250×, it freezes.

4. **The scheduler traps the main thread.** `scheduler.c` (≈ lines 548–551)
   busy-spins waiting for the next gyro cycle:

   ```c
   while (schedLoopRemainingCycles > 0) {
       nowCycles = getCycleCounter();      // = frozen scaled clock in SITL
       schedLoopRemainingCycles = cmpTimeCycles(nextTargetCycles, nowCycles);
   }
   ```

   With a frozen counter this never exits → PID, mixer, motor output, MSP, RX —
   everything on the main thread is dead, one core pegged.

5. **Zombie equilibrium.** Only the (real-time) UDP thread stays alive; its
   emergency branch answers each FDM that arrives after >500 ms of silence. The
   plugin therefore sees just enough life to stay in 1000 ms-blocking lockstep
   mode → the world advances ~1 step/second forever. Every 5 missed receives the
   plugin resets to offline (the observed 4–5 s gaps), reconnects on the next
   emergency reply, and re-latches.

The same latch also triggers mid-flight on any single >500 ms FDM hiccup
(GUI stall, host load spike): the timeout branch fires once, and the next
normal packet computes `simRate = 0.004 / (stale gap ≈ 1 s) ≈ 0.004`, which is
already slow enough that SITL cannot answer within the plugin's 1 s window —
self-sustaining by the same mechanism.

**Why the configurator setting didn't help:** `use_unsynced_pwm` only affects
`pid_process_denom` clamping (`config.c` `validateAndFixGyroConfig()`); it fixes a
CPU-overload failure mode (8 kHz PID on the SITL scheduler). This bug is in the
SITL↔simulator time-synchronization layer and is orthogonal to any FC configuration.

## 4. The fix

`src/platform/SIMULATOR/sitl.c`, two changes in `updateState()` (plus one carried-over
baro fix). Applied in worktree `~/projects/bf_2025_simrate_fix`:

**(a) Timeout branch — reset the clock reference instead of leaving it stale:**

```c
if (realtime_now > last_realtime + 500*1e3) { // 500ms timeout
    last_timestamp = pkt->timestamp;
    last_realtime = realtime_now;
    // Reset the lockstep clock reference: computing simRate against a
    // stale (or never-initialised) last_ts collapses the scaled clock,
    // trapping the scheduler in its spin-wait and stalling the sim.
    last_ts.tv_sec = now_ts.tv_sec;
    last_ts.tv_nsec = now_ts.tv_nsec;
    simRate = 1.0;
    sendMotorUpdate();
    return;
}
```

**(b) simRate computation — only trust sane wall-clock gaps:**

```c
struct timespec out_ts;
timeval_sub(&out_ts, &now_ts, &last_ts);
const double wallDelta = out_ts.tv_sec + 1e-9*out_ts.tv_nsec;
// Only trust simRate when the wall-clock gap is sane; a stall or
// uninitialised reference would otherwise freeze the virtual clock.
if (wallDelta > 0 && wallDelta < 0.5) {
    simRate = deltaSim / wallDelta;
}
```

**(c) Baro (carried over from local branch `my_bt_45`, commit "fix baro"):** the
betaloop plugin sends `pressure = 0` in the FDM packet (verified by decoding live
packets), which breaks baro altitude. Pressure is instead derived from FDM altitude:

```c
const double altMeters = pkt->position_xyz[2];
const int32_t pressurePa = (int32_t)(101325.0 * pow(1.0 - 2.25577e-5 * altMeters, 5.25588));
virtualBaroSet(pressurePa, 2500);
```

### Build notes (worktree)

```bash
cd ~/projects/bf_2025_simrate_fix
rm -rf src/config && cp -r ~/projects/betaflight/src/config src/config   # hydrate configs
export PATH=~/projects/betaflight/tools/arm-gnu-toolchain-13.3.rel1-x86_64-arm-none-eabi/bin:$PATH
make TARGET=SITL -j16
# -> obj/main/betaflight_SITL.elf  (obj/betaflight_2025.12.3-alpha_SITL)
```

The Makefile checks for `arm-none-eabi-gcc` even for the native SITL target, and the
worktree does not share the main checkout's untracked `tools/` and `src/config/`.

## 5. Verification procedure (repeatable)

1. **Wire rate:** `sudo timeout 15 tcpdump -ni lo 'udp and (port 9002 or port 9003)' -w x.pcap`
   → healthy = ~250 Hz both directions, p50 gap 4 ms, no ~1005 ms gaps.
2. **MSP:** raw MSP_STATUS frames to TCP `127.0.0.1:5761` → healthy = 10–30 ms rtt.
   (Do **not** use the CLI on 5761 for checks — `exit` reboots/kills SITL.)
3. **CPU:** `top -p $(pgrep -f betaflight_SITL)` → healthy ≈ 0–10%; wedged ≈ 90%+ of one core.
4. **RTF:** `gz topic -e -t /world/betaloop_demo/stats -n 1` → `real_time_factor ≈ 1.0`.

All four passed after the fix (240 Hz / 10–30 ms / ~0% / RTF 1.00), with the original
`eeprom.bin` and the q1 configurator settings unchanged.

## 6. Current deployment state & how to make it permanent

- The **patched** `betaflight_SITL.elf` is running detached (started via
  `/tmp/start_patched.sh`, CWD `~/projects/bt_ws` so it uses the existing `eeprom.bin`).
- The original `run_sitl.sh` terminal session ended when the wedged instance was killed.
- To switch back to the normal workflow:

  ```bash
  pkill -f betaflight_SITL.elf
  cp ~/projects/bf_2025_simrate_fix/obj/main/betaflight_SITL.elf \
     ~/projects/bt_ws/bt_bringup/bin/betaflight_2025.12.3_SITL_simratefix
  # point bt_bringup/launch/run_sitl.sh at the new binary, then run it as usual
  ```

- The worktree changes are **uncommitted** on branch `my_bt_2025_simrate_fix` —
  review with `git -C ~/projects/bf_2025_simrate_fix diff` and commit.

## 7. Known residual issues (not fixed here)

1. **Zero accelerometer at rest:** betaloop sends body linear acceleration excluding
   gravity (0,0,0 at rest); Betaflight's SITL expects gravity-included specific force
   ("sim 1G = 9.80665"). `accADC` therefore reads 0. Attitude is unaffected
   (`USE_IMU_CALC` is off in SITL — the quaternion is passed through), but
   acc-dependent features (GPS rescue, position/alt hold quality) may misbehave.
   Proper fix belongs in the plugin's `SendState()`.
2. **FDM struct mismatch (benign today):** the plugin sends 296-byte FDM packets;
   this SITL's `fdm_packet` is 144 bytes. `recvfrom()` silently truncates and the
   `n == sizeof(fdm_packet)` check passes because it compares against the truncated
   length. The first 18 doubles happen to align, so it works — but any field
   reordering upstream would corrupt sensors silently. A size/version field or an
   exact-size check with `MSG_TRUNC` would harden this.
3. **Upstream:** the simRate latch affects stock `betaflight/betaflight`
   (`2025.12-maintenance` and master share the pattern) with any lockstep bridge that
   pauses FDM for >500 ms. Worth submitting as a PR (patch §4a/§4b applies cleanly).
4. **Arming:** currently blocked only by `RX_FAILSAFE` (no RC feed was running during
   diagnosis) — start the joystick/RC bridge as usual.
