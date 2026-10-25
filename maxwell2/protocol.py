"""
Protocol framing, command definitions, and response parsers for Audeze Maxwell 2.
Implements the Airoha RACE protocol over 62-byte USB HID reports.
Strictly verified and validated against safety allowlists.
"""

import struct
from typing import List, Tuple, Optional, Dict, Any

# USB HID Constants
REPORT_ID_OUTPUT = 0x06
REPORT_ID_INPUT = 0x07
REPORT_LENGTH = 62
CHUNK_MAX = 59

ROUTE_DONGLE = 0x80
ROUTE_DIRECT = 0x00

# RACE Protocol Constants
SYNC_BYTE = 0x05
DIRECTION_REQUEST = 0x5A
DIRECTION_RESPONSE = 0x5B
DIRECTION_NOTIFICATION = 0x5D

# RACE Opcodes
CMD_SETTING_WRITE = 0x0900
CMD_SETTING_READ = 0x0901
CMD_PAIR_WRITE = 0x2C82
CMD_PAIR_READ = 0x2C83
CMD_NVDM_READ = 0x0A0C
CMD_NVDM_WRITE = 0x0A0D
CMD_NVDM_SPACE = 0x0A03
CMD_LIVE_EQ = 0x0E03
CMD_BATTERY = 0x0CD6
CMD_FIRMWARE = 0x1C07

# Settings Subcommands (0x0900 / 0x0901)
SUB_PRESET_INDEX = 0x00
SUB_AUTO_OFF = 0x01
SUB_VOICE_PROMPT = 0x20
SUB_MIC_MUTE = 0x22
SUB_NOISE_REDUCTION = 0x24
SUB_AMP_GAIN = 0x28
SUB_LEFT_GAIN = 0x29
SUB_RIGHT_GAIN = 0x2A
SUB_SIDETONE_LEVEL = 0x2C
SUB_MAX_SIDETONE = 0x2D
SUB_SOURCE_PROFILE = 0x2F

# Pair Subcommands (0x2C82 / 0x2C83)
SUB_PAIR_AUTO_OFF = 0x01
SUB_SIDETONE_ON = 0x07
SUB_CHAT_MIX = 0x0B

# Presets
PRESET_NAMES = [
    "Audeze",
    "Treble Boost",
    "Bass Boost",
    "Immersive",
    "Competition",
    "Footsteps",
    "Preset 1 (Custom)",
    "Preset 2 (Custom)",
    "Preset 3 (Custom)",
    "Preset 4 (Custom)",
]

# NVDM Storage Keys
KEY_UI_BASE = 0xEF00         # 0xEF00..0xEF03 for custom slots 0..3
KEY_COEFF_BASE = 0xE42C      # 0xE42C..0xE42F for custom slots 0..3
COEFFICIENT_BLOB_SIZE = 844

# Safety limits
MAX_CHAT_MIX = 20
MAX_VOICE_PROMPT = 100
LIMITER_ON = 136
LIMITER_OFF = 142


class ProtocolError(ValueError):
    """Raised on invalid protocol framing or violated safety bounds."""
    pass


def build_race_packet(command: int, payload: bytes = b"") -> bytes:
    """Builds a RACE packet: 0x05 0x5A <len_le16> <cmd_le16> <payload>."""
    length = len(payload) + 2
    if length > 1024:
        raise ProtocolError(f"RACE payload too large ({length} bytes)")
    return struct.pack("<BBHH", SYNC_BYTE, DIRECTION_REQUEST, length, command) + payload


def parse_race_packet(packet: bytes, expected_dir: Optional[int] = None) -> Tuple[int, bytes]:
    """
    Parses and validates a RACE packet.
    Returns (command_id, payload).
    """
    if len(packet) < 6:
        raise ProtocolError(f"Packet too short for RACE header ({len(packet)} bytes)")
    sync, direction, length, command = struct.unpack_from("<BBHH", packet, 0)
    if sync != SYNC_BYTE:
        raise ProtocolError(f"Invalid RACE sync byte: 0x{sync:02X}")
    if expected_dir is not None and direction != expected_dir:
        raise ProtocolError(f"Unexpected RACE direction: 0x{direction:02X} (expected 0x{expected_dir:02X})")
    if length < 2 or length + 4 != len(packet):
        raise ProtocolError(f"RACE length mismatch: declared {length}, actual {len(packet) - 4}")
    return command, packet[6:]


