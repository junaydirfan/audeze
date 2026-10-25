# audezeforlinux: Linux Control Tool for Audeze Maxwell 2

An open-source, safe Linux command-line control tool for the **Audeze Maxwell 2** (and Maxwell 1) gaming headset and USB dongle on Linux (CachyOS, Arch, Fedora, Ubuntu, etc.).

This tool provides native Linux access to onboard headset features previously restricted to official Windows/macOS companion apps, including:
- **Real-time Status**: Battery percentage, active preset, firmware version, and hardware microphone mute switch.
- **Onboard Presets**: Select factory presets (Audeze, Treble Boost, Bass Boost, Immersive, Competition, Footsteps) or custom slots (1–4).
- **Custom 10-Band EQ**: Read, export, and inspect custom graphic EQ curves.
- **Hardware Controls**: Sidetone volume and toggle, Game/Chat audio mix balance, AI noise reduction, and volume limiter.
- **Safety First**: Non-destructive, automatic state backups before every write, and complete `--dry-run` simulation support.

---

## Safety Principles

1. **Strictly Non-Destructive**: No firmware flashing or bootloader commands. Firmware queries are read-only.
2. **Explicit Verification & Allowlist**: Every command is validated against verified packet ranges before sending. Arbitrary or fuzzed bytes are rejected.
3. **Pre-Write Backups**: Before modifying any hardware setting (preset, sidetone, chat mix, EQ), the current state is snapshotted to `~/.config/maxwell2/backups/`.
4. **Dry-Run Capability**: Any command can be run with `--dry-run` to print exact hex reports and payloads without touching hardware.

---

## Supported Hardware

| Product Name | USB VID:PID | Transport | Status |
|:---|:---:|:---:|:---:|
| **Maxwell 2 (Xbox Dongle)** | `3329:4B28` | Wireless Dongle | **Verified & Tested** |
| **Maxwell 2 (PlayStation / PC Dongle)** | `3329:4B29` | Wireless Dongle | Supported |
| **Maxwell 2 (USB-C Direct)** | `3329:4B2A` | Direct USB | Supported |
| **Maxwell 1 (Xbox Dongle)** | `3329:4B18` | Wireless Dongle | Supported |
| **Maxwell 1 (PlayStation Dongle)** | `3329:4B19` | Wireless Dongle | Supported |
| **Maxwell 1 (PlayStation USB-C)** | `3329:4B1A` | Direct USB | Supported |
| **Maxwell 1 (Xbox USB-C)** | `3329:4B1E` | Direct USB | Supported |

---

## Installation & Setup

### 1. Install Udev Rules (Run Without Sudo)
To allow your normal user account to access the headset's HID control interface:

```bash
sudo cp udev/70-audeze-maxwell.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```
*(Unplug and replug the USB dongle or headset cable after installing).*

### 2. Run Directly or Install via pip
The tool requires Python 3.8+ and uses only the Python standard library.

Run directly:
```bash
./audezeforlinux status
# or
./maxwell_ctl.py status
```

Or install locally in editable mode:
```bash
pip install -e .
audezeforlinux status
```

---

## CLI & TUI Usage

### Interactive Live Studio Dashboard
Launch the unified 4-tab Studio TUI directly in your terminal — everything can be controlled interactively without typing individual commands:
```bash
audezeforlinux dashboard
```
- **Tab 1: `[ 1. CONTROLS ]` (Controls & Presets)**:
  - `↑` / `↓`: Move cursor across 10 Presets and hardware sliders (Sidetone, Game/Chat Mix, AI Noise Reduction, Volume Limiter).
  - `←` / `→`: Live adjustment of Sidetone volume, Game/Chat mix, or AI Noise Reduction mode.
  - `Enter` / `Space` / **Mouse Click**: Instantly activate preset or toggle setting.
  - `[` / `]`: Quick fine-tune sidetone volume (0..31).
