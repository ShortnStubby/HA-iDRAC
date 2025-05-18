#!/usr/bin/with-contenv bashio
# The 'with-contenv bashio' shebang makes bashio helper functions available.

# Exit immediately if a command exits with a non-zero status.
set -e

bashio::log.info "Starting HA iDRAC Controller Add-on..."

# Read configuration options (defined in config.yaml's 'options' section)
# bashio::config gets these from /data/options.json
export IDRAC_IP=$(bashio::config 'idrac_ip')
export IDRAC_USERNAME=$(bashio::config 'idrac_username')
export IDRAC_PASSWORD=$(bashio::config 'idrac_password')
export CHECK_INTERVAL_SECONDS=$(bashio::config 'check_interval_seconds')
export LOG_LEVEL=$(bashio::config 'log_level')

# Log the configuration (be careful with passwords in production logs)
bashio::log.info "iDRAC Host: ${IDRAC_IP}"
bashio::log.info "iDRAC User: ${IDRAC_USERNAME}"
# bashio::log.info "iDRAC Password: [SET]" # Don't log the actual password
bashio::log.info "Check Interval: ${CHECK_INTERVAL_SECONDS}s"
bashio::log.info "Log Level: ${LOG_LEVEL}"

# Check if critical configurations are set
if bashio::var.empty "$IDRAC_IP"; then
  bashio::log.fatal "iDRAC IP address is not configured. Please set it in the add-on configuration."
  bashio::exit.nok "iDRAC IP not set"
fi
if bashio::var.empty "$IDRAC_USERNAME"; then
  bashio::log.fatal "iDRAC username is not configured."
  bashio::exit.nok "iDRAC username not set"
fi
if bashio::var.empty "$IDRAC_PASSWORD"; then
  bashio::log.fatal "iDRAC password is not configured."
  bashio::exit.nok "iDRAC password not set"
fi

# Execute your main Python application.
# This assumes your main Python script is at /app/main.py inside the container.
bashio::log.info "Starting Python application: /app/main.py"
python3 /app/main.py

bashio::log.info "HA iDRAC Controller Add-on has stopped."