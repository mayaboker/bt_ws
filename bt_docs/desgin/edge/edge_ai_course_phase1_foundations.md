# Edge AI Course — Phase 1: Foundations

## Phase Goal

Build a strong embedded-vision foundation before introducing neural-network deployment.

By the end of Phase 1, you should be able to:

- Develop remotely on the Radxa from VS Code.
- Compile C++ natively and cross-compile ARM64 binaries.
- Understand NumPy arrays, C++ buffers, image memory layouts, and tensor layouts.
- Understand RGB, YUV, RAW, and thermal image formats.
- Bring up and debug a MIPI CSI camera on embedded Linux.
- Use V4L2, OpenCV, and basic GStreamer pipelines.
- Measure FPS, latency, bandwidth, memory copies, and bottlenecks.
- Build a real-time RGB/thermal camera pipeline without AI.

---

# Phase 1 Structure

| Part | Subject | Main Topics | Mini-Capstone |
|---|---|---|---|
| 1 | Embedded Linux & Development Environment | Linux, SSH, Git, GCC/G++, CMake, VS Code Remote SSH, cross-compilation, sysroot, GDB | Remote Embedded Development Environment |
| 2 | NumPy, C++ Memory & Tensors | ndarray, dtype, shape, pointers, buffers, HWC/CHW, NHWC/NCHW, contiguous memory | Image-to-Tensor Converter |
| 3 | Digital Images & Camera Formats | RGB/BGR, grayscale, YUV, NV12, YUYV, RAW, Bayer, JPEG/PNG, H.264/H.265, bandwidth | Image Format Analyzer |
| 4 | RGB & Thermal Camera Fundamentals | Exposure, gain, shutter, radiometric thermal, uint16, AGC, NUC, metadata | RGB/Thermal Characterization |
| 5 | MIPI CSI, ISP & Linux Cameras | CSI-2, D-PHY, lanes, I2C, ISP, V4L2, Media Controller, device tree basics | MIPI Camera Bring-Up |
| 6 | OpenCV, GStreamer & Real-Time Video | cv::Mat, capture, conversion, appsink/appsrc, queues, buffering, dropped frames | Low-Latency Camera Pipeline |
| 7 | Edge Performance & Computer Architecture | CPU/GPU/NPU, RAM/cache, bandwidth, DMA, zero-copy concepts, profiling, throttling | Pipeline Optimizer |
| Final | Phase 1 Capstone | Integration of all Phase 1 skills | Dual RGB + Thermal Edge Camera System |

---

# Part 1 — Embedded Linux & Development Environment

## Topics

### Linux
- Filesystem hierarchy
- Shell basics
- Bash
- Pipes and redirection
- grep, find, awk
- Permissions
- Processes
- systemctl
- journalctl
- dmesg
- /dev
- Package management
- Python virtual environments
- CPU, RAM, storage, kernel, user space

### Remote Development
- SSH
- SSH keys
- SCP
- rsync
- VS Code Remote SSH
- Remote terminal
- Remote C++ and Python development

### C++ Build Environment
- GCC / G++
- Native compilation
- CMake
- Basic GDB
- Git fundamentals

### Cross-Compilation
- x86_64 vs ARM64 / AArch64
- ABI basics
- ELF basics
- file
- ldd
- readelf
- aarch64-linux-gnu-gcc
- aarch64-linux-gnu-g++
- Sysroot
- Cross-compiling dependencies
- CMake toolchain files
- Remote debugging with gdbserver

## Development Modes

### Native
PC → VS Code Remote SSH → Radxa → g++ → executable

### Cross-Compile
x86 PC → ARM64 toolchain → binary → scp/rsync → Radxa

### Later: Containerized Cross-Build
x86 PC → Docker → fixed ARM64 toolchain → Radxa binary

## Mini-Capstone

### Remote Embedded Development Environment

Build a small C++ system-monitor application.

It should report:
- CPU
- RAM
- temperature
- storage
- network interfaces
- attached devices
- available camera devices

Demonstrate:
1. Native build on the Radxa.
2. Cross-compilation on the host.
3. Deployment with rsync/scp.
4. ELF architecture verification.
5. Remote debugging with a breakpoint.

## Quiz Categories
- Linux concepts
- Shell commands
- Device nodes
- Native vs cross-compilation
- ELF / architecture
- CMake
- Sysroot
- Remote debugging

## Exit Criterion

You can connect to a fresh Radxa, inspect it, compile and deploy C++/Python code, cross-compile ARM64 software, and debug remotely.

---

# Part 2 — NumPy, C++ Memory & Tensors

