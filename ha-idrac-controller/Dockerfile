# HA-iDRAC/ha-idrac-controller/Dockerfile

# Try the :latest tag for the python base image, since :latest worked for the non-python amd64-base on HomeServer
FROM ghcr.io/home-assistant/amd64-base-python:latest

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ipmitool \
    bash \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Ensure requirements.txt is in app/
COPY app/requirements.txt ./requirements.txt 
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/
COPY run.sh /
RUN chmod +x /run.sh