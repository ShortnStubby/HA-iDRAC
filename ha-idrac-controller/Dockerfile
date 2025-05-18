# HA-iDRAC/ha-idrac-controller/Dockerfile

# Use a specific patch version for the Python base image.
# This is a default and will be overridden by build.json for specific architectures.
ARG BUILD_FROM="ghcr.io/home-assistant/python-base:3.12.3-slim" 
FROM ${BUILD_FROM}

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ipmitool \
    bash \
 && rm -rf /var/lib/apt/lists/*

# Set up the working directory for your application
WORKDIR /app

# Copy your Python application code into the image
COPY app/ /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the run.sh script and make it executable
COPY run.sh /
RUN chmod +x /run.sh