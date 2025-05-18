# HA-iDRAC/ha-idrac-controller/app/web_server.py
from flask import Flask, render_template, request, redirect, url_for, flash
import os
import json
import logging # For more structured logging from Flask

# Configure basic logging for Flask
log = logging.getLogger('werkzeug') # Get Flask's default logger
# You can set log level from environment variable later if needed
# log.setLevel(logging.INFO) # Or DEBUG

app = Flask(__name__)
app.secret_key = os.urandom(24) # Needed for flash messages

# Path for persistent settings storage within the add-on's /data directory
APP_CONFIG_FILE = "/data/app_config.json"

def load_app_config():
    """Loads application-specific configuration (e.g., fan curve) from /data."""
    default_config = {"fan_curve": [{"temp": 50, "speed": 20}, {"temp": 70, "speed": 50}]}
    if not os.path.exists(APP_CONFIG_FILE):
        return default_config # Return defaults if file doesn't exist
    try:
        with open(APP_CONFIG_FILE, 'r') as f:
            config = json.load(f)
            # Ensure essential keys exist
            if "fan_curve" not in config:
                config["fan_curve"] = default_config["fan_curve"]
            return config
    except (json.JSONDecodeError, FileNotFoundError, PermissionError) as e:
        print(f"[ERROR] Could not load {APP_CONFIG_FILE}: {e}. Returning default config.")
        return default_config

def save_app_config(config_data):
    """Saves application-specific configuration to /data."""
    try:
        with open(APP_CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=4)
        print(f"[INFO] Application configuration saved to {APP_CONFIG_FILE}")
        return True
    except (PermissionError, IOError) as e:
        print(f"[ERROR] Could not save config to {APP_CONFIG_FILE}: {e}")
        return False

@app.route('/')
def index():
    # Read add-on options passed as environment variables by run.sh
    idrac_ip_from_options = os.getenv("IDRAC_IP", "Not Set in Add-on Options")
    current_app_config = load_app_config()
    
    # TODO: Fetch current server status (temps, fan speeds) from your main loop/ipmi_manager
    # For now, just passing dummy data or config data.
    current_status = {
        "cpu1_temp": "N/A",
        "current_fan_speed_target": "N/A"
    }

    return render_template('index.html',
                           idrac_ip=idrac_ip_from_options,
                           fan_curve=current_app_config.get("fan_curve", []),
                           status=current_status)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    config = load_app_config()
    if request.method == 'POST':
        new_fan_curve = []
        # Process submitted fan curve points
        # Assumes form fields like temp_0, speed_0, temp_1, speed_1 etc.
        # and a hidden field 'num_fan_points' indicating how many points were submitted.
        try:
            num_points_str = request.form.get('num_fan_points', '0')
            num_points = int(num_points_str) if num_points_str.isdigit() else 0

            for i in range(num_points):
                temp_str = request.form.get(f'temp_{i}')
                speed_str = request.form.get(f'speed_{i}')
                
                if temp_str and speed_str and temp_str.isdigit() and speed_str.isdigit():
                    new_fan_curve.append({"temp": int(temp_str), "speed": int(speed_str)})
                elif temp_str or speed_str: # If one is filled but not the other, or non-digit
                    flash(f"Invalid input for point {i+1}. Both temperature and speed must be numbers.", "error")
                    # Keep existing curve if there's an error to avoid data loss on bad submit
                    return render_template('settings.html', fan_curve=config.get("fan_curve", []))


            config["fan_curve"] = sorted(new_fan_curve, key=lambda x: x['temp']) # Sort by temperature
            
            if save_app_config(config):
                flash("Settings saved successfully!", "success")
                # TODO: Signal the main control loop in main.py to reload its configuration
                # This is important so the running process picks up the new fan curve.
                # Could be done by writing to a temp file that main.py checks, a global event,
                # or by main.py periodically re-reading app_config.json.
            else:
                flash("Error saving settings.", "error")

        except ValueError:
            flash("Invalid number submitted for fan curve points.", "error")
        
        return redirect(url_for('settings')) # Redirect to GET to show updated settings and clear form

    return render_template('settings.html', fan_curve=config.get("fan_curve", []))

# This function will be called from app/main.py to start the Flask server
def run_web_server(port=8099): # Port should match ingress_port in config.yaml
    host = '0.0.0.0' # Important to listen on all interfaces within Docker
    print(f"[INFO] Starting Flask web server on {host}:{port}")
    try:
        # Setting use_reloader=False is important for production within an add-on
        # as the reloader can interfere with process management.
        # debug=False is also critical for production.
        app.run(host=host, port=port, debug=False, use_reloader=False)
    except Exception as e:
        print(f"[ERROR] Web server failed to start: {e}")