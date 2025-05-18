# HA-iDRAC/ha-idrac-controller/Dockerfile

# Use an official Home Assistant base image. It includes s6-overlay for process management.
# Choose the Python version you intend to use. 3.11 or 3.12 are good choices for now.
# Check https://developers.home-assistant.io/docs/add-ons/configuration#base-images for latest.
ARG BUILD_FROM="ghcr.io/home-assistant/python-base:3.12-slim"
FROM ${BUILD_FROM}

# Install system dependencies
# - ipmitool: For iDRAC communication
# - bash: For run.sh
# - Other tools you might need
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ipmitool \
    bash \
    # Add any other system packages your app might need
 && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container for your application
WORKDIR /app

# Copy your Python application code into the image.
# We'll create an 'app' subdirectory next to this Dockerfile for all Python code.
COPY app/ /app/

# Install Python dependencies listed in app/requirements.txt
# Ensure app/requirements.txt exists and lists libraries like Flask, paho-mqtt, etc.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the run.sh script into the root of the container and make it executable.
# This script will be the entry point for your add-on.
COPY run.sh /
RUN chmod +x /run.sh

# The Home Assistant Supervisor will execute /run.sh when the add-on starts.
# No need for CMD or ENTRYPOINT here typically.