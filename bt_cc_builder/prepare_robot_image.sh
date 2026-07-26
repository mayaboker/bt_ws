#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_INVENTORY="$SCRIPT_DIR/inventory.yml"
DEFAULT_PLAYBOOK="$SCRIPT_DIR/robot.yml"
DEFAULT_OUTPUT_DIR="$SCRIPT_DIR/images"
DEFAULT_EXTRA_SIZE="8G"
ROOT_MOUNT="/mnt/robot-root"
BOOT_MOUNT="/mnt/robot-boot"
SOURCE_DIALOG_TITLE="Select source Raspberry Pi image"
OUTPUT_DIALOG_TITLE="Choose output image file"
DONE_DIALOG_TITLE="Raspberry Pi image prepared"
SOURCE_FILE_FILTER_LABEL="Image files"
SOURCE_FILE_FILTER_PATTERNS="*.img *.IMG *.img.xz *.IMG.XZ *.zip *.ZIP"
OUTPUT_FILE_FILTER_LABEL="Image files"
OUTPUT_FILE_FILTER_PATTERNS="*.img *.IMG"

SOURCE_IMAGE=""
OUTPUT_IMAGE=""
OUTPUT_DIR="$DEFAULT_OUTPUT_DIR"
EXTRA_SIZE="$DEFAULT_EXTRA_SIZE"
INVENTORY="$DEFAULT_INVENTORY"
PLAYBOOK="$DEFAULT_PLAYBOOK"
KEEP_MOUNTED=0
RUN_ANSIBLE=1
ASK_OUTPUT=0
GROW_IMAGE=1
LOOP_DEV=""
ROOT_PART=""
ROOT_PART_NUM=""
BOOT_PART=""
MOUNTED_ROOT=0
MOUNTED_BOOT=0
COPIED_QEMU=""
RESOLV_BACKUP=""
RESOLV_REPLACED=0

usage() {
  cat <<'EOF'
Usage:
  ./prepare_robot_image.sh [options]

Options:
  -s, --source PATH       Source image: .img, .img.xz, or .zip containing one .img
  -o, --output PATH       Output image path. Default: ./images/<source>-prepared-<time>.img
  -d, --output-dir DIR    Output directory when --output is not set
      --extra-size SIZE   Add free space to copied image. Default: 8G
      --no-grow          Do not grow the copied image/root filesystem
  -p, --playbook PATH     Ansible playbook. Default: ./robot.yml
  -i, --inventory PATH    Ansible inventory. Default: ./inventory.yml
      --ask-output        Open a GUI save dialog for the output image path
      --mount-only        Copy and mount image, but do not run Ansible
      --keep-mounted      Leave loop device and mounts active after finishing
  -h, --help              Show this help

The script uses yad, zenity, or kdialog for file dialogs when available and no source is given.
It must use sudo for loop setup, mounts, chroot preparation, and Ansible.
EOF
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

info() {
  printf '\n==> %s\n' "$*"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

real_path() {
  local path="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath -m "$path"
  else
    readlink -f "$path"
  fi
}

select_source_with_gui() {
  if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    return 1
  fi

  if command -v yad >/dev/null 2>&1; then
    yad --file-selection \
      --title="$SOURCE_DIALOG_TITLE" \
      --file-filter="$SOURCE_FILE_FILTER_LABEL | $SOURCE_FILE_FILTER_PATTERNS" \
      --file-filter="All files | *"
  elif command -v zenity >/dev/null 2>&1; then
    zenity --file-selection \
      --title="$SOURCE_DIALOG_TITLE" \
      --file-filter="$SOURCE_FILE_FILTER_LABEL | $SOURCE_FILE_FILTER_PATTERNS" \
      --file-filter="All files | *"
  elif command -v kdialog >/dev/null 2>&1; then
    kdialog --title "$SOURCE_DIALOG_TITLE" \
      --getopenfilename "$HOME" "$SOURCE_FILE_FILTER_LABEL ($SOURCE_FILE_FILTER_PATTERNS)"
  else
    return 1
  fi
}

select_output_with_gui() {
  if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    return 1
  fi

  if command -v yad >/dev/null 2>&1; then
    yad --file-selection --save --confirm-overwrite \
      --title="$OUTPUT_DIALOG_TITLE" \
      --filename="$1" \
      --file-filter="$OUTPUT_FILE_FILTER_LABEL | $OUTPUT_FILE_FILTER_PATTERNS" \
      --file-filter="All files | *"
  elif command -v zenity >/dev/null 2>&1; then
    zenity --file-selection --save --confirm-overwrite \
      --title="$OUTPUT_DIALOG_TITLE" \
      --filename="$1" \
      --file-filter="$OUTPUT_FILE_FILTER_LABEL | $OUTPUT_FILE_FILTER_PATTERNS" \
      --file-filter="All files | *"
  elif command -v kdialog >/dev/null 2>&1; then
    kdialog --title "$OUTPUT_DIALOG_TITLE" \
      --getsavefilename "$1" "$OUTPUT_FILE_FILTER_LABEL ($OUTPUT_FILE_FILTER_PATTERNS)"
  else
    return 1
  fi
}

notify_gui() {
  local title="$1"
  local text="$2"
  if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    return
  fi

  if command -v yad >/dev/null 2>&1; then
    yad --info --title="$title" --text="$text" --button=OK:0 >/dev/null 2>&1 || true
  elif command -v zenity >/dev/null 2>&1; then
    zenity --info --title="$title" --text="$text" >/dev/null 2>&1 || true
  elif command -v kdialog >/dev/null 2>&1; then
    kdialog --title "$title" --msgbox "$text" >/dev/null 2>&1 || true
  fi
}

parse_args() {
  while (($#)); do
    case "$1" in
      -s|--source)
        SOURCE_IMAGE="${2:-}"
        [[ -n "$SOURCE_IMAGE" ]] || die "$1 requires a path"
        shift 2
        ;;
      -o|--output)
        OUTPUT_IMAGE="${2:-}"
        [[ -n "$OUTPUT_IMAGE" ]] || die "$1 requires a path"
        shift 2
        ;;
      -d|--output-dir)
        OUTPUT_DIR="${2:-}"
        [[ -n "$OUTPUT_DIR" ]] || die "$1 requires a directory"
        shift 2
        ;;
      --extra-size)
        EXTRA_SIZE="${2:-}"
        [[ -n "$EXTRA_SIZE" ]] || die "$1 requires a size, for example 8G"
        shift 2
        ;;
      --no-grow)
        GROW_IMAGE=0
        shift
        ;;
      -p|--playbook)
        PLAYBOOK="${2:-}"
        [[ -n "$PLAYBOOK" ]] || die "$1 requires a path"
        shift 2
        ;;
      -i|--inventory)
        INVENTORY="${2:-}"
        [[ -n "$INVENTORY" ]] || die "$1 requires a path"
        shift 2
        ;;
      --mount-only)
        RUN_ANSIBLE=0
        shift
        ;;
      --ask-output)
        ASK_OUTPUT=1
        shift
        ;;
      --keep-mounted)
        KEEP_MOUNTED=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "unknown option: $1"
        ;;
    esac
  done
}

