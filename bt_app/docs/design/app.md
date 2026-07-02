

### app cli and config
The cli split to command and command argument

#### Commands
- version: show application version to stdout
- run: run joystick application that read config override with cli argument read joystick input map and send udp packet to server

#### command arguments

| command  | arguments  |
|---|---|
| version | no arguments |
| run | check sub table |

#### run command arguments

| argument  | description  |
|---|---|
| -c | config path  |
