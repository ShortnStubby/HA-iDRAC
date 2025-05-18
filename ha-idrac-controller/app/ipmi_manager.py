# HA-iDRAC/ha-idrac-controller/app/ipmi_manager.py
import subprocess
import time
import re 
import os

# --- Globals ---
_IDRAC_IP = ""
_IDRAC_USER = ""
_IDRAC_PASSWORD = ""
_IPMI_BASE_ARGS = []
_LOG_LEVEL = "info" 

# --- Configuration ---
def configure_ipmi(ip, user, password, conn_type="lanplus", log_level="info"):
    global _IDRAC_IP, _IDRAC_USER, _IDRAC_PASSWORD, _IPMI_BASE_ARGS, _LOG_LEVEL
    _IDRAC_IP = ip
    _IDRAC_USER = user
    _IDRAC_PASSWORD = password
    _LOG_LEVEL = log_level.lower()

    if conn_type.lower() == "local" or conn_type.lower() == "open":
        _IPMI_BASE_ARGS = ["-I", "open"]
        _log("info", f"IPMI configured for local access via 'open' interface.")
    else: 
        _IPMI_BASE_ARGS = ["-I", "lanplus", "-H", _IDRAC_IP, "-U", _IDRAC_USER, "-P", _IDRAC_PASSWORD]
        _log("info", f"IPMI configured for lanplus access to host: {_IDRAC_IP}")

# --- Logging ---
def _log(level, message):
    # This log function relies on addon_options being available if main.py imports this module.
    # A more robust way would be to pass the logger or log_level.
    # For now, assuming main.py's global addon_options can be seen or _LOG_LEVEL is set by configure_ipmi.
    levels = {"trace": -1, "debug": 0, "info": 1, "warning": 2, "error": 3, "fatal": 4}
    # Use the module-level _LOG_LEVEL set by configure_ipmi
    if levels.get(_LOG_LEVEL, levels["info"]) <= levels.get(level.lower(), levels["info"]):
        print(f"[{level.upper()}] IPMI: {message}", flush=True)

# --- Core IPMI Command Execution ---
def _run_ipmi_command(args_list, is_raw_command=True, timeout=15):
    if not _IPMI_BASE_ARGS:
        _log("error", "IPMI not configured. Call configure_ipmi first.")
        return None

    base_command = ["ipmitool"] + _IPMI_BASE_ARGS
    if is_raw_command:
        command_to_run = base_command + ["raw"] + args_list
    else:
        command_to_run = base_command + args_list
    
    _log("debug", f"Executing IPMI command: {' '.join(command_to_run)}")

    try:
        result = subprocess.run(command_to_run, capture_output=True, text=True, check=False, timeout=timeout)
        
        if result.returncode != 0:
            _log("error", f"IPMI command failed: {' '.join(command_to_run)}")
            _log("error", f"STDOUT: {result.stdout.strip()}")
            _log("error", f"STDERR: {result.stderr.strip()}")
            return None
        
        _log("debug", f"IPMI command STDOUT: {result.stdout.strip()}")
        return result.stdout.strip()
        
    except FileNotFoundError:
        _log("error", "ipmitool command not found. Is it installed and in the system PATH?")
    except subprocess.TimeoutExpired:
        _log("error", f"IPMI command timed out: {' '.join(command_to_run)}")
    except Exception as e:
        _log("error", f"An unexpected error occurred with IPMI command: {e}")
    return None

# --- Fan Control ---
def decimal_to_hex_for_ipmi(decimal_value):
    try:
        val = int(decimal_value)
        if 0 <= val <= 100:
            return f"0x{val:02x}"
        else:
            _log("warning", f"Decimal value {val} out of range (0-100) for fan speed. Clamping.")
            return f"0x{max(0, min(100, val)):02x}" 
    except ValueError:
        _log("warning", f"Invalid decimal value '{decimal_value}' for fan speed. Using 0x00.")
        return "0x00"

def apply_dell_fan_control_profile():
    _log("info", "Attempting to apply Dell default dynamic fan control profile.")
    return _run_ipmi_command(["0x30", "0x30", "0x01", "0x01"])

