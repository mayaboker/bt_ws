# pipeline

This document describe the pipeline capabilities and requirements
The idea is to select source : file, simulation or camera and stream the video as rtp udp stream, the pipeline use h265/h264 encoder
the pipe has many config settings that control how it build
the pipe expose many options to control the pipe dynamic
the command to control dynamic get from bridge that put command in command que for gst loop to execute


the main pipe component build from
- source
- tracker and atr plugins
- tee that split the video and metadata
  - stream branch: encoder -> rtp -> udp
  - debug branch: view the video locally
  - metadata : tracker and atr output send via bridge to other application component



## config

| field          | type              | description             |
| -------------- | ----------------- | ----------------------- |
| source         | camera, sim, file |                         |
| video_local    | bool              | create the debug branch |
| detector       | mapping           | optional red detector and HSV thresholds |
| encode setting | TBD               |                         |
| host           | string            | udp sink host           |
| port           | int               | udp sink port           |
| mtu            | int               | rtp mtu                 |


