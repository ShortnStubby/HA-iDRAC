# HA-iDRAC/ha-idrac-controller/app/ipmi_manager.py
import subprocess
import time
import re 
import os

_IDRAC_IP = ""
_IDRAC_USER = ""
_IDRAC_PASSWORD = ""
_IPMI_BASE_ARGS = []
_LOG_LEVEL = "info"

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

def _log(level, message):
    levels = {"trace": -1, "debug": 0, "info": 1, "warning": 2, "error": 3, "fatal": 4}
    # Ensure log_level from addon_options is used if available, otherwise default _LOG_LEVEL
    current_log_level_setting = addon_options.get("log_level", _LOG_LEVEL) if 'addon_options' in globals() else _LOG_LEVEL
    
    if levels.get(current_log_level_setting, 1) <= levels.get(level.lower(), 1):
        print(f"[{level.upper()}] IPMI: {message}", flush=True)


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

def decimal_to_hex_for_ipmi(decimal_value):
    try:
        val = int(decimal_value)
        if 0 <= val <= 100:
            return f"0x{val:02x}"
        else:
            _log("warning", f"Decimal value {val} out of range (0-100) for fan speed. Clamping to 0x00 or 0x64.")
            return f"0x{max(0, min(100, val)):02x}" # Clamp and convert
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
    return result

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
        # Clean up Dell naming if present
        if "dell" in model_info.get("manufacturer","").lower():
            model_info["manufacturer"] = "DELL"
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
    temps = {
        "cpu_temps": [], 
        "inlet_temp": None,
        "exhaust_temp": None
    }
    if not sdr_data:
        _log("warning", "SDR data is empty, cannot parse temperatures.")
        return temps

    _log("debug", f"Attempting to compile regex patterns: CPU='{cpu_generic_pattern_str}', Inlet='{inlet_pattern_str}', Exhaust='{exhaust_pattern_str}'")
    try:
        cpu_generic_pattern = re.compile(cpu_generic_pattern_str, re.IGNORECASE) if cpu_generic_pattern_str else None
        inlet_pattern = re.compile(inlet_pattern_str, re.IGNORECASE) if inlet_pattern_str else None
        exhaust_pattern = re.compile(exhaust_pattern_str, re.IGNORECASE) if exhaust_pattern_str else None
    except re.error as e:
        _log("error", f"Invalid regex pattern provided for temperature parsing: {e}")
        return temps 

    # Regex to capture sensor name and its temperature value
    # Example line: "Inlet Temp       | 04h | ok  |  7.1 | 18 degrees C"
    # Group 1: Sensor Name (e.g., "Inlet Temp       ")
    # Group 3: Temperature Value (e.g., "18")
    temp_line_regex = re.compile(
        r"^(.*?)\s*\|\s*[\da-fA-F]+h\s*\|\s*(?:ok|ns|nr|cr|u|\[Unknown\])\s*.*?\|\s*([-+]?\d*\.?\d+)\s*(?:degrees C|C)",
        # Added 'u' to status for "unknown" sometimes seen
        re.IGNORECASE
    )
    
    _log("debug", "Starting to parse SDR lines for temperatures...")
    lines = sdr_data.splitlines()
    inlet_found = False
    exhaust_found = False

    for i, line in enumerate(lines):
        line_content = line.strip()
        _log("trace", f"Processing SDR Line {i+1}: '{line_content}'") # Use TRACE for very verbose
        
        match_temp = temp_line_regex.match(line_content)

        if match_temp:
            sensor_name_from_line = match_temp.group(1).strip() # Sensor name
            temp_value_str = match_temp.group(2) # Temperature value as string
            _log("trace", f"  Line matched temp_line_regex. Sensor: '{sensor_name_from_line}', ValueStr: '{temp_value_str}'")

            try:
                temp_value = int(float(temp_value_str))
            except (ValueError, IndexError) as e:
                _log("warning", f"  Could not parse numeric temperature value ('{temp_value_str}') from line: {line_content}. Error: {e}")
                continue

            # Check for Inlet Temp
            if not inlet_found and inlet_pattern and inlet_pattern.search(sensor_name_from_line):
                temps["inlet_temp"] = temp_value
                inlet_found = True
                _log("debug", f"  MATCHED INLET: '{sensor_name_from_line}' as {temp_value}°C")
                continue 
            
            # Check for Exhaust Temp
            if not exhaust_found and exhaust_pattern and exhaust_pattern.search(sensor_name_from_line):
                temps["exhaust_temp"] = temp_value
                exhaust_found = True
                _log("debug", f"  MATCHED EXHAUST: '{sensor_name_from_line}' as {temp_value}°C")
                continue

            # Check for generic CPU temperatures
            if cpu_generic_pattern and cpu_generic_pattern.search(sensor_name_from_line):
                # Ensure it's not an Inlet/Exhaust that was missed if their patterns were too loose
                # (This check is mostly a safeguard, depends on pattern specificity)
                is_inlet_by_pattern = inlet_pattern and inlet_pattern.search(sensor_name_from_line)
                is_exhaust_by_pattern = exhaust_pattern and exhaust_pattern.search(sensor_name_from_line)

                if (is_inlet_by_pattern and inlet_found) or \
                   (is_exhaust_by_pattern and exhaust_found):
                    # This line matched a generic CPU pattern but was already categorized as Inlet/Exhaust.
                    # This should ideally not happen if Inlet/Exhaust patterns are specific enough.
                    _log("trace", f"  Skipping generic CPU match for '{sensor_name_from_line}' as it was already categorized or matched a specific sensor that was found.")
                elif not is_inlet_by_pattern and not is_exhaust_by_pattern :
                    temps["cpu_temps"].append(temp_value)
                    _log("debug", f"  MATCHED GENERIC CPU: '{sensor_name_from_line}' as {temp_value}°C, added to list.")
                else:
                    _log("trace", f"  Generic CPU pattern matched '{sensor_name_from_line}', but it also matched a specific (Inlet/Exhaust) pattern that wasn't yet found. Prioritizing specific patterns if they trigger later.")

        else:
            _log("trace", f"  Line did not match temp_line_regex: {line_content}")
            
    if not temps["cpu_temps"]: _log("warning", f"No CPU temperature sensors found using generic pattern: {cpu_generic_pattern_str}")
    if not inlet_found: _log("info", f"Inlet temperature sensor not found using pattern: {inlet_pattern_str}")
    if not exhaust_found: _log("info", f"Exhaust temperature sensor not found using pattern: {exhaust_pattern_str}")
    
    return temps