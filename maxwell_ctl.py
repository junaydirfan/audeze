#!/usr/bin/env python3
"""
maxwell-ctl: Linux CLI control tool for Audeze Maxwell 2 headset and USB dongle.
Supports device status, preset switching, custom 10-band EQ import/export,
sidetone, chat mix, noise reduction, and state backups.
"""

import sys
import os
import json
import argparse
from typing import Optional

from maxwell2.transport import Transport, DeviceNotFoundError, DevicePermissionError
from maxwell2.client import MaxwellClient
from maxwell2.protocol import PRESET_NAMES
from maxwell2.backup import list_backups, load_backup


def format_status(status: dict) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("  AUDEZE MAXWELL 2 - DEVICE STATUS")
    lines.append("=" * 60)

    # Preset
    preset = status.get("preset", {})
    p_name = preset.get("name", "Unknown")
    p_idx = preset.get("index", "?")
    p_custom = " (Custom Slot " + str(preset.get("slot") + 1) + ")" if preset.get("is_custom") else ""
    lines.append(f"  Active Preset      : [{p_idx}] {p_name}{p_custom}")

    # Battery
    batt = status.get("battery_percent")
    batt_str = f"{batt}%" if batt is not None else "Unknown / Disconnected"
    lines.append(f"  Battery Level      : {batt_str}")

    # Firmware
    fw = status.get("firmware", {}).get("firmware", "Unknown")
    lines.append(f"  Firmware Version   : {fw}")

    # Mic Mute
    mute = status.get("mic_muted")
    mute_str = "MUTED" if mute is True else ("UNMUTED" if mute is False else "Unknown")
    lines.append(f"  Hardware Mic Switch: {mute_str}")

    # Sidetone
    st = status.get("sidetone", {})
    st_state = "ON" if st.get("enabled") else "OFF"
    st_lvl = st.get("level", 0)
    st_max = st.get("max_level", 31)
    lines.append(f"  Sidetone           : {st_state} (Level {st_lvl}/{st_max})")

    # Chat Mix
    cm = status.get("chat_mix", {})
    game_pct = cm.get("game_pct", 50)
    chat_pct = cm.get("chat_pct", 50)
    lines.append(f"  Game / Chat Mix    : Game {game_pct}% | Chat {chat_pct}%")

    # Noise Reduction
    nr = status.get("noise_reduction", {}).get("name", "Unknown")
    lines.append(f"  AI Noise Reduction : {nr}")

    # Limiter
    lim = status.get("limiter", {}).get("enabled")
    lim_str = "Enabled (85 dB)" if lim else "Disabled"
    lines.append(f"  Volume Limiter     : {lim_str}")

    lines.append("=" * 60)
    return "\n".join(lines)


