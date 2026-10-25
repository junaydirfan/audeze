//! Maxwell 1 RACE framing, derived offline (see PROOF.md). Never opens hardware.
//!
//! An ACK establishes command acceptance, not acoustics.

use crate::{Error, Result};
use serde_json::{Value, json};

pub const MAX_PACKET: usize = 1024;
pub const CHUNK: usize = 59;
pub const REPORT_BYTES: usize = 62;
pub const SAVED_BYTES: usize = 844;

const UI_KEY: u16 = 0xEF00;
const COEFFICIENT_KEY: u16 = 0xE42C;

fn error(message: impl Into<String>) -> Error {
    Error::value(message)
}

fn le16(bytes: &[u8], offset: usize) -> u16 {
    u16::from_le_bytes([bytes[offset], bytes[offset + 1]])
}

fn packet(command: u16, payload: &[u8]) -> Result<Vec<u8>> {
    let mut packet = vec![0x05, 0x5A];
    packet.extend(((payload.len() + 2) as u16).to_le_bytes());
    packet.extend(command.to_le_bytes());
    packet.extend(payload);
    if packet.len() > MAX_PACKET {
        return Err(error("Packet exceeds the vendor receive buffer"));
    }
    Ok(packet)
}

fn check_slot(slot: u8) -> Result<()> {
    if slot > 3 {
        return Err(error("Custom preset storage slot must be 0..3"));
    }
    Ok(())
}

fn key_read(key: u16) -> [u8; 4] {
    let mut payload = [0u8; 4];
    payload[..2].copy_from_slice(&key.to_le_bytes());
    payload[2..].copy_from_slice(&1000u16.to_le_bytes());
    payload
}

pub fn read_index_command() -> Vec<u8> {
    setting_read_command(0)
}

/// Settings behind RACE 0x0901 (read) and 0x0900 (write), from kats1123's
/// maxwell-firmware-research. Writes apply live and persist to NVDM at once.
pub const LEFT_GAIN: u8 = 0x29;
pub const RIGHT_GAIN: u8 = 0x2A;
/// NVDM 0xF702: 0x0A selects the USB-C DSP profile, anything else wireless.
pub const SOURCE_PROFILE: u8 = 0x2F;
pub const USB_C_PROFILE: u8 = 0x0A;
pub const WIRELESS_PROFILE: u8 = 0x00;
/// The research tool's driver-safety cap.
pub const MAX_GAIN: u8 = 150;

const READABLE_SETTINGS: [u8; 4] = [0, LEFT_GAIN, RIGHT_GAIN, SOURCE_PROFILE];

fn setting_read_command(sub: u8) -> Vec<u8> {
    vec![0x05, 0x5A, 0x04, 0x00, 0x01, 0x09, sub, 0x00]
}

/// A 0x0901 read of one known setting.
pub fn read_setting_command(sub: u8) -> Result<Vec<u8>> {
    if !READABLE_SETTINGS[1..].contains(&sub) {
        return Err(error("Only channel gains and the source profile can be read"));
    }
    Ok(setting_read_command(sub))
}

/// 136 and 142 are firmware codes, not levels: 136 is special-cased and 142 is
/// silently rejected.
pub fn check_gain(value: u8) -> Result<()> {
    if value > MAX_GAIN {
        return Err(error(format!("Channel gain must be 0..{MAX_GAIN}")));
    }
    if value == 136 || value == 142 {
        return Err(error("136 and 142 are reserved firmware codes; pick a nearby value"));
    }
    Ok(())
}

fn check_setting_value(sub: u8, value: u8) -> Result<()> {
    match sub {
        LEFT_GAIN | RIGHT_GAIN => check_gain(value),
        SOURCE_PROFILE if value == USB_C_PROFILE || value == WIRELESS_PROFILE => Ok(()),
        SOURCE_PROFILE => Err(error("Source profile must be USB-C (0x0A) or wireless (0x00)")),
        _ => Err(error("Only channel gains and the source profile can be written")),
    }
}

/// A 0x0900 write. It changes the headset immediately and persistently.
pub fn write_setting_command(sub: u8, value: u8) -> Result<Vec<u8>> {
    check_setting_value(sub, value)?;
    packet(0x0900, &[sub, 0, value])
}

/// Voice-prompt level ([`VOICE_PROMPT`]). Audeze HQ 1.2.48 mutes it around a
/// Maxwell 2 USB preset reselect (static analysis only; untested on hardware).
pub fn read_voice_prompt_command() -> Vec<u8> {
    setting_read_command(VOICE_PROMPT)
}