default_output_path() {
  local source="$1"
  local base stamp
  base="$(basename "$source")"
  base="${base%.xz}"
  base="${base%.zip}"
  base="${base%.img}"
  stamp="$(date +%Y%m%d-%H%M%S)"
  printf '%s/%s-prepared-%s.img\n' "$OUTPUT_DIR" "$base" "$stamp"
}

rerun_with_sudo_if_needed() {
  if ((EUID == 0)); then
    return
  fi

  mkdir -p "$(dirname "$OUTPUT_IMAGE")"
  need_cmd sudo
  info "Requesting sudo for loop devices, mounts, chroot setup, and Ansible"
  exec sudo -E bash "$0" \
    --source "$SOURCE_IMAGE" \
    --output "$OUTPUT_IMAGE" \
    --inventory "$INVENTORY" \
    --playbook "$PLAYBOOK" \
    --extra-size "$EXTRA_SIZE" \
    $([[ "$GROW_IMAGE" -eq 0 ]] && printf '%s\n' "--no-grow") \
    $([[ "$ASK_OUTPUT" -eq 1 ]] && printf '%s\n' "--ask-output") \
    $([[ "$RUN_ANSIBLE" -eq 0 ]] && printf '%s\n' "--mount-only") \
    $([[ "$KEEP_MOUNTED" -eq 1 ]] && printf '%s\n' "--keep-mounted")
}

cleanup() {
  local exit_code=$?

  if ((KEEP_MOUNTED)); then
    if [[ -n "$LOOP_DEV" ]]; then
      printf '\nKept mounted:\n  root: %s\n  boot: %s\n  loop: %s\n' "$ROOT_MOUNT" "$BOOT_MOUNT" "$LOOP_DEV"
    fi
    exit "$exit_code"
  fi

  set +e
  if [[ -n "$COPIED_QEMU" && -e "$COPIED_QEMU" ]]; then
    rm -f "$COPIED_QEMU"
  fi
  if ((RESOLV_REPLACED)); then
    rm -f "$ROOT_MOUNT/etc/resolv.conf"
    if [[ -n "$RESOLV_BACKUP" && -e "$RESOLV_BACKUP" ]]; then
      mv "$RESOLV_BACKUP" "$ROOT_MOUNT/etc/resolv.conf"
    fi
  fi
  mountpoint -q "$ROOT_MOUNT/dev/pts" && umount "$ROOT_MOUNT/dev/pts"
  mountpoint -q "$ROOT_MOUNT/dev" && umount "$ROOT_MOUNT/dev"
  mountpoint -q "$ROOT_MOUNT/proc" && umount "$ROOT_MOUNT/proc"
  mountpoint -q "$ROOT_MOUNT/sys" && umount "$ROOT_MOUNT/sys"
  if ((MOUNTED_BOOT)); then
    mountpoint -q "$BOOT_MOUNT" && umount "$BOOT_MOUNT"
  fi
  if ((MOUNTED_ROOT)); then
    mountpoint -q "$ROOT_MOUNT" && umount "$ROOT_MOUNT"
  fi
  if [[ -n "$LOOP_DEV" ]]; then
    losetup -d "$LOOP_DEV"
  fi
  exit "$exit_code"
}

