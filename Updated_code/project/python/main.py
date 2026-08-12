"""
Main Entry Point
----------------
Wires Modules 1 through 5 together and starts the data acquisition pipeline.
Press Ctrl+C to gracefully stop all modules.
"""

import logging
import time

from serial_reader import SerialReader
from parser import PacketParser
from sync_manager import SyncManager
from timestamp import TimestampAssigner
from foxglove_publisher import FoxglovePublisher

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger = logging.getLogger("main")
    
    logger.info("Starting Robotics Data Acquisition System...")

    # Module 1
    reader = SerialReader()
    reader.start()

    # Module 2
    parser = PacketParser(reader.raw_queue)
    parser.start()

    # Module 3
    sync_manager = SyncManager(parser.parsed_queue)
    sync_manager.start()

    # Module 4
    ts_assigner = TimestampAssigner(sync_manager.frame_queue)
    ts_assigner.start()

    # Module 5
    foxglove = FoxglovePublisher(ts_assigner.timestamped_queue)
    foxglove.start()

    logger.info("System is running. Open Foxglove Studio and connect to ws://localhost:8765")
    logger.info("Press Ctrl+C to stop.")

    try:
        # Keep main thread alive
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Caught KeyboardInterrupt. Stopping all modules...")
    finally:
        foxglove.stop()
        ts_assigner.stop()
        sync_manager.stop()
        parser.stop()
        reader.stop()
        logger.info("All modules stopped cleanly.")

if __name__ == "__main__":
    main()
