import os
import time
import logging
import glob

# Configuration
BAT_PATH = "/sys/class/power_supply/BAT0"
STATUS_FILE = os.path.join(BAT_PATH, "status")
CURRENT_FILE = os.path.join(BAT_PATH, "current_now")

# Thresholds
# Note: current_now unit is microamperes (uA) in most Linux kernels.
# 500mA = 500,000 uA.
DRAIN_THRESHOLD = -500000
RECONNECT_OBSERVATION_PERIOD = 30
EXPANSION_STEP_PERCENT = 0.05
CHECK_INTERVAL = 2

# Hardware Clamping Settings
SAFE_FREQ_FACTOR = 0.4           # 40% of max during EMERGENCY
MAX_FREQ_LIMIT_FACTOR = 0.8      # 80% of max during normal operation (optional cap)
# To allow full performance, we might want to use 1.0 in expansion,
# but let's start with a safe 0.8 to prevent immediate spikes.

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')

class PowerGuardStateMachine:
    def __init__(self):
        self.state = "DISCHARGING"
        self.last_current = 0
        self.reconnect_start_time = 0
        self.is_clamped = False
        self.original_freqs = {}  # path -> original_value (int)
        self.current_limit_factor = 1.0
        self.cpu_paths = glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_max_freq")

    def get_status(self):
        try:
            if not os.path.exists(STATUS_FILE):
                return "Unknown"
            with open(STATUS_FILE, 'r') as f:
                return f.read().strip()
        except Exception as e:
            logging.error(f"Failed to read status: {e}")
            return "Unknown"

    def get_current(self):
        try:
            if not os.path.exists(CURRENT_FILE):
                return 0
            with open(CURRENT_FILE, 'r') as f:
                return int(f.read().strip())
        except Exception as e:
            logging.error(f"Failed to read current: {e}")
            return 0

    def _ensure_originals_captured(self):
        """Captures the original max frequency if not already stored."""
        if not self.original_freqs:
            for path in self.cpu_paths:
                try:
                    with open(path, 'r') as f:
                        self.original_freqs[path] = int(f.read().strip())
                except Exception as e:
                    logging.error(f"Failed to capture original freq for {path}: {e}")
            if self.original_freqs:
                logging.info(f"Captured original frequencies for {len(self.original_freqs)} CPU paths.")

    def _apply_freq_limit(self, factor):
        """Writes the new frequency limit to sysfs."""
        for path in self.cpu_paths:
            try:
                # We always calculate based on the original frequency to prevent compounding reduction
                if path in self.original_freqs:
                    new_val = int(self.original_freqs[path] * factor)
                    with open(path, 'w') as f:
                        f.write(str(new_val))
                else:
                    # Fallback if original wasn't captured (shouldn't happen with _ensure_originals_captured)
                    with open(path, 'r') as f:
                        curr = int(f.read().strip())
                    with open(path, 'w') as f:
                        f.write(str(int(curr * factor)))
            except Exception as e:
                logging.error(f"Failed to set freq for {path}: {e}")

    def set_clamp(self, active):
        if active == self.is_clamped:
            return

        if active:
            logging.warning("!!! STATE: EMERGENCY CLAMP ACTIVATED !!!")
            self._ensure_originals_captured()
            self._apply_freq_limit(SAFE_FREQ_FACTOR)
            self.is_clamped = True
        else:
            logging.info("--- STATE: CLAMP RELEASED (Restoring original performance) ---")
            if self.original_freqs:
                for path, val in self.original_freqs.items():
                    try:
                        with open(path, 'w') as f:
                            f.write(str(val))
                    except Exception as e:
                        logging.error(f"Failed to restore {path}: {e}")
            self.is_clamped = False

    def update(self):
        status = self.get_status()
        current = self.get_current()
        delta_current = current - self.last_current
        now = time.time()

        # 1. Handle Transition from Discharging to Charging (Reconnection)
        if status == "Charging" and self.state == "DISCHARGING":
            logging.info(f"AC Detected. Entering RECONNECTING state. Observing for {RECONNECT_OBSERVATION_PERIOD}s...")
            self.state = "RECONNECTING"
            self.reconnect_start_time = now
            # Start with a conservative limit during reconnection to prevent instant spike
            self.current_limit_factor = 0.5
            self._apply_freq_limit(self.current_limit_factor)

        # 2. State Machine Logic
        if self.state == "DISCHARGING":
            if status == "Charging":
                self.state = "RECONNECTING"
                self.reconnect_start_time = now

        elif self.state == "RECONNECTING":
            if now - self.reconnect_start_time > RECONNECT_OBSERVATION_PERIOD:
                logging.info("Observation period finished. Entering EXPANDING state.")
                self.state = "EXPANDING"

            # If we see a drain while supposedly charging, go to EMERGENCY
            if current < DRAIN_THRESHOLD:
                logging.warning("Drain detected during reconnection! Reverting to EMERGENCY.")
                self.state = "EMERGENCY"
                self.set_clamp(True)

        elif self.state == "EMERGENCY":
            if current >= DRAIN_THRESHOLD and status == "Charging":
                logging.info("Power stabilized. Moving to CAUTIONARY.")
                self.state = "CAUTIONARY"
                self.set_clamp(False)
                self.current_limit_factor = 0.8 # Baseline for recovery
            elif status == "Discharging":
                self.state = "DISCHARGING"

        elif self.state == "EXPANDING":
            if current < DRAIN_THRESHOLD:
                logging.warning("Power drain detected during expansion! Reverting to EMERGENCY.")
                self.state = "EMERGENCY"
                self.set_clamp(True)
            elif delta_current < 0:
                logging.info("Current dropping. Moving to CAUTIONARY.")
                self.state = "CAUTIONARY"
            else:
                # Incrementally increase the limit
                new_factor = min(1.0, self.current_limit_factor + EXPANSION_STEP_PERCENT)
                if new_factor > self.current_limit_factor:
                    self.current_limit_factor = new_factor
                    self._apply_freq_limit(self.current_limit_factor)
                    logging.debug(f"Expanding limit to {self.current_limit_factor:.2f}")

        elif self.state == "CAUTIONARY":
            if current < DRAIN_THRESHOLD:
                logging.warning("Critical drain in Cautionary state! Reverting to EMERGENCY.")
                self.state = "EMERGENCY"
                self.set_clamp(True)
            elif delta_current > 0:
                logging.info("Current rising. Moving to EXPANDING.")
                self.state = "EXPANDING"
            elif status == "Discharging":
                self.state = "DISCHARGING"

        self.last_current = current

    def run(self):
        logging.info(f"Power Guard Daemon Started. Initial State: {self.state}")
        # Initial capture of frequencies to ensure we always have a baseline
        self._ensure_originals_captured()

        while True:
            try:
                self.update()
            except Exception as e:
                logging.error(f"Runtime error in loop: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    guard = PowerGuardStateMachine()
    guard.run()
