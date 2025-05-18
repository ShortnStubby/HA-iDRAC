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

# TODO: Implement more specific temperature parsing here based on sdr_output and server generation
# def parse_temperatures(sdr_data, server_gen_info):
#     pass

# TODO: Implement PCIe card control functions if desired, with generation checks
# def disable_third_party_pcie_cooling_response():
#     pass
# def enable_third_party_pcie_cooling_response():
#     pass

# TODO: Implement disk health retrieval functions (may require different ipmitool commands or racadm/redfish)