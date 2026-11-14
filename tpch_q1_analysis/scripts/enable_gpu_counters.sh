#!/usr/bin/env bash
# Permanently allow non-admin users to read NVIDIA GPU performance counters (needed by ncu).
# Takes effect after a reboot.
set -euo pipefail
echo 'options nvidia NVreg_RestrictProfilingToAdminUsers=0' | sudo tee /etc/modprobe.d/nvidia-profiling.conf
sudo dracut -f
echo "Done. Reboot, then check: grep RmProfilingAdminOnly /proc/driver/nvidia/params (should be 0)"
