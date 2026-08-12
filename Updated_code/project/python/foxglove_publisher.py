"""
Module 5: Foxglove Publisher
--------------------------------
Responsibility: take TimestampedFrames and stream them out over a
Foxglove WebSocket server so that Foxglove Studio can connect to it
and visualize the data in real-time.

Why this needs its own module:
By keeping visualization and streaming separate from the raw timestamping
logic, we maintain clean boundaries. If you later decide to stream via
ROS2 or save to an MCAP file, you just add another module (e.g. McapWriter)
without modifying the core logic that handles data synchronization.
"""

import asyncio
import json
import logging
import queue
import threading
from typing import Optional, Dict

from foxglove_websocket.server import FoxgloveServer

from timestamp import TimestampedFrame
import config

logger = logging.getLogger("foxglove")

class FoxglovePublisher:
    """
    Starts an asynchronous Foxglove WebSocket server and continuously pulls
    TimestampedFrames from a queue to publish them to Foxglove Studio clients.
    """

    def __init__(self, ts_queue: queue.Queue, host: str = "0.0.0.0", port: int = 8765):
        self.ts_queue = ts_queue
        self.host = host
        self.port = port
        self.server: Optional[FoxgloveServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._channels: Dict[int, int] = {}

    def start(self):
        self._running.set()
        self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._thread.start()
        logger.info(f"FoxglovePublisher started on ws://{self.host}:{self.port}")

    def stop(self):
        self._running.clear()
        if self._thread is not None:
            self._thread.join(timeout=2)
        logger.info("FoxglovePublisher stopped")

    def _run_async_loop(self):
        """Run the asyncio event loop in a dedicated thread."""
        asyncio.run(self._async_main())

    async def _async_main(self):
        """Main async task that runs the server and publishes data."""
        self.server = FoxgloveServer(self.host, self.port, "ESP32 Sync System")
        async with self.server:
            # Pre-register channels for the maximum number of expected transmitters
            for tx_id in range(1, config.MAX_TRANSMITTERS + 1):
                self._channels[tx_id] = await self.server.add_channel(
                    {
                        "topic": f"/imu_{tx_id}",
                        "encoding": "json",
                        "schemaName": "esp32.ImuData",
                        "schema": json.dumps({
                            "type": "object",
                            "properties": {
                                "transmitter_id": {"type": "integer"},
                                "sync_count": {"type": "integer"},
                                "ax": {"type": "number"},
                                "ay": {"type": "number"},
                                "az": {"type": "number"},
                                "gx": {"type": "number"},
                                "gy": {"type": "number"},
                                "gz": {"type": "number"},
                                "board_millis": {"type": "integer"},
                            }
                        })
                    }
                )
            
            # Continuously check the queue and send messages to Foxglove clients
            while self._running.is_set():
                # We use asyncio.to_thread to wait on the synchronous queue
                # without blocking the async event loop serving WebSocket clients.
                try:
                    frame: TimestampedFrame = await asyncio.to_thread(self.ts_queue.get, True, 0.1)
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Error reading queue: {e}")
                    continue
                
                # Publish packets from the synchronized frame
                if not frame.is_complete:
                    continue
                
                for tx_id, packet in frame.packets.items():
                    if tx_id in self._channels:
                        payload_dict = {
                            "transmitter_id": packet.transmitter_id,
                            "sync_count": packet.sync_count,
                            "ax": packet.ax,
                            "ay": packet.ay,
                            "az": packet.az,
                            "gx": packet.gx,
                            "gy": packet.gy,
                            "gz": packet.gz,
                            "board_millis": packet.board_millis,
                        }
                        print(f"IMU TX:{packet.transmitter_id} SYNC:{packet.sync_count} A:({packet.ax},{packet.ay},{packet.az}) G:({packet.gx},{packet.gy},{packet.gz})")
                        payload = json.dumps(payload_dict).encode("utf8")
                        
                        # Use the exact same unified timestamp for all packets in this frame
                        await self.server.send_message(
                            self._channels[tx_id],
                            frame.timestamp_ns,
                            payload
                        )