copy_source_image() {
  local source="$1"
  local dest="$2"
  local lower="${source,,}"

  mkdir -p "$(dirname "$dest")"
  case "$lower" in
    *.img)
      info "Copying source image"
      cp --sparse=always "$source" "$dest"
      ;;
    *.img.xz)
      need_cmd xz
      info "Decompressing source image"
      xz -dc "$source" > "$dest"
      ;;
    *.zip)
      need_cmd unzip
      info "Extracting image from zip"
      local img_count
      img_count="$(unzip -Z1 "$source" '*.img' 2>/dev/null | wc -l)"
      [[ "$img_count" -eq 1 ]] || die "zip must contain exactly one .img file; found $img_count"
      unzip -p "$source" '*.img' > "$dest"
      ;;
    *)
      die "unsupported source type. Use .img, .img.xz, or .zip"
      ;;
  esac
}

copy_qemu_if_needed() {
  local host_arch image_arch shell_info qemu_name qemu_bin

  host_arch="$(uname -m)"
  image_arch="$(chroot "$ROOT_MOUNT" /bin/sh -c 'uname -m' 2>/dev/null || true)"
  if [[ -n "$image_arch" ]]; then
    return
  fi
  if [[ "$host_arch" == aarch64 || "$host_arch" == arm* ]]; then
    die "chroot is not executable even though host architecture appears ARM"
  fi

  need_cmd file
  shell_info="$(file -L "$ROOT_MOUNT/bin/sh")"
  case "$shell_info" in
    *ARM\ aarch64*|*ARM64*|*aarch64*)
      qemu_name="qemu-aarch64-static"
      ;;
    *ARM*)
      qemu_name="qemu-arm-static"
      ;;
    *)
      die "cannot determine image CPU architecture from $ROOT_MOUNT/bin/sh"
      ;;
  esac

  qemu_bin="$(command -v "$qemu_name" || true)"
  [[ -n "$qemu_bin" ]] || die "missing $qemu_name. Install qemu-user-static and binfmt-support"
  cp "$qemu_bin" "$ROOT_MOUNT/usr/bin/$qemu_name"
  COPIED_QEMU="$ROOT_MOUNT/usr/bin/$qemu_name"

  image_arch="$(chroot "$ROOT_MOUNT" /bin/sh -c 'uname -m' 2>/dev/null || true)"
  [[ -n "$image_arch" ]] || die "chroot is not executable. Check binfmt-support registration for $qemu_name"
}

detect_partitions() {
  local loop="$1"
  local name type fstype size partn root_name="" root_size=0 root_partn="" boot_name=""

  while read -r name type fstype size partn; do
    [[ "$type" == "part" ]] || continue
    case "$fstype" in
      ext2|ext3|ext4)
        if ((size > root_size)); then
          root_name="$name"
          root_size="$size"
          root_partn="$partn"
        fi
        ;;
      vfat|fat16|fat32)
        if [[ -z "$boot_name" ]]; then
          boot_name="$name"
        fi
        ;;
    esac
  done < <(lsblk -rpnbo NAME,TYPE,FSTYPE,SIZE,PARTN "$loop")

  [[ -n "$root_name" ]] || die "could not find an ext root partition in $loop"
  [[ -n "$root_partn" ]] || die "could not determine root partition number for $root_name"
  ROOT_PART="$root_name"
  ROOT_PART_NUM="$root_partn"
  BOOT_PART=""
  if [[ -n "$boot_name" ]]; then
    BOOT_PART="$boot_name"
  fi
}

grow_image_and_rootfs() {
  if ((GROW_IMAGE == 0)); then
    info "Skipping image growth because --no-grow was requested"
    return
  fi

  need_cmd truncate
  need_cmd parted
  need_cmd e2fsck
  need_cmd resize2fs

  info "Adding $EXTRA_SIZE free space to copied image"
  truncate -s "+$EXTRA_SIZE" "$OUTPUT_IMAGE"

  info "Growing root partition $ROOT_PART to fill image"
  parted -s "$LOOP_DEV" resizepart "$ROOT_PART_NUM" 100%
  partprobe "$LOOP_DEV" >/dev/null 2>&1 || true
  blockdev --rereadpt "$LOOP_DEV" >/dev/null 2>&1 || true
  sleep 1

  info "Growing root filesystem on $ROOT_PART"
  e2fsck -fy "$ROOT_PART"
  resize2fs "$ROOT_PART"
}

