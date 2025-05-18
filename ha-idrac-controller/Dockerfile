FROM ghcr.io/home-assistant/amd64-base-python:3.12.3-slim-bookworm 
# Or even just FROM ghcr.io/home-assistant/amd64-base:stable (and install python manually)

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Use apt-get again
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv ipmitool bash \
 && rm -rf /var/lib/apt/lists/*

# If using amd64-base:stable, you'd need to install python3, python3-pip, python3-venv first
# RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip python3-venv ...

# ... rest of your Dockerfile ...
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY app/ /app/

# Copy run.sh to root and make executable
COPY run.sh /
RUN chmod +x /run.sh