# Audeze Maxwell 2 Hardware Specification & Enumeration

## Hardware Identification
- **Product**: Audeze Maxwell 2 (Xbox Dongle variant)
- **Vendor ID (VID)**: `0x3329` (Audeze LLC)
- **Product ID (PID)**: `0x4B28` (Maxwell 2 Xbox Dongle)
- **Speed**: High Speed (USB 2.0, 480 Mbps)
- **Kernel Audio Driver**: `snd-usb-audio`
- **Kernel HID Driver**: `usbhid` (`hid-generic`)
- **Sysfs Path**: `/sys/bus/usb/devices/1-12.2.1`

---

## USB Interfaces
| Interface # | Class / Subclass | Driver | Description |
|:---:|:---|:---|:---|
| **0** | `Audio (0x01)` / `Control Device (0x01)` | `snd-usb-audio` | Primary UAC Audio Control header |
| **1** | `Audio (0x01)` / `Streaming (0x02)` | `snd-usb-audio` | Audio Output (Game channel playback) |
| **2** | `Audio (0x01)` / `Streaming (0x02)` | `snd-usb-audio` | Audio Output (Chat channel playback) |
| **3** | `Audio (0x01)` / `Control Device (0x01)` | `snd-usb-audio` | Secondary UAC Audio Control |
| **4** | `Audio (0x01)` / `Streaming (0x02)` | `snd-usb-audio` | Audio Input (Microphone recording) |
| **5** | `HID (0x03)` / `None (0x00)` | `usbhid` | Vendor Control, Telephony, Consumer Controls |

---

## Interface 5 HID Topology & Report Descriptors

Interface 5 exposes an Interrupt IN endpoint (`0x82`, 64 bytes max packet, 1ms polling interval) with a 175-byte Report Descriptor parsed into three distinct application collections:

### 1. Vendor Control Collection (Airoha RACE Channel)
- **Usage Page**: `0xFF13` (Vendor-Defined)
- **Application Usage**: `0x01`
- **Reports**:
  - **Output Report `0x06`**: 61 bytes payload. Used by host to send RACE command packets to dongle/headset. Full USB transfer length = 62 bytes (1 byte Report ID `0x06` + 61 bytes payload).
  - **Input Report `0x07`**: 61 bytes payload. Used by device to return RACE response packets and notifications to host. Full USB transfer length = 62 bytes (1 byte Report ID `0x07` + 61 bytes payload).
  - **Input Report `0x03`**: 13 bytes payload (telemetry / status).
  - **Input Report `0x04`**: 1 byte payload (state flag).
  - **Input Report `0x0A`**: 16 bytes payload (telemetry buffer).

### 2. Telephony Collection
- **Usage Page**: `0x0B` (Telephony)
- **Application Usage**: `0x05` (Headset)
- **Reports**:
  - **Input Report `0x05`**: 4 bytes payload (Hook switch, Phone Mute, etc.)
  - **Output Report `0x05`**: 2 bytes payload (Mute / Off-Hook LED controls)

### 3. Consumer Control Collection
- **Usage Page**: `0x0C` (Consumer Devices)
- **Application Usage**: `0x01` (Consumer Control)
- **Reports**:
  - **Input Report `0x0C`**: 1 byte payload (Volume Up/Down, Play/Pause, Mute buttons)

---

## Sysfs & Dev Nodes
- **Active Node**: `/dev/hidraw1`
- **Uevent**:
  ```text
  DRIVER=hid-generic
  HID_ID=0003:00003329:00004B28
  HID_NAME=Audeze LLC Audeze Maxwell XBOX Dongle
  HID_PHYS=usb-0000:00:14.0-12.2.1/input5
  ```
- **Permission requirement**: Unprivileged user access requires udev rule tagging `TAG+="uaccess"`.
