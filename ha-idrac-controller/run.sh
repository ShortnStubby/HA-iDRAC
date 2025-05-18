#!/bin/sh
# Using plain /bin/sh for maximum compatibility and simplicity for this test.
# Alpine base images (which we suspect this is) always have /bin/sh (ash).

echo "[RUN.SH PLAIN] >>> SCRIPT ATTEMPTING TO START at $(date)"
echo "[RUN.SH PLAIN] >>> This is a simple echo test." >&2 # Output to stderr as well

# Try to run the simplified Python script from the previous step
# (the one that just prints and sleeps in a loop)
echo "[RUN.SH PLAIN] >>> About to try executing Python: /app/main.py"
python3 /app/main.py

PYTHON_EXIT_CODE=$?
echo "[RUN.SH PLAIN] >>> Python script finished with exit code: ${PYTHON_EXIT_CODE}"
echo "[RUN.SH PLAIN] >>> SCRIPT FINISHED at $(date)"