# Edge AI Course - Radxa Zero 3W

## Goal

Build practical Edge AI skills around the complete deployment pipeline:

**PyTorch -> ONNX -> quantization/conversion -> RKNN -> NPU -> C++/Python application -> camera/sensors -> benchmarking**

The course assumes you already know C++ and Python, but are new to Edge AI.

---

## Course Philosophy

This should be an applied Edge AI course, not a generic machine-learning course. The central skill is:

> Train or obtain a model -> optimize it -> deploy it on constrained hardware -> connect it to real sensors -> measure latency/FPS/power -> build a complete application.

The Radxa Zero 3W, based on the Rockchip RK3566, is a good platform for learning this workflow because it supports Rockchip's RKNN NPU deployment ecosystem.

---

# Syllabus

## Module 1 - What is Edge AI?

Start with the big picture rather than neural-network mathematics.

Learn the distinction between:

- Cloud inference
- Desktop/GPU inference
- Embedded/edge inference
- MCU/TinyML
- SBCs such as the Radxa Zero 3W
- CPU vs GPU vs NPU/DSP

Important concepts:

- Latency
- Throughput
- FPS
- TOPS
- Memory bandwidth
- RAM
- Power
- Model size

### Exercise

Run a simple Python image-processing program on the Radxa and measure CPU execution time.

---

## Module 2 - Linux for Embedded AI

Learn the Linux tools you will repeatedly use on Edge AI devices:

- SSH
- `scp` and `rsync`
- Processes
- Permissions
- `systemd`
- CPU/RAM monitoring
- `htop`
- `top`
- `free`
- `dmesg`
- `/dev/video*`
- USB devices
- Networking
- Python virtual environments

### Exercise

Connect to the Radxa remotely from your PC and run a Python or C++ program without a monitor or keyboard connected to the board.

---

## Module 3 - Sensors and Computer Vision

Before AI acceleration, learn how data enters the system.

Use a USB camera if available.

Typical pipeline:

```text
Camera
   |
   v
V4L2
   |
   v
OpenCV
   |
   v
BGR/RGB image
   |
   v
Resize / normalize
   |
   v
Model
```

Learn OpenCV in Python and C++:

- Capture camera frames
- Resize
- Crop
- Draw overlays
- Measure FPS
- Record video

### Project

Build a camera application that continuously displays or streams frames and prints the measured FPS.

---

## Module 4 - Neural-Network Inference Basics

You do not need to become an ML researcher first. Learn enough PyTorch to understand inference.

```text
Input
  |
  v
Neural Network
  |
  v
Tensor
  |
  v
Postprocessing
  |
  v
Result
```

Understand:

- Tensor dimensions
- NCHW vs NHWC
- FP32
- FP16
- INT8
- Classification
- Detection
- Segmentation

Start with a small model such as MobileNet.

### Exercise

Run an existing pretrained MobileNet model on your development PC and classify images.

Do not train a model yet.

---

## Module 5 - Model Interchange with ONNX

Learn the model-export pipeline:

```text
PyTorch
   |
   v
ONNX
   |
   v
Converter / compiler
   |
   v
Target hardware model
```

Learn:

- What ONNX is
- Operators
- Input/output shapes
- Static vs dynamic shapes
- ONNX Runtime
- Unsupported operators

### Exercise

Export MobileNet from PyTorch to ONNX and run it using ONNX Runtime.

Verify that PyTorch and ONNX produce approximately the same result.

---

## Module 6 - Why Edge AI Optimization Exists

Study the main Edge AI constraints and model representations:

- FP32
- FP16
- INT8

Learn:

- Quantization
- Calibration
- Post-training quantization (PTQ)
- Quantization-aware training (QAT)
- Accuracy degradation
- Memory footprint
- Model size
- Latency

Example comparison:

| Property | FP32 | INT8 |
|---|---:|---:|
| Model size | 15 MB | 4 MB |
| Inference | 80 ms | 20 ms |
| Accuracy | 72.1% | 71.5% |

The exact numbers are not important. The goal is to understand the tradeoff.

---

## Module 7 - Radxa Zero 3W NPU and RKNN

Learn the Rockchip RKNN deployment architecture.

Development workflow:

```text
             DEVELOPMENT PC
                   |
             PyTorch model
                   |
                  ONNX
                   |
             RKNN-Toolkit2
                   |
                   v
              model.rknn
                   |
              copy model
                   |
                   v
          +-----------------+
          | Radxa Zero 3W   |
          |                 |
Camera -> | CPU -> NPU -> CPU | -> Result
          +-----------------+
```

Learn:

- RKNN-Toolkit2
- RKNN Toolkit Lite2
- RKNN Runtime
- Model conversion
- Calibration
- NPU inference
- Python deployment
- C/C++ deployment APIs

### Exercise

Run your first network on the NPU and compare CPU latency against NPU latency.

This should be considered a major course milestone.

---

## Module 8 - Object Detection

Move from classification to a real object detector such as a small YOLO model.

Learn the complete pipeline:

```text
Camera
  |
  v
Resize / letterbox
  |
  v
YOLO
  |
  v
Raw tensors
  |
  v
Decode
  |
  v
NMS
  |
  v
Bounding boxes
  |
  v
Display
```

Learn that inference is only one stage of the full system.

