# HA-iDRAC/ha-idrac-controller/app/web_server.py
from flask import Flask, render_template, request, redirect, url_for, flash
import os
import json
import logging

log = logging.getLogger('werkzeug')
app = Flask(__name__)
app.secret_key = os.urandom(24)

APP_CONFIG_FILE = "/data/app_config.json" # For user-settable fan curve from web UI (advanced mode)
STATUS_FILE = "/data/current_status.json" # For live data display from main.py

def load_app_config():
    default_config = {"fan_curve": []} # Default for advanced fan curve
    if not os.path.exists(APP_CONFIG_FILE):
        return default_config
    try:
        with open(APP_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            if "fan_curve" not in config:
                config["fan_curve"] = default_config["fan_curve"]
            return config
    except (json.JSONDecodeError, FileNotFoundError, PermissionError) as e:
        print(f"[WEBSERVER ERROR] Could not load {APP_CONFIG_FILE}: {e}. Returning default.", flush=True)
        return default_config

def save_app_config(config_data):
    try:
        with open(APP_CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=4)
        print(f"[WEBSERVER INFO] App config saved to {APP_CONFIG_FILE}", flush=True)
        return True
    except (PermissionError, IOError) as e:
        print(f"[WEBSERVER ERROR] Could not save config to {APP_CONFIG_FILE}: {e}", flush=True)
        return False

def load_current_status_from_file():
    """Loads current operational status written by main.py."""
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, PermissionError) as e:
            print(f"[WEBSERVER ERROR] Could not load status from {STATUS_FILE}: {e}", flush=True)
    # Return default/empty status if file doesn't exist or is invalid
    return {
        "cpu_temps_c": ["N/A"], "hottest_cpu_temp_c": "N/A",
        "inlet_temp_c": "N/A", "exhaust_temp_c": "N/A",
        "target_fan_speed_percent": "N/A", "actual_fan_rpms": [],
        "last_updated": "Never"
    }

@app.route('/')
def index():
    idrac_ip_from_options = os.getenv("IDRAC_IP", "Not Set")
    # Get add-on options for display (simple fan mode thresholds)
    addon_opts_display = {
        "temp_unit": os.getenv("TEMPERATURE_UNIT", "C"),
        "base_fan": os.getenv("BASE_FAN_SPEED_PERCENT", "N/A"),
        "low_thresh": os.getenv("LOW_TEMP_THRESHOLD", "N/A"),
        "high_fan": os.getenv("HIGH_TEMP_FAN_SPEED_PERCENT", "N/A"),
        "crit_thresh": os.getenv("CRITICAL_TEMP_THRESHOLD", "N/A")
    }
    
    advanced_fan_curve = load_app_config().get("fan_curve", []) # From app_config.json
    current_op_status = load_current_status_from_file() # From current_status.json

    return render_template('index.html',
                           idrac_ip=idrac_ip_from_options,
                           simple_fan_mode_settings=addon_opts_display,
                           advanced_fan_curve=advanced_fan_curve,
                           status=current_op_status)

@app.route('/settings', methods=['GET', 'POST'])
def settings(): # This settings page is for the "Advanced Fan Curve"
    config = load_app_config()
    if request.method == 'POST':
        new_fan_curve = []
        try:
            num_points_str = request.form.get('num_fan_points', '0')
            num_points = int(num_points_str) if num_points_str.isdigit() else 0

            for i in range(num_points):
                temp_str = request.form.get(f'temp_{i}')
                speed_str = request.form.get(f'speed_{i}')
                if temp_str and speed_str and temp_str.isdigit() and speed_str.isdigit():
                    new_fan_curve.append({"temp": int(temp_str), "speed": int(speed_str)})
                elif temp_str or speed_str: 
                    flash(f"Invalid input for point {i+1}. Both must be numbers.", "error")
                    return render_template('settings.html', fan_curve=config.get("fan_curve", []))
            
            config["fan_curve"] = sorted(new_fan_curve, key=lambda x: x['temp'])
            if save_app_config(config):
                flash("Advanced fan curve settings saved successfully!", "success")
                # TODO: Consider how main.py picks up this change if "advanced mode" is active.
                # Currently main.py uses simple mode from HA config.
            else:
                flash("Error saving advanced fan curve settings.", "error")
        except ValueError:
            flash("Invalid number submitted for fan curve points.", "error")
        return redirect(url_for('settings'))

    return render_template('settings.html', fan_curve=config.get("fan_curve", []))

def run_web_server(port=8099):
    host = '0.0.0.0'
    print(f"[WEBSERVER INFO] Starting Flask web server on {host}:{port}", flush=True)
    try:
        app.run(host=host, port=port, debug=False, use_reloader=False)
    except Exception as e:
        print(f"[WEBSERVER ERROR] Web server failed to start: {e}", flush=True)