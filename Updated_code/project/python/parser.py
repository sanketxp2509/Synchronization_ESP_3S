"""
Module 2: Packet Parser
------------------------
Responsibility: turn raw text lines (from Module 1) into structured,
typed Python objects. This is where we finally interpret what a line
from the receiver means -- but still nothing about synchronization
or "which reading pairs with which" happens here. That's Module 3.

Why parsing is its own module:
Today the format is one simple CSV line from one sensor type (IMU).
Later you'll add cameras, LiDAR, GPS -- each with a completely
different wire format. Keeping "parsing" as its own stage means
adding a new sensor type later is: write a new parser function,
not rewrite this whole pipeline. This mirrors how ROS2 message
definitions work -- one clear contract for what a decoded reading
looks like, regardless of how many sensor types exist.
"""

import logging
import threading
import queue
from dataclasses import dataclass
from typing import Optional

import config

logger = logging.getLogger("parser")

# Expected line format from the receiver:
# id,syncCount,recvMillis,ax,ay,az,gx,gy,gz
EXPECTED_FIELDS = 9


@dataclass
class ImuPacket:
    """One IMU reading from one transmitter, already type-converted."""
    transmitter_id: int
    sync_count: int
    board_millis: int      # timestamp from the ESP32 receiver's own clock
    pc_timestamp: float    # timestamp from Module 1 -- when this line arrived at the PC
    ax: int
    ay: int
    az: int
    gx: int
    gy: int
    gz: int


def parse_line(pc_timestamp: float, line: str) -> Optional[ImuPacket]:
    """
    Turn one raw CSV line into an ImuPacket, or return None if the
    line isn't valid sensor data (boot messages, the CSV header line,
    or a corrupted/incomplete line all return None here).
    """
    fields = line.split(",")

    if len(fields) != EXPECTED_FIELDS:
        return None  # not a data line -- silently ignore (boot text, header, etc.)

    try:
        transmitter_id = int(fields[0])
        sync_count     = int(fields[1])
        board_millis   = int(fields[2])
        ax, ay, az     = int(fields[3]), int(fields[4]), int(fields[5])
        gx, gy, gz     = int(fields[6]), int(fields[7]), int(fields[8])
    except ValueError:
        # A field wasn't a valid number -- e.g. a half-corrupted line
        # that still happened to have 9 comma-separated chunks.
        logger.debug("Skipping malformed line: %s", line)
        return None

    if not (1 <= transmitter_id <= config.MAX_TRANSMITTERS):
        # Protects downstream code from ever seeing a bogus/out-of-range id,
        # e.g. from a bit-flipped byte during transmission.
        logger.warning("Ignoring packet with out-of-range id=%d", transmitter_id)
        return None

    return ImuPacket(
        transmitter_id=transmitter_id,
        sync_count=sync_count,
        board_millis=board_millis,
        pc_timestamp=pc_timestamp,
        ax=ax, ay=ay, az=az,
        gx=gx, gy=gy, gz=gz,
    )


class PacketParser:
    """
    Pulls raw (timestamp, line) tuples from a SerialReader's queue,
    parses them, and puts valid ImuPacket objects onto its own queue
    for the next stage (Module 3) to consume.

    Runs in its own thread, same pattern as SerialReader -- so parsing
    speed never blocks reading speed, and vice versa.
    """

    def __init__(self, raw_queue: queue.Queue):
        self.raw_queue = raw_queue
        self.parsed_queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._initial_sync_count: Optional[int] = None

    def start(self):
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("PacketParser started")

    def stop(self):
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2)
        logger.info("PacketParser stopped")

    def _run(self):
        while self._running.is_set():
            try:
                item = self.raw_queue.get(timeout=1)
            except queue.Empty:
                continue

            pc_timestamp, line = item
            packet = parse_line(pc_timestamp, line)
            if packet is not None:
                if self._initial_sync_count is None:
                    self._initial_sync_count = packet.sync_count
                
                packet.sync_count = packet.sync_count - self._initial_sync_count
                self.parsed_queue.put(packet)

    def get_packet(self, block=True, timeout=None) -> Optional[ImuPacket]:
        try:
            return self.parsed_queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None


# ---- Standalone test: run this file directly to see parsed packets ----
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    from serial_reader import SerialReader

    reader = SerialReader()
    reader.start()

    parser = PacketParser(reader.raw_queue)
    parser.start()

    try:
        while True:
            pkt = parser.get_packet(timeout=1)
            if pkt:
                print(pkt)
    except KeyboardInterrupt:
        print("\nStopping...")
        parser.stop()
        reader.stop()
