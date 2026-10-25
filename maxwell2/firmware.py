"""
audezeforlinux: Firmware diagnostics, verification, and inspection subsystem.
Provides dual-device firmware version queries, parity checks, update safety prerequisites,
and offline inspection of official Audeze/Airoha firmware binary packages.
"""

import os
import sys
import struct
import hashlib
import binascii
import re
from typing import Optional, Dict, Any, List

from maxwell2.client import MaxwellClient
from maxwell2.protocol import (
    build_firmware_command,
    parse_firmware_notification,
    CMD_FIRMWARE,
    ROUTE_DONGLE,
    ROUTE_DIRECT,
)


def get_firmware_diagnostics(client: MaxwellClient) -> Dict[str, Any]:
    """
    Performs comprehensive firmware diagnostic checks across both computational nodes
    (Dongle and Headset) and evaluates safety prerequisites for updates.
    """
    if client.transport.dry_run:
        return {
            "dongle": {"firmware": "v1.0.5.7.4", "route": 0x00, "status": "Operational"},
            "headset": {"firmware": "v1.0.5.7.4", "route": 0x80, "status": "Operational"},
            "parity_match": True,
            "battery_percent": 94,
            "battery_safe_for_flashing": True,
            "update_prerequisites_met": True,
            "dry_run": True,
        }

    # 1. Query dual firmware versions
    fw_info = client.get_firmware()
    dongle_fw = fw_info.get("dongle", "Unknown")
    headset_fw = fw_info.get("headset", "Unknown")
    dongle_ok = (dongle_fw != "Unknown")
    headset_ok = (headset_fw != "Unknown")

    # 3. Query Battery
    batt_pct = client.get_battery()
    batt_safe = (batt_pct is not None and batt_pct >= 50)

    # 4. Parity check
    parity = (dongle_ok and headset_ok and dongle_fw == headset_fw)

    # 5. Overall flash safety evaluation
    safe_to_update = parity and batt_safe and dongle_ok and headset_ok

    return {
        "dongle": {
            "firmware": dongle_fw,
            "route": 0x00,
            "status": "Operational" if dongle_ok else "Unreachable",
        },
        "headset": {
            "firmware": headset_fw,
            "route": 0x80,
            "status": "Operational" if headset_ok else "Unreachable",
        },
        "parity_match": parity,
        "battery_percent": batt_pct,
        "battery_safe_for_flashing": batt_safe,
        "update_prerequisites_met": safe_to_update,
    }


