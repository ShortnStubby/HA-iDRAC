#!/bin/bash
# This script will be the main process for the add-on

echo "[RUN.SH] >>> Add-on execution started at $(date)"

# Read options from /data/options.json provided by Home Assistant
# and export them as environment variables for the Python script.
# Requires 'jq' to be installed (added to Dockerfile)
if [ -f /data/options.json ]; then
    echo "[RUN.SH] Reading configuration from /data/options.json"
    export IDRAC_IP=$(jq -r '.idrac_ip // empty' /data/options.json)
    export IDRAC_USERNAME=$(jq -r '.idrac_username // "root"' /data/options.json)
    export IDRAC_PASSWORD=$(jq -r '.idrac_password // empty' /data/options.json)
    export CHECK_INTERVAL_SECONDS=$(jq -r '.check_interval_seconds // 60' /data/options.json)
    export LOG_LEVEL=$(jq -r '.log_level // "info"' /data/options.json)
    export MQTT_HOST=$(jq -r '.mqtt_host // "core-mosquitto"' /data/options.json)
    export MQTT_PORT=$(jq -r '.mqtt_port // 1883' /data/options.json)
    export MQTT_USERNAME=$(jq -r '.mqtt_username // empty' /data/options.json)
    export MQTT_PASSWORD=$(jq -r '.mqtt_password // empty' /data/options.json)

    echo "[RUN.SH] Effective Configuration:"
    echo "[RUN.SH]   IDRAC_IP: ${IDRAC_IP}"
    echo "[RUN.SH]   IDRAC_USERNAME: ${IDRAC_USERNAME}"
    echo "[RUN.SH]   CHECK_INTERVAL_SECONDS: ${CHECK_INTERVAL_SECONDS}"
    echo "[RUN.SH]   LOG_LEVEL: ${LOG_LEVEL}"
    echo "[RUN.SH]   MQTT_HOST: ${MQTT_HOST}"
else
    echo "[RUN.SH] WARNING: /data/options.json not found. Using internal defaults or expecting Python defaults."
    # Set defaults if options.json is missing
    export IDRAC_IP=""
    export IDRAC_USERNAME="root"
    export IDRAC_PASSWORD=""
    export CHECK_INTERVAL_SECONDS=60
    export LOG_LEVEL="info"
    export MQTT_HOST="core-mosquitto"
    export MQTT_PORT=1883
    export MQTT_USERNAME=""
    export MQTT_PASSWORD=""
fi

echo "[RUN.SH] Starting Python application from within /app directory..."

# Change to the directory containing the 'app' package, which is / (root)
# because app was copied to /app in the Dockerfile and WORKDIR is /app.
# We need to ensure Python can find the 'app' module.
# The Dockerfile sets WORKDIR /app. So when python3 is called, /app is the current dir.
# To run 'app' as a module, Python needs to find it from its parent.
# Let's adjust how we call Python.
# The WORKDIR in Dockerfile is /app.
# We will execute python from / (root) to run 'app.main' as a module.
# Or, more simply, stay in /app and execute main.py as a script but ensure PYTHONPATH includes the parent of 'app'.
# Simplest for this context: python3 -m app.main (if python is run from /)
# OR, if WORKDIR is /app, then python3 main.py should work if imports are "from app import x"

# Given WORKDIR /app in Dockerfile, run.sh (copied to /usr/local/bin/run.sh) is run from /.
# Python needs to be able to find the 'app' module.
# The Dockerfile's WORKDIR /app means when main.py runs, its CWD is /app.

# The issue is how Python's module finder works when a script is run directly.
# Let's try running Python with the -m switch to treat 'app.main' as a module.
# For this to work, the directory *containing* 'app' must be in Python's search path.
# In our Dockerfile, 'app' is copied to '/app'. So the parent is '/'.
# We can add '/' to PYTHONPATH, or just execute from '/'

cd / 
echo "[RUN.SH] Current directory: $(pwd). About to run python3 -m app.main"
exec python3 -m app.main

# If exec is used, the script below this line will not be reached unless python3 fails to exec.
echo "[RUN.SH] !!!!! CRITICAL ERROR: python3 -m app.main failed to start or exited unexpectedly via exec !!!!!" >&2
exit 1