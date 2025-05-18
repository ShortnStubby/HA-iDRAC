#!/usr/bin/with-contenv bashio
# Using with-contenv gives access to bashio functions.
# set -e # Temporarily disable 'exit on error' for more verbose debugging if a bashio call fails early.

echo "[RUN.SH] >>> Script execution started at $(date)"
bashio::log.info "[RUN.SH] >>> bashio::log.info: Script started."

# Test reading a config option
CONFIG_IDRAC_IP=$(bashio::config 'idrac_ip')
echo "[RUN.SH] >>> Config - iDRAC IP: ${CONFIG_IDRAC_IP}"
bashio::log.info "[RUN.SH] >>> bashio::log.info: Config - iDRAC IP: ${CONFIG_IDRAC_IP}"

echo "[RUN.SH] >>> About to execute Python script: /app/main.py"
bashio::log.info "[RUN.SH] >>> bashio::log.info: About to execute Python script."

# Execute Python script
python3 /app/main.py

# Capture exit code
PYTHON_EXIT_CODE=$?
echo "[RUN.SH] >>> Python script /app/main.py finished with exit code: ${PYTHON_EXIT_CODE}"
bashio::log.info "[RUN.SH] >>> bashio::log.info: Python script finished with exit code: ${PYTHON_EXIT_CODE}."

echo "[RUN.SH] >>> Script execution finished at $(date)."
bashio::log.info "[RUN.SH] >>> bashio::log.info: Script finished."

# Optional: keep the container alive for a minute to ensure logs flush if Python script exits very fast
# echo "[RUN.SH] >>> Entering 60s sleep to keep container alive for log inspection..."
# sleep 60