### Exercise

Run YOLO on images using the Radxa NPU.

Measure:

- Preprocessing time
- Inference time
- Postprocessing time
- Total FPS

---

## Module 9 - Python vs C++ Deployment

Implement the same application twice.

First:

```text
Python + RKNN Lite
```

Then:

```text
C++ + RKNN Runtime
```

Compare:

- Complexity
- Startup time
- Memory use
- FPS
- Maintainability

This teaches the common relationship:

```text
Python -> experimentation
C++    -> production deployment
```

---

## Module 10 - Real-Time System Design

A naive program often looks like:

```python
while True:
    frame = camera.read()
    result = model(frame)
```

Instead, learn real-time pipelines:

```text
Camera thread
     |
     v
Frame queue
     |
     v
Preprocessing
     |
     v
NPU inference
     |
     v
Postprocessing
     |
     v
Output
```

Learn:

- Threads
- Queues
- Buffering
- Dropped frames
- Producer/consumer patterns
- Latency vs throughput
- Zero-copy concepts
- Memory copies

Because you already know C++, this module should receive significant attention.

---

## Module 11 - Profiling and Optimization

Profile the entire application, not just neural-network inference.

Example:

```text
Camera capture       6 ms
Resize               4 ms
Inference           21 ms
Postprocess           5 ms
Drawing               3 ms
--------------------------
Total                39 ms

~25 FPS
```

Then optimize the largest bottlenecks first.

Learn:

- `perf`
- CPU utilization
- Memory use
- NPU utilization where available
- Thermal throttling
- CPU affinity
- Memory copies
- SIMD concepts
- Pipeline parallelism

---

## Module 12 - Building an Edge AI Product

Add the non-AI pieces needed to turn a demo into a system.

```text
              Edge device
                   |
      +------------+------------+
      |            |            |
      v            v            v
    Camera       Model        Sensors
      |            |            |
      +------------+------------+
                   |
                   v
                 Logic
                   |
                   v
          Network / GPIO / UI
```

Learn:

- GPIO
- LEDs
- UART/I2C basics
- REST concepts
- MQTT concepts
- Saving events
- Remote configuration
- Watchdogs
- Automatic startup with `systemd`

---

# Recommended Capstone Project - Smart Edge Camera

Do not make the capstone simply "run YOLO on Radxa". Build a complete embedded AI application.

## System Architecture

```text
                    USB Camera
                        |
                        v
                +---------------+
                | Radxa Zero 3W |
                |               |
                | OpenCV        |
                |      |        |
                | preprocessing |
                |      |        |
                | RK3566 NPU    |
                |      |        |
                | YOLO          |
                |      |        |
                | tracking      |
                +-------+-------+
                        |
              +---------+---------+
              |         |         |
              v         v         v
             LED      Video      MQTT/
            GPIO    recording     REST
```

A good concrete version is a **person/vehicle monitoring camera**.

## Capstone Requirements

1. Detect people and/or vehicles.
2. Run detection on the NPU.
3. Track detected objects between frames.
4. Display bounding boxes and object IDs.
5. Maintain a defined target FPS.
6. Trigger a GPIO LED when a person enters a configured region.
7. Save an image or short video event.
8. Expose runtime statistics:
   - FPS
   - Inference latency
   - Number of detections
   - CPU usage
   - Memory usage
9. Automatically launch when the Radxa boots.

## Advanced Requirement - Restricted Zone

```text
+---------------------------------+
|                                 |
|              Person             |
|                []               |
|                |                |
|        +-------+--------+       |
|        | restricted area|       |
|        |                |       |
|        +----------------+       |
|                                 |
+---------------------------------+

Person enters region
        |
        v
GPIO LED ON
        |
        v
Save event
```

Possible extensions:

- MQTT notification
- Local web dashboard
- RTSP stream
- Event database
- Multiple detection zones
- Object counting
- Track trajectories
- Compare Python vs C++ performance
- Compare FP16/FP32 CPU inference against INT8 NPU inference

---

# Suggested 12-Week Schedule

| Week | Topic | Deliverable |
|---:|---|---|
| 1 | Edge AI + Linux | Radxa environment |
| 2 | Camera + OpenCV | Live camera application |
| 3 | Neural-network inference | MobileNet inference |
| 4 | PyTorch -> ONNX | ONNX model |
| 5 | Quantization | FP32 vs INT8 experiment |
| 6 | RKNN/NPU | First NPU inference |
| 7 | YOLO | Image object detection |
| 8 | Real-time YOLO | Camera detector |
| 9 | C++ RKNN | C++ inference application |
| 10 | Threads/pipelines | Real-time pipeline |
| 11 | Profiling/optimization | Benchmark report |
| 12 | Capstone | Smart Edge Camera |

---

# What Not to Study First

Do not begin with:

- Training large CNNs from scratch
- Transformers
- Deep backpropagation mathematics
- CUDA programming
- TensorRT
- LLM deployment

Those are useful later, but they are not required to learn the core Edge AI workflow.

Your first objective is to become comfortable with the complete deployment chain:

> **PyTorch -> ONNX -> quantization/conversion -> RKNN -> NPU -> C++/Python application -> camera/sensors -> benchmarking**

Once you can build this entire chain yourself, you have the core practical skill set needed for Edge AI development.