pub fn write_voice_prompt_command(level: u8) -> Result<Vec<u8>> {
    packet(0x0900, &[VOICE_PROMPT, 0, level])
}

/// The Maxwell 2 reselect sequence, allowed only with the save capability.
fn is_reselect_request(packet: &[u8]) -> bool {
    packet == read_voice_prompt_command()
        || matches!(check_packet(packet, 0x5A), Ok((0x0900, [VOICE_PROMPT, 0, _])))
        || matches!(check_packet(packet, 0x5A), Ok((0x0900, [PRESET_INDEX, 0, 7..=10])))
}

/// Opt-in writes: channel gains and the source profile, nothing else.
pub fn validate_setting_write(packet: &[u8]) -> Result<()> {
    let (command, payload) = check_packet(packet, 0x5A)?;
    if command != 0x0900 || payload.len() != 3 || payload[1] != 0 {
        return Err(error("Command is outside the settings allowlist"));
    }
    check_setting_value(payload[0], payload[2])
}

/// Presets 7..10 are the four custom slots, shown as Preset 1..4 in the Audeze app.
pub const CUSTOM_INDEXES: std::ops::RangeInclusive<u8> = 7..=10;

/// Make preset `index` active: 0x0900 sub 0, as the Audeze app's
/// `MaxwellTransport::writePeqIndex` sends it. Only the custom presets. HQ
/// also sends it after a Maxwell 2 USB save so the headset reloads the preset.
pub fn select_preset_command(index: u8) -> Result<Vec<u8>> {
    if !CUSTOM_INDEXES.contains(&index) {
        return Err(error("Only custom presets 7..10 can be selected"));
    }
    packet(0x0900, &[PRESET_INDEX, 0, index])
}

/// Opt-in preset selection, nothing else.
pub fn validate_select(packet: &[u8]) -> Result<()> {
    let (command, payload) = check_packet(packet, 0x5A)?;
    if command != 0x0900
        || payload.len() != 3
        || payload[..2] != [PRESET_INDEX, 0]
        || !CUSTOM_INDEXES.contains(&payload[2])
    {
        return Err(error("Command is outside the preset-select allowlist"));
    }
    Ok(())
}

/// Headset controls, decoded from Audeze HQ 1.2.48. The first group lives
/// behind 0x0901 / 0x0900 like the gains; the second behind 0x2C83 (read) and
/// 0x2C82 (write). None of them is confirmed on hardware yet.
pub const PRESET_INDEX: u8 = 0x00;
pub const VOICE_PROMPT: u8 = 0x20;
/// Read only: 0x00 when muted, 0xFF when not.
pub const MIC_MUTE: u8 = 0x22;
pub const NOISE_REDUCTION: u8 = 0x24;
/// Amp gain. HQ only ever writes the two volume-limiter codes.
pub const AMP_GAIN: u8 = 0x28;
pub const SIDETONE_LEVEL: u8 = 0x2C;
/// Read only: the largest sidetone level the headset accepts.
pub const MAX_SIDETONE: u8 = 0x2D;
pub const AUTO_OFF: u8 = 0x01;
pub const SIDETONE_ON: u8 = 0x07;
pub const CHAT_MIX: u8 = 0x0B;
pub const LIMITER_ON: u8 = 136;
pub const LIMITER_OFF: u8 = 142;
pub const MAX_CHAT_MIX: u8 = 20;
pub const MAX_VOICE_PROMPT: u8 = 15;
/// HQ's auto-shutdown steps in seconds; 0 is Never.
pub const AUTO_OFF_SECONDS: [u16; 11] = [300, 600, 900, 1800, 2700, 3600, 5400, 7200, 14400, 21600, 0];

const SETTING_CONTROLS: [u8; 7] =
    [PRESET_INDEX, VOICE_PROMPT, MIC_MUTE, NOISE_REDUCTION, AMP_GAIN, SIDETONE_LEVEL, MAX_SIDETONE];
const PAIR_CONTROLS: [u8; 3] = [AUTO_OFF, SIDETONE_ON, CHAT_MIX];
const BATTERY: u16 = 0x0CD6;
const FIRMWARE: u16 = 0x1C07;

