# HA-iDRAC/ha-idrac-controller/Dockerfile
FROM ghcr.io/home-assistant/amd64-base-python:latest

# Explicitly set the shell for RUN commands to bash
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# --- Start Diagnostic Block ---
RUN echo "===== DIAGNOSTIC INFORMATION =====" && \
    echo "Step 1: Running as user: $(whoami)" && \
    echo "Step 2: Current Shell: $SHELL (Note: this env var shows default, not necessarily the one used by RUN)" && \
    echo "Step 3: Bash Version Check: $(bash --version || echo 'bash command not found or errored')" && \
    echo "Step 4: Current PATH: $PATH" && \
    echo "Step 5: Listing /usr/bin to find apt-get:" && \
    (ls -l /usr/bin/apt-get || echo "/usr/bin/apt-get not found") && \
    echo "Step 6: Output of 'which apt-get': $(which apt-get || echo 'which apt-get: command not found')" && \
    echo "Step 7: Listing /bin:" && \
    ls -l /bin && \
    echo "Step 8: Listing /sbin for apk (Alpine check):" && \
    (ls -l /sbin/apk || echo "/sbin/apk not found (expected for Debian)") && \
    echo "Step 9: Trying apt-cache to see if apt tools are responsive (pre-update):" && \
    (apt-cache policy ipmitool || echo "apt-cache command failed or not found") && \
    echo "===== END DIAGNOSTIC INFORMATION ====="

# The original command that is failing
RUN echo "Attempting apt-get update and install..." && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    ipmitool \
 && rm -rf /var/lib/apt/lists/*

# --- Rest of your Dockerfile ---
WORKDIR /app

COPY app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/
COPY run.sh /
RUN chmod +x /run.sh