import cv2
from ultralytics import YOLO

# load trained model
model = YOLO("runs/detect/train/weights/best.pt")

# load image
frame = cv2.imread("/home/user/projects/bt_ws/yolo_500_frames/images/frame_000398.png")

# run inference
results = model(frame, imgsz=416, conf=0.25)

# draw detections
annotated = results[0].plot()

# show result
cv2.imshow("YOLO", annotated)

print("detections:")
for box in results[0].boxes:
    cls = int(box.cls[0])
    conf = float(box.conf[0])

    x1, y1, x2, y2 = box.xyxy[0].tolist()

    print(
        f"class={cls} "
        f"conf={conf:.2f} "
        f"box=({x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f})"
    )

cv2.waitKey(0)
cv2.destroyAllWindows()