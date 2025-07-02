# HA-iDRAC/ha-idrac-controller-dev/app/web_server.py
from flask import Flask, render_template, request, redirect, url_for, flash
import os
import json
import logging
import threading

log = logging.getLogger('werkzeug')
app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- Global paths and locks ---
STATUS_FILE = None
SERVERS_CONFIG_FILE = "/data/servers_config.json"
status_lock = None
config_lock = threading.Lock() # New lock for the config file

# --- Helper functions for config management ---
def load_servers_config():
    with config_lock:
        if not os.path.exists(SERVERS_CONFIG_FILE):
            return []
        try:
            with open(SERVERS_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

def save_servers_config(servers):
    with config_lock:
        try:
            with open(SERVERS_CONFIG_FILE, 'w') as f:
                json.dump(servers, f, indent=4)
            flash("Configuration saved! Please RESTART the add-on for changes to take effect.", "success")
            return True
        except IOError:
            flash("Error: Could not write to config file.", "error")
            return False

# --- Status loading for dashboard ---
def load_all_servers_status():
    if STATUS_FILE and os.path.exists(STATUS_FILE):
        try:
            # The status_lock is handled by the main thread writing the file
            with open(STATUS_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, PermissionError) as e:
            print(f"[WEBSERVER ERROR] Could not load status from {STATUS_FILE}: {e}", flush=True)
    return []

# --- Routes ---
@app.route('/')
def index():
    all_statuses = load_all_servers_status()
    all_statuses.sort(key=lambda x: x.get('alias', ''))
    return render_template('index.html', servers=all_statuses)

@app.route('/servers')
def manage_servers():
    servers = load_servers_config()
    return render_template('servers.html', servers=servers)

@app.route('/servers/add', methods=['POST'])
def add_server():
    servers = load_servers_config()
    new_alias = request.form.get('alias')

    # Check if alias already exists
    if any(s['alias'] == new_alias for s in servers):
        flash(f"Server alias '{new_alias}' already exists.", "error")
        return redirect(url_for('manage_servers'))

    new_server = {
        "alias": new_alias,
        "idrac_ip": request.form.get('idrac_ip'),
        "idrac_username": request.form.get('idrac_username'),
        # In a real implementation, this would be encrypted before saving.
        "idrac_password": request.form.get('idrac_password'),
        "enabled": True,
        "base_fan_speed_percent": int(request.form.get('base_fan_speed_percent', 20)),
        "low_temp_threshold": int(request.form.get('low_temp_threshold', 45)),
        "high_temp_fan_speed_percent": int(request.form.get('high_temp_fan_speed_percent', 50)),
        "critical_temp_threshold": int(request.form.get('critical_temp_threshold', 65))
    }
    servers.append(new_server)
    save_servers_config(servers)
    return redirect(url_for('manage_servers'))

@app.route('/servers/delete/<alias>', methods=['POST'])
def delete_server(alias):
    servers = load_servers_config()
    servers_to_keep = [s for s in servers if s['alias'] != alias]
    
    if len(servers_to_keep) == len(servers):
        flash(f"Server with alias '{alias}' not found.", "error")
    else:
        save_servers_config(servers_to_keep)
        
    return redirect(url_for('manage_servers'))

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