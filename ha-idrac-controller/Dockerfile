# HA-iDRAC/ha-idrac-controller/Dockerfile

# Temporarily hardcode 'amd64' for testing.
# Replace $(arch) with amd64 if you are building on an amd64 system for testing.
FROM ghcr.io/home-assistant/amd64-base-python:3.12.3-slim-bookworm

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ipmitool \
    bash \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app/ /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY run.sh /
RUN chmod +x /run.sh