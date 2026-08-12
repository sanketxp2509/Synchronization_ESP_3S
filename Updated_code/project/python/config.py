"""
Central configuration for the robotics data acquisition system.
"""

# ---- Serial connection settings (Module 1) ----
SERIAL_PORT = "/dev/ttyACM0"
BAUD_RATE = 115200
SERIAL_TIMEOUT = 1.0
RECONNECT_DELAY = 2.0

# ---- System scale (used by later modules) ----
MAX_TRANSMITTERS = 15

# ---- Sync manager settings (Module 3) ----
EXPECTED_TRANSMITTERS = 2
FRAME_TIMEOUT_MS = 10
