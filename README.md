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

### Interactive Live Console Dashboard & Custom EQ Studio
Launch the live, zero-scrollback, keyboard & mouse-controlled Studio TUI directly in your terminal:
```bash
audezeforlinux dashboard
```
- **Navigation & Controls**:
  - `↑` / `↓`: Move cursor across presets and hardware controls (Sidetone, Game/Chat, AI Noise Reduction)
  - `←` / `→`: Live adjustment of Sidetone volume, Game/Chat mix balance, or AI Noise Reduction modes
  - `Enter` / `Space` / **Mouse Click**: Instantly activate preset or toggle setting
  - `Tab` / **Click**: Switch between **Dashboard & Controls** and **Custom EQ Studio**
  - `r`: Refresh live telemetry from hardware
  - `q` / `Esc`: Exit cleanly back to your shell
- **Custom EQ Studio**:
  - `1` – `4`: Switch between custom hardware slots
  - `←` / `→` or **Click**: Select frequency band (32Hz to 16kHz)
  - `↑` / `↓` or `+` / `-`: Tune band gain in ±0.5 dB steps
  - `s`: **Save directly to Maxwell 2 headset memory** (with automated pre-write backup snapshot)
  - `p`: Cycle pre-tuned audio curves (Harman Curve, Bass Cannon, FPS Footsteps, V-Shape, Warm Vocal, Flat)
  - `f`: Flatten all 10 bands to 0.0 dB

### View Device Status
Displays the stylized branding, active preset pill, battery gauge, mic status, and crossfader slider:
```bash
audezeforlinux status
```
*(Add `--plain` for plain ASCII or `--json` for machine-readable JSON output).*

### Switch Active Preset
```bash
# List all available presets
audezeforlinux eq list

# Select by name
audezeforlinux eq preset "Bass Boost"
audezeforlinux eq preset "Immersive"
audezeforlinux eq preset "Audeze"

# Select custom preset slot (1..4)
audezeforlinux eq preset "Preset 1"
```

### Inspect & Export Custom 10-Band EQ
```bash
# Display 10-band profile for Custom Slot 1 (Preset 1)
audezeforlinux eq custom 1

# Export slot profile to a JSON file
audezeforlinux eq custom 1 --export my_eq.json
```

### Adjust Sidetone
```bash
# Toggle sidetone on / off
audezeforlinux sidetone on
audezeforlinux sidetone off

# Set volume level (0..31)
audezeforlinux sidetone 15
```

### Adjust Game / Chat Balance
```bash
# Set Game/Chat mix by Chat percentage:
audezeforlinux chatmix 50   # 50% Game / 50% Chat (Center)
audezeforlinux chatmix 25   # 75% Game / 25% Chat
audezeforlinux chatmix 80   # 20% Game / 80% Chat
```

### Full Configuration Dump
Exports current status and all 4 custom EQ profiles as a single JSON file:
```bash
audezeforlinux dump --out maxwell_backup.json
```

### State Backups & Recovery
Every change creates a snapshot in `~/.config/maxwell2/backups/`:
```bash
# List all automated pre-write backups
audezeforlinux backup list

# Inspect a specific backup
audezeforlinux backup show backup_set_preset_20261025_034403.json
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
