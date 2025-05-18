# HA-iDRAC/ha-idrac-controller/Dockerfile
# We've discovered ghcr.io/home-assistant/amd64-base-python:latest is currently Alpine-based in this environment
FROM ghcr.io/home-assistant/amd64-base-python:latest

# Alpine's default shell is ash. Bash was found to be present in the diagnostic,
# but we can ensure commands run with it if needed, or just let apk run with ash.
# The SHELL directive is fine to keep if bash is indeed present and preferred for complex RUN lines.
SHELL ["/bin/bash", "-o", "pipefail", "-c"] # Bash was found in the Alpine image.

# Use apk to install packages on Alpine
RUN echo "Attempting apk update and add for Alpine..." && \
    apk update && \
    apk add --no-cache \
        ipmitool \
        bash \  
    && echo "Packages installed successfully with apk."

# --- Rest of your Dockerfile ---
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY app/ /app/

# Copy run.sh to root and make executable
COPY run.sh /
RUN chmod +x /run.sh