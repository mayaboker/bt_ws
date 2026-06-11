#!/bin/bash
export GZ_IP=127.0.0.1
export GZ_SIM_SYSTEM_PLUGIN_PATH="${PWD}/bt_gazebo/bin:${env:GZ_SIM_SYSTEM_PLUGIN_PATH}"
export GZ_SIM_RESOURCE_PATH="${PWD}/bt_gazebo/models:${PWD}/bt_gazebo/worlds:${env:GZ_SIM_RESOURCE_PATH}"

kill -9 "$(pgrep -f 'gz sim server' | head -n1)"
gz sim -v 1 -r betaloop_iris_betaflight_demo_harmonic.sdf