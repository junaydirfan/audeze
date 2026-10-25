# USB Packet Capture Workflow & Checklist

This document defines the procedure for capturing and isolating USB HID control packets from the official Audeze HQ app without a dedicated physical Windows/macOS machine.

---

## 1. Capture Environment Setup on CachyOS / Linux

Since no native Windows or macOS machine is available, we use a lightweight Windows Virtual Machine on CachyOS with USB device passthrough:

### Setup Options
1. **QEMU / KVM with USB Host Passthrough**:
   - Install `qemu-desktop` and `virt-manager` (or run a quick Windows 10/11 VM using QEMU directly).
   - Pass through the dongle to the guest VM:
     ```bash
     -device qemu-xhci -device usb-host,vendorid=0x3329,productid=0x4b28
     ```
2. **Alternative: Quickemu**:
   - `quickemu --vm windows-11.conf` with USB passthrough enabled in configuration.
3. **Alternative: Windows To Go / Dual Boot or temporary loaner**:
   - If a VM is too heavy, a temporary Windows PE / live environment with USBPcap.

### Capture Mechanism: Host vs Guest
- **Host Capture via `usbmon` (Recommended)**:
  - Load the kernel module: `sudo modprobe usbmon`
  - Install Wireshark / tshark on CachyOS: `sudo pacman -S wireshark-cli wireshark-qt`
  - Wireshark will show `usbmon1` (Bus 1 where the dongle resides).
  - Filter in Wireshark:
    ```text
    usb.idVendor == 0x3329 && usb.idProduct == 0x4b28
    ```
- **Guest Capture via USBPcap**:
  - Install Wireshark + USBPcap inside the Windows VM.
  - Bind USBPcap to the Audeze Maxwell USB device.

---

## 2. Packet Capture Naming Convention

All captures must be saved in `captures/` using the format:
```text
captures/<category>_<action>_<value>_<iteration>.pcapng
```

### Examples:
- `captures/baseline_idle_1.pcapng`
- `captures/preset_select_audeze_1.pcapng`
- `captures/preset_select_custom1_1.pcapng`
- `captures/eq_custom1_band1_plus3db_1.pcapng`
- `captures/sidetone_set_50_1.pcapng`
- `captures/sidetone_toggle_off_1.pcapng`
- `captures/chatmix_game_100_1.pcapng`
- `captures/noise_removal_high_1.pcapng`
- `captures/firmware_read_1.pcapng`

---

## 3. Step-by-Step Capture Checklist

> [!IMPORTANT]
> To make packet diffing trivial, capture **one action at a time**.
> Start capture -> perform exactly ONE click/slider adjustment -> wait 2 seconds -> stop capture.

### Phase 1: Baseline & Telemetry
- [ ] `baseline_idle_1.pcapng`: Start capture with Audeze HQ open, no user interaction for 10 seconds.
- [ ] `firmware_version_read_1.pcapng`: Refreshing / viewing device info screen showing dongle and headset firmware versions.

### Phase 2: Preset Selection
- [ ] `preset_select_audeze_1.pcapng`: Select stock "Audeze" preset
- [ ] `preset_select_treble_boost_1.pcapng`: Select stock "Treble Boost" preset
- [ ] `preset_select_bass_boost_1.pcapng`: Select stock "Bass Boost" preset
- [ ] `preset_select_immersive_1.pcapng`: Select stock "Immersive" preset
- [ ] `preset_select_competition_1.pcapng`: Select stock "Competition" preset
- [ ] `preset_select_footsteps_1.pcapng`: Select stock "Footsteps" preset
- [ ] `preset_select_custom1_1.pcapng`: Select "Preset 1" (Custom Slot 0)
- [ ] `preset_select_custom2_1.pcapng`: Select "Preset 2" (Custom Slot 1)
- [ ] `preset_select_custom3_1.pcapng`: Select "Preset 3" (Custom Slot 2)
- [ ] `preset_select_custom4_1.pcapng`: Select "Preset 4" (Custom Slot 3)

### Phase 3: Custom EQ Edits (Slot 1)
- [ ] `eq_custom1_flat_baseline_1.pcapng`: Custom 1 with all bands at 0 dB
- [ ] `eq_custom1_band1_32hz_plus6db_1.pcapng`: Move Band 1 (32 Hz) from 0 dB to +6 dB
- [ ] `eq_custom1_band2_64hz_minus4db_1.pcapng`: Move Band 2 (64 Hz) from 0 dB to -4 dB
- [ ] `eq_custom1_band10_16khz_plus3db_1.pcapng`: Move Band 10 (16 kHz) from 0 dB to +3 dB

### Phase 4: Headset Hardware Controls
- [ ] `sidetone_toggle_on_1.pcapng`: Toggle Sidetone ON
- [ ] `sidetone_toggle_off_1.pcapng`: Toggle Sidetone OFF
- [ ] `sidetone_level_25_1.pcapng`: Set Sidetone level to 25%
- [ ] `sidetone_level_75_1.pcapng`: Set Sidetone level to 75%
- [ ] `chatmix_center_1.pcapng`: Set Game/Chat mix to 50/50 (center)
- [ ] `chatmix_game_75_1.pcapng`: Set Game/Chat mix favoring Game (75%)
- [ ] `chatmix_chat_75_1.pcapng`: Set Game/Chat mix favoring Chat (75%)
- [ ] `noise_reduction_off_1.pcapng`: Set AI Noise Reduction to OFF
- [ ] `noise_reduction_low_1.pcapng`: Set AI Noise Reduction to LOW
- [ ] `noise_reduction_high_1.pcapng`: Set AI Noise Reduction to HIGH
- [ ] `mic_mute_read_1.pcapng`: Flip hardware mic mute switch ON and OFF while capturing
