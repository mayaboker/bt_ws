```
sudo -E ansible \
    -i inventory.yml \
    robot_image \
    -m ansible.builtin.command \
    -a "uname -m"
```

## Prepare a Raspberry Pi image

Use the helper script to choose a source image, copy it, mount the copied root
partition at `/mnt/robot-root`, and run `robot.yml` through Ansible chroot.
The copied image is expanded by 8G by default so package installs have room:

```bash
./prepare_robot_image.sh
```

With explicit paths:

```bash
./prepare_robot_image.sh \
  --source ~/Downloads/raspios.img.xz \
  --output ./images/robot.img
```

To choose the output image path with a second GUI save dialog:

```bash
./prepare_robot_image.sh --ask-output
```

To add a different amount of free space:

```bash
./prepare_robot_image.sh --extra-size 4G
```

Optional GUI file dialogs use `yad`, `zenity`, or `kdialog` when one is
installed. Required host tools:
`sudo`, `losetup`, `mount`, `umount`, `lsblk`, `ansible-playbook`, and for ARM
images on x86 hosts, `qemu-user-static`/`binfmt-support`.

## Run Ansible over SSH

After booting the prepared image, use `inventory_ssh.yml` to run against the
robot over SSH.

```bash
ANSIBLE_CONFIG=./ansible.cfg ansible \
  -i inventory_ssh.yml \
  robot_image \
  -e ansible_become=false \
  -m ping
```

Run the playbook over SSH. This playbook installs packages and edits system
files, so it needs sudo on the robot:

```bash
ANSIBLE_CONFIG=./ansible.cfg ansible-playbook \
  -i inventory_ssh.yml \
  --ask-become-pass \
  robot.yml
```

Override the host without editing the inventory:

```bash
ANSIBLE_CONFIG=./ansible.cfg ansible \
  -i inventory_ssh.yml \
  robot_image \
  -e ansible_become=false \
  -e ansible_host=192.168.1.42 \
  -m ansible.builtin.command \
  -a "uname -m"
```

Run one sudo command over SSH:

```bash
ANSIBLE_CONFIG=./ansible.cfg ansible-playbook \
    -i inventory_ssh.yml \
    --ask-become-pass \
    robot.yml
```
