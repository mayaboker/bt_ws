# NanoTrack / Siamese Tracking — Simple Explanation

Think of NanoTrack/Siamese tracking like this:

You show the tracker an object once, for example a car:

```text
Frame 1:

        +--------+
        |  CAR   |    <- you give this box to tracker
        +--------+
```

Then for every new video frame, the tracker asks:

> “Where inside this new image is something that looks most like the car I was given?”

That is the basic idea behind **Siamese tracking**.

NanoTrack is a very small, fast Siamese tracker designed for embedded/mobile hardware. It is based mainly on ideas from SiamBAN and LightTrack and uses a lightweight MobileNetV3 backbone.

---

## 1. First frame: make a memory of the object

Suppose your first frame is:

```text
+----------------------------------+
|                                  |
|        +--------+                |
|        |  CAR   |                |
|        +--------+                |
|                                  |
+----------------------------------+
```

You tell NanoTrack:

```text
track this rectangle
```

NanoTrack crops a small image around the car. This crop is usually called the **template**:

```text
Template image
+------------+
|            |
|    CAR     |
|            |
+------------+
```

The template is normally fairly small, commonly around `127×127` in Siamese-style trackers.

It then sends that image through a neural network:

```text
Template
   |
   v
MobileNetV3
   |
   v
Template features
```

The important point is that the neural network does **not** simply remember the RGB pixels.

It converts the car into a compact numerical description called a **feature map**.

You can imagine:

```text
pixels:

red, gray, black, edges, wheels...

             ↓ neural network

features:

[0.3, 1.2, -0.4, 0.8, ...]
```

These features represent things useful for recognizing the object.

---

## 2. Next frame: don't search the entire image

Now the car moves:

```text
Frame 2

+----------------------------------+
|                                  |
|                    +--------+    |
|                    |  CAR   |    |
|                    +--------+    |
|                                  |
+----------------------------------+
```

NanoTrack already knows approximately where the car was.

So instead of checking the entire image, it takes a **larger crop around the previous position**.

This is called the **search image**:

```text
Search image

+-----------------------------+
|                             |
|             +-----+         |
|             | CAR |         |
|             +-----+         |
|                             |
+-----------------------------+
```

This is one major reason trackers can be extremely fast.

A detector like YOLO typically asks:

```text
What objects exist anywhere in this whole image?
```

NanoTrack asks a much easier question:

```text
Where is MY object near where it was one frame ago?
```

---

## 3. The "Siamese" part

Now comes the important part.

Both images go through essentially the **same feature extractor**:

```text
             same network
                 |
      +----------+----------+
      |                     |
      v                     v

 TEMPLATE                 SEARCH
    |                       |
    v                       v
MobileNetV3              MobileNetV3
    |                       |
    v                       v
Template features       Search features
```

They share weights.

That is why it is called a **Siamese network** — like identical twins.

The two branches perform the same kind of feature extraction.

---

## 4. Compare template against search

The network then tries to find where the template features best match the search features.

Conceptually:

```text
Template feature

       ↓

      MATCH

       ↓

Search feature map
```

Imagine that NanoTrack checks many possible positions:

```text
search area

+-----------------------------+
|  .   .   .   .   .         |
|                             |
|  .   .   X   .   .         |
|                             |
|  .   .   .   .   .         |
+-----------------------------+
```

The `X` gets the strongest score because the object's features match there.

You can think of the result as a heat map:

```text
0.1  0.1  0.2  0.1
0.1  0.3  0.6  0.2
0.2  0.5  0.95 0.3
0.1  0.2  0.3  0.1
```

The `0.95` location probably contains your car.

This comparison operation in Siamese trackers is often implemented using **cross-correlation**.

For now, think:

```text
cross correlation ≈ slide the remembered object's features
                    over the search features
                    and measure similarity
```

---

## 5. But we need more than the center

Finding:

```text
"The object is probably HERE"
```

isn't enough.

We want:

```text
x
y
width
height
```

So NanoTrack has a **tracking head**.

Very roughly, it produces two outputs:

```text
                  comparison
                      |
             +--------+--------+
             |                 |
             v                 v
       classification      regression
             |                 |
             v                 v
       "object here?"    "what size box?"
```

### Classification

For each candidate location:

```text
Is the target here?
```

