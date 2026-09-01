#!/usr/bin/env bash

options=("sim" "app" "bt-app" "joy" "analysis")

select choice in "${options[@]}"; do
  case "$choice" in
    sim) tmuxp load bt_bringup/launch/sim.yaml ;;
    app) tmuxp load bt_bringup/launch/app.yaml ;;
    bt-app) ./bt_bringup/launch/run_bt_app.sh ;;
    joy) tmuxp load bt_bringup/launch/joy.yaml ;;
    analysis) ./bt_bringup/launch/run_analysis.sh ;;
    *) echo "invalid option" ;;
  esac
done
