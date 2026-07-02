# gstreamer pipe player

The application play gst pipe that capture vide from camera or other source load multiple plugin for detection and tracking, the final stream the video as rtp udp stream that encode using h264/5
The application control the framerate video bitrate and resolution using crop from home application
The application can play multiple source that control from the cli

- camera
- simulation
- movie

The pipe control dynamically 

## Additional functionality
- TBD



### app cli and config
The cli split to command and command argument

#### Commands
- version: show application version to stdout
- show: show pipe
- run: run 

#### command arguments

| command  | arguments  |
|---|---|
| version | no arguments |
| show  | -c config path |
| run | check sub table |

#### run command arguments

| argument  | description  |
|---|---|
| -s | source  |

#### source 
Source has sub argument depend in source type

- simulation: 
  - topic
- camera
  - device
- file
  - path