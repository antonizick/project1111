# Clean-install test image: stock Arch Linux, a normal user with passwordless sudo (like a desktop
# user who types their password), and nothing else. Used by tests/install/run.sh.
FROM archlinux:base
# The packages install.sh would ask for are installed here, not by the script: with `--gpus all` the
# NVIDIA runtime injects host files such as /usr/lib/libGLX_indirect.so.0, which makes pacman fail
# on mesa (a container artefact, not an installer problem). The pacman step is covered by
# tests/unit/test_install_scripts.py with a fake pacman and sudo.
RUN pacman -Syu --noconfirm --needed sudo git ffmpeg curl diffutils xdg-utils nodejs npm uv && useradd -m tester \
    && echo 'tester ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/tester
USER tester
WORKDIR /home/tester