def frame_output_reports(packet: bytes, is_dongle: bool = True) -> List[bytes]:
    """
    Splits a RACE packet into fixed 62-byte HID Output Reports (Report ID 0x06).
    Header: [0x06, chunk_len, route_byte, ...payload..., zero_padding]
    """
    reports = []
    route = ROUTE_DONGLE if is_dongle else ROUTE_DIRECT
    for i in range(0, len(packet), CHUNK_MAX):
        chunk = packet[i : i + CHUNK_MAX]
        header = bytes([REPORT_ID_OUTPUT, len(chunk), route])
        report = header + chunk
        if len(report) < REPORT_LENGTH:
            report += b"\x00" * (REPORT_LENGTH - len(report))
        reports.append(report)
    return reports


class InputStream:
    """
    Reassembles incoming 62-byte HID Input Reports (Report ID 0x07) into complete RACE packets.
    """

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, report: bytes) -> List[bytes]:
        """Feeds a raw 62-byte input report and returns any fully reassembled RACE packets."""
        if len(report) < 3 or report[0] != REPORT_ID_INPUT:
            raise ProtocolError(f"Invalid input report ID: 0x{report[0]:02X}")

        chunk_len = report[1]
        if chunk_len > CHUNK_MAX or len(report) < 3 + chunk_len:
            raise ProtocolError(f"Invalid chunk length {chunk_len} in input report")

        chunk = report[3 : 3 + chunk_len]
        self.buffer.extend(chunk)

        packets = []
        while len(self.buffer) >= 6:
            if self.buffer[0] != SYNC_BYTE:
                raise ProtocolError(f"RACE sync lost at stream byte 0x{self.buffer[0]:02X}")
            length = struct.unpack_from("<H", self.buffer, 2)[0]
            total_size = length + 4
            if len(self.buffer) < total_size:
                break
            complete_packet = bytes(self.buffer[:total_size])
            del self.buffer[:total_size]
            packets.append(complete_packet)

        return packets


# ==============================================================================
# Command Builders (Safe & Strictly Validated)
# ==============================================================================

def build_read_preset_command() -> bytes:
    """Reads current active preset index (0x0901, sub 0x00)."""
    return build_race_packet(CMD_SETTING_READ, struct.pack("<BB", SUB_PRESET_INDEX, 0x00))


def build_select_preset_command(index: int) -> bytes:
    """Selects an onboard preset (1..10)."""
    if not (1 <= index <= 10):
        raise ProtocolError(f"Preset index must be 1..10, got {index}")
    return build_race_packet(CMD_SETTING_WRITE, struct.pack("<BBB", SUB_PRESET_INDEX, 0x00, index))


def build_battery_command() -> bytes:
    """Queries headset battery percentage (0x0CD6)."""
    return build_race_packet(CMD_BATTERY, b"\x00")


def build_firmware_command() -> bytes:
    """Queries firmware version (0x1C07)."""
    return build_race_packet(CMD_FIRMWARE, b"\x00")


def build_read_control_command(sub: int) -> bytes:
    """Reads a setting control (0x0901 or 0x2C83)."""
    if sub in (SUB_PRESET_INDEX, SUB_VOICE_PROMPT, SUB_MIC_MUTE, SUB_NOISE_REDUCTION,
               SUB_AMP_GAIN, SUB_SIDETONE_LEVEL, SUB_MAX_SIDETONE, SUB_LEFT_GAIN, SUB_RIGHT_GAIN):
        return build_race_packet(CMD_SETTING_READ, struct.pack("<BB", sub, 0x00))
    elif sub in (SUB_PAIR_AUTO_OFF, SUB_SIDETONE_ON, SUB_CHAT_MIX):
        return build_race_packet(CMD_PAIR_READ, struct.pack("<BB", sub, 0x00))
    raise ProtocolError(f"Unknown control subcommand: 0x{sub:02X}")


