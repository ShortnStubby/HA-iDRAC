#!/bin/bash
# This script will be the main process for the add-on

echo "[RUN.SH] >>> Add-on execution started at $(date)"

# Default values for configuration
IDRAC_IP_DEFAULT=""
IDRAC_USERNAME_DEFAULT="root"
IDRAC_PASSWORD_DEFAULT=""
CHECK_INTERVAL_SECONDS_DEFAULT=60
LOG_LEVEL_DEFAULT="info"
# Add MQTT defaults if you have them in config.yaml
# MQTT_HOST_DEFAULT="core-mosquitto"
# MQTT_PORT_DEFAULT=1883
# MQTT_USERNAME_DEFAULT=""
# MQTT_PASSWORD_DEFAULT=""

# Read configuration from /data/options.json if it exists
if [ -f /data/options.json ]; then
    echo "[RUN.SH] Reading configuration from /data/options.json"
    export IDRAC_IP=$(jq -r '.idrac_ip // empty' /data/options.json)
    export IDRAC_USERNAME=$(jq -r '.idrac_username // "'"$IDRAC_USERNAME_DEFAULT"'"' /data/options.json)
    export IDRAC_PASSWORD=$(jq -r '.idrac_password // empty' /data/options.json) # Be careful with passwords
    export CHECK_INTERVAL_SECONDS=$(jq -r '.check_interval_seconds // "'"$CHECK_INTERVAL_SECONDS_DEFAULT"'"' /data/options.json)
    export LOG_LEVEL=$(jq -r '.log_level // "'"$LOG_LEVEL_DEFAULT"'"' /data/options.json)
    # Export MQTT options if defined
    # export MQTT_HOST=$(jq -r '.mqtt_host // "'"$MQTT_HOST_DEFAULT"'"' /data/options.json)
    # export MQTT_PORT=$(jq -r '.mqtt_port // '$MQTT_PORT_DEFAULT /data/options.json) # Note: jq treats numbers as numbers
    # export MQTT_USERNAME=$(jq -r '.mqtt_username // empty' /data/options.json)
    # export MQTT_PASSWORD=$(jq -r '.mqtt_password // empty' /data/options.json)
else
    echo "[RUN.SH] WARNING: /data/options.json not found. Using internal defaults or expecting Python defaults."
    export IDRAC_IP="$IDRAC_IP_DEFAULT"
    export IDRAC_USERNAME="$IDRAC_USERNAME_DEFAULT"
    export IDRAC_PASSWORD="$IDRAC_PASSWORD_DEFAULT"
    export CHECK_INTERVAL_SECONDS="$CHECK_INTERVAL_SECONDS_DEFAULT"
    export LOG_LEVEL="$LOG_LEVEL_DEFAULT"
    # Export MQTT defaults
    # export MQTT_HOST="$MQTT_HOST_DEFAULT"
    # ...
fi

echo "[RUN.SH] Effective Configuration:"
echo "[RUN.SH]   IDRAC_IP: ${IDRAC_IP}"
echo "[RUN.SH]   IDRAC_USERNAME: ${IDRAC_USERNAME}"
# Avoid logging password: echo "[RUN.SH] IDRAC_PASSWORD: [SET_IF_PROVIDED]"
echo "[RUN.SH]   CHECK_INTERVAL_SECONDS: ${CHECK_INTERVAL_SECONDS}"
echo "[RUN.SH]   LOG_LEVEL: ${LOG_LEVEL}"
# echo "[RUN.SH] MQTT_HOST: ${MQTT_HOST}"

echo "[RUN.SH] Starting Python application /app/main.py..."

# Use 'exec' to replace the shell process with the Python process.
# This makes Python the main process (PID 1 in this context) and ensures
# signals (like stop signals from Docker/HA) go directly to Python.
# It also means Python's stdout/stderr will be the container's stdout/stderr.
exec python3 /app/main.py

# The script will not reach here if 'exec python3 ...' is successful.
# This part only runs if python3 fails to start via exec.
echo "[RUN.SH] !!!!! CRITICAL ERROR: python3 /app/main.py failed to start or exited immediately via exec !!!!!" >&2
exit 1