def apply_user_fan_control_profile(decimal_fan_speed):
    hex_fan_speed = decimal_to_hex_for_ipmi(decimal_fan_speed)
    _log("info", f"Attempting to apply user static fan control: {decimal_fan_speed}% ({hex_fan_speed})")
    
    if _run_ipmi_command(["0x30", "0x30", "0x01", "0x00"]) is None:
        _log("error", "Failed to enable manual fan control mode.")
        return None
    time.sleep(0.5) 
    result = _run_ipmi_command(["0x30", "0x30", "0x02", "0xff", hex_fan_speed])
    if result is None:
        _log("error", f"Failed to set fan speed to {hex_fan_speed}.")
    else:
        _log("info", f"Successfully applied user fan control: {decimal_fan_speed}%")
    return result

# --- Sensor Data Retrieval & Parsing ---
def get_server_model_info():
    _log("info", "Attempting to retrieve server model information...")
    fru_data = _run_ipmi_command(["fru"], is_raw_command=False, timeout=20)
    
    if fru_data:
        model_info = {"manufacturer": "Unknown", "model": "Unknown"}
        for line in fru_data.splitlines():
            line_l = line.lower()
            if "product manufacturer" in line_l and ":" in line:
                model_info["manufacturer"] = line.split(":", 1)[1].strip()
            elif "product name" in line_l and ":" in line:
                model_info["model"] = line.split(":", 1)[1].strip()
        
        if not model_info["manufacturer"] or model_info["manufacturer"] == "Unknown":
            for line in fru_data.splitlines():
                if "board mfg" in line.lower() and ":" in line:
                    model_info["manufacturer"] = line.split(":", 1)[1].strip()
                    break
        if not model_info["model"] or model_info["model"] == "Unknown":
            for line in fru_data.splitlines():
                 if "board product" in line.lower() and ":" in line:
                    model_info["model"] = line.split(":", 1)[1].strip()
                    break
        _log("info", f"Server Info Raw: Manufacturer='{model_info['manufacturer']}', Model='{model_info['model']}'")
        if "dell" in model_info.get("manufacturer","").lower():
            model_info["manufacturer"] = "DELL" # Standardize
        return model_info
    _log("warning", "Could not retrieve server model information from FRU data.")
    return None

def retrieve_temperatures_raw():
    _log("debug", "Retrieving raw temperature SDR data...")
    sdr_output = _run_ipmi_command(["sdr", "type", "temperature"], is_raw_command=False)
    if sdr_output:
        _log("debug", "Successfully retrieved SDR temperature data.")
    else:
        _log("warning", "Failed to retrieve SDR temperature data.")
    return sdr_output

