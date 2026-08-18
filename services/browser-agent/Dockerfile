# Imagen oficial de Playwright: trae Python + Chromium + dependencias del
# sistema ya instaladas y en la versión correcta entre sí. No reinstalar
# playwright por pip con otra versión: rompería esa compatibilidad.
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

USER root

# DEBIAN_FRONTEND=noninteractive + TZ evita que tzdata (dependencia de los
# paquetes de VNC) pregunte interactivamente la zona horaria durante el
# build, lo cual colgaría el proceso sin input posible.
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Lima

# Xvfb + x11vnc + noVNC: permiten ver el Chrome de este agente en vivo desde
# un navegador (vía ENABLE_VNC=true). Si ENABLE_VNC=false, start.sh nunca
# arranca estos procesos, así que no consumen recursos de más.
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb x11vnc fluxbox novnc websockify \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent_runtime ./agent_runtime
COPY start.sh .
RUN chmod +x start.sh

EXPOSE 6080

ENTRYPOINT ["./start.sh"]