/// A read of one headset control: 0x0901 or 0x2C83, by sub-command.
pub fn read_control_command(sub: u8) -> Result<Vec<u8>> {
    if SETTING_CONTROLS.contains(&sub) {
        return Ok(setting_read_command(sub));
    }
    if PAIR_CONTROLS.contains(&sub) {
        return Ok(vec![0x05, 0x5A, 0x04, 0x00, 0x83, 0x2C, sub, 0x00]);
    }
    Err(error(format!("Control 0x{sub:02X} cannot be read")))
}

fn check_control_value(sub: u8, value: u16) -> Result<()> {
    let ok = match sub {
        PRESET_INDEX => (1..=10).contains(&value),
        VOICE_PROMPT => value <= u16::from(MAX_VOICE_PROMPT),
        NOISE_REDUCTION => value <= 2,
        AMP_GAIN => value == u16::from(LIMITER_ON) || value == u16::from(LIMITER_OFF),
        // The headset reports its own maximum; callers check against it.
        SIDETONE_LEVEL => value <= 0xFF,
        SIDETONE_ON => value <= 1,
        CHAT_MIX => value <= u16::from(MAX_CHAT_MIX),
        AUTO_OFF => AUTO_OFF_SECONDS.contains(&value),
        _ => return Err(error(format!("Control 0x{sub:02X} cannot be written"))),
    };
    if !ok {
        return Err(error(format!("{value} is out of range for control 0x{sub:02X}")));
    }
    Ok(())
}

/// The Audeze app accepts `05 5B 05 00 00 09 00 00 ..`: status 0, sub 0.
pub fn parse_select_ack(packet: &[u8]) -> Result<()> {
    let (command, payload) = check_packet(packet, 0x5B)?;
    if command != 0x0900 || payload.len() != 3 || payload[1] != 0 {
        return Err(error("Unexpected preset-change acknowledgement"));
    }
    if payload[0] != 0 {
        return Err(error(format!("Headset rejected the preset change (status {})", payload[0])));
    }
    Ok(())
}

/// A write of one headset control, in the exact form Audeze HQ sends.
pub fn write_control_command(sub: u8, value: u16) -> Result<Vec<u8>> {
    check_control_value(sub, value)?;
    match sub {
        AUTO_OFF => {
            let enabled = u8::from(value != 0);
            let [lo, hi] = value.to_le_bytes();
            packet(0x2C82, &[AUTO_OFF, 0, enabled, 0, lo, hi, enabled, 0, lo, hi])
        }
        SIDETONE_ON | CHAT_MIX => packet(0x2C82, &[sub, 0, value as u8]),
        _ => packet(0x0900, &[sub, 0, value as u8]),
    }
}

/// Whether a read-back value shows that `written` took effect. HQ treats any
/// amp gain at or below 136 as the limiter being on.
pub fn control_matches(sub: u8, written: u16, read: u16) -> bool {
    if sub == AMP_GAIN {
        return (written == u16::from(LIMITER_ON)) == (read <= u16::from(LIMITER_ON));
    }
    written == read
}

/// Battery level: an acknowledgement, then a 0x5D notification.
pub fn battery_command() -> Vec<u8> {
    packet(BATTERY, &[0]).expect("fits")
}

/// Firmware version string: an acknowledgement, then a 0x5D notification.
/// Sent with report flags 0 on the dongle, it asks the dongle itself.
pub fn firmware_command() -> Vec<u8> {
    packet(FIRMWARE, &[0]).expect("fits")
}

/// Control reads, battery and firmware queries, and with `allow_write` the
/// control writes above. Never EQ.
pub fn validate_control(packet: &[u8], allow_write: bool) -> Result<()> {
    let (command, payload) = check_packet(packet, 0x5A)?;
    if packet == battery_command() || packet == firmware_command() {
        return Ok(());
    }
    if SETTING_CONTROLS.iter().chain(&PAIR_CONTROLS).any(|&sub| read_control_command(sub).is_ok_and(|p| p == packet)) {
        return Ok(());
    }
    if allow_write && matches!(command, 0x0900 | 0x2C82) && !payload.is_empty() {
        let sub = payload[0];
        let value = match payload {
            [AUTO_OFF, 0, _, 0, lo, hi, ..] => u16::from_le_bytes([*lo, *hi]),
            [_, 0, value] => u16::from(*value),
            _ => return Err(error("Command is outside the controls allowlist")),
        };
        if write_control_command(sub, value).is_ok_and(|expected| expected == packet) {
            return Ok(());
        }
    }
    Err(error("Command is outside the controls allowlist"))
}

