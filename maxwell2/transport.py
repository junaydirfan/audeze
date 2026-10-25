"""
Low-level Linux hidraw transport for Audeze Maxwell 2.
Uses Python standard library (os, select, glob).
Supports --dry-run mode to inspect outgoing packets without transmitting.
"""

import os
import sys
import glob
import time
import select
from typing import Optional, List, Tuple
from maxwell2.protocol import (
    REPORT_LENGTH,
    REPORT_ID_OUTPUT,
    REPORT_ID_INPUT,
    InputStream,
    frame_output_reports,
    parse_race_packet,
    ProtocolError,
)

AUDEZE_VID = 0x3329
KNOWN_PIDS = [0x4B18, 0x4B19, 0x4B1A, 0x4B1E, 0x4B28, 0x4B29, 0x4B2A]
DONGLE_PIDS = [0x4B18, 0x4B19, 0x4B28, 0x4B29]


class DeviceNotFoundError(Exception):
    """Raised when no compatible Audeze Maxwell device node is found."""
    pass


class DevicePermissionError(Exception):
    """Raised when the user does not have read/write access to /dev/hidraw*."""
    pass


class Transport:
    """
    Handles bidirectional HID communication with the Audeze Maxwell over /dev/hidraw.
    """

    def __init__(self, hidraw_path: Optional[str] = None, dry_run: bool = False):
        self.dry_run = dry_run
        self.hidraw_path = hidraw_path
        self.fd: Optional[int] = None
        self.is_dongle = True
        self.product_id: Optional[int] = None
        self.input_stream = InputStream()

    @classmethod
    def find_device(cls) -> Tuple[str, int, bool]:
        """
        Scans sysfs to locate the Audeze Maxwell hidraw node.
        Returns (hidraw_path, product_id, is_dongle).
        """
        for hidraw_dir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
            uevent_path = os.path.join(hidraw_dir, "device", "uevent")
            if not os.path.exists(uevent_path):
                continue
            try:
                with open(uevent_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                props = dict(line.split("=", 1) for line in content.splitlines() if "=" in line)
                hid_id = props.get("HID_ID", "")
                parts = hid_id.split(":")
                if len(parts) >= 3:
                    vid = int(parts[1], 16)
                    pid = int(parts[2], 16)
                    if vid == AUDEZE_VID and pid in KNOWN_PIDS:
                        node_name = os.path.basename(hidraw_dir)
                        dev_path = f"/dev/{node_name}"
                        is_dongle = pid in DONGLE_PIDS
                        return dev_path, pid, is_dongle
            except Exception:
                continue

        raise DeviceNotFoundError(
            "No compatible Audeze Maxwell device found on /sys/class/hidraw/.\n"
            "Please ensure the USB dongle or headset is plugged in."
        )

    def open(self):
        """Opens the hidraw device node."""
        if self.dry_run:
            print("[DRY-RUN] Transport initialized in simulated dry-run mode (no hardware access).")
            return

        if not self.hidraw_path:
            self.hidraw_path, self.product_id, self.is_dongle = self.find_device()

        if not os.path.exists(self.hidraw_path):
            raise DeviceNotFoundError(f"Device node {self.hidraw_path} does not exist.")

        try:
            # Open non-blocking so select can handle timeouts reliably
            self.fd = os.open(self.hidraw_path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError:
            raise DevicePermissionError(
                f"Permission denied accessing {self.hidraw_path}.\n"
                f"To run without sudo, install the udev rule:\n"
                f"  sudo cp udev/70-audeze-maxwell.rules /etc/udev/rules.d/\n"
                f"  sudo udevadm control --reload-rules && sudo udevadm trigger\n"
                f"Then unplug and replug your Audeze dongle/headset."
            )

        # Drain any pending incoming reports
        self._drain()

    def close(self):
        """Closes the hidraw file descriptor."""
        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _drain(self, duration_sec: float = 0.05):
        """Drains any unread reports left in the OS buffer."""
        if self.dry_run or self.fd is None:
            return
        end_time = time.time() + duration_sec
        while time.time() < end_time:
            r, _, _ = select.select([self.fd], [], [], 0.01)
            if r:
                try:
                    os.read(self.fd, 64)
                except Exception:
                    break
            else:
                break

    def write_race_packet(self, race_packet: bytes) -> List[bytes]:
        """
        Frames and transmits a RACE packet over HID output reports.
        In dry-run mode, prints the outgoing report bytes and returns them.
        """
        reports = frame_output_reports(race_packet, is_dongle=self.is_dongle)

        if self.dry_run:
            print(f"[DRY-RUN] Sending RACE packet ({len(race_packet)} bytes):")
            print(f"  RACE Raw: {race_packet.hex(' ')}")
            for idx, rep in enumerate(reports):
                print(f"  HID Report #{idx + 1} (Report ID 0x{rep[0]:02X}, len {len(rep)}): {rep.hex(' ')}")
            return reports

        if self.fd is None:
            raise RuntimeError("Transport is not open.")

        for rep in reports:
            written = os.write(self.fd, rep)
            if written != len(rep):
                raise IOError(f"Incomplete HID write: {written}/{len(rep)} bytes")

        return reports

    def read_race_packets(self, timeout_sec: float = 1.0) -> List[bytes]:
        """
        Reads incoming HID reports and returns reassembled complete RACE packets.
        """
        if self.dry_run:
            return []

        if self.fd is None:
            raise RuntimeError("Transport is not open.")

        packets = []
        deadline = time.time() + timeout_sec

        while time.time() < deadline:
            remaining = max(0.01, deadline - time.time())
            r, _, _ = select.select([self.fd], [], [], remaining)
            if r:
                try:
                    data = os.read(self.fd, 64)
                    if data:
                        new_packets = self.input_stream.feed(data)
                        if new_packets:
                            packets.extend(new_packets)
                            # Once we have at least one complete packet, break out
                            break
                except BlockingIOError:
                    continue
                except Exception as e:
                    raise IOError(f"Error reading HID report: {e}")

        return packets

    def exchange(self, race_packet: bytes, timeout_sec: float = 1.0) -> Optional[bytes]:
        """
        Sends a RACE packet and waits for its corresponding synchronous response.
        """
        self.write_race_packet(race_packet)
        if self.dry_run:
            return None

        packets = self.read_race_packets(timeout_sec=timeout_sec)
        if not packets:
            raise TimeoutError(f"Timed out waiting for device response to {race_packet.hex(' ')}")

        return packets[0]