Example:

```text
0.02 0.05 0.10
0.10 0.93 0.20
0.04 0.15 0.05
```

`0.93` wins.

### Regression

At that location the network predicts approximately:

```text
left distance
top distance
right distance
bottom distance
```

which becomes:

```text
+----------------+
|                |
|      CAR       |
|                |
+----------------+
```

So the network returns the new bounding box.

---

## 6. The complete loop

This is the most useful mental picture:

```text
FRAME 1
                         ┌──────────────┐
Object bounding box ---> │ Template crop│
                         └──────┬───────┘
                                │
                                v
                          MobileNetV3
                                │
                                v
                        Template features
                                │
                                │ save
                                v


FRAME 2
Previous object position
           |
           v
    Search crop
           |
           v
     MobileNetV3
           |
           v
    Search features
           |
           +--------------------+
                                |
Template features --------------+
                                |
                                v
                           compare
                                |
                         Tracking Head
                         /           \
                        /             \
                       v               v
               classification      regression
                       \               /
                        \             /
                         v           v
                         New bbox
                            |
                            v
                     previous position
                         for Frame 3
```

And repeat:

```text
Frame 1 → initialize
Frame 2 → track
Frame 3 → track
Frame 4 → track
...
```

---

## 7. Why doesn't it need YOLO?

This distinction is very important.

A detector has to solve:

```text
"What objects are present?"

dog?
car?
person?
bike?
truck?
where?
```

A Siamese tracker already knows:

```text
THIS is what I'm interested in.
```

So its problem is:

```text
"Find something that looks like THIS."
```

The tracker doesn't really need to understand that the template is a **car**.

You could give it:

```text
car
person
drone
ball
box
logo
```

Its task is basically similarity matching.

---

## 8. Why is NanoTrack so small?

NanoTrack intentionally uses a lightweight architecture.

For example, NanoTrackV1 uses a small MobileNetV3-based backbone and a small tracking head.

This makes the architecture attractive for embedded hardware such as Rockchip NPUs:

```text
small input
     ↓
small MobileNetV3
     ↓
small feature maps
     ↓
simple matching
     ↓
small classification/regression head
```

Instead of a heavier detector pipeline:

```text
large full image
     ↓
large detector
     ↓
hundreds/thousands of candidate objects
     ↓
NMS
     ↓
tracking
```

---

## 9. One important weakness: tracker drift

Suppose you track this red car:

```text
template

+---------+
| RED CAR |
+---------+
```

Then it passes behind a building.

When it comes back there are five similar red cars:

```text
🚗   🚗   🚗   🚗   🚗
```

NanoTrack can choose the wrong one.

Why?

Because it is mainly using:

```text
appearance similarity
+
near previous location
```

It does **not** have the same long-term reasoning or re-identification ability that a more complicated tracking system may have.

This is called **tracker drift**.

---

## 10. The three concepts to learn first

Don't worry yet about all the names such as SiamFC, SiamRPN, SiamRPN++, SiamMask, SiamBAN and LightTrack.

First understand only these three ideas:

1. **Backbone** — turns an image into useful features.
2. **Template vs search image** — template says *what to find*; search says *where to look*.
3. **Head** — compares them and produces a score plus bounding box.

If those are clear, you understand most of the basic idea behind NanoTrack.

---

## 11. NanoTrack in one sentence

> **NanoTrack remembers the features of the object you selected, looks for similar features near the previous position in every new frame, and predicts the new bounding box.**

---

## 12. Useful next step for RKNN

For an RKNN / Rockchip implementation, the next useful step is to inspect the actual NanoTrack model tensor-by-tensor:

```text
Template RGB image
      ↓
Template backbone
      ↓
Template feature tensor
      ↓
                        \
                         → Tracking Head → cls + bbox
                        /
Search RGB image
      ↓
Search backbone
      ↓
Search feature tensor
```

The important implementation questions are then:

- What is the exact template input shape?
- What is the exact search input shape?
- What tensors come out of the backbone?
- Which tensors must be saved between frames?
- What are the classification output dimensions?
- What are the regression output dimensions?
- Which parts should run on RKNN/NPU?
- Which post-processing should run on the CPU?

Those are the key details for turning NanoTrack from a neural-network idea into a practical Rockchip tracker.
