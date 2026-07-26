```
sudo -E ansible \
    -i inventory.yml \
    robot_image \
    -m ansible.builtin.command \
    -a "uname -m"
```