/// The value in a control reply. 0x2C83 replies carry `status, sub, 00, value`.
pub fn parse_control(packet: &[u8], sub: u8) -> Result<u16> {
    if SETTING_CONTROLS.contains(&sub) {
        return parse_setting(packet, sub).map(u16::from);
    }
    let (command, payload) = check_packet(packet, 0x5B)?;
    let size = if sub == AUTO_OFF { 11 } else { 4 };
    if command != 0x2C83 || payload.len() != size || payload[1..3] != [sub, 0] {
        return Err(error("Unexpected control reply"));
    }
    if payload[0] != 0 {
        return Err(error(format!("Headset rejected the control read (status {})", payload[0])));
    }
    if sub == AUTO_OFF {
        return Ok(le16(payload, 5));
    }
    Ok(u16::from(payload[3]))
}

/// The acknowledgement before a battery or firmware notification.
pub fn parse_query_ack(packet: &[u8], command: u16) -> Result<()> {
    let (actual, payload) = check_packet(packet, 0x5B)?;
    if actual != command || payload.is_empty() {
        return Err(error("Unexpected query acknowledgement"));
    }
    if payload[0] != 0 {
        return Err(error(format!("Headset rejected the query (status {})", payload[0])));
    }
    Ok(())
}

pub fn parse_battery(packet: &[u8]) -> Result<u8> {
    let (command, payload) = check_packet(packet, 0x5D)?;
    if command != BATTERY || payload.len() < 3 {
        return Err(error("Unexpected battery notification"));
    }
    Ok(payload[2])
}

pub fn parse_firmware(packet: &[u8]) -> Result<String> {
    let (command, payload) = check_packet(packet, 0x5D)?;
    let length = payload.get(2).map(|&n| usize::from(n));
    match length {
        Some(length) if command == FIRMWARE && payload.len() >= 3 + length => {
            let text = String::from_utf8_lossy(&payload[3..3 + length]);
            Ok(text.trim_end_matches('\0').trim().to_owned())
        }
        _ => Err(error("Unexpected firmware notification")),
    }
}

pub fn read_ui_command(slot: u8) -> Result<Vec<u8>> {
    check_slot(slot)?;
    packet(0x0A0C, &key_read(UI_KEY + u16::from(slot)))
}

pub fn read_coefficients_command(slot: u8) -> Result<Vec<u8>> {
    check_slot(slot)?;
    packet(0x0A0C, &key_read(COEFFICIENT_KEY + u16::from(slot)))
}

pub fn live_command(coefficients: &[u8]) -> Result<Vec<u8>> {
    if coefficients.is_empty() {
        return Err(error("Coefficient blob must be nonempty bytes"));
    }
    packet(0x0E03, &[&[0u8][..], coefficients].concat())
}

/// Firmware query only: whether an 844-byte NVDM value fits.
pub fn storage_space_command() -> Vec<u8> {
    packet(0x0A03, &(SAVED_BYTES as u16).to_le_bytes()).expect("fits")
}

pub fn save_coefficients_command(slot: u8, coefficients: &[u8]) -> Result<Vec<u8>> {
    check_slot(slot)?;
    if coefficients.len() != SAVED_BYTES {
        return Err(error("Saved coefficients must be the 844-byte four-rate format"));
    }
    packet(0x0A0D, &[&(COEFFICIENT_KEY + u16::from(slot)).to_le_bytes()[..], coefficients].concat())
}

/// Check the header and length; returns the command and payload.
pub fn check_packet(packet: &[u8], kind: u8) -> Result<(u16, &[u8])> {
    if packet.len() < 6 || packet.len() > MAX_PACKET || packet[..2] != [5, kind] {
        return Err(error("Invalid RACE header"));
    }
    let length = usize::from(le16(packet, 2));
    if length < 2 || length + 4 != packet.len() {
        return Err(error("RACE length does not match complete packet"));
    }
    Ok((le16(packet, 4), &packet[6..]))
}

