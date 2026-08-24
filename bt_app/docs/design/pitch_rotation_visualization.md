# Pitch rotation visualization

`bt-pitch-effect` generates a synthetic 640×480 calibration image and a 2×2 comparison showing pure camera rotation at 0°, −5°, −10°, and −15° pitch.

```bash
source /home/user/projects/bt_ws/venv/bin/activate
cd /home/user/projects/bt_ws/bt_app
bt-pitch-effect
```

Outputs:

- `logs/pitch_rotation_base.png`
- `logs/pitch_rotation_comparison.png`

Negative pitch follows the application convention: forward/nose-down. Fixed scene features therefore move upward in the resulting image.

The visualization uses the simulated camera defaults:

```text
image = 640 x 480
fx = fy = 320 px
cx = 320 px
cy = 240 px
```

The tool applies the pure-rotation homography `H = K R K⁻¹`. This is appropriate for visualizing camera rotation from a single image, but it cannot reveal pixels outside the original view or reproduce translation and depth-dependent parallax. Newly exposed pixels are intentionally black.

Values can be overridden:

```bash
bt-pitch-effect \
  --angles 0 -3 -6 -9 \
  --fx 320 --fy 320 --cx 320 --cy 240 \
  --base-output logs/custom_base.png \
  --output logs/custom_pitch_comparison.png
```
