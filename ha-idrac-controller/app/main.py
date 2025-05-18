# HA-iDRAC/ha-idrac-controller/app/main.py
import os
import time
import sys # For flushing output

print("[PYTHON SCRIPT] >>> main.py execution started!", flush=True)

try:
    idrac_ip_env = os.getenv("IDRAC_IP", "NOT_SET_IN_ENV")
    print(f"[PYTHON SCRIPT] >>> Read IDRAC_IP from environment: {idrac_ip_env}", flush=True)

    # Simulate the main work of the add-on.
    # In a real add-on, this would be your web server thread and main control loop.
    # If this script just prints and exits, the add-on will stop.
    # For testing, we'll just print and then sleep in a loop to keep it alive.
    print("[PYTHON SCRIPT] >>> Entering keep-alive loop (simulating continuous operation)...", flush=True)
    
    # Count iterations to see if it's looping
    loop_count = 0
    while loop_count < 300: # Run for about 5 minutes (300 * 1s) for testing
        print(f"[PYTHON SCRIPT] >>> Keep-alive loop: iteration {loop_count + 1}. Still running...", flush=True)
        time.sleep(1) # Sleep for 1 second
        loop_count += 1
        # In your actual app, this is where your main_control_loop and web server thread would be keeping things alive.
        # If your main_control_loop in the actual app finishes or errors, the script would end.

    print("[PYTHON SCRIPT] >>> Keep-alive loop finished after 300 iterations.", flush=True)

except Exception as e:
    print(f"[PYTHON SCRIPT] >>> An unhandled EXCEPTION occurred: {e}", flush=True)
    # For more detail on exceptions:
    import traceback
    print("[PYTHON SCRIPT] >>> Traceback:", flush=True)
    traceback.print_exc(file=sys.stdout) # Print traceback to stdout
    sys.stdout.flush() # Ensure it's flushed

finally:
    print("[PYTHON SCRIPT] >>> main.py execution is finishing (finally block).", flush=True)
    sys.stdout.flush() # Ensure final message is flushed