/// Only reads, live EQ, and opt-in writes to the four coefficient keys.
pub fn validate_request(packet: &[u8], allow_live: bool, allow_persistent: bool) -> Result<()> {
    let (command, payload) = check_packet(packet, 0x5A)?;
    if READABLE_SETTINGS.iter().any(|&sub| packet == setting_read_command(sub)) || packet == storage_space_command() {
        return Ok(());
    }
    if command == 0x0A0C && [UI_KEY, COEFFICIENT_KEY].iter().any(|base| (0..4).any(|i| payload == key_read(base + i))) {
        return Ok(());
    }
    if allow_live && command == 0x0E03 && payload.len() > 1 && payload[0] == 0 {
        return Ok(());
    }
    if allow_persistent
        && command == 0x0A0D
        && payload.len() == SAVED_BYTES + 2
        && (COEFFICIENT_KEY..=COEFFICIENT_KEY + 3).contains(&le16(payload, 0))
    {
        return Ok(());
    }
    if allow_persistent && is_reselect_request(packet) {
        return Ok(());
    }
    Err(error("Command is outside the EQ allowlist"))
}

/// Split a request into output reports: `06, length, flags`, then up to 59 bytes, zero padded.
pub fn output_reports(
    packet: &[u8],
    dongle: bool,
    report_size: usize,
    allow_live: bool,
    allow_persistent: bool,
) -> Result<Vec<Vec<u8>>> {
    validate_request(packet, allow_live, allow_persistent)?;
    frame(packet, dongle, report_size)
}

/// [`output_reports`] for a packet the caller has already validated.
pub(crate) fn frame(packet: &[u8], dongle: bool, report_size: usize) -> Result<Vec<Vec<u8>>> {
    if !(REPORT_BYTES..=1024).contains(&report_size) {
        return Err(error("Unsupported HID report size"));
    }
    Ok(packet
        .chunks(CHUNK)
        .map(|chunk| {
            let mut report = vec![6, chunk.len() as u8, if dongle { 0x80 } else { 0 }];
            report.extend(chunk);
            report.resize(report_size, 0);
            report
        })
        .collect())
}

/// Reassembles input reports; one report can complete several messages.
#[derive(Default)]
pub struct InputStream {
    pending: Vec<u8>,
}

impl InputStream {
    pub fn feed(&mut self, report: &[u8]) -> Result<Vec<Vec<u8>>> {
        if report.len() < REPORT_BYTES || report[0] != 7 || usize::from(report[1]) > CHUNK {
            return Err(error("Invalid HID input report"));
        }
        // Byte 2 is metadata, not the upper byte of a length.
        self.pending.extend(&report[3..3 + usize::from(report[1])]);
        let mut messages = Vec::new();
        while self.pending.len() >= 4 {
            if self.pending[0] != 5 {
                return Err(error("RACE stream lost its packet boundary"));
            }
            let size = usize::from(le16(&self.pending, 2)) + 4;
            if !(6..=MAX_PACKET).contains(&size) {
                return Err(error("Invalid RACE stream length"));
            }
            if self.pending.len() < size {
                break;
            }
            messages.push(self.pending.drain(..size).collect());
        }
        Ok(messages)
    }
}

pub fn parse_index(packet: &[u8]) -> Result<u8> {
    let (command, payload) = check_packet(packet, 0x5B)?;
    if command != 0x0901 || payload.len() != 4 || payload[..2] != [0, 0] {
        return Err(error("Unexpected current-preset reply"));
    }
    // The app does not interpret payload[2]; backups keep the full raw reply.
    Ok(payload[3])
}

/// The value in a 0x0901 reply: `sub, 00, ?, value`.
pub fn parse_setting(packet: &[u8], sub: u8) -> Result<u8> {
    if sub == 0 {
        return parse_index(packet);
    }
    let (command, payload) = check_packet(packet, 0x5B)?;
    if command != 0x0901 || payload.len() != 4 || payload[..2] != [sub, 0] {
        return Err(error("Unexpected settings reply"));
    }
    Ok(payload[3])
}

pub fn parse_live_ack(packet: &[u8]) -> Result<()> {
    let (command, payload) = check_packet(packet, 0x5B)?;
    if command != 0x0E03 || payload.len() != 1 {
        return Err(error("Unexpected live-EQ acknowledgement"));
    }
    if payload[0] != 0 {
        return Err(error(format!("Headset rejected live EQ (status {})", payload[0])));
    }
    Ok(())
}

/// True when an 844-byte value fits. The byte is a flag, not a status.
pub fn parse_storage_space(packet: &[u8]) -> Result<bool> {
    let (command, payload) = check_packet(packet, 0x5B)?;
    if command != 0x0A03 || payload.len() != 1 || payload[0] > 1 {
        return Err(error("Unexpected storage-space response"));
    }
    Ok(payload[0] == 1)
}

