# HA-iDRAC/ha-idrac-controller-dev/app/web_server.py
from flask import Flask, render_template, request, redirect, url_for, flash
import os
import json
import logging

log = logging.getLogger('werkzeug')
app = Flask(__name__)
app.secret_key = os.urandom(24)

# These will be passed in when the web server is started
STATUS_FILE = None
status_lock = None

def load_all_servers_status():
    """Loads a list of current operational statuses for all servers."""
    if STATUS_FILE and os.path.exists(STATUS_FILE):
        try:
            with status_lock:
                with open(STATUS_FILE, 'r') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError, PermissionError) as e:
            print(f"[WEBSERVER ERROR] Could not load status from {STATUS_FILE}: {e}", flush=True)
    return [] # Return an empty list if file doesn't exist or is invalid

@app.route('/')
def index():
    all_statuses = load_all_servers_status()
    # Sort servers by alias for consistent display
    all_statuses.sort(key=lambda x: x.get('alias', ''))
    
    return render_template('index.html', servers=all_statuses)

# The settings page for advanced fan curves can remain as is, since it's a global config
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    # This functionality is less relevant in the multi-server model unless
    # you adapt it to be per-server. For now, we can leave it as a non-functional placeholder.
    flash("Advanced settings are not implemented in the multi-server version yet.", "warning")
    return render_template('settings.html', fan_curve=[])

def run_web_server(port, status_file_path, lock):
    global STATUS_FILE, status_lock
    STATUS_FILE = status_file_path
    status_lock = lock
    
    host = '0.0.0.0'
    print(f"[WEBSERVER INFO] Starting Flask web server on {host}:{port}", flush=True)
    try:
        app.run(host=host, port=port, debug=False, use_reloader=False)
    except Exception as e:
        print(f"[WEBSERVER ERROR] Web server failed to start: {e}", flush=True)