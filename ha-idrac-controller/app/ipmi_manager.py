# HA-iDRAC/ha-idrac-controller/app/ipmi_manager.py
import subprocess
import time
import re # For parsing later
import os # For logging an error if ipmitool isn't found

# Module-level variables to store IPMI configuration
_IDRAC_IP = ""
_IDRAC_USER = ""
_IDRAC_PASSWORD = ""
_IPMI_BASE_ARGS = []
_LOG_LEVEL = "info" # Default log level

def configure_ipmi(ip, user, password, conn_type="lanplus", log_level="info"):
    global _IDRAC_IP, _IDRAC_USER, _IDRAC_PASSWORD, _IPMI_BASE_ARGS, _LOG_LEVEL
    _IDRAC_IP = ip
    _IDRAC_USER = user
    _IDRAC_PASSWORD = password # Store password carefully
    _LOG_LEVEL = log_level.lower()

    if conn_type.lower() == "local" or conn_type.lower() == "open":
        _IPMI_BASE_ARGS = ["-I", "open"]
        print(f"[{_LOG_LEVEL.upper()}] IPMI configured for local access via 'open' interface.")
    else: # Default to lanplus for network connections
        _IPMI_BASE_ARGS = ["-I", "lanplus", "-H", _IDRAC_IP, "-U", _IDRAC_USER, "-P", _IDRAC_PASSWORD]
        print(f"[{_LOG_LEVEL.upper()}] IPMI configured for lanplus access to host: {_IDRAC_IP}")

def _log(level, message):
    """Helper function for conditional logging."""
    levels = {"debug": 0, "info": 1, "warning": 2, "error": 3}
    if levels.get(_LOG_LEVEL, 1) <= levels.get(level.lower(), 1):
        print(f"[{level.upper()}] {message}")

def _run_ipmi_command(args_list, is_raw_command=True, timeout=15):
    if not _IPMI_BASE_ARGS:
        _log("error", "IPMI not configured. Call configure_ipmi first.")
        return None

    base_command = ["ipmitool"] + _IPMI_BASE_ARGS
    if is_raw_command:
        command_to_run = base_command + ["raw"] + args_list
    else:
        command_to_run = base_command + args_list
    
    if _LOG_LEVEL == "debug":
        # In debug mode, be careful with displaying passwords if they are part of command_to_run
        # For lanplus, password is in _IPMI_BASE_ARGS, not args_list for raw commands
        _log("debug", f"Executing IPMI command: {' '.join(command_to_run)}")

    try:
        result = subprocess.run(command_to_run, capture_output=True, text=True, check=False, timeout=timeout)
        
        if result.returncode != 0:
            _log("error", f"IPMI command failed: {' '.join(command_to_run)}")
            _log("error", f"STDOUT: {result.stdout.strip()}")
            _log("error", f"STDERR: {result.stderr.strip()}")
            return None
        
        if _LOG_LEVEL == "debug":
             _log("debug", f"IPMI command STDOUT: {result.stdout.strip()}")
        return result.stdout.strip()
        
    except FileNotFoundError:
        _log("error", "ipmitool command not found. Is it installed and in the system PATH?")
        # This is a critical error for the add-on, might need to stop.
    except subprocess.TimeoutExpired:
        _log("error", f"IPMI command timed out: {' '.join(command_to_run)}")
    except Exception as e:
        _log("error", f"An unexpected error occurred with IPMI command: {e}")
    return None

def decimal_to_hex_for_ipmi(decimal_value):
    """Converts a decimal (0-100) to a 0x prefixed hex string like '0x14' for 20."""
    try:
        val = int(decimal_value)
        if 0 <= val <= 100:
            return f"0x{val:02x}"
        else:
            _log("warning", f"Decimal value {val} out of range (0-100) for fan speed.")
            return "0x00" # Default to 0% if out of range
    except ValueError:
        _log("warning", f"Invalid decimal value '{decimal_value}' for fan speed.")
        return "0x00"

def apply_dell_fan_control_profile():
    _log("info", "Attempting to apply Dell default dynamic fan control profile.")
    return _run_ipmi_command(["0x30", "0x30", "0x01", "0x01"])

def apply_user_fan_control_profile(decimal_fan_speed):
    hex_fan_speed = decimal_to_hex_for_ipmi(decimal_fan_speed)
    _log("info", f"Attempting to apply user static fan control: {decimal_fan_speed}% ({hex_fan_speed})")
    
    # 1. Enable manual fan control
    if _run_ipmi_command(["0x30", "0x30", "0x01", "0x00"]) is None:
        _log("error", "Failed to enable manual fan control mode.")
        return None
    
    # Small delay is often crucial between enabling manual mode and setting speed
    time.sleep(0.5) 
    
    # 2. Set the fan speed
    result = _run_ipmi_command(["0x30", "0x30", "0x02", "0xff", hex_fan_speed])
    if result is None:
        _log("error", f"Failed to set fan speed to {hex_fan_speed}.")
    return result

