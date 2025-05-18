# HA-iDRAC/ha-idrac-controller/app/main.py
import os
import time
import sys

print(f"[PYTHON SCRIPT] >>> main.py execution started at {time.strftime('%Y-%m-%d %H:%M:%S')}!", flush=True)

try:
    idrac_ip_env = os.getenv("IDRAC_IP", "NOT_SET_BY_RUN_SH")
    log_level_env = os.getenv("LOG_LEVEL", "info") # Example of reading another var

    print(f"[PYTHON SCRIPT] >>> Log Level from env: {log_level_env.upper()}", flush=True)
    print(f"[PYTHON SCRIPT] >>> Read IDRAC_IP from environment: {idrac_ip_env}", flush=True)

    print(f"[{log_level_env.upper()}] [PYTHON SCRIPT] Entering keep-alive loop (simulating continuous operation)...", flush=True)
    
    loop_count = 0
    while True: # A service add-on needs to run indefinitely
        print(f"[{log_level_env.upper()}] [PYTHON SCRIPT] Keep-alive loop: iteration {loop_count + 1}. Still running...", flush=True)
        # TODO: Here you would call your actual iDRAC logic, web server management, MQTT, etc.
        time.sleep(int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))) # Use the interval
        loop_count += 1

except KeyboardInterrupt:
    print("[PYTHON SCRIPT] >>> KeyboardInterrupt received, exiting loop.", flush=True)
except Exception as e:
    print(f"[PYTHON SCRIPT] >>> An unhandled EXCEPTION occurred: {e}", flush=True)
    import traceback
    print("[PYTHON SCRIPT] >>> Traceback:", flush=True)
    traceback.print_exc(file=sys.stdout)
    sys.stdout.flush()
finally:
    print(f"[PYTHON SCRIPT] >>> main.py execution is finishing (finally block) at {time.strftime('%Y-%m-%d %H:%M:%S')}.", flush=True)
    sys.stdout.flush()