#!/usr/bin/env bash

options=("sim" "app" "joy")

select choice in "${options[@]}"; do
  case "$choice" in
    sim) tmuxp load bt_bringup/launch/sim.yaml ;;
    app) tmuxp load bt_bringup/launch/app.yaml ;;
    joy) tmuxp load bt_bringup/launch/joy.yaml ;;
    *) echo "invalid option" ;;
  esac
done