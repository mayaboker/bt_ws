
# milestone #1
- [x] read the app.md in design folder and create cli.py that support all command and sub arguments
- [x] create main app.py that use as entry point the module use the cli and run the correct command module
- [x] create config object and yaml example
- [x] load the config and merge with cli


# milestone #2
- [x] add main gst loop that load the pipe and play it
- [x] create module the has responsibility to build the pipe


# milestone #3
- [x] add H.264 RTP/UDP stream branch
- [x] add optional local debug video branch controlled by config
- [x] add stream config fields: video_local, codec, host, port, mtu
- [x] keep tracker/ATR and metadata bridge branches deferred


# milestone #4
- [x] add simulation source using native `gzimgsrc`
- [x] add simulation source rate config
- [x] configure GStreamer plugin path in active runtime
- [x] keep Gazebo Python modules as optional runtime dependencies
