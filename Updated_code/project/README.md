# Distributed Robotics Data Acquisition System

A highly scalable, strictly time-synchronized data acquisition system designed for robotics (ROS2/MCAP ready). The system uses ESP32 microcontrollers and ESP-NOW to achieve microsecond-level hardware synchronization across multiple wireless sensors (IMUs, Cameras, LiDAR) and streams the unified data to Foxglove Studio for live visualization.

## 🎯 Architecture Overview

In robotics, if two sensors sample the world at slightly different times, the robot's state estimation will fail. This project solves that by separating the system into a **Hardware Sync Layer** and a **Python Processing Pipeline**.

### 1. Hardware Sync Layer (ESP-NOW)
- **Receiver (Master):** Plugged into the PC via USB. It broadcasts a `SYNC` pulse over ESP-NOW every 20ms (50Hz).
- **Transmitters (Slaves):** Multiple wireless ESP32s (currently IMUs). The instant they receive the `SYNC` pulse, they sample their sensors and transmit the data back to the receiver.
- *Result:* All physical sensors sample the real world at the exact same physical instant.

### 2. Python Processing Pipeline
The receiver streams raw serial data to the PC. The Python software acts as an assembly line, broken down into 5 strict modules to ensure the code remains perfectly scalable as more sensors are added.

#### Module 1: Serial Reader (`serial_reader.py`)
- Reads raw text lines from the USB serial port.
- Immediately stamps each incoming line with a `pc_timestamp` to record the exact arrival time.
- Pushes lines into a thread-safe queue.

#### Module 2: Packet Parser (`parser.py`)
- Takes raw CSV strings and converts them into typed Python data classes (`ImuPacket`).
- Validates data and drops corrupted packets.

#### Module 3: Sync Manager (`sync_manager.py`)
- The "traffic cop" of the system.
- Groups arriving packets based on their `sync_count`.
- Waits until all expected transmitters (defined in `config.py`) report in for a given round before releasing them as a unified `SyncFrame`.
- Handles timeouts if a wireless packet is dropped.

#### Module 4: Timestamp Assignment (`timestamp.py`)
- Averages the `pc_timestamp` of all packets inside a `SyncFrame` to generate a single, highly accurate nanosecond Unix timestamp for the entire frame.
- Calculates "jitter" (time difference between the earliest and latest packet in the frame) to monitor radio health.
- Prepares the data format required by ROS2 and MCAP.

#### Module 5: Foxglove Publisher (`foxglove_publisher.py`)
- Runs a non-blocking `foxglove-websocket` server.
- Packages the synchronized frames into a JSON schema and broadcasts them.
- Allows Foxglove Studio to subscribe to the live data and plot multiple sensors on the exact same timeline.

---

## 🚀 How to Run the System

### 1. Hardware Setup
1. Flash the receiver code to the ESP32 connected to your PC.
2. Flash the transmitter code to your wireless ESP32s.
3. Power on the transmitters.

### 2. Software Setup
Ensure you have Python 3 installed. Install the required WebSocket library:
```bash
pip install foxglove-websocket
```

### 3. Start the Pipeline
Run the main orchestrator script:
```bash
cd project/python
python main.py
```
You should see terminal logs indicating that the modules have started and the WebSocket server is listening on port `8765`.

### 4. Visualize in Foxglove Studio
1. Open Foxglove Studio (Web or Desktop app).
2. Click **Open connection** -> **Foxglove WebSocket**.
3. Enter the URL: `ws://localhost:8765`.
4. Open a **Plot** panel.
5. In the Plot panel settings, click **Add Series** and select your desired topics (e.g., `/imu_1.ax` and `/imu_2.ax`).
6. Perform a physical "Shake Test" by moving both IMUs simultaneously to verify that the spikes align perfectly on the graph.

---

## ⚙️ Configuration

System parameters can be tweaked in `project/python/config.py`:
- `SERIAL_PORT`: The USB port for the receiver (e.g., `/dev/ttyACM0`).
- `MAX_TRANSMITTERS`: The upper limit of sensors the system supports.
- `EXPECTED_TRANSMITTERS`: The number of active sensors currently running. The Sync Manager will wait for this many packets before finalizing a frame.
- `FRAME_TIMEOUT_MS`: How long to wait for a straggling wireless packet before giving up on a frame.

<!-- cd python
python main.py -->

