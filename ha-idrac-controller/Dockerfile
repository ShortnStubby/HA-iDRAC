# HA-iDRAC/ha-idrac-controller/Dockerfile
FROM ghcr.io/home-assistant/amd64-base-python:latest

# Explicitly set the shell for RUN commands to bash
# This ensures apt-get and other commands are found correctly.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install system dependencies
RUN apt update
RUN apt install -y --no-install-recommends ipmitool \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY app/ /app/

# Copy run.sh to root and make executable
COPY run.sh /
RUN chmod +x /run.sh