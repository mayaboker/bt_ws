```yolo detect train \
  model=yolo11n.pt \
  data=/home/user/projects/bt_ws/yolo_500_frames/data.yaml \
  imgsz=416 \
  epochs=100
  ```

```
pip install --upgrade pip

pip install rknn-toolkit2==2.3.2
pip install onnx==1.18.0 onnxruntime==1.18.0 protobuf==4.25.4
```

  ```
  yolo export \
  model=runs/detect/train/weights/best.pt \
  format=rknn \
  name=rk3566
  ```