def inspect_firmware_package(filepath: str) -> Dict[str, Any]:
    """
    Safely inspects and parses an official Audeze / Airoha firmware package file (.bin).
    Extracts embedded version numbers, detects LZMA partitions, computes SHA-256 and CRC32,
    and validates target hardware signatures without writing anything to hardware.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Firmware file not found: {filepath}")

    file_size = os.path.getsize(filepath)
    if file_size == 0:
        raise ValueError("Firmware file is empty.")

    with open(filepath, "rb") as f:
        data = f.read()

    # 1. Cryptographic Hashes
    sha256 = hashlib.sha256(data).hexdigest()
    crc32 = f"{binascii.crc32(data) & 0xFFFFFFFF:08X}"

    # 2. String & Version Extraction (search for version signatures like v1.0.X.X or 1.0.X)
    text_strings = []
    # Find all printable ASCII sequences of length 4+
    for match in re.finditer(b"[\x20-\x7E]{4,}", data):
        try:
            s = match.group(0).decode("ascii")
            if any(k in s.lower() for k in ["v1.", "maxwell", "audeze", "airoha", "fota", "ab156"]):
                text_strings.append(s)
        except Exception:
            pass

    # Detect embedded version
    detected_versions = re.findall(r"v?1\.\d+\.\d+(?:\.\d+)?(?:\.\d+)?", " ".join(text_strings))
    best_version = detected_versions[0] if detected_versions else "Unknown"

    # 3. Detect LZMA partitions (Header starts with 0x5D 0x00 0x00)
    lzma_offsets = []
    pos = 0
    while True:
        pos = data.find(b"\x5D\x00\x00", pos)
        if pos == -1:
            break
        lzma_offsets.append(pos)
        pos += 3

    # 4. Check for Airoha FOTA / RACE headers
    has_fota_magic = (b"FOTA" in data) or (b"AIROHA" in data) or (b"\x15\x5A" in data)

    # 5. Header Summary
    return {
        "filepath": filepath,
        "filename": os.path.basename(filepath),
        "size_bytes": file_size,
        "size_kb": round(file_size / 1024, 2),
        "sha256": sha256,
        "crc32": crc32,
        "detected_version": best_version,
        "has_fota_signature": has_fota_magic,
        "lzma_partitions_found": len(lzma_offsets),
        "lzma_partition_offsets": lzma_offsets[:8],
        "identified_strings": text_strings[:10],
    }


def format_firmware_status_plain(diag: Dict[str, Any]) -> str:
    """Formats diagnostic status in clean monochrome ASCII."""
    lines = []
    lines.append("┌─ AUDEZE MAXWELL 2 — FIRMWARE DIAGNOSTICS ────────────────────────────┐")
    lines.append("│                                                                      │")

    # Dongle row
    d = diag.get("dongle", {})
    lines.append(f"│  USB Dongle Firmware       : {d.get('firmware', 'Unknown'):<24} [{d.get('status', 'Unknown')}]   │")

    # Headset row
    h = diag.get("headset", {})
    lines.append(f"│  Wireless Headset Firmware : {h.get('firmware', 'Unknown'):<24} [{h.get('status', 'Unknown')}]   │")

    # Parity
    parity = diag.get("parity_match", False)
    p_str = "MATCHED (Synchronized)" if parity else "MISMATCH WARNING"
    lines.append(f"│  Version Parity Check      : {p_str:<38} │")

    # Battery
    batt = diag.get("battery_percent")
    batt_str = f"{batt}%" if batt is not None else "Unknown"
    batt_safe = diag.get("battery_safe_for_flashing", False)
    safe_badge = "(Pass >= 50%)" if batt_safe else "(LOW - Flashing Unsafe)"
    lines.append(f"│  Headset Battery Level     : {batt_str:<8} {safe_badge:<29} │")

    lines.append("│                                                                      │")
    lines.append("├─ UPDATE SAFETY READINESS ────────────────────────────────────────────┤")

    ready = diag.get("update_prerequisites_met", False)
    if ready:
        lines.append("│  [PASS] All pre-flight safety requirements satisfied for updates.     │")
        lines.append("│         - Dongle and headset firmware are synchronized.             │")
        lines.append("│         - Battery level is safe (>= 50%).                            │")
    else:
        lines.append("│  [CAUTION] Pre-flight prerequisites not fully satisfied:             │")
        if not batt_safe:
            lines.append("│         - Battery is below 50%. Charge headset before flashing.     │")
        if not parity:
            lines.append("│         - Firmware mismatch detected between dongle and headset.     │")

    lines.append("└──────────────────────────────────────────────────────────────────────┘")
    return "\n".join(lines)


def format_firmware_inspect_plain(info: Dict[str, Any]) -> str:
    """Formats firmware package inspection results."""
    lines = []
    lines.append("┌─ FIRMWARE PACKAGE INSPECTION ────────────────────────────────────────┐")
    lines.append(f"│  File Name                 : {info.get('filename', 'Unknown'):<38} │")
    lines.append(f"│  File Size                 : {info.get('size_kb', 0)} KB ({info.get('size_bytes', 0)} bytes)             │")
    lines.append(f"│  Detected Version          : {info.get('detected_version', 'Unknown'):<38} │")
    lines.append(f"│  CRC32 Checksum            : {info.get('crc32', 'Unknown'):<38} │")
    lines.append(f"│  SHA-256 Digest            : {info.get('sha256', 'Unknown')[:34]}... │")
    lines.append(f"│  LZMA Compressed Partitions: {info.get('lzma_partitions_found', 0):<38} │")

    fota = "YES (Airoha FOTA / RACE)" if info.get("has_fota_signature") else "Standard Binary"
    lines.append(f"│  Architecture Signature    : {fota:<38} │")

    lines.append("├─ EMBEDDED IDENTIFIERS ───────────────────────────────────────────────┤")
    for s in info.get("identified_strings", []):
        lines.append(f"│  • {s[:64]:<64} │")

    lines.append("└──────────────────────────────────────────────────────────────────────┘")
    return "\n".join(lines)
