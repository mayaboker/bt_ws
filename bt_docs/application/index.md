# Application

![Application architecture](../assets/images/sections/application.png){ .section-hero }

Runtime architecture, flight modes, controllers, communication services, and
application-level integration belong in this section.


## Block diagram

![](images/app_blocks.drawio.png)

## Controllers

![](images/app_controllers.drawio.png)

## State Machine

```mermaid
stateDiagram-v2
    [*] --> IDLE

    IDLE --> ARM
    IDLE --> MANUAL
    IDLE --> ALT_HOLD

    ARM --> MANUAL
    ARM --> TAKEOFF

    MANUAL --> FAILSAFE
    MANUAL --> IDLE
    MANUAL --> ALT_HOLD

    TAKEOFF --> ALT_HOLD
    TAKEOFF --> MANUAL

    ALT_HOLD --> FAILSAFE
    ALT_HOLD --> MANUAL
    ALT_HOLD --> TRACKING

    FAILSAFE --> ALT_HOLD
    FAILSAFE --> IDLE

    TRACKING --> ALT_HOLD

```

### States

| mode  | description  |
|---|---|
| IDLE  | send low pwn to drone (safety mode)  |
| ARM   | send arm sequence to drone  |


---

### Controllers

#### ARM

Send ARM sequence
- ARM / AUX1 and Throttle to pwm min for 1 sec
- ARM / AUX1 to High pwm and Throttle to Mon pwm for 2 sec

!!! 
    Hold ARM hight until disarmed


!!!
    Aux1 must config to ARM in betaflight configure

    ![alt text](images/bt_modes.png)

!!!
    The system set ARM and init in ANGEL mode

#### rc_channel_override
The controller open mavlink udp socket and listen to rc_channel_override message

#### Manual

Manual mode pass through joystick request , 

TODO: what about acro
TODO: what about payload

