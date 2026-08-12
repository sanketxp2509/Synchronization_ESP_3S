"""
Module 1: Serial Reader
------------------------
Responsibility (and ONLY responsibility): read raw lines from the
receiver's serial port and hand them off, reliably, without blocking
the rest of the program.

This module knows NOTHING about what the data means. It doesn't know
about "id", "syncCount", or sensor values. That parsing happens in
Module 2. This separation matters: it mirrors how real ROS2 driver
nodes work -- a driver node's only job is moving bytes off the wire
reliably; a separate node interprets them. Keeping these jobs apart
means you can test/replace one without touching the other, and it's
what makes this scale cleanly later.
"""

import serial
import threading
import queue
import time
import logging

import config

logger = logging.getLogger("serial_reader")


class SerialReader:
    def __init__(self, port=None, baud=None, timeout=None):
        self.port = port or config.SERIAL_PORT
        self.baud = baud or config.BAUD_RATE
        self.timeout = timeout or config.SERIAL_TIMEOUT

        self._serial = None
        self._thread = None
        self._running = threading.Event()

        # Thread-safe queue: the background thread PUTS raw lines in,
        # the rest of the application TAKES lines out whenever it's
        # ready. This decouples "how fast data arrives" from "how fast
        # we process it" -- essential once 15 transmitters are pushing
        # data through this one serial port at once.
        self.raw_queue = queue.Queue()

    def start(self):
        """Begin reading in a background thread. Non-blocking."""
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("SerialReader started on %s @ %d baud", self.port, self.baud)

    def stop(self):
        """Cleanly shut down the reading thread and close the port."""
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
        logger.info("SerialReader stopped")

    def _connect(self):
        """Keep retrying until the serial port opens successfully.

        Why: in a real robot, USB connections can drop (vibration,
        power glitches, a cable getting bumped). A robotics-grade
        program should never just crash and stop logging data --
        it should recover automatically.
        """
        while self._running.is_set():
            try:
                self._serial = serial.Serial(self.port, self.baud, timeout=self.timeout)
                logger.info("Connected to %s", self.port)
                return
            except serial.SerialException as e:
                logger.warning(
                    "Could not open %s (%s). Retrying in %.1fs",
                    self.port, e, config.RECONNECT_DELAY
                )
                time.sleep(config.RECONNECT_DELAY)

    def _run(self):
        """Background thread loop: read lines, timestamp them, queue them."""
        self._connect()
        while self._running.is_set():
            try:
                raw = self._serial.readline()
                if not raw:
                    continue  # read timed out, no data yet -- just loop again

                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                # Timestamp the MOMENT this line arrived at the PC.
                # This is the PC-side arrival time, not the sensor's
                # own timestamp -- Module 4 will build the real timing
                # model. For now we just capture it so nothing is lost.
                arrival_time = time.time()
                self.raw_queue.put((arrival_time, line))

            except serial.SerialException:
                logger.warning("Serial connection lost. Reconnecting...")
                if self._serial:
                    self._serial.close()
                self._connect()

    def get_line(self, block=True, timeout=None):
        """Fetch one (timestamp, line) tuple. Returns None on timeout."""
        try:
            return self.raw_queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None


# ---- Standalone test: run this file directly to sanity-check the port ----
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    reader = SerialReader()
    reader.start()

    try:
        while True:
            item = reader.get_line(timeout=1)
            if item:
                ts, line = item
                print(f"[{ts:.3f}] {line}")
    except KeyboardInterrupt:
        print("\nStopping...")
        reader.stop()