def format_eq(eq_data: dict) -> str:
    lines = []
    slot = eq_data.get("slot", 0)
    lines.append("=" * 60)
    lines.append(f"  CUSTOM EQ PROFILE (Preset {slot + 1} / Slot {slot})")
    lines.append("=" * 60)
    lines.append(f"  {'Band':<6} | {'Frequency':<12} | {'Gain (dB)':<12} | {'Q':<8}")
    lines.append("  " + "-" * 46)

    for band in eq_data.get("bands", []):
        b_idx = band.get("band_index", 0) + 1
        freq = band.get("frequency_hz", 0)
        freq_str = f"{freq:.0f} Hz" if freq < 1000 else f"{freq/1000:.1f} kHz"
        gain = band.get("gain_db", 0.0)
        gain_str = f"{gain:+.1f} dB"
        q = band.get("q", 1.41)
        lines.append(f"  {b_idx:<6} | {freq_str:<12} | {gain_str:<12} | {q:<8.2f}")

    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        prog="maxwell-ctl",
        description="Safe Linux control CLI for Audeze Maxwell 2 headset and USB dongle.",
    )
    parser.add_argument("--device", help="Direct path to /dev/hidraw node (auto-detected by default)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate commands and print bytes without sending")
    parser.add_argument("--json", action="store_true", help="Format CLI output as JSON")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. status
    subparsers.add_parser("status", help="Read headset status (battery, preset, mic, controls)")

    # 2. eq
    eq_parser = subparsers.add_parser("eq", help="Equalizer controls")
    eq_sub = eq_parser.add_subparsers(dest="eq_action", required=True)

    # eq preset <name_or_number>
    eq_preset = eq_sub.add_parser("preset", help="Select active preset")
    eq_preset.add_argument("name", help="Preset name or index (1..10, e.g. 'Audeze', 'Bass Boost', '1', '7')")

    # eq list
    eq_sub.add_parser("list", help="List all available preset names")

    # eq custom <slot> [--file profile.json] [--export out.json]
    eq_custom = eq_sub.add_parser("custom", help="View, import, or export custom 10-band EQ")
    eq_custom.add_argument("slot", type=int, choices=[1, 2, 3, 4], help="Custom preset slot number (1..4)")
    eq_custom.add_argument("--file", help="JSON profile to write to the slot")
    eq_custom.add_argument("--export", help="Save the slot's current EQ profile to a JSON file")

    # 3. sidetone
    st_parser = subparsers.add_parser("sidetone", help="Control sidetone")
    st_parser.add_argument("value", help="Level (0..31), 'on', or 'off'")

    # 4. chatmix
    cm_parser = subparsers.add_parser("chatmix", help="Adjust Game/Chat balance (0..100 percent Chat)")
    cm_parser.add_argument("value", type=int, help="Chat percentage (0 = 100 percent Game, 50 = 50/50, 100 = 100 percent Chat)")

    # 5. dump
    dump_parser = subparsers.add_parser("dump", help="Dump complete state and all 4 custom EQ slots as JSON")
    dump_parser.add_argument("--out", help="Save dump to specified JSON file")

    # 6. backup
    bk_parser = subparsers.add_parser("backup", help="Manage automated pre-write configuration backups")
    bk_sub = bk_parser.add_subparsers(dest="backup_action", required=True)
    bk_sub.add_parser("list", help="List all available backups")
    bk_show = bk_sub.add_parser("show", help="Display details of a backup file")
    bk_show.add_argument("file", help="Filename or path of backup")

    args = parser.parse_args()

    # Handle offline commands first (backups, eq list)
    if args.command == "eq" and args.eq_action == "list":
        if args.json:
            print(json.dumps([{"index": i, "name": n} for i, n in enumerate(PRESET_NAMES, 1)], indent=2))
        else:
            print("\nAvailable Onboard Presets:")
            for idx, name in enumerate(PRESET_NAMES, 1):
                custom_tag = " [Custom Slot " + str(idx - 6) + "]" if idx >= 7 else ""
                print(f"  {idx:2d}. {name}{custom_tag}")
            print()
        return

    if args.command == "backup":
        if args.backup_action == "list":
            backups = list_backups()
            if args.json:
                print(json.dumps(backups, indent=2))
            else:
                if not backups:
                    print("No backups found in ~/.config/maxwell2/backups/.")
                else:
                    print(f"\nAvailable Backups ({len(backups)}):")
                    for b in backups:
                        print(f"  - {b['filename']} (Action: {b['action']}, Time: {b['timestamp']})")
                    print()
            return
        elif args.backup_action == "show":
            data = load_backup(args.file)
            print(json.dumps(data, indent=2))
            return

    # Initialize transport and client
    try:
        transport = Transport(hidraw_path=args.device, dry_run=args.dry_run)
        with transport:
            client = MaxwellClient(transport)

            if args.command == "status":
                status = client.get_status()
                if args.json:
                    print(json.dumps(status, indent=2))
                else:
                    print(format_status(status))

            elif args.command == "eq" and args.eq_action == "preset":
                res = client.set_preset(args.name)
                if args.json:
                    print(json.dumps(res, indent=2))
                else:
                    p = res["preset"]
                    dry = " [DRY-RUN]" if res.get("dry_run") else ""
                    print(f"[+] Preset switched successfully to: [{p['index']}] {p['name']}{dry}")
                    print(f"    Backup saved to: {res['backup_file']}")

            elif args.command == "eq" and args.eq_action == "custom":
                slot_idx = args.slot - 1  # 0..3
                eq_data = client.read_custom_eq(slot_idx)

                if args.export:
                    with open(args.export, "w", encoding="utf-8") as f:
                        json.dump(eq_data, f, indent=2)
                    print(f"[+] Exported Custom Preset {args.slot} to {args.export}")
                elif args.json:
                    print(json.dumps(eq_data, indent=2))
                else:
                    print(format_eq(eq_data))

            elif args.command == "sidetone":
                val_str = args.value.strip().lower()
                if val_str in ("on", "enable", "true"):
                    res = client.set_sidetone(enabled=True)
                    print("[+] Sidetone enabled.")
                elif val_str in ("off", "disable", "false"):
                    res = client.set_sidetone(enabled=False)
                    print("[+] Sidetone disabled.")
                else:
                    try:
                        lvl = int(val_str)
                        res = client.set_sidetone(level=lvl)
                        print(f"[+] Sidetone level set to {lvl}.")
                    except ValueError:
                        print(f"[-] Invalid sidetone value '{args.value}'. Use 'on', 'off', or a number.")
                        sys.exit(1)

            elif args.command == "chatmix":
                # Convert 0..100% Chat to 0..20 raw value
                raw_val = int((args.value / 100.0) * 20)
                raw_val = max(0, min(20, raw_val))
                res = client.set_chat_mix(raw_val)
                print(f"[+] Game/Chat mix adjusted to {args.value}% Chat (Raw: {raw_val}/20).")

            elif args.command == "dump":
                full_dump = client.dump_all()
                if args.out:
                    with open(args.out, "w", encoding="utf-8") as f:
                        json.dump(full_dump, f, indent=2)
                    print(f"[+] Complete configuration dumped to {args.out}")
                else:
                    print(json.dumps(full_dump, indent=2))

    except DeviceNotFoundError as e:
        print(f"[-] {e}")
        sys.exit(1)
    except DevicePermissionError as e:
        print(f"[-] {e}")
        sys.exit(2)
    except Exception as e:
        print(f"[-] Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