## NumPy
- ndarray
- shape
- ndim
- dtype
- indexing
- slicing
- reshape
- transpose
- broadcasting
- stack
- concatenate
- astype
- contiguous memory
- copy vs view

## C++
- std::vector
- std::array
- std::span
- uint8_t
- uint16_t
- float
- pointers
- references
- sizeof
- data()
- memcpy

## Tensor / Memory Layout
- HWC
- CHW
- NHWC
- NCHW
- Stride
- Contiguous vs non-contiguous data
- Buffer interpretation
- uint8 vs uint16 vs float32

## Mini-Capstone

### Image-to-Tensor Converter

Convert:

640 × 480 × 3 uint8 HWC

to:

1 × 3 × 224 × 224 float32 NCHW

Implement in:
- Python / NumPy
- C++

Operations:
- resize
- BGR → RGB
- uint8 → float32
- normalization
- HWC → CHW
- batch dimension

Compare selected values between both implementations.

## Quiz Categories
- Shapes
- Dtypes
- Memory size
- Layout
- Stride
- Contiguous memory
- Copies vs views

## Exit Criterion

Given any image/tensor shape and dtype, you can explain its memory representation and convert it to a model-ready tensor.

---

# Part 3 — Digital Images & Camera Formats

## Topics

### Common Pixel Formats
- RGB
- BGR
- RGBA
- GRAY8
- YUV
- YUYV / YUY2
- UYVY
- NV12
- NV21

### RAW Formats
- RAW8
- RAW10
- RAW12
- RAW16
- Bayer patterns:
  - RGGB
  - BGGR
  - GRBG
  - GBRG

### Storage and Compression
Understand the difference between:
- Pixel formats: RGB, NV12, RAW10
- Image formats: JPEG, PNG
- Video codecs: H.264, H.265

### Bandwidth
Calculate:
- bytes/frame
- MB/s
- effect of resolution
- effect of FPS
- effect of pixel format

## Mini-Capstone

### Image Format Analyzer

Given several images or camera streams, report:
- resolution
- channels
- dtype
- pixel format
- bytes/frame
- raw bandwidth
- compressed/uncompressed status

## Quiz Categories
- Pixel format identification
- RAW/Bayer
- Codec vs pixel format
- Memory calculations
- Bandwidth calculations

## Exit Criterion

You can inspect a camera or image specification and understand what data is actually being transported and stored.

---

# Part 4 — RGB & Thermal Camera Fundamentals

## RGB Camera Topics
- CMOS sensors
- Resolution
- FPS
- Exposure
- Analog/digital gain
- White balance
- Dynamic range
- Noise
- Rolling shutter
- Global shutter
- Motion blur

## Thermal Camera Topics
- Radiometric vs non-radiometric
- uint8 vs uint16 thermal data
- Temperature calibration
- AGC
- Dynamic range compression
- NUC
- Bad/dead pixels
- Thermal noise
- Palettes / colormaps
- Raw thermal data vs display image

## Metadata
- Timestamp
- Exposure
- Gain
- Frame counter
- Sensor temperature

## Mini-Capstone

### RGB/Thermal Characterization

For one RGB and one thermal camera, report:
- resolution
- FPS
- pixel format
- dtype
- channels
- bytes/frame
- MB/s
- min/max/mean values
- metadata availability

For thermal:
- compare raw/radiometric representation and display/AGC representation where available.

## Quiz Categories
- Exposure vs gain
- Rolling vs global shutter
- Radiometric thermal data
- AGC
- uint8 vs uint16
- Sensor metadata

## Exit Criterion

You can explain what an RGB or thermal sensor outputs and how camera settings affect the data used by AI.

---

# Part 5 — MIPI CSI, ISP & Linux Camera Architecture

## MIPI CSI-2
- MIPI
- CSI-2
- D-PHY
- Data lanes
- Clock lane
- Lane bandwidth
- Virtual channels
- RAW transport
- I2C sensor control

## Camera Pipeline

Sensor
→ MIPI CSI-2
→ CSI receiver
→ ISP
→ memory
→ V4L2
→ application

## ISP
- Black-level correction
- Demosaicing
- White balance
- Noise reduction
- Color correction
- Gamma
- Sharpening
- Auto-exposure concepts

## Linux Camera Stack
- V4L2
- Media Controller
- Subdevices
- /dev/videoX
- /dev/mediaX
- v4l2-ctl
- media-ctl
- dmesg

## Device Tree Basics
- What device tree is
- Sensor configuration
- I2C addresses
- Lane configuration
- Why embedded camera bring-up depends on it

