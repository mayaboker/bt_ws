#!/bin/bash
export GZ_IP=127.0.0.1
export GZ_SIM_SYSTEM_PLUGIN_PATH="${PWD}/bt_gazebo/bin:${env:GZ_SIM_SYSTEM_PLUGIN_PATH}"
export GZ_SIM_RESOURCE_PATH="${PWD}/bt_gazebo/models:${PWD}/bt_gazebo/worlds:${env:GZ_SIM_RESOURCE_PATH}"
# export __NV_PRIME_RENDER_OFFLOAD=1
# export __GLX_VENDOR_LIBRARY_NAME=nvidia
kill -9 "$(pgrep -f 'gz sim server' | head -n1)"
gz sim -v 3 -r betaloop_iris_betaflight_demo_harmonic.sdf