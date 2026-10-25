# Audeze Maxwell 2 Firmware Architecture & Update Specification

## 1. Executive Summary & Safety Policy

Firmware updates are the highest-risk hardware operation on the Audeze Maxwell 2. An incomplete, corrupted, or out-of-sync firmware write can render the headset or USB wireless dongle inoperable ("bricked"), requiring factory service or low-level JTAG/SWD hardware recovery.

### Safety Invariants
1. **Never Auto-Update**: No update will ever begin automatically or in the background.
2. **Dual-Target Parity Check**: The Audeze Maxwell system consists of **two independent computational nodes** (the USB Dongle and the Headset). Their firmware versions must match. Flashing one without the other can break the proprietary 2.4 GHz wireless pairing link.
3. **Power & Transport Prerequisite**: The headset must report **$\ge 50\%$ battery**, and firmware writes to the headset should ideally take place over direct USB-C rather than over the air (FOTA).
4. **Mandatory Checksum Verification**: Every firmware package must be parsed, uncompressed, and cryptographically verified before any transport packets are sent.
5. **Dry-Run Analysis First**: Any flashing implementation will require an explicit dry-run step that verifies packet layout against official captures.

---

## 2. Hardware Identification & Current Status

Querying the user's live device via `CMD_FIRMWARE` (`0x1C07`):

| Device Node | Transport Routing Byte | Active Firmware Version | Hardware Status |
|:---|:---:|:---:|:---:|
| **USB Dongle** | `0x00` | **`v1.0.5.7.4`** | Operational |
| **Wireless Headset** | `0x80` | **`v1.0.5.7.4`** | Operational & Paired |

Both nodes are currently synchronized on version `v1.0.5.7.4`.

---

## 3. Protocol Architecture: Airoha FOTA & RACE 0x15

The Audeze Maxwell and its dongle run the **Airoha (MediaTek) AB1568** System-on-Chip (SoC).

### 3.1 Packet Framing
While standard settings and telemetry use RACE sync byte `0x05`, Airoha's Firmware-Over-The-Air (FOTA) subsystem uses sync byte **`0x15`**:

```
+------------+------------+--------------------+--------------------+-----------------------+
| Sync Byte  | Direction  | Length (LE16)      | Command ID (LE16)  | Payload               |
| 0x15       | 0x5A / 0x5B| len(Payload) + 2   | FOTA Opcode        | Block data            |
+------------+------------+--------------------+--------------------+-----------------------+
```

- **`0x15 0x5A`**: Host $\rightarrow$ Device firmware block transmission.
- **`0x15 0x5B`**: Device $\rightarrow$ Host block acknowledgment and flash status.

### 3.2 Dual-Device Update Flow
1. **Pre-flight Check**:
   - Query dongle version: `0x05 0x5A 0x03 0x00 0x07 0x1C 0x00` (route `0x00`)
   - Query headset version: `0x05 0x5A 0x03 0x00 0x07 0x1C 0x00` (route `0x80`)
   - Query battery level: `0x05 0x5A 0x03 0x00 0xD6 0x0C 0x00` (must be $\ge 50\%$)
2. **Phase A: Update USB Dongle**:
   - Dongle switches to bootloader mode.
   - Host streams LZMA-compressed firmware partitions via 62-byte HID reports.
   - Dongle verifies flash CRC32 and reboots.
3. **Phase B: Update Headset**:
   - If connected via USB-C: updated directly over USB HID.
   - If connected wirelessly: updated via FOTA over 2.4 GHz link.
   - Headset commits image to secondary flash bank, verifies checksum, and switches partition on reboot.

---

## 4. Firmware Image Container Format

Official Audeze Maxwell firmware distributions encapsulate Airoha AB1568 multi-binary packages containing:
1. **Package Header**: Target product ID list (`0x4B28`, `0x4B29`, `0x4B2A`), version string, and total image length.
2. **System Partition**: Bootloader and OS kernel image.
3. **DSP Partition**: Tensilica HiFi DSP algorithms, biquad filter engines, and AI noise suppression models.
4. **NVDM Default Table**: Default Non-Volatile Data Memory key/value table (including factory EQ presets 1–6 and baseline volume limiter tables).
5. **Checksum Block**: CRC32 and SHA-256 signatures for each discrete partition.

---

## 5. Development Roadmap: Steps Toward a Safe Linux Flasher

To ensure total safety and avoid bricking hardware, firmware update support will be developed strictly according to the following phased milestones:

### Milestone 1: Non-Destructive Version Checking (Completed)
- Implement independent firmware version queries for both dongle (`route 0x00`) and headset (`route 0x80`).
- Display firmware versions side-by-side in `status` and `dashboard` with parity warning if versions diverge.

### Milestone 2: Offline Firmware Package Inspector
- Build an offline tool `scripts/inspect_firmware.py` to parse official firmware `.bin` files:
  - Extract version strings, target device IDs, and partition sizes.
  - Compute and verify checksums against official manifests without sending anything to hardware.

### Milestone 3: Passive Protocol Capture Analysis
- Capture official Audeze HQ firmware update sessions via USBPcap / `usbmon`:
  - Map bootloader entry commands.
  - Map FOTA block chunking sizes and acknowledgment pacing.
  - Mark every command as **CONFIRMED** in `docs/PROTOCOL.md`.

### Milestone 4: Two-Step Interactive CLI Flasher
- Require explicit command line confirmation (`maxwell-ctl firmware flash <file.bin> --confirm-risk`).
- Perform pre-flight battery and connection checks.
- Support progress bar reporting with block retry and safe abort.
