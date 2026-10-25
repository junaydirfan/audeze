# maxwell-ctl: Linux Control Tool for Audeze Maxwell 2

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
./maxwell_ctl.py status
```

Or install locally in editable mode:
```bash
pip install -e .
maxwell-ctl status
```

---

## CLI Usage

### View Device Status
Displays active preset, battery level, firmware version, mic switch, sidetone, and chat mix:
```bash
maxwell-ctl status
```
*(Add `--json` for machine-readable JSON output).*

### Switch Active Preset
```bash
# List all available presets
maxwell-ctl eq list

# Select by name
maxwell-ctl eq preset "Bass Boost"
maxwell-ctl eq preset "Audeze"

# Select custom preset slot (1..4)
maxwell-ctl eq preset "Preset 1"
```

### Inspect & Export Custom 10-Band EQ
```bash
# Display 10-band profile for Custom Slot 1 (Preset 1)
maxwell-ctl eq custom 1

# Export slot profile to a JSON file
maxwell-ctl eq custom 1 --export my_eq.json
```

### Adjust Sidetone
```bash
# Toggle sidetone on / off
maxwell-ctl sidetone on
maxwell-ctl sidetone off

# Set volume level (0..31)
maxwell-ctl sidetone 15
```

### Adjust Game / Chat Balance
```bash
# Set Game/Chat mix by Chat percentage:
maxwell-ctl chatmix 50   # 50% Game / 50% Chat (Center)
maxwell-ctl chatmix 25   # 75% Game / 25% Chat
maxwell-ctl chatmix 80   # 20% Game / 80% Chat
```

### Full Configuration Dump
Exports current status and all 4 custom EQ profiles as a single JSON file:
```bash
maxwell-ctl dump --out maxwell_backup.json
```

### State Backups & Recovery
Every change creates a snapshot in `~/.config/maxwell2/backups/`:
```bash
# List all automated pre-write backups
maxwell-ctl backup list

# Inspect a specific backup
maxwell-ctl backup show backup_set_preset_20261025_034403.json
```

### Dry-Run Simulation Mode
Inspect exact USB HID report byte layouts without opening or transmitting to the hardware:
```bash
maxwell-ctl --dry-run status
maxwell-ctl --dry-run eq preset "Immersive"
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
