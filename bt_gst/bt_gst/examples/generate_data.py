import cv2
import numpy as np

W, H = 640, 480
N_FRAMES = 80
TRUE_DX, TRUE_DY = 3, 1   # known movement vector

# random features inside ROI
rng = np.random.default_rng(0)
points = rng.integers([120, 120], [420, 320], size=(80, 2))

fourcc = cv2.VideoWriter_fourcc(*"XVID")
out = cv2.VideoWriter("synthetic_flow.avi", fourcc, 20, (W, H))

for t in range(N_FRAMES):
    frame = np.zeros((H, W, 3), dtype=np.uint8)

    # draw ROI
    cv2.rectangle(frame, (100, 100), (450, 350), (80, 80, 80), 1)

    shift = np.array([TRUE_DX * t, TRUE_DY * t])

    for p in points:
        x, y = p + shift
        if 0 <= x < W and 0 <= y < H:
            cv2.circle(frame, (int(x), int(y)), 3, (255, 255, 255), -1)

    out.write(frame)

out.release()

print("created synthetic_flow.avi")
print("true vector:", TRUE_DX, TRUE_DY)
print("true angle:", np.degrees(np.arctan2(TRUE_DY, TRUE_DX)))

cap = cv2.VideoCapture("synthetic_flow.avi")

ret, old_frame = cap.read()
if not ret:
    raise RuntimeError("failed to read first frame")

old_gray = cv2.cvtColor(old_frame, cv2.COLOR_BGR2GRAY)

roi = old_gray[100:350, 100:450]
pts = cv2.goodFeaturesToTrack(
    roi,
    maxCorners=100,
    qualityLevel=0.01,
    minDistance=5
)
if pts is None:
    raise RuntimeError("no features found in ROI")

# convert ROI-local points to full-frame coordinates
# (number_of_points, 1, 2)
pts[:, 0, 0] += 100
pts[:, 0, 1] += 100

all_vectors = []

while True:
    ret, frame = cap.read()
    if not ret:
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    new_pts, status, err = cv2.calcOpticalFlowPyrLK(old_gray, gray, pts, None)
    if new_pts is None or status is None:
        break

    good = status.ravel() == 1
    good_old = pts[good].reshape(-1, 2)
    good_new = new_pts[good].reshape(-1, 2)

    if len(good_new) == 0:
        break

    # Keep only real movement and ignore tiny tracking noise.
    vectors = good_new - good_old
    mag = np.linalg.norm(vectors, axis=1)
    vectors = vectors[mag > 0.5]

    if len(vectors) > 0:
        all_vectors.append(vectors)

    old_gray = gray
    pts = good_new.reshape(-1, 1, 2)

cap.release()

if not all_vectors:
    raise RuntimeError("no valid optical-flow vectors found")

all_vectors = np.vstack(all_vectors)
majority_vec = np.median(all_vectors, axis=0)
angle = np.degrees(np.arctan2(majority_vec[1], majority_vec[0]))

print("estimated vector:", majority_vec)
print("estimated angle:", angle)
