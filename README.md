# audezeforlinux: Linux Control Tool for Audeze Maxwell 2

An open-source, safe Linux command-line control tool for the **Audeze Maxwell 2** (and Maxwell 1) gaming headset and USB dongle on Linux (CachyOS, Arch, Fedora, Ubuntu, etc.).

This tool provides native Linux access to onboard headset features previously restricted to official Windows/macOS companion apps, including:
- **Real-time Status**: Battery percentage, active preset, firmware version, and hardware microphone mute switch.
- **Onboard Presets**: Select factory presets (Audeze, Treble Boost, Bass Boost, Immersive, Footsteps, Competition) or custom slots (1–4).
- **Custom 10-Band EQ**: Interactive horizontal graphic equalizer with Harman Target, FPS Footsteps, and custom curves saved directly to headset hardware memory.
- **Hardware Controls**: Sidetone volume and toggle, Game/Chat audio mix balance, and AI noise reduction.
- **Firmware & Flashing**: Official Maxwell 2 changelog browser, dual-node parity inspection, package verification, and dual-bank protected FOTA flasher.
- **Linux Distro Portability**: Comprehensive environment diagnostics (`doctor`), 1-step udev rule setup (`setup-udev`), and desktop app integration (`install-system`).
- **Safety First**: Non-destructive, automatic state backups before every write, and complete `--dry-run` simulation support.

---

## Quick Setup & Distro Portability

`audezeforlinux` is 100% written in pure Python (standard library only) and works out-of-the-box on **Arch Linux, CachyOS, Fedora, Ubuntu, Debian, openSUSE, and Steam Deck**.

### 1. Automated 1-Step Setup (Recommended)
Run the automated setup to install udev rules for non-root hardware access and add the command to your desktop menu:

```bash
# 1. Install udev rules (prompts for sudo if needed, reloads udev rules automatically)
./audezeforlinux setup-udev

# 2. Install desktop launcher and user PATH symlink (~/.local/bin/audezeforlinux)
./audezeforlinux install-system

# 3. Verify your Linux audio environment and device permissions
./audezeforlinux doctor
```

*(Unplug and replug the USB dongle once after running `setup-udev`).*

---

## CLI & TUI Usage

### Interactive Live Studio Dashboard
Launch the unified 4-tab Studio TUI directly in your terminal — everything can be controlled interactively without typing individual commands:
```bash
audezeforlinux dashboard
```
- **Tab 1: `[ 1. CONTROLS ]` (Controls & Presets)**:
  - `↑` / `↓`: Move cursor across 10 Presets and hardware sliders (Sidetone, Game/Chat Mix, AI Noise Reduction).
  - `←` / `→`: Live adjustment of Sidetone volume, Game/Chat mix, or AI Noise Reduction mode.
  - `Enter` / `Space` / **Mouse Click**: Instantly activate preset or toggle setting.
  - `[` / `]`: Quick fine-tune sidetone volume (0..31).
- **Tab 2: `[ 2. EQ STUDIO ]` (Horizontal 10-Band Graphic Equalizer)**:
  - `←` / `→` or **Click**: Select frequency band across the horizontal spectrum (32 Hz to 16 kHz).
  - `↑` / `↓` or `+` / `-`: Tune band gain in ±0.5 dB steps (-12.0 dB to +12.0 dB).
  - `1` – `4`: Switch custom hardware slots (Presets 7–10).
  - `s`: **Save & write directly to Maxwell 2 headset hardware NVDM memory**.
  - `p`: Cycle pre-tuned audio curves (Harman Target, Bass Boost, FPS Footsteps, V-Shape, Vocal Clarity, Flat).
  - `e`: Export current custom curve to a JSON file.
  - `0` / `f`: Flatten all 10 bands to 0.0 dB.
- **Tab 3: `[ 3. FIRMWARE & FLASHER ]` (Firmware Diagnostics & Flasher)**:
  - **Live Dual-Node Telemetry**: Dongle & Headset version parity, battery level, and dual-bank safety readiness.
  - **Official Changelog Browser**: `↑` / `↓` scroll through official Audeze Maxwell 2 releases (v1.0.5.7.4 back to v1.0.2.49) with full release notes.
  - **Pre-Flight Verified Flasher**: Live safety gate verifying node responsiveness, battery reserve (>30%), and package integrity.
- **Tab 4: `[ 4. SYSTEM & BACKUPS ]` (Diagnostics & Backups)**:
  - **Environment Doctor**: Live check of Linux kernel hidraw, PipeWire/WirePlumber, USB detection, and permissions.
  - **Hardware Diagnostics**: View USB VID:PID, device nodes, SoC processor info, and NVDM balance key state.
  - **Backups Browser**: View recent timestamped pre-write backups from `~/.config/maxwell2/backups/`.
  - `b`: Create instant full snapshot backup of all settings & EQ curves.
  - `d`: Export complete state to `./maxwell_dump.json`.
  - `r`: Refresh live telemetry from device.
- **Global Keys**:
  - `Tab` / **Mouse Click**: Switch tabs.
  - `q` / `Esc`: Exit cleanly back to your shell.

---

### Firmware Diagnostics, Inspection & Updates
```bash
# 1. Dual-node version check, parity verification & battery safety gate
audezeforlinux firmware status

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