## Mini-Capstone

### MIPI Camera Bring-Up

From reboot:
1. Connect camera.
2. Verify sensor detection.
3. Inspect kernel logs.
4. Inspect media graph.
5. Find video node.
6. Inspect formats.
7. Capture 500 frames.
8. Measure FPS.
9. Record dropped frames.
10. Create a diagnostic report.

## Quiz Categories
- CSI-2
- Lane concepts
- ISP
- V4L2
- Media Controller
- Device tree
- Troubleshooting scenarios

## Exit Criterion

You can bring up and debug a supported MIPI CSI camera without treating the camera stack as a black box.

---

# Part 6 — OpenCV, GStreamer & Real-Time Video

## OpenCV
- cv::Mat
- VideoCapture
- Resize
- Color conversion
- Crop / ROI
- Drawing
- Encoding
- data
- rows / cols / channels
- step
- clone
- shallow vs deep copy
- continuous memory

## Performance
Measure:
- capture time
- color conversion
- resize
- normalization
- copy cost
- display
- total pipeline time

## GStreamer
- Elements
- Pipelines
- Pads
- Caps
- Queues
- Sources
- Sinks
- appsink
- appsrc
- Hardware conversion / decoding concepts

## Real-Time Behavior
- FPS vs latency
- Producer / consumer
- Buffering
- Queue growth
- Frame dropping
- Latest-frame processing
- Throughput vs latency

## Mini-Capstone

### Low-Latency Camera Pipeline

Build:

Camera
→ GStreamer
→ OpenCV
→ resize / conversion
→ display

Measure:
- capture FPS
- processing FPS
- end-to-end latency
- CPU usage
- memory
- dropped frames

Then intentionally slow processing and redesign the pipeline to keep the latest frame rather than accumulate latency.

## Quiz Categories
- cv::Mat memory
- Copy vs view
- GStreamer basics
- appsink / appsrc
- Caps
- FPS vs latency
- Buffer growth

## Exit Criterion

You can build and profile a low-latency camera pipeline and understand why it behaves the way it does.

---

# Part 7 — Edge Performance & Computer Architecture

## Topics
- CPU
- GPU
- NPU
- RAM
- Cache
- Memory bandwidth
- DMA
- Memory copies
- Allocation
- Zero-copy concept
- SIMD
- ARM NEON basics
- CPU utilization
- Thermal throttling

## Profiling Methodology

Always:

Measure → find bottleneck → optimize → measure again

Measure individual pipeline stages:
- capture
- conversion
- resize
- preprocessing
- application logic
- output

## Mini-Capstone

### Pipeline Optimizer

Start with an intentionally inefficient camera application.

Tasks:
1. Establish baseline FPS and latency.
2. Profile each stage.
3. Identify bottlenecks.
4. Reduce unnecessary copies/allocations/conversions.
5. Re-measure.
6. Document performance improvements.

## Quiz Categories
- Latency
- Throughput
- FPS calculations
- Bottleneck analysis
- Memory copies
- DMA / zero-copy concepts
- CPU/NPU roles
- Thermal throttling

## Exit Criterion

You can profile a camera-processing application and make optimization decisions using measurements rather than guesses.

---

# Phase 1 Final Capstone

## Dual RGB + Thermal Edge Camera System

Build a complete non-AI edge vision application.

### Requirements

- Capture RGB video.
- Capture thermal video.
- Identify both pixel formats.
- Timestamp frames.
- Preserve useful thermal representation.
- Convert frames to OpenCV / NumPy representations.
- Display both streams.
- Measure FPS.
- Measure processing latency.
- Detect dropped frames.
- Log camera metadata.
- Record data.
- Implement performance-critical portions in C++.
- Optionally stream output using GStreamer.
- Automatically launch on the device as an extension exercise.

### Final Performance Report

For each stream document:

- Camera/interface
- Resolution
- Pixel format
- dtype
- FPS requested
- FPS measured
- Bytes/frame
- Raw bandwidth
- Processing latency
- CPU usage
- Memory usage
- Dropped frames

---

# Quiz Format for Every Part

Every part should contain four kinds of questions:

1. **Concept questions** — explain what something is and why it matters.
2. **Calculation questions** — memory, FPS, bandwidth, latency.
3. **Code-reading questions** — interpret Python/C++ snippets.
4. **Troubleshooting questions** — diagnose realistic embedded problems.

A part is complete only after:
- Labs are completed.
- Quiz is passed.
- Mini-capstone works.
- Exit criterion can be demonstrated.
