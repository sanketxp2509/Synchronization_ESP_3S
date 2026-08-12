# Standard Operating Procedure (SOP)
## Distributed Robotics Data Acquisition System

**Status as of this document:** Modules 1-4 built and hardware-verified.
Modules 5-15 (sensor classes, data manager, MCAP recording, Foxglove
visualization, cameras/LiDAR/GPS, ROS2) are planned but not yet built.
Sections below are labeled **[WORKING NOW]** or **[PLANNED]** accordingly.

---

### 1. Objective

Operate the multi-transmitter ESP32 synchronization system, stream
real-time IMU data to the host PC, and process it through the Python
pipeline that reads, parses, synchronizes, and timestamps every
reading -- as the foundation for the MCAP recording and Foxglove
visualization stages that come later.

---

### 2. System Architecture (current)

```
ESP32 Transmitter 1 ──┐
                       │  ESP-NOW (SYNC broadcast + data replies)
ESP32 Transmitter 2 ──┘
                       │
                ESP32-C3 Receiver

# Confirms id=1 / id=2 readings are correctly grouped by sync_count
python3 sync_manager.py

# Confirms each synchronized frame gets one clean timestamp
python3 timestamp.py
                       │  USB Serial (115200 baud)
                       ▼
                  Ubuntu PC
                       │
        ┌──────────────┴──────────────┐
        │      Python Pipeline          │
        │                               │
        │  serial_reader.py  (Module 1) │
        │        ▼                      │
        │  parser.py          (Module 2)│
        │        ▼                      │
        │  sync_manager.py    (Module 3)│
        │        ▼                      │
        │  timestamp.py        (Module 4)│
        └───────────────────────────────┘
                       │
              [PLANNED: Module 5-8]
              Sensor classes → Data Manager
              → MCAP file → Foxglove Studio
```

---

### 3. Hardware Requirements & Setup

- 1x ESP32-C3 module (Receiver / sync master)

# Confirms id=1 / id=2 readings are correctly grouped by sync_count
python3 sync_manager.py

# Confirms each synchronized frame gets one clean timestamp
python3 timestamp.py
- 2x ESP32 modules (Transmitters), each with one MPU6050 connected over I2C
- USB cable connecting the Receiver to the host PC
- Power source for each Transmitter (battery or USB power bank)

**Boot sequence:**
1. Connect the Receiver to the PC via USB.
2. Power on both Transmitters. They boot idle and wait for the first
   `SYNC` broadcast -- no action needed on your part.
3. The Receiver begins broadcasting `SYNC` at 50Hz (every 20ms) as
   soon as it boots.

---

### 4. Software Environment Setup **[WORKING NOW]**

```bash
# One-time setup
pip3 install pyserial
```

*(Optional, recommended for larger installs later: use a virtual
environment — `python3 -m venv venv && source venv/bin/activate`
before installing packages.)*

Confirm your receiver's serial port and update it if needed in
`project/python/config.py`:

```python
SERIAL_PORT = "/dev/ttyACM0"   # check with: ls /dev/tty*
```

---

### 5. Flashing Firmware (only if code changes)

- **Receiver:** upload `esp32/receiver/receiver.ino` to the ESP32-C3
  via Arduino IDE, board = `ESP32C3 Dev Module`.
- **Transmitters:** upload the respective `transmitter1.ino` /
  `transmitter2.ino` to each remote ESP32.

If a compile error mentions a missing `{build.partitions}` file,
reinstall the ESP32 board package via **Tools → Board → Boards
Manager → esp32 → reinstall**, then reselect the correct board.

---

### 6. Running the Current Pipeline **[WORKING NOW]**

There is no single `main.py` yet — each module currently runs
standalone for testing and verification. Run them in this order,
each building on the previous:

```bash
cd project/python

# Confirms raw serial lines are arriving cleanly
python3 serial_reader.py

# Confirms lines are parsed into structured ImuPacket objects
python3 parser.py

# Confirms id=1 / id=2 readings are correctly grouped by sync_count
python3 sync_manager.py

# Confirms each synchronized frame gets one clean timestamp
python3 timestamp.py
```

**What good output looks like** (from `timestamp.py`, the most
complete stage currently built):

```
sync_count=14604 timestamp_ns=1784627465123456000 jitter_ns=1823000 [COMPLETE]
```

- `[COMPLETE]` — both transmitters reported in for this round.
- `jitter_ns` around 1-2ms — consistent with the ESP32 sync accuracy
  already verified on the hardware side.

---

### 7. Interpreting Diagnostic Warnings **[WORKING NOW]**

- **`sync_count=... unusually high jitter`** — the gap between when
  TX1's and TX2's replies arrived at the PC exceeded 5ms. Usually
  caused by USB buffering delays or heavy CPU load on the PC, not the
  ESP32 sync mechanism itself. Worth a look if it happens often, but
  not necessarily an error.
- **`Frame sync_count=... timed out, missing transmitters: [...]`** —
  one transmitter's reply for that round never arrived within 15ms,
  most likely ordinary wireless packet loss. The frame is emitted
  anyway, marked incomplete, rather than blocking the pipeline
  waiting forever.

---

### 8. Troubleshooting **[WORKING NOW]**

- **No data appears at all:** Confirm only ONE program has the serial
  port open at a time (Arduino Serial Monitor and the Python script
  can't both hold it). Also confirm both transmitters are powered on.
- **Garbled / corrupted-looking lines:** This was a known issue caused
  by the receiver printing sensor data across multiple `Serial.print()`
  calls, which could interleave when two transmitters replied within
  milliseconds of each other. Fixed by having the receiver build each
  line into a single buffer and print it with one `Serial.println()`
  call from `loop()`. Make sure you're running the updated
  `receiver.ino`.
- **Port `/dev/ttyACM0` busy or permission denied:**
  ```bash
  sudo chmod a+rw /dev/ttyACM0
  ```
  or check nothing else (Arduino IDE, another terminal) has it open.
- **ESP32-C3 shows nothing over Serial at all:** Enable
  **Tools → USB CDC On Boot → Enabled** in Arduino IDE and re-upload
  — native USB serial on the C3 doesn't work without it.

---

### 9. Planned / Not Yet Available **[PLANNED]**

The following are part of the project roadmap but do **not** exist
yet — don't expect these commands or behaviors until the
corresponding module is built and confirmed:

| Module | Capability |
|---|---|
| 5 | Reusable `Sensor` classes |
| 6 | Data Manager — one synchronized frame across all transmitters |
| 7 | MCAP file writer |
| 8 | Opening the recorded `.mcap` file in Foxglove Studio |
| 9-11 | Camera, LiDAR, GPS support |
| 12-13 | ROS2 publishers, ROS2-based MCAP recording |
| 14 | Performance optimization for 15 transmitters |

Note: the current plan records to an **MCAP file you open afterward**
in Foxglove Studio, not a live WebSocket stream — so `main.py` and a
`ws://localhost:8765` connection are not part of the near-term plan
unless you specifically want live streaming added as an additional
feature alongside MCAP recording.

---

### 10. Folder Structure Reference

```
project/
├── esp32/
│   ├── receiver/         (receiver.ino)
│   └── transmitter1/, transmitter2/
├── python/
│   ├── config.py
│   ├── serial_reader.py   (Module 1)
│   ├── parser.py           (Module 2)
│   ├── sync_manager.py     (Module 3)
│   └── timestamp.py         (Module 4)
├── recordings/            (empty until Module 7 exists)
├── tests/                 (empty, planned for automated test coverage)
└── README.md
```