def get_server_model_info():
    _log("info", "Attempting to retrieve server model information...")
    # FRU data can be extensive, consider a longer timeout if necessary
    fru_data = _run_ipmi_command(["fru"], is_raw_command=False, timeout=20)
    
    if fru_data:
        model_info = {"manufacturer": "Unknown", "model": "Unknown"}
        # Basic parsing based on shell script logic. Regex could make this more robust.
        for line in fru_data.splitlines():
            line_l = line.lower()
            if "product manufacturer" in line_l and ":" in line:
                model_info["manufacturer"] = line.split(":", 1)[1].strip()
            elif "product name" in line_l and ":" in line:
                model_info["model"] = line.split(":", 1)[1].strip()
        
        # Fallback parsing from shell script
        if model_info["manufacturer"] == "Unknown" or not model_info["manufacturer"]:
            for line in fru_data.splitlines():
                if "board mfg" in line.lower() and ":" in line:
                    model_info["manufacturer"] = line.split(":", 1)[1].strip()
                    break # Take the first one found
        if model_info["model"] == "Unknown" or not model_info["model"]:
            for line in fru_data.splitlines():
                 if "board product" in line.lower() and ":" in line:
                    model_info["model"] = line.split(":", 1)[1].strip()
                    break
        _log("info", f"Server Info: Manufacturer='{model_info['manufacturer']}', Model='{model_info['model']}'")
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

def parse_temperatures(sdr_data, cpu1_pattern, cpu2_pattern, inlet_pattern, exhaust_pattern):
    """
    Parses the output of 'ipmitool sdr type temperature' to extract specific temps.
    sdr_data: The raw string output from the ipmitool command.
    *_pattern: Regex patterns to identify specific sensor lines.
    Returns a dictionary of temperatures.
    """
    temps = {
        "cpu1_temp": None,
        "cpu2_temp": None,
        "inlet_temp": None,
        "exhaust_temp": None
    }
    if not sdr_data:
        _log("warning", "SDR data is empty, cannot parse temperatures.")
        return temps

    # General regex to find lines with temperature readings
    # Example line: "CPU1 Temp        | 30h | ok  |  3.1 | 34 degrees C"
    # Or sometimes:   "Temp             | 0Eh | ns  |  3.1 | 20 C" (no "degrees")
    # Or:             "Ambient Temp     | 32h | ok  | 30.1 | 23 degrees C"
    temp_line_regex = re.compile(r"^(.*?)\s*\|\s*[\da-fA-F]+h\s*\|\s*(ok|ns|cr|nr)\s*.*?\|\s*(\d+)\s*(?:degrees C|C)", re.IGNORECASE)

    lines = sdr_data.splitlines()
    
    # Helper to extract temperature if a pattern matches
    def extract_temp(line_content, pattern_to_search, current_value):
        if current_value is not None: # If already found, don't overwrite (e.g. if multiple sensors match a loose pattern)
            return current_value
        if pattern_to_search and re.search(pattern_to_search, line_content, re.IGNORECASE):
            match_temp = temp_line_regex.match(line_content)
            if match_temp:
                try:
                    return int(match_temp.group(3))
                except (ValueError, IndexError):
                    _log("debug", f"Could not parse temperature value from line: {line_content}")
        return None

    for line in lines:
        line_content = line.strip()
        
        # Try to extract CPU1 Temp
        temp_val = extract_temp(line_content, cpu1_pattern, temps["cpu1_temp"])
        if temp_val is not None and temps["cpu1_temp"] is None : # Prioritize first match for CPU1
            temps["cpu1_temp"] = temp_val
            _log("debug", f"Found CPU1 Temp: {temp_val}°C from line: {line_content}")
            continue # Move to next line once CPU1 is found by its specific pattern, to avoid generic patterns overwriting

        # Try to extract CPU2 Temp (only if CPU1 was not also matched by this line with a looser CPU2 pattern)
        temp_val = extract_temp(line_content, cpu2_pattern, temps["cpu2_temp"])
        if temp_val is not None and temps["cpu2_temp"] is None:
            # Avoid re-assigning CPU1 if cpu2_pattern is too generic and also matches CPU1 line
            is_cpu1_line = cpu1_pattern and re.search(cpu1_pattern, line_content, re.IGNORECASE)
            if not is_cpu1_line:
                 temps["cpu2_temp"] = temp_val
                 _log("debug", f"Found CPU2 Temp: {temp_val}°C from line: {line_content}")
                 continue

        # Try to extract Inlet Temp
        temp_val = extract_temp(line_content, inlet_pattern, temps["inlet_temp"])
        if temp_val is not None and temps["inlet_temp"] is None:
            temps["inlet_temp"] = temp_val
            _log("debug", f"Found Inlet Temp: {temp_val}°C from line: {line_content}")
            continue

        # Try to extract Exhaust Temp
        temp_val = extract_temp(line_content, exhaust_pattern, temps["exhaust_temp"])
        if temp_val is not None and temps["exhaust_temp"] is None:
            temps["exhaust_temp"] = temp_val
            _log("debug", f"Found Exhaust Temp: {temp_val}°C from line: {line_content}")
            continue
            
    if temps["cpu1_temp"] is None:
        _log("warning", f"Could not find CPU1 temperature using pattern: {cpu1_pattern}")
    if temps["cpu2_temp"] is None and cpu2_pattern: # Only warn if a pattern was provided
        _log("info", f"CPU2 temperature not found or not applicable using pattern: {cpu2_pattern}")


    return temps

# You might want to keep the retrieve_temperatures_raw() function as well,
# so main.py calls that, then passes the raw data to parse_temperatures().
# TODO: Implement PCIe card control functions if desired, with generation checks
# def disable_third_party_pcie_cooling_response():
#     pass
# def enable_third_party_pcie_cooling_response():
#     pass

# TODO: Implement disk health retrieval functions (may require different ipmitool commands or racadm/redfish)