pub fn parse_save_ack(packet: &[u8], slot: u8) -> Result<()> {
    check_slot(slot)?;
    let (command, payload) = check_packet(packet, 0x5B)?;
    if command != 0x0A0D || payload.len() != 3 || le16(payload, 1) != COEFFICIENT_KEY + u16::from(slot) {
        return Err(error("Unexpected coefficient-save acknowledgement"));
    }
    if payload[0] != 0 {
        return Err(error(format!("Headset rejected coefficient save (status {})", payload[0])));
    }
    Ok(())
}

/// The stored value for a key-read reply, after its status, key and length.
fn stored_value<'a>(packet: &'a [u8], payload: &[u8], key: u16, message: &str) -> Result<&'a [u8]> {
    if payload.len() < 5 || payload[0] != 0 || le16(payload, 1) != key {
        return Err(error(message));
    }
    Ok(&packet[11..])
}

pub fn parse_coefficients(packet: &[u8], slot: u8) -> Result<Vec<u8>> {
    parse_stored_coefficients(packet, slot)?
        .ok_or_else(|| error(format!("Preset {} has no saved EQ on the headset", slot + 1)))
}

/// Like [`parse_coefficients`], but a key the headset reports as missing (a
/// nonzero status for the right key) is `None`: that preset was never saved.
pub fn parse_stored_coefficients(packet: &[u8], slot: u8) -> Result<Option<Vec<u8>>> {
    check_slot(slot)?;
    let (command, payload) = check_packet(packet, 0x5B)?;
    let message = "Unexpected saved coefficient response";
    if command != 0x0A0C {
        return Err(error(message));
    }
    let key = COEFFICIENT_KEY + u16::from(slot);
    if payload.len() >= 3 && payload[0] != 0 && le16(payload, 1) == key {
        return Ok(None);
    }
    let raw = stored_value(packet, payload, key, message)?;
    if usize::from(le16(payload, 3)) != raw.len() {
        return Err(error("Saved coefficient length does not match data"));
    }
    Ok(Some(raw.to_vec()))
}

#[derive(Debug, Clone, PartialEq)]
pub struct UiBand {
    pub tag: u16,
    pub frequency_hundredths: i32,
    pub gain_hundredths: i32,
    pub width_hundredths: i32,
    pub unknown: i32,
}

impl UiBand {
    pub fn to_json(&self) -> Value {
        json!({
            "tag": self.tag,
            "frequency_hundredths": self.frequency_hundredths,
            "gain_hundredths": self.gain_hundredths,
            "width_hundredths": self.width_hundredths,
            "unknown": self.unknown,
        })
    }
}

#[derive(Debug, Clone)]
pub struct UiPreset {
    pub slot: u8,
    pub header: Vec<u8>,
    pub bands: Vec<UiBand>,
    pub raw_payload: Vec<u8>,
    pub raw_response: Vec<u8>,
}

pub fn parse_ui(packet: &[u8], slot: u8) -> Result<UiPreset> {
    check_slot(slot)?;
    let (command, payload) = check_packet(packet, 0x5B)?;
    let length = packet.len() - 4;
    if command != 0x0A0C || !(12..=192).contains(&length) || payload.len() < 10 {
        return Err(error("Unexpected preset UI reply"));
    }
    if payload[0] != 0 || le16(payload, 1) != UI_KEY + u16::from(slot) {
        return Err(error("Preset UI reply has failure status or wrong key"));
    }
    let raw = &packet[11..];
    if usize::from(le16(payload, 3)) != raw.len() {
        return Err(error("Preset UI stored length does not match data"));
    }
    if raw.len() < 5 || !(raw.len() - 5).is_multiple_of(18) {
        return Err(error("Preset UI record length is invalid"));
    }
    let int = |offset: usize| i32::from_le_bytes(raw[offset..offset + 4].try_into().expect("4 bytes"));
    let bands = (5..raw.len())
        .step_by(18)
        .map(|o| UiBand {
            tag: le16(raw, o),
            frequency_hundredths: int(o + 2),
            gain_hundredths: int(o + 6),
            width_hundredths: int(o + 10),
            unknown: int(o + 14),
        })
        .collect();
    // Header interpretation is deliberately deferred: the app's decoder and encoder disagree.
    Ok(UiPreset { slot, header: raw[..5].to_vec(), bands, raw_payload: raw.to_vec(), raw_response: packet.to_vec() })
}