prepare_chroot() {
  info "Preparing chroot bind mounts"
  mount --bind /dev "$ROOT_MOUNT/dev"
  mount --bind /dev/pts "$ROOT_MOUNT/dev/pts"
  mount -t proc proc "$ROOT_MOUNT/proc"
  mount -t sysfs sys "$ROOT_MOUNT/sys"

  if [[ -e "$ROOT_MOUNT/etc/resolv.conf" || -L "$ROOT_MOUNT/etc/resolv.conf" ]]; then
    RESOLV_BACKUP="$ROOT_MOUNT/etc/resolv.conf.bt_cc_builder_backup"
    mv "$ROOT_MOUNT/etc/resolv.conf" "$RESOLV_BACKUP"
  fi
  cp --remove-destination /etc/resolv.conf "$ROOT_MOUNT/etc/resolv.conf"
  RESOLV_REPLACED=1

  copy_qemu_if_needed
}

run_ansible() {
  need_cmd ansible-playbook
  info "Running Ansible playbook"
  ansible-playbook -i "$INVENTORY" "$PLAYBOOK"
}

restore_output_owner() {
  if [[ -n "${SUDO_UID:-}" && -n "${SUDO_GID:-}" && -e "$OUTPUT_IMAGE" ]]; then
    chown "$SUDO_UID:$SUDO_GID" "$OUTPUT_IMAGE"
  fi
}

main() {
  parse_args "$@"

  if [[ -z "$SOURCE_IMAGE" ]]; then
    SOURCE_IMAGE="$(select_source_with_gui || true)"
  fi
  [[ -n "$SOURCE_IMAGE" ]] || die "no source image selected. Install yad, zenity, or kdialog, or pass --source /path/to/image.img"
  [[ -f "$SOURCE_IMAGE" ]] || die "source image does not exist: $SOURCE_IMAGE"

  SOURCE_IMAGE="$(real_path "$SOURCE_IMAGE")"
  INVENTORY="$(real_path "$INVENTORY")"
  PLAYBOOK="$(real_path "$PLAYBOOK")"
  [[ -f "$INVENTORY" ]] || die "inventory not found: $INVENTORY"
  [[ -f "$PLAYBOOK" ]] || die "playbook not found: $PLAYBOOK"

  if [[ -z "$OUTPUT_IMAGE" ]]; then
    OUTPUT_IMAGE="$(default_output_path "$SOURCE_IMAGE")"
    if ((ASK_OUTPUT)); then
      OUTPUT_IMAGE="$(select_output_with_gui "$OUTPUT_IMAGE" || printf '%s\n' "$OUTPUT_IMAGE")"
    fi
  fi
  [[ -n "$OUTPUT_IMAGE" ]] || die "no output image selected"
  OUTPUT_IMAGE="$(real_path "$OUTPUT_IMAGE")"
  [[ "$OUTPUT_IMAGE" != "$SOURCE_IMAGE" ]] || die "output image must be different from source image"

  rerun_with_sudo_if_needed

  need_cmd losetup
  need_cmd lsblk
  need_cmd mount
  need_cmd umount
  need_cmd chroot

  trap cleanup EXIT INT TERM

  copy_source_image "$SOURCE_IMAGE" "$OUTPUT_IMAGE"

  info "Attaching image to loop device"
  LOOP_DEV="$(losetup --find --partscan --show "$OUTPUT_IMAGE")"
  partprobe "$LOOP_DEV" >/dev/null 2>&1 || true
  sleep 1

  detect_partitions "$LOOP_DEV"
  grow_image_and_rootfs

  info "Mounting root partition $ROOT_PART"
  mkdir -p "$ROOT_MOUNT" "$BOOT_MOUNT"
  mount "$ROOT_PART" "$ROOT_MOUNT"
  MOUNTED_ROOT=1

  if [[ -n "${BOOT_PART:-}" ]]; then
    info "Mounting boot partition $BOOT_PART"
    mount "$BOOT_PART" "$BOOT_MOUNT"
    MOUNTED_BOOT=1
  fi

  prepare_chroot

  if ((RUN_ANSIBLE)); then
    run_ansible
  else
    info "Skipping Ansible because --mount-only was requested"
  fi

  sync
  restore_output_owner
  notify_gui "$DONE_DIALOG_TITLE" "Prepared image:\n$OUTPUT_IMAGE"
  info "Prepared image: $OUTPUT_IMAGE"
}

main "$@"
