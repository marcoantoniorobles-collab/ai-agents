#!/bin/bash
set -e

if [ "${ENABLE_VNC}" = "true" ]; then
    echo "ENABLE_VNC=true: iniciando Xvfb + fluxbox + x11vnc + noVNC..."
    rm -f /tmp/.X99-lock
    Xvfb :99 -screen 0 1280x800x24 &
    sleep 1
    export DISPLAY=:99
    fluxbox >/tmp/fluxbox.log 2>&1 &
    x11vnc -display :99 -forever -nopw -shared -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
    websockify --web=/usr/share/novnc 6080 localhost:5900 >/tmp/novnc.log 2>&1 &
    echo "noVNC disponible en el puerto 6080 (/vnc.html)"
fi

exec python -m agent_runtime.run_agent