- **Tab 2: `[ 2. EQ STUDIO ]` (10-Band Graphic Equalizer)**:
  - `1` – `4`: Switch custom hardware slots (Presets 7–10).
  - `←` / `→` or **Click**: Select frequency band (32 Hz to 16 kHz).
  - `↑` / `↓` or `+` / `-`: Tune band gain in ±0.5 dB steps.
  - `s`: **Save & activate directly in Maxwell 2 headset memory**.
  - `p`: Cycle pre-tuned audio curves (Harman Target, Bass Boost, FPS Footsteps, V-Shape, Vocal Clarity, Flat).
  - `e`: Export current custom curve to a JSON file.
  - `0` / `f`: Flatten all 10 bands to 0.0 dB.
- **Tab 3: `[ 3. FIRMWARE & FLASHER ]` (Firmware & Safety Studio)**:
  - **Live Hardware Telemetry**: Dongle & Headset version parity, battery level, and dual-bank safety status.
  - **Official Changelog Browser**: `↑` / `↓` scroll through official Audeze Maxwell 2 releases (v1.0.5.7.4 back to v1.0.2.49) with full release notes.
  - **FOTA Flashing & Block Simulator**:
    - `s`: Run real-time FOTA block streaming simulation with live animated progress bar, KB/s throughput, and ETA.
    - `t`: Toggle target node between `[ DONGLE ]` and `[ HEADSET ]`.
    - `c`: Cancel active simulation.
- **Tab 4: `[ 4. SYSTEM & BACKUPS ]` (Diagnostics & Backups)**:
  - **Hardware Diagnostics**: View USB VID:PID, device nodes, SoC processor info, and NVDM balance key state.
  - **Backups Browser**: View recent timestamped pre-write backups from `~/.config/maxwell2/backups/`.
  - `b`: Create instant full snapshot backup of all settings & EQ curves.
  - `d`: Export complete state to `./maxwell_dump.json`.
  - `r`: Refresh live telemetry from device.
- **Global Keys**:
  - `Tab` / **Mouse Click**: Switch tabs.
  - `q` / `Esc`: Exit cleanly back to your shell.

### Volume Limiter (Hearing Safety 85 dB)
```bash
# Query current volume limiter status
audezeforlinux limiter

# Enable hearing-safe 85 dB volume limit
audezeforlinux limiter on

# Disable limiter for full dynamic range
audezeforlinux limiter off
```

### Firmware Diagnostics, Inspection & Updates
```bash
# 1. Dual-node version check, parity verification & battery safety gate
audezeforlinux firmware

# 2. Check official release catalog and changelogs against installed version
audezeforlinux firmware check
# Or compare directly against an official package:
audezeforlinux firmware check --package path/to/firmware.bin

# 3. Stream firmware update with dual-bank recovery safety (dry-run by default):
audezeforlinux firmware flash path/to/firmware.bin --target dongle --dry-run
# Live flashing requires explicit confirmation gate:
audezeforlinux firmware flash path/to/firmware.bin --target dongle --confirm-risk

# 4. Offline inspection of an official .bin firmware package (SHA-256 & partition hashes)
audezeforlinux firmware inspect path/to/firmware.bin

# 5. Decompress LZMA payload and extract individual partitions (Bootloader, Kernel, DSP, NVDM)
audezeforlinux firmware unpack path/to/firmware.bin --out ./extracted_firmware

# 6. Simulate FOTA transmission parameters and chunk layout
audezeforlinux firmware simulate path/to/firmware.bin --target headset
```

### Dry-Run Simulation Mode
Inspect exact USB HID report byte layouts without opening or transmitting to the hardware:
```bash
audezeforlinux --dry-run status
audezeforlinux --dry-run eq preset "Immersive"
```

---

## Documentation

- [docs/DEVICE.md](docs/DEVICE.md): USB interface tree, endpoint addresses, and report descriptor breakdown.
- [docs/PROTOCOL.md](docs/PROTOCOL.md): Airoha RACE protocol framing, opcode reference, and memory layouts.
- [docs/CAPTURE_WORKFLOW.md](docs/CAPTURE_WORKFLOW.md): Packet capture naming conventions and isolation checklist.
- [docs/NOTES.md](docs/NOTES.md): Running technical log of verified hardware findings vs hypotheses.

---

## Running Offline Tests

The protocol parser and framing layer include offline unit tests:
```bash
python3 -m unittest discover tests
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
