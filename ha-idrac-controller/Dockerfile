# HA-iDRAC/ha-idrac-controller/Dockerfile

# Use the $(arch) variable provided by the Home Assistant build system.
# This ensures the correct architecture-specific base image is pulled.
# Using a specific patch version and Debian release for stability.
# Example: for amd64, $(arch) becomes "amd64", so it pulls "ghcr.io/home-assistant/amd64-base-python:..."
FROM ghcr.io/home-assistant/$(arch)-base-python:3.12.3-slim-bookworm

# We are no longer using ARG BUILD_FROM as the FROM line is now arch-aware.

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