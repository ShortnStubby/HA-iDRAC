#!/usr/bin/with-contenv bashio
#set -e # Keep this commented out for now to prevent silent exits on minor errors

bashio::log.emergency "RUN.SH (bashio) --- EMERGENCY LOG TEST --- SCRIPT STARTED"
bashio::log.warning "RUN.SH (bashio) --- This is a warning log test."
bashio::log.info "RUN.SH (bashio) --- About to try running Python."

python3 /app/main.py

PYTHON_EXIT_CODE=$?
bashio::log.info "RUN.SH (bashio) --- Python script finished with exit code: ${PYTHON_EXIT_CODE}."
bashio::log.emergency "RUN.SH (bashio) --- EMERGENCY LOG TEST --- SCRIPT FINISHED"