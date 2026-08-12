"""
Module 3: Sync Manager
------------------------
Responsibility: group individual ImuPacket readings (Module 2) into
synchronized "frames" -- one frame per sync_count, containing every
transmitter's reading for that same SYNC broadcast round.

IMPORTANT: this does NOT touch the ESP32 synchronization architecture
at all. The ESP32 side already guarantees both transmitters sample at
nearly the same instant and tag their reply with the same syncCount.
This module's job is purely on the PC side: collect those tagged
replies back together into one unit, and decide what to do if one is
missing or arrives late -- which happens sometimes over wireless, as
you already saw occasional dropped packets in the raw logs.
"""

import threading
import queue
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import config
from parser import ImuPacket

logger = logging.getLogger("sync_manager")


@dataclass
class SyncFrame:
    """All readings collected for one sync_count round."""
    sync_count: int
    packets: Dict[int, ImuPacket] = field(default_factory=dict)
    first_seen: float = 0.0   # PC time when the first packet for this round arrived

    @property
    def is_complete(self) -> bool:
        return len(self.packets) >= config.EXPECTED_TRANSMITTERS

    @property
    def missing_ids(self) -> List[int]:
        expected = set(range(1, config.EXPECTED_TRANSMITTERS + 1))
        return sorted(expected - set(self.packets.keys()))


class SyncManager:
    """
    Pulls ImuPacket objects from Module 2's parsed_queue, groups them
    by sync_count, and emits a SyncFrame onto frame_queue as soon as
    either:
      (a) every expected transmitter has reported in for that round, or
      (b) FRAME_TIMEOUT_MS has passed since the first packet in that
          round arrived, and we give up waiting for the rest.

    Emitting on a timeout (rather than waiting forever) matters: with
    a real wireless link, packets occasionally get dropped. A frame
    with 1 of 2 transmitters is still useful data and shouldn't block
    the whole pipeline waiting for a packet that will never arrive.
    """

    def __init__(self, parsed_queue: queue.Queue):
        self.parsed_queue = parsed_queue
        self.frame_queue: queue.Queue = queue.Queue()

        # Pending frames, keyed by sync_count, waiting to be completed or timed out.
        self._pending: Dict[int, SyncFrame] = {}
        self.total_missing_data = 0

        # Highest sync_count we've already finalized (completed or timed out).
        # A packet arriving late for a round <= this value is a straggler for
        # a round that's already closed -- drop it instead of spawning a new,
        # phantom "incomplete" frame for a round that was actually complete.
        self._highest_finalized: int = -1

        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()

    def start(self):
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(
            "SyncManager started (expecting %d transmitters, %dms timeout)",
            config.EXPECTED_TRANSMITTERS, config.FRAME_TIMEOUT_MS
        )

    def stop(self):
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2)
        logger.info("SyncManager stopped. TOTAL MISSING DATA THIS SESSION: %d", self.total_missing_data)

    def _run(self):
        while self._running.is_set():
            # Short timeout on the queue read so we regularly sweep for
            # timed-out frames even if no new packets are arriving.
            try:
                packet: ImuPacket = self.parsed_queue.get(timeout=0.01)
                self._add_packet(packet)
            except queue.Empty:
                pass

            self._flush_timed_out_frames()

    def _add_packet(self, packet: ImuPacket):
        sc = packet.sync_count

        if sc <= self._highest_finalized:
            # This round already finished (completed or timed out) --
            # this is a late straggler, not a new round. Drop it rather
            # than creating a phantom frame that will falsely report
            # a "missing" transmitter for a round that was actually fine.
            logger.debug("Dropping late packet for already-finalized sync_count=%d", sc)
            return

        frame = self._pending.get(sc)

        if frame is None:
            frame = SyncFrame(sync_count=sc, first_seen=time.time())
            self._pending[sc] = frame

        if packet.transmitter_id in frame.packets:
            # Duplicate packet for a round we already have -- ignore it.
            logger.debug("Duplicate packet for sync_count=%d id=%d", sc, packet.transmitter_id)
            return

        frame.packets[packet.transmitter_id] = packet

        if frame.is_complete:
            self._emit(frame)
            del self._pending[sc]

    def _flush_timed_out_frames(self):
        now = time.time()
        timeout_s = config.FRAME_TIMEOUT_MS / 1000.0

        expired = [
            sc for sc, frame in self._pending.items()
            if (now - frame.first_seen) >= timeout_s
        ]

        for sc in expired:
            frame = self._pending.pop(sc)
            self.total_missing_data += len(frame.missing_ids)
            logger.warning(
                "Frame sync_count=%d timed out, missing transmitters: %s. Total missing data so far: %d",
                sc, frame.missing_ids, self.total_missing_data
            )
            self._emit(frame)

    def _emit(self, frame: SyncFrame):
        self._highest_finalized = max(self._highest_finalized, frame.sync_count)
        self.frame_queue.put(frame)

    def get_frame(self, block=True, timeout=None) -> Optional[SyncFrame]:
        try:
            return self.frame_queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None


# ---- Standalone test: run this file directly to see synchronized frames ----
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    from serial_reader import SerialReader
    from parser import PacketParser

    reader = SerialReader()
    reader.start()

    parser = PacketParser(reader.raw_queue)
    parser.start()

    sync_manager = SyncManager(parser.parsed_queue)
    sync_manager.start()

    try:
        while True:
            frame = sync_manager.get_frame(timeout=1)
            if frame:
                ids = sorted(frame.packets.keys())
                status = "COMPLETE" if frame.is_complete else f"INCOMPLETE missing={frame.missing_ids}"
                print(f"sync_count={frame.sync_count} ids={ids} [{status}]")
    except KeyboardInterrupt:
        print("\nStopping...")
        sync_manager.stop()
        parser.stop()
        reader.stop()