def parse_temperatures(sdr_data, 
                       cpu_generic_pattern_str, 
                       inlet_pattern_str, 
                       exhaust_pattern_str):
    temps = { "cpu_temps": [], "inlet_temp": None, "exhaust_temp": None }
    if not sdr_data:
        _log("warning", "SDR data is empty for temperature parsing.")
        return temps

    _log("debug", f"Compiling temp regex: CPU='{cpu_generic_pattern_str}', Inlet='{inlet_pattern_str}', Exhaust='{exhaust_pattern_str}'")
    try:
        cpu_generic_pattern = re.compile(cpu_generic_pattern_str, re.IGNORECASE) if cpu_generic_pattern_str else None
        inlet_pattern = re.compile(inlet_pattern_str, re.IGNORECASE) if inlet_pattern_str else None
        exhaust_pattern = re.compile(exhaust_pattern_str, re.IGNORECASE) if exhaust_pattern_str else None
    except re.error as e:
        _log("error", f"Invalid regex for temperature parsing: {e}")
        return temps 

    temp_line_regex = re.compile(
        r"^(.*?)\s*\|\s*[\da-fA-F]+h\s*\|\s*(?:ok|ns|nr|cr|u|\[Unknown\])\s*.*?\|\s*([-+]?\d*\.?\d+)\s*(?:degrees C|C)", 
        re.IGNORECASE
    )
    
    _log("debug", "Parsing SDR lines for temperatures...")
    lines = sdr_data.splitlines()
    inlet_found, exhaust_found = False, False

    for i, line in enumerate(lines):
        line_content = line.strip()
        _log("trace", f"Processing Temp Line {i+1}: '{line_content}'")
        
        match_temp = temp_line_regex.match(line_content)
        if match_temp:
            sensor_name = match_temp.group(1).strip()
            temp_val_str = match_temp.group(2)
            _log("trace", f"  Line matched main temp regex. Sensor: '{sensor_name}', ValueStr: '{temp_val_str}'")
            try:
                temp_value = int(float(temp_val_str))
            except (ValueError, IndexError) as e:
                _log("warning", f"  Could not parse numeric temp ('{temp_val_str}') from: {line_content}. Error: {e}")
                continue

            if not inlet_found and inlet_pattern and inlet_pattern.search(sensor_name):
                temps["inlet_temp"] = temp_value
                inlet_found = True
                _log("debug", f"  MATCHED INLET: '{sensor_name}' as {temp_value}°C")
                continue 
            
            if not exhaust_found and exhaust_pattern and exhaust_pattern.search(sensor_name):
                temps["exhaust_temp"] = temp_value
                exhaust_found = True
                _log("debug", f"  MATCHED EXHAUST: '{sensor_name}' as {temp_value}°C")
                continue

            if cpu_generic_pattern and cpu_generic_pattern.search(sensor_name):
                is_already_cat = (inlet_found and inlet_pattern and inlet_pattern.search(sensor_name)) or \
                                 (exhaust_found and exhaust_pattern and exhaust_pattern.search(sensor_name))
                if not is_already_cat:
                    temps["cpu_temps"].append(temp_value)
                    _log("debug", f"  MATCHED GENERIC CPU: '{sensor_name}' as {temp_value}°C, added to list.")
                else:
                     _log("trace", f"  Generic CPU pattern matched '{sensor_name}', but it was already categorized as Inlet/Exhaust.")
        else:
            _log("trace", f"  Line did not match temp_line_regex: {line_content}")
            
    if not temps["cpu_temps"]: _log("warning", f"No CPU temperature sensors found using pattern: {cpu_generic_pattern_str}")
    # It's okay if these are not found, they might not be present on all systems or a pattern might be missing
    if not inlet_found and inlet_pattern_str : _log("info", f"Inlet temperature sensor not found using pattern: {inlet_pattern_str}")
    if not exhaust_found and exhaust_pattern_str: _log("info", f"Exhaust temperature sensor not found using pattern: {exhaust_pattern_str}")
    return temps

def retrieve_fan_rpms_raw():
    _log("debug", "Retrieving raw fan SDR data...")
    sdr_output = _run_ipmi_command(["sdr", "type", "fan"], is_raw_command=False)
    if sdr_output:
        _log("debug", "Successfully retrieved SDR fan data.")
    else:
        _log("warning", "Failed to retrieve SDR fan data.")
    return sdr_output

def parse_fan_rpms(sdr_data):
    """
    Parses 'ipmitool sdr type fan' output for fan RPMs.
    Returns a list of dictionaries: [{"name": "Fan1A Tach", "rpm": 2040}, ...]
    """
    fans = []
    if not sdr_data:
        _log("warning", "SDR data is empty for fan RPM parsing.")
        return fans

    # Example line: Fan1A Tach       | 30h | ok  |  7.1 | 2040 RPM
    fan_line_regex = re.compile(
        r"^(.*?)\s*\|\s*[\da-fA-F]+h\s*\|\s*(?:ok|ns|nr|cr|u|\[Unknown\])\s*.*?\|\s*([\d\.]+)\s*RPM", 
        re.IGNORECASE
    )
    _log("debug", "Parsing SDR lines for fan RPMs...")
    lines = sdr_data.splitlines()

    for i, line in enumerate(lines):
        line_content = line.strip()
        _log("trace", f"Processing Fan Line {i+1}: '{line_content}'")
        match_fan = fan_line_regex.match(line_content)
        if match_fan:
            fan_name = match_fan.group(1).strip()
            rpm_str = match_fan.group(2)
            _log("trace", f"  Line matched fan_line_regex. Fan: '{fan_name}', RPM_Str: '{rpm_str}'")
            try:
                rpm_value = int(float(rpm_str))
                fans.append({"name": fan_name, "rpm": rpm_value})
                _log("debug", f"  MATCHED FAN: '{fan_name}' as {rpm_value} RPM")
            except (ValueError, IndexError) as e:
                _log("warning", f"  Could not parse numeric RPM value ('{rpm_str}') from: {line_content}. Error: {e}")
        else:
            _log("trace", f"  Line did not match fan_line_regex: {line_content}")
            
    if not fans: _log("info", "No fan RPMs found or parsed.")
    return fans