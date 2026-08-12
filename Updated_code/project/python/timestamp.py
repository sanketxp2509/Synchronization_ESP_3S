"""
Module 4: Timestamp Assignment
--------------------------------
Responsibility: give every SyncFrame (Module 3) ONE authoritative
timestamp, in the exact format MCAP/ROS2 expect -- an integer count
of nanoseconds since the Unix epoch.

Why this needs its own module:
Each ImuPacket inside a frame already carries a pc_timestamp (when
Module 1 saw that specific line arrive) and a board_millis (the
receiver's own uptime clock -- not wall-clock time, not meaningful
outside the ESP32). Neither one alone is "the timestamp of the frame"
-- a frame is made of several packets that each arrived at a very
slightly different moment. This module turns those several timestamps
into one clean number for the whole frame, and records how much
jitter there was, so you can keep verifying synchronization quality
as this system scales up to more sensors.
"""

import logging
import threading
import queue
from dataclasses import dataclass
from typing import Dict, Optional

from parser import ImuPacket
from sync_manager import SyncFrame

logger = logging.getLogger("timestamp")

NS_PER_SECOND = 1_000_000_000
HIGH_JITTER_WARN_NS = 5_000_000  # 5ms -- unusual for this design, worth flagging


@dataclass
class TimestampedFrame:
    """A SyncFrame with one authoritative timestamp attached."""
    sync_count: int
    timestamp_ns: int              # unified frame timestamp, ns since epoch -- what MCAP/ROS2 use
    jitter_ns: int                 # spread between earliest and latest packet in this frame
    packets: Dict[int, ImuPacket]
    is_complete: bool


def assign_timestamp(frame: SyncFrame) -> TimestampedFrame:
    """
    Compute one timestamp for a frame from its packets' pc_timestamps.

    We use the MEAN of all packets' pc_timestamp values. Since your
    ESP32 sync design already gets both transmitters sampling within
    1-2ms of each other, averaging their PC-arrival times gives a
    timestamp very close to "the instant this round was actually
    sampled" -- much better than arbitrarily picking just one packet's
    time and calling it the frame's time.
    """
    pc_timestamps = [p.pc_timestamp for p in frame.packets.values()]

    mean_ts = sum(pc_timestamps) / len(pc_timestamps)
    jitter_s = (max(pc_timestamps) - min(pc_timestamps)) if len(pc_timestamps) > 1 else 0.0

    timestamp_ns = int(mean_ts * NS_PER_SECOND)
    jitter_ns = int(jitter_s * NS_PER_SECOND)

    if jitter_ns > HIGH_JITTER_WARN_NS:
        logger.warning(
            "sync_count=%d unusually high jitter: %.2fms",
            frame.sync_count, jitter_ns / 1e6
        )

    return TimestampedFrame(
        sync_count=frame.sync_count,
        timestamp_ns=timestamp_ns,
        jitter_ns=jitter_ns,
        packets=frame.packets,
        is_complete=frame.is_complete,
    )


class TimestampAssigner:
    """
    Pulls SyncFrame objects from Module 3's frame_queue, attaches a
    unified timestamp to each, and puts the result on timestamped_queue.
    """

    def __init__(self, frame_queue: queue.Queue):
        self.frame_queue = frame_queue
        self.timestamped_queue: queue.Queue = queue.Queue()

        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()

    def start(self):
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("TimestampAssigner started")

    def stop(self):
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2)
        logger.info("TimestampAssigner stopped")

    def _run(self):
        while self._running.is_set():
            try:
                frame: SyncFrame = self.frame_queue.get(timeout=1)
            except queue.Empty:
                continue

            if not frame.packets:
                continue  # nothing to timestamp -- shouldn't normally happen

            ts_frame = assign_timestamp(frame)
            self.timestamped_queue.put(ts_frame)

    def get_frame(self, block=True, timeout=None) -> Optional[TimestampedFrame]:
        try:
            return self.timestamped_queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None


# ---- Standalone test: run this file directly to see timestamped frames ----
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    from serial_reader import SerialReader
    from parser import PacketParser
    from sync_manager import SyncManager

    reader = SerialReader()
    reader.start()

    parser = PacketParser(reader.raw_queue)
    parser.start()

    sync_manager = SyncManager(parser.parsed_queue)
    sync_manager.start()

    ts_assigner = TimestampAssigner(sync_manager.frame_queue)
    ts_assigner.start()

    try:
        while True:
            tf = ts_assigner.get_frame(timeout=1)
            if tf:
                status = "COMPLETE" if tf.is_complete else "INCOMPLETE"
                print(f"sync_count={tf.sync_count} timestamp_ns={tf.timestamp_ns} "
                      f"jitter_ns={tf.jitter_ns} [{status}]")
    except KeyboardInterrupt:
        print("\nStopping...")
        ts_assigner.stop()
        sync_manager.stop()
        parser.stop()
        reader.stop()
