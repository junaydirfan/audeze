# Project Notes & Decision Log

## Objectives
- Reverse-engineer and provide a safe, open-source Linux CLI control tool (`maxwell-ctl`) for the Audeze Maxwell 2 headset and USB dongle.
- Primary target: CachyOS / Arch Linux with PipeWire & WirePlumber.
- Language: Python 3 prototype (standard library direct sysfs/hidraw access, no external dependencies).

## Core Safety Principles
1. **Never send arbitrary or fuzzed bytes**: Only replay commands explicitly marked `CONFIRMED` in `docs/PROTOCOL.md` or manually approved.
2. **Explicit write controls & `--dry-run`**: Any action mutating hardware state must be clearly surfaced and support a dry-run flag.
3. **No firmware or bootloader modifications in Phases 1-3**: Firmware reading only.
4. **No unauthorized PipeWire / WirePlumber audio stack mutations**: Report diffs or suggestions without automated invasive changes.
5. **State backup**: Read and store state prior to writing any changes so they can be restored.

---

## Log of Findings and Decisions

### Phase 1: Discovery (Verified)
- **Status**: Completed device enumeration and descriptor parsing.
- **Hardware Found**:
  - Device: Audeze Maxwell 2 (Xbox Dongle variant)
  - USB VID:PID: `3329:4B28`
  - Linux Kernel Audio: `snd-usb-audio` (Interfaces 0, 1, 2, 3, 4)
  - Linux Kernel HID: `usbhid` (Interface 5) mapped to `/dev/hidraw1`
- **Verified HID Architecture**:
  - Report Descriptor length: 175 bytes
  - Vendor collection: Usage Page `0xFF13`
  - Command output: Report ID `0x06` (61 bytes payload -> 62 bytes total HID report)
  - Reply input: Report ID `0x07` (61 bytes payload -> 62 bytes total HID report)
  - Telemetry: Report ID `0x03` (13 bytes), `0x04` (1 byte), `0x0A` (16 bytes)
  - Telephony: Report ID `0x05` (Hook, Phone Mute)
  - Consumer: Report ID `0x0C` (Volume buttons)

### Phase 2: Protocol Analysis (Completed)
- **Status**: Completed protocol analysis, formal specification in `docs/PROTOCOL.md`, Python protocol layer, and offline unit tests.
- **Verified Protocol Standard**:
  - Transport: Fixed 62-byte HID reports with Report ID 0x06 (Host -> Device) and 0x07 (Device -> Host).
  - Routing: Dongle routing flag `0x80` at report offset 2; direct USB-C headset uses `0x00`.
  - Framing: Airoha RACE protocol (`0x05 0x5A <len_le16> <cmd_le16> <payload>`).
  - Active Preset: Read via `0x0901`, Sub `0x00` (`05 5A 04 00 01 09 00 00`). Write via `0x0900`, Sub `0x00`.
  - Battery Query: Opcode `0x0CD6` (`05 5A 03 00 D6 0C 00`), notified asynchronously via direction `0x5D`.
  - Firmware Query: Opcode `0x1C07` (`05 5A 03 00 07 1C 00`), notified asynchronously via direction `0x5D`.
  - Controls: Subcommands for Sidetone (`0x07`/`0x2C`), Chat Mix (`0x0B`), Limiter (`0x28`), AI Noise Suppression (`0x24`), Mic Mute (`0x22`).
  - Equalizer: NVDM storage keys `0xEF00..0xEF03` for 10-band slider records (185 bytes each, little-endian); keys `0xE42C..0xE42F` for 844-byte DSP biquads.

### Phase 3: Safe Client & CLI (Completed)
- **Status**: Full Python module, transport layer, backup manager, CLI (`maxwell-ctl`), udev rules, and pyproject.toml created.
- **Components Built**:
  - `maxwell2/transport.py`: Linux `/dev/hidraw` transport with auto-discovery, report chunking, and `--dry-run` simulation.
  - `maxwell2/backup.py`: Pre-write snapshot manager creating timestamped rollback JSON files in `~/.config/maxwell2/backups/`.
  - `maxwell2/client.py`: High-level operations (`get_status`, `set_preset`, `read_custom_eq`, `set_sidetone`, `set_chat_mix`, `dump_all`).
  - `maxwell_ctl.py`: Full CLI utility supporting:
    - `maxwell-ctl status`
    - `maxwell-ctl eq preset <name>`
    - `maxwell-ctl eq list`
    - `maxwell-ctl eq custom <slot> [--export file.json]`
    - `maxwell-ctl sidetone <0-31|on|off>`
    - `maxwell-ctl chatmix <0-100>`
    - `maxwell-ctl dump [--out file.json]`
    - `maxwell-ctl backup list` / `maxwell-ctl backup show <file>`
- **Assumptions vs. Verified**:
  - *Verified*: Dry-run report generation and report chunking produce exact byte sequences matching the specification. Pre-write backups write and load valid JSON snapshots. All unit tests pass.
