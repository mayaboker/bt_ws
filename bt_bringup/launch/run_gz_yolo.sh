#!/bin/bash

export GZ_SIM_SYSTEM_PLUGIN_PATH="/workspace/bt_gazebo/bin:${env:GZ_SIM_SYSTEM_PLUGIN_PATH}"
export GZ_SIM_RESOURCE_PATH="/home/user/projects/bt_ws/bt_gazebo/models:/home/user/projects/bt_ws/bt_gazebo/worlds:${env:GZ_SIM_RESOURCE_PATH}"

kill -9 "$(pgrep -f 'gz sim server' | head -n1)"
gz sim -v 4 -r yolo_car_targets.sdf