def build_write_control_command(sub: int, value: int) -> bytes:
    """Writes a setting control with explicit bounds checking."""
    if sub == SUB_SIDETONE_ON:
        if value not in (0, 1):
            raise ProtocolError(f"Sidetone enable must be 0 or 1, got {value}")
        return build_race_packet(CMD_PAIR_WRITE, struct.pack("<BBB", sub, 0x00, value))
    elif sub == SUB_CHAT_MIX:
        if not (0 <= value <= MAX_CHAT_MIX):
            raise ProtocolError(f"Chat mix must be 0..{MAX_CHAT_MIX}, got {value}")
        return build_race_packet(CMD_PAIR_WRITE, struct.pack("<BBB", sub, 0x00, value))
    elif sub == SUB_NOISE_REDUCTION:
        if value not in (0, 1, 2):
            raise ProtocolError(f"Noise reduction must be 0 (Off), 1 (Low), or 2 (High), got {value}")
        return build_race_packet(CMD_SETTING_WRITE, struct.pack("<BBB", sub, 0x00, value))
    elif sub == SUB_SIDETONE_LEVEL:
        if not (0 <= value <= 255):
            raise ProtocolError(f"Sidetone level must be 0..255, got {value}")
        return build_race_packet(CMD_SETTING_WRITE, struct.pack("<BBB", sub, 0x00, value))
    elif sub == SUB_AMP_GAIN:
        if value not in (LIMITER_ON, LIMITER_OFF):
            raise ProtocolError(f"Amp gain must be {LIMITER_ON} (ON) or {LIMITER_OFF} (OFF), got {value}")
        return build_race_packet(CMD_SETTING_WRITE, struct.pack("<BBB", sub, 0x00, value))
    raise ProtocolError(f"Writing control 0x{sub:02X} is not allowed or unsupported")


def build_read_nvdm_key(key: int, max_bytes: int = 1000) -> bytes:
    """Reads a key from NVDM storage (0x0A0C)."""
    return build_race_packet(CMD_NVDM_READ, struct.pack("<HH", key, max_bytes))


def build_read_ui_eq_command(slot: int) -> bytes:
    """Reads the 10-band slider records for custom slot (0..3)."""
    if not (0 <= slot <= 3):
        raise ProtocolError(f"Custom EQ slot must be 0..3, got {slot}")
    return build_read_nvdm_key(KEY_UI_BASE + slot)


def build_read_coefficients_command(slot: int) -> bytes:
    """Reads the 844-byte DSP coefficients for custom slot (0..3)."""
    if not (0 <= slot <= 3):
        raise ProtocolError(f"Custom EQ slot must be 0..3, got {slot}")
    return build_read_nvdm_key(KEY_COEFF_BASE + slot)


def build_write_ui_eq_command(slot: int, bands: List[Dict[str, Any]], header: Optional[bytes] = None) -> bytes:
    """
    Builds the 185-byte NVDM write packet for 10-band slider records (Key 0xEF00 + slot).
    Validates slot (0..3), 10 bands, and gain ranges (-12.0 dB .. +12.0 dB).
    """
    if not (0 <= slot <= 3):
        raise ProtocolError(f"Custom EQ slot must be 0..3, got {slot}")
    if len(bands) != 10:
        raise ProtocolError(f"EQ must contain exactly 10 bands, got {len(bands)}")

    if header is None or len(header) != 5:
        header = b"\x01\x00\x00\x00\x00"

    raw_payload = bytearray(header)
    STANDARD_FREQS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

    for i in range(10):
        b = bands[i]
        freq = b.get("frequency_hz", STANDARD_FREQS[i])
        gain = float(b.get("gain_db", 0.0))
        if not (-12.0 <= gain <= 12.0):
            raise ProtocolError(f"Band {i+1} gain out of range (-12..+12 dB): {gain}")
        tag = b.get("band_index", 513)
        freq_100 = int(round(freq * 100))
        gain_100 = int(round(gain * 100))
        q_100 = int(round(b.get("q", freq / 2.0) * 100))
        raw_payload.extend(struct.pack("<Hiiii", tag, freq_100, gain_100, q_100, 0))

    key = KEY_UI_BASE + slot
    return build_race_packet(CMD_NVDM_WRITE, struct.pack("<H", key) + bytes(raw_payload))


