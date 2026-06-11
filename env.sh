echo '🚀 Environment ready!'
# bash key bindings
# replace bringup with full bringup name
bind '"\C-b": "bt_bringup/launch/launch.sh\n"'

# Function to get git branch
parse_git_branch() {
    git branch 2> /dev/null | sed -e '/^[^*]/d' -e 's/* \(.*\)/[\1]/'
}

alias kill_app="tmux kill-session -t app"
# Custom PS1 with rocket icon and git branch
export PS1="🚀 \[\033[32m\]\u@\h\[\033[00m\]:\[\033[34m\]\w\[\033[33m\]\$(parse_git_branch)\[\033[00m\]\$ "