# ==============================================================================
# Response Parsers
# ==============================================================================

def parse_preset_index(packet: bytes) -> Dict[str, Any]:
    """Parses response from read preset index command."""
    cmd, payload = parse_race_packet(packet, expected_dir=DIRECTION_RESPONSE)
    if cmd != CMD_SETTING_READ or len(payload) < 4:
        raise ProtocolError(f"Invalid preset index response: cmd 0x{cmd:04X}, len {len(payload)}")
    idx = payload[3]
    name = PRESET_NAMES[idx - 1] if 1 <= idx <= len(PRESET_NAMES) else f"Unknown ({idx})"
    return {
        "index": idx,
        "name": name,
        "is_custom": 7 <= idx <= 10,
        "slot": (idx - 7) if 7 <= idx <= 10 else None,
    }


def parse_battery_notification(packet: bytes) -> int:
    """Parses asynchronous battery notification (0x0CD6)."""
    cmd, payload = parse_race_packet(packet, expected_dir=DIRECTION_NOTIFICATION)
    if cmd != CMD_BATTERY or len(payload) < 3:
        raise ProtocolError("Invalid battery notification")
    return payload[2]


def parse_firmware_notification(packet: bytes) -> str:
    """Parses asynchronous firmware version notification (0x1C07)."""
    cmd, payload = parse_race_packet(packet, expected_dir=DIRECTION_NOTIFICATION)
    if cmd != CMD_FIRMWARE or len(payload) < 3:
        raise ProtocolError("Invalid firmware notification")
    str_len = payload[2]
    text = payload[3 : 3 + str_len].decode("ascii", errors="replace")
    return text.rstrip("\x00").strip()


def parse_control_response(packet: bytes, sub: int) -> int:
    """Parses read response for a control."""
    cmd, payload = parse_race_packet(packet, expected_dir=DIRECTION_RESPONSE)
    if cmd == CMD_SETTING_READ:
        if len(payload) < 4 or payload[0] != sub:
            raise ProtocolError(f"Mismatch in setting read reply for sub 0x{sub:02X}")
        return payload[3]
    elif cmd == CMD_PAIR_READ:
        if len(payload) < 4 or payload[1] != sub:
            raise ProtocolError(f"Mismatch in pair read reply for sub 0x{sub:02X}")
        return payload[3]
    raise ProtocolError(f"Unexpected response command: 0x{cmd:04X}")


def parse_ui_eq_preset(packet: bytes, expected_slot: int) -> Dict[str, Any]:
    """
    Parses a 10-band slider record from NVDM key 0xEF00 + slot.
    Format: 5-byte header + 10 bands x 18 bytes.
    """
    cmd, payload = parse_race_packet(packet, expected_dir=DIRECTION_RESPONSE)
    if cmd != CMD_NVDM_READ:
        raise ProtocolError(f"Expected NVDM read reply (0x0A0C), got 0x{cmd:04X}")

    status, key, data_len = struct.unpack_from("<BHH", payload, 0)
    expected_key = KEY_UI_BASE + expected_slot
    if key != expected_key:
        raise ProtocolError(f"Key mismatch: expected 0x{expected_key:04X}, got 0x{key:04X}")
    if status != 0:
        raise ProtocolError(f"Device reported error status reading EQ: {status}")

    raw_data = payload[5:]
    if len(raw_data) != data_len:
        raise ProtocolError(f"EQ data length mismatch: declared {data_len}, got {len(raw_data)}")
    if len(raw_data) < 5 or (len(raw_data) - 5) % 18 != 0:
        raise ProtocolError(f"Invalid EQ payload size ({len(raw_data)} bytes)")

    bands = []
    for offset in range(5, len(raw_data), 18):
        tag, freq_100, gain_100, q_100, flags = struct.unpack_from("<Hiiii", raw_data, offset)
        bands.append({
            "band_index": tag,
            "frequency_hz": freq_100 / 100.0,
            "gain_db": gain_100 / 100.0,
            "q": q_100 / 100.0,
        })

    return {
        "slot": expected_slot,
        "key": key,
        "header": list(raw_data[:5]),
        "bands": bands,
    }
