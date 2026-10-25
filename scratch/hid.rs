//! Request/reply transactions over the headset's vendor HID collection.
//!
//! Only opening a session enumerates devices. Every write passes the read /
//! live / save allowlist, the preset-select allowlist or the settings allowlist,
//! each enabled explicitly. HID calls are synchronous: the timeout bounds polling but cannot interrupt a stalled
//! `HidD_GetInputReport`, so the app runs sessions in a worker process.

use crate::balance::Settings;
use crate::controls::Controls;
use crate::device::Device;
use crate::json::object;
use crate::protocol::{
    InputStream, VOICE_PROMPT, battery_command, check_packet, control_matches, firmware_command, frame, live_command,
    parse_battery, parse_coefficients, parse_control, parse_firmware, parse_index, parse_live_ack, parse_query_ack,
    parse_save_ack, parse_select_ack, parse_setting, parse_storage_space, parse_stored_coefficients, parse_ui,
    read_coefficients_command, read_control_command, read_index_command, read_setting_command, read_ui_command,
    read_voice_prompt_command, save_coefficients_command, select_preset_command, storage_space_command,
    validate_control, validate_request, validate_select, validate_setting_write, write_control_command,
    write_setting_command, write_voice_prompt_command,
};
use crate::{Error, Result};
use serde_json::{Value, json};
use std::time::{Duration, Instant};

pub const VENDOR_ID: u16 = 0x3329;
pub const USAGE_PAGE: u16 = 0xFF13;

pub const LINUX_PERMISSION: &str = "No permission to open the headset. Install 70-maxwell-peq.rules into /etc/udev/rules.d (the .deb and .rpm do this), then unplug and replug the headset or dongle. No EQ was sent.";

pub const BUSY: &str = "The headset control interface is busy. Fully quit Audeze HQ (including its tray icon) and other Maxwell tools, then retry. No EQ was sent.";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Transport {
    Usb,
    Dongle,
}

impl Transport {
    pub fn parse(name: &str) -> Option<Transport> {
        match name {
            "usb" => Some(Transport::Usb),
            "dongle" => Some(Transport::Dongle),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Transport::Usb => "usb",
            Transport::Dongle => "dongle",
        }
    }
}

/// Headset models this app talks to. Only the original Maxwell PlayStation is
/// tested. The Xbox edition is the same model to HQ and is untested; Maxwell 2
/// support follows Audeze HQ 1.2.48 and is untested.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Model {
    Maxwell,
    Maxwell2,
}

impl Model {
    pub fn name(self) -> &'static str {
        match self {
            Model::Maxwell => "maxwell",
            Model::Maxwell2 => "maxwell2",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Model::Maxwell => "Original Maxwell PS",
            Model::Maxwell2 => "Maxwell 2 (untested)",
        }
    }
}

/// `(product ID, model, transport)`. The Xbox IDs come from
/// kats1123/maxwell-firmware-research; HQ's `GetDevType` puts them in the
/// original Maxwell's range. Maxwell 2 IDs come from HQ's
/// `GetDevType`/`IsDongle`; 0x4B2A as its USB headset is inferred.
pub const PRODUCTS: [(u16, Model, Transport); 7] = [
    (0x4B1A, Model::Maxwell, Transport::Usb),
    (0x4B19, Model::Maxwell, Transport::Dongle),
    (0x4B1E, Model::Maxwell, Transport::Usb),
    (0x4B18, Model::Maxwell, Transport::Dongle),
    (0x4B2A, Model::Maxwell2, Transport::Usb),
    (0x4B28, Model::Maxwell2, Transport::Dongle),
    (0x4B29, Model::Maxwell2, Transport::Dongle),
];

/// Maxwell 2 ANC stores EQ differently in HQ and is unknown here.
pub fn is_maxwell2_anc(product_id: u16) -> bool {
    (0x4BA8..=0x4BAF).contains(&product_id)
}

/// The original Maxwell's Xbox edition, over USB-C or its dongle.
pub fn is_xbox(product_id: u16) -> bool {
    matches!(product_id, 0x4B1E | 0x4B18)
}

/// What the device line calls the connected headset.
pub fn label(model: Model, product_id: u16) -> &'static str {
    if is_xbox(product_id) { "Original Maxwell Xbox (untested)" } else { model.label() }
}

pub fn product(product_id: u16) -> Option<(Model, Transport)> {
    PRODUCTS.iter().find(|(id, ..)| *id == product_id).map(|&(_, model, transport)| (model, transport))
}

/// Pick the one supported control interface for `transport` from
/// `(product ID, interface)` pairs with the vendor ID and usage page.
pub fn select<T>(found: Vec<(u16, T)>, transport: Transport) -> Result<(Model, u16, T)> {
    let anc = found.iter().any(|(id, _)| is_maxwell2_anc(*id));
    let mut matching: Vec<_> = found
        .into_iter()
        .filter_map(|(id, item)| product(id).filter(|p| p.1 == transport).map(|(model, _)| (model, id, item)))
        .collect();
    if matching.is_empty() && anc {
        return Err(Error::other(
            "This looks like a Maxwell 2 ANC. Its EQ storage is unknown and unsupported here. No EQ was sent.",
        ));
    }
    if matching.len() != 1 {
        return Err(Error::other(format!(
            "Expected one Maxwell {} control interface, found {}",
            transport.name(),
            matching.len()
        )));
    }
    Ok(matching.remove(0))
}

/// The connection a request asks for: `None` means automatic. A missing
/// transport is automatic too.
pub fn requested(request: &serde_json::Value) -> Result<Option<Transport>> {
    match crate::json::get(request, "transport") {
        None => Ok(None),
        Some(serde_json::Value::String(name)) if name == "auto" => Ok(None),
        Some(value) => value
            .as_str()
            .and_then(Transport::parse)
            .map(Some)
            .ok_or_else(|| Error::value("Choose auto, usb or dongle transport.")),
    }
}

/// Open through `requested`, or automatically: USB-C first, since its
/// interface exists only while the cable is plugged in, then the dongle,
/// which is present even when the headset is off.
pub fn connect<T>(
    requested: Option<Transport>,
    mut open: impl FnMut(Transport) -> Result<T>,
) -> Result<(T, Transport)> {
    if let Some(transport) = requested {
        return open(transport).map(|device| (device, transport));
    }
    let missing = |error: &Error| error.to_string().contains(", found 0");
    let usb = match open(Transport::Usb) {
        Ok(device) => return Ok((device, Transport::Usb)),
        Err(error) if missing(&error) => error,
        Err(error) => return Err(error),
    };
    match open(Transport::Dongle) {
        Ok(device) => Ok((device, Transport::Dongle)),
        Err(dongle) if missing(&dongle) && missing(&usb) => Err(Error::other(
            "No headset found. Connect it by USB-C, or plug in its wireless dongle and turn the headset on.",
        )),
        Err(dongle) => Err(dongle),
    }
}

/// Raw report I/O on one opened collection.
pub trait ReportIo {
    /// One input report (report ID 7), `input_size` bytes long.
    fn input(&mut self) -> Result<Vec<u8>>;
    /// Write one output report; false when the write failed or was short.
    fn write(&mut self, report: &[u8]) -> Result<bool>;
}

#[derive(Debug, Clone)]
pub struct Interface {
    pub path: String,
    pub input_size: usize,
    pub output_size: usize,
    pub device_version: u16,
}

pub struct Session<T: ReportIo> {
    pub io: T,
    pub transport: Transport,
    pub model: Model,
    pub product_id: u16,
    pub interface: Interface,
    pub allow_live: bool,
    pub allow_persistent: bool,
    /// Channel gain and source-profile writes. Never set with the EQ permissions.
    pub allow_settings: bool,
    /// Switching the active preset to one of the four custom presets.
    pub allow_select: bool,
    /// Control writes (chat mix, sidetone, preset index...). Never set with the EQ permissions.
    pub allow_controls: bool,
    /// Pause between polls; tests replace it.
    pub sleep: fn(Duration),
}

impl<T: ReportIo> Session<T> {
    pub fn new(io: T, transport: Transport, interface: Interface, allow_live: bool, allow_persistent: bool) -> Self {
        Session {
            io,
            transport,
            model: Model::Maxwell,
            product_id: PRODUCTS.iter().find(|p| p.1 == Model::Maxwell && p.2 == transport).map_or(0, |p| p.0),
            interface,
            allow_live,
            allow_persistent,
            allow_settings: false,
            allow_select: false,
            allow_controls: false,
            sleep: std::thread::sleep,
        }
    }

    fn check(&self, packet: &[u8]) -> Result<()> {
        if self.allow_settings && validate_setting_write(packet).is_ok() {
            return Ok(());
        }
        if self.allow_select && validate_select(packet).is_ok() {
            return Ok(());
        }
        if validate_control(packet, self.allow_controls).is_ok() {
            return Ok(());
        }
        validate_request(packet, self.allow_live, self.allow_persistent)
    }

    /// One input report; those carrying data are traced.
    fn input(&mut self) -> Result<Vec<u8>> {
        let report = self.io.input()?;
        if report.get(1).is_some_and(|&length| length > 0) {
            crate::traffic::trace("in", &report);
        }
        Ok(report)
    }

    /// Validate, empty old input, and write every report of one request.
    fn send(&mut self, packet: &[u8]) -> Result<()> {
        self.send_flagged(packet, self.transport == Transport::Dongle)
    }

    /// [`Self::send`] with an explicit dongle flag: clearing it on the dongle
    /// addresses the dongle instead of the headset.
    fn send_flagged(&mut self, packet: &[u8], dongle: bool) -> Result<()> {
        self.check(packet)?;
        let reports = frame(packet, dongle, self.interface.output_size)?;
        // Empty old responses before writing. Failure to empty aborts the write.
        self.drain()?;
        for report in reports {
            crate::traffic::trace("out", &report);
            if !self.io.write(&report)? {
                return Err(Error::other("Incomplete HID write; live state may be uncertain"));
            }
        }
        Ok(())
    }

    fn default_timeout(&self) -> f64 {
        if self.transport == Transport::Dongle { 6.0 } else { 3.0 }
    }

    /// The first reply to `packet` before `timeout` seconds pass. 0x0901
    /// replies must also echo the sub-command, so a late gain reply cannot
    /// answer a different read.
    fn reply(&mut self, packet: &[u8], timeout: f64) -> Result<Option<Vec<u8>>> {
        let (command, _) = check_packet(packet, 0x5A)?;
        let mut stream = InputStream::default();
        let deadline = Instant::now() + Duration::from_secs_f64(timeout);
        while Instant::now() < deadline {
            (self.sleep)(Duration::from_millis(10));
            for message in stream.feed(&self.input()?)? {
                if message[..2] != [0x05, 0x5B] || check_packet(&message, 0x5B)?.0 != command {
                    continue;
                }
                if command == 0x0901 && message.get(6) != packet.get(6) {
                    continue;
                }
                // 0x2C83 replies put a status first, then the sub-command.
                if command == 0x2C83 && message.get(7) != packet.get(6) {
                    continue;
                }
                return Ok(Some(message));
            }
        }
        Ok(None)
    }

    /// Send a query answered by an acknowledgement and a 0x5D notification.
    /// Both can arrive in one input report, in either order.
    fn query(&mut self, packet: &[u8], dongle: bool, timeout: f64) -> Result<Vec<u8>> {
        let (command, _) = check_packet(packet, 0x5A)?;
        self.send_flagged(packet, dongle)?;
        let mut stream = InputStream::default();
        let (mut ack, mut notice) = (None, None);
        let deadline = Instant::now() + Duration::from_secs_f64(timeout);
        while Instant::now() < deadline {
            (self.sleep)(Duration::from_millis(10));
            for message in stream.feed(&self.input()?)? {
                let kind = message[1];
                if !matches!(kind, 0x5B | 0x5D) || check_packet(&message, kind)?.0 != command {
                    continue;
                }
                if kind == 0x5B {
                    ack.get_or_insert(message);
                } else {
                    notice.get_or_insert(message);
                }
            }
            if let (Some(ack), Some(notice)) = (&ack, &notice) {
                parse_query_ack(ack, command)?;
                return Ok(notice.clone());
            }
        }
        match ack {
            Some(ack) => {
                parse_query_ack(&ack, command)?;
                Err(Error::other("The headset acknowledged the query but sent no answer"))
            }
            None => Err(Error::other("No answer to the query")),
        }
    }

    /// Reconnects can leave delayed fragments and notifications queued, and one
    /// empty poll does not show that an old stream has ended.
    pub fn drain(&mut self) -> Result<()> {
        let mut empty_polls = 0;
        for _ in 0..100 {
            let report = self.input()?;
            if report.len() < 2 || report[0] != 7 || report[1] > 59 {
                return Err(Error::value("Malformed report while draining input"));
            }
            empty_polls = if report[1] == 0 { empty_polls + 1 } else { 0 };
            if empty_polls >= 6 {
                return Ok(());
            }
            (self.sleep)(Duration::from_millis(10));
        }
        Err(Error::value("Input queue did not drain; no command sent"))
    }

    /// Send one allowed request and return its matching, parsed reply.
    pub fn transact(&mut self, packet: &[u8], timeout: Option<f64>) -> Result<Vec<u8>> {
        let timeout = timeout.unwrap_or(self.default_timeout());
        if !(0.1..=30.0).contains(&timeout) {
            return Err(Error::value("Timeout must be 0.1..30 seconds"));
        }
        let (command, _) = check_packet(packet, 0x5A)?;
        self.send(packet)?;
        let message = self
            .reply(packet, timeout)?
            .ok_or_else(|| Error::other("No matching command response; live state may be uncertain"))?;
        match command {
            0x0E03 => parse_live_ack(&message)?,
            0x0A03 => {
                parse_storage_space(&message)?;
            }
            0x0A0D => parse_save_ack(&message, (u16::from_le_bytes([packet[6], packet[7]]) - 0xE42C) as u8)?,
            0x0901 => {
                parse_setting(&message, packet[6])?;
            }
            0x0900 if packet[6] == 0 => parse_select_ack(&message)?,
            0x0900 | 0x2C82 => {}
            0x2C83 => {
                parse_control(&message, packet[6])?;
            }
            _ if packet[7] == 0xEF => {
                parse_ui(&message, packet[6])?;
            }
            _ => {
                parse_stored_coefficients(&message, packet[6] - 0x2C)?;
            }
        }
        Ok(message)
    }

    /// A 0x0901 value, counted only when two reads in a row agree.
    fn read_stable(&mut self, packet: &[u8], sub: u8) -> Result<u8> {
        let mut previous = None;
        for _ in 0..READ_ROUNDS {
            let value = parse_setting(&self.transact(packet, None)?, sub)?;
            if previous == Some(value) {
                return Ok(value);
            }
            previous = Some(value);
            (self.sleep)(Duration::from_millis(120));
        }
        Err(Error::other("The headset kept returning different values. Try reading again."))
    }

    /// Send a 0x0900 write. Its reply format is undocumented; keep it for diagnosis only.
    fn write_0900(&mut self, packet: &[u8]) -> Result<Option<Vec<u8>>> {
        self.send(packet)?;
        self.reply(packet, 1.0)
    }

    /// Audeze HQ's Maxwell 2 USB step after a save: mute voice prompts,
    /// reselect the current preset, wait one second, restore the prompts.
    fn reselect(&mut self, index: u8) -> Result<()> {
        let level = self.read_stable(&read_voice_prompt_command(), VOICE_PROMPT)?;
        self.write_0900(&write_voice_prompt_command(0)?)?;
        let reselected = self.write_0900(&select_preset_command(index)?).map(|_| (self.sleep)(Duration::from_secs(1)));
        // Restore the prompt level even when the reselect failed.
        let restored = self.write_0900(&write_voice_prompt_command(level)?);
        reselected?;
        restored?;
        if parse_index(&self.transact(&read_index_command(), None)?)? != index {
            return Err(Error::other("The headset did not return to the custom preset after reloading it."));
        }
        Ok(())
    }
}

/// Reads right after a write can return a stale value, so a setting counts
/// only when two reads in a row agree.
const READ_ROUNDS: usize = 6;
const VERIFY_ATTEMPTS: usize = 4;
const SELECT_ATTEMPTS: usize = 5;

impl<T: ReportIo> Settings for Session<T> {
    fn read_setting(&mut self, sub: u8) -> Result<u8> {
        self.read_stable(&read_setting_command(sub)?, sub)
    }

    fn write_setting(&mut self, sub: u8, value: u8) -> Result<Option<Vec<u8>>> {
        let packet = write_setting_command(sub, value)?;
        if !self.allow_settings {
            return Err(Error::value("Settings writes are not enabled for this session"));
        }
        let reply = self.write_0900(&packet)?;
        for attempt in 0..VERIFY_ATTEMPTS {
            (self.sleep)(Duration::from_millis(if attempt == 0 { 300 } else { 600 }));
            if self.read_setting(sub)? == value {
                return Ok(reply);
            }
        }
        Err(Error::other(format!(
            "The headset did not keep the new value (setting 0x{sub:02X}). Read again to see what it holds now."
        )))
    }
}

impl<T: ReportIo> Session<T> {
    /// A control value that two reads in a row agree on.
    fn stable_control(&mut self, sub: u8) -> Result<u16> {
        let packet = read_control_command(sub)?;
        let mut previous = None;
        for _ in 0..READ_ROUNDS {
            let value = parse_control(&self.transact(&packet, None)?, sub)?;
            if previous == Some(value) {
                return Ok(value);
            }
            previous = Some(value);
            (self.sleep)(Duration::from_millis(120));
        }
        Err(Error::other("The headset kept returning different values. Try reading again."))
    }
}

impl<T: ReportIo> Controls for Session<T> {
    fn read_control(&mut self, sub: u8) -> Result<u16> {
        parse_control(&self.transact(&read_control_command(sub)?, None)?, sub)
    }

    fn write_control(&mut self, sub: u8, value: u16) -> Result<Option<Vec<u8>>> {
        let packet = write_control_command(sub, value)?;
        if !self.allow_controls {
            return Err(Error::value("Control writes are not enabled for this session"));
        }
        self.send(&packet)?;
        // Write replies are kept for diagnosis only; the read-back decides.
        let reply = self.reply(&packet, 1.0)?;
        for attempt in 0..VERIFY_ATTEMPTS {
            (self.sleep)(Duration::from_millis(if attempt == 0 { 300 } else { 600 }));
            if control_matches(sub, value, self.stable_control(sub)?) {
                return Ok(reply);
            }
        }
        Err(Error::other(format!(
            "The headset did not keep the new value (control 0x{sub:02X}). Read again to see what it holds now."
        )))
    }

    fn battery(&mut self) -> Result<u8> {
        let dongle = self.transport == Transport::Dongle;
        parse_battery(&self.query(&battery_command(), dongle, 2.0)?)
    }

    fn firmware(&mut self, dongle: bool) -> Result<String> {
        if dongle && self.transport != Transport::Dongle {
            return Err(Error::value("The dongle's firmware can only be read through the dongle"));
        }
        // Flags 0x80 address the headset through the dongle; 0 addresses the dongle.
        let flag = self.transport == Transport::Dongle && !dongle;
        parse_firmware(&self.query(&firmware_command(), flag, 2.0)?)
    }
}

impl<T: ReportIo> Device for Session<T> {
    /// Read-only snapshot. UI data exists only for the four custom slots.
    fn read_state(&mut self) -> Result<Value> {
        let raw_index = self.transact(&read_index_command(), None)?;
        let index = parse_index(&raw_index)?;
        let slot = (7..=10).contains(&index).then(|| index - 7);
        let interface = &self.interface;
        let mut state = object([
            (
                "device",
                object([
                    ("vid", json!(VENDOR_ID)),
                    ("pid", json!(self.product_id)),
                    ("model", json!(self.model.name())),
                    ("model_label", json!(label(self.model, self.product_id))),
                    ("usage_page", json!(USAGE_PAGE)),
                    ("transport", json!(self.transport.name())),
                    ("path", json!(interface.path)),
                    ("bcd_device", json!(interface.device_version)),
                    ("input_report_bytes", json!(interface.input_size)),
                    ("output_report_bytes", json!(interface.output_size)),
                ]),
            ),
            ("firmware", Value::Null),
            ("firmware_note", json!("Firmware command is outside this minimal allowlist")),
            ("index", json!(index)),
            ("slot", json!(slot)),
            ("raw_index_hex", json!(hex::encode(&raw_index))),
            ("bands", Value::Null),
            ("raw_ui_hex", Value::Null),
        ]);
        if let Some(slot) = slot {
            let preset = parse_ui(&self.transact(&read_ui_command(slot)?, None)?, slot)?;
            state["raw_ui_hex"] = json!(hex::encode(&preset.raw_payload));
            state["raw_ui_response_hex"] = json!(hex::encode(&preset.raw_response));
            state["ui_header_hex"] = json!(hex::encode(&preset.header));
            state["bands"] = Value::Array(preset.bands.iter().map(|band| band.to_json()).collect());
            let reply = self.transact(&read_coefficients_command(slot)?, None)?;
            state["saved_coefficients_hex"] = json!(parse_stored_coefficients(&reply, slot)?.map(hex::encode));
            state["raw_coefficient_response_hex"] = json!(hex::encode(&reply));
            if parse_index(&self.transact(&read_index_command(), None)?)? != index {
                return Err(Error::value("Preset changed while reading the headset; read it again"));
            }
        }
        Ok(state)
    }

    fn read_slot(&mut self, slot: u8) -> Result<Option<Vec<u8>>> {
        parse_stored_coefficients(&self.transact(&read_coefficients_command(slot)?, None)?, slot)
    }

    /// Switch presets, then read the index back until the headset reports it.
    fn select_preset(&mut self, index: u8) -> Result<Value> {
        let ack = self.transact(&select_preset_command(index)?, None)?;
        for attempt in 0..SELECT_ATTEMPTS {
            (self.sleep)(Duration::from_millis(if attempt == 0 { 150 } else { 400 }));
            if parse_index(&self.transact(&read_index_command(), None)?)? == index {
                return Ok(object([("select_ack_hex", json!(hex::encode(&ack)))]));
            }
        }
        Err(Error::other("The headset did not switch presets. Read it again to see which preset is active."))
    }

    fn has_storage_space(&mut self) -> Result<bool> {
        parse_storage_space(&self.transact(&storage_space_command(), None)?)
    }

    fn save_coefficients(&mut self, slot: u8, coefficients: &[u8]) -> Result<Value> {
        let ack = self.transact(&save_coefficients_command(slot, coefficients)?, Some(8.0))?;
        let actual = parse_coefficients(&self.transact(&read_coefficients_command(slot)?, None)?, slot)?;
        if actual != coefficients {
            return Err(Error::value("Saved coefficient read-back differs from the requested profile. Save it again."));
        }
        Ok(object([
            ("save_ack_hex", json!(hex::encode(&ack))),
            ("saved_verified", json!(true)),
            ("persistence_write_sent", json!(true)),
        ]))
    }

    /// One live update; callers enforce a custom preset and filter validation.
    fn apply_live(&mut self, coefficients: &[u8]) -> Result<Value> {
        let ack = self.transact(&live_command(coefficients)?, None)?;
        Ok(object([
            ("accepted", json!(true)),
            ("ack_hex", json!(hex::encode(&ack))),
            ("persistence_write_sent", json!(false)),
        ]))
    }

    fn reload_saved(&mut self, index: u8) -> Result<bool> {
        if self.model != Model::Maxwell2 || self.transport != Transport::Usb {
            return Ok(false);
        }
        self.reselect(index)?;
        Ok(true)
    }
}

/// Settings subcommands were analyzed only on the original Maxwell.
pub fn check_settings_model(model: Model) -> Result<()> {
    if model != Model::Maxwell {
        return Err(Error::other(
            "Channel balance and source profile are only supported on the original Maxwell. Nothing was changed.",
        ));
    }
    Ok(())
}

/// The headset controls were decoded for the original Maxwell only.
pub fn check_controls_model(model: Model) -> Result<()> {
    if model != Model::Maxwell {
        return Err(Error::other("Headset controls are only supported on the original Maxwell. Nothing was changed."));
    }
    Ok(())
}

#[cfg(windows)]
pub use windows::{WinHid, open, open_controls, open_exclusive, open_settings};

#[cfg(not(windows))]
pub use hidapi_backend::{open, open_controls, open_settings};

/// hidapi, for macOS and Linux. The `hidapi` feature builds it on Windows too, so it
/// can be checked there; Windows itself uses the native module below.
#[cfg(any(not(windows), feature = "hidapi"))]
pub mod hidapi_backend {
    use super::{
        BUSY, Interface, LINUX_PERMISSION, ReportIo, Session, Transport, USAGE_PAGE, VENDOR_ID, check_controls_model,
        check_settings_model, select,
    };
    use crate::balance::Settings;
    use crate::controls::Controls;
    use crate::descriptor::report_sizes;
    use crate::device::{Access, Device};
    use crate::{Error, Result};
    use hidapi::{HidApi, HidDevice};

    /// An opened control collection. hidapi opens it exclusively on macOS.
    pub struct HidapiIo {
        device: HidDevice,
        input_size: usize,
    }

    impl ReportIo for HidapiIo {
        fn input(&mut self) -> Result<Vec<u8>> {
            // Same shape as HidD_GetInputReport: full length, report ID first.
            let mut report = vec![0u8; self.input_size];
            report[0] = 7;
            self.device.get_input_report(&mut report).map_err(|error| Error::other(error.to_string()))?;
            Ok(report)
        }

        fn write(&mut self, report: &[u8]) -> Result<bool> {
            Ok(self.device.write(report).is_ok_and(|written| written == report.len()))
        }
    }

    /// On Linux the usual cause is a root-only `/dev/hidraw*` node, not a busy device.
    fn open_failure(path: &std::ffi::CStr) -> &'static str {
        let denied = cfg!(target_os = "linux")
            && std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .open(path.to_string_lossy().as_ref())
                .is_err_and(|error| error.kind() == std::io::ErrorKind::PermissionDenied);
        if denied { LINUX_PERMISSION } else { BUSY }
    }

    fn session(transport: Transport, allow_live: bool, allow_persistent: bool) -> Result<Session<HidapiIo>> {
        let api = HidApi::new().map_err(|error| Error::other(format!("Could not start HID access: {error}")))?;
        let found: Vec<_> = api
            .device_list()
            .filter(|info| info.vendor_id() == VENDOR_ID && info.usage_page() == USAGE_PAGE)
            .map(|info| (info.product_id(), info))
            .collect();
        let (model, product_id, info) = select(found, transport)?;
        let device = info.open_device(&api).map_err(|_| Error::other(open_failure(info.path())))?;
        let mut descriptor = vec![0u8; 4096];
        let length = device.get_report_descriptor(&mut descriptor).map_err(|error| Error::other(error.to_string()))?;
        let (input_size, output_size) = report_sizes(&descriptor[..length], USAGE_PAGE)
            .filter(|&(input, output)| (62..=1024).contains(&input) && (62..=1024).contains(&output))
            .ok_or_else(|| Error::other("The headset's HID report layout was not recognized. No EQ was sent."))?;
        let interface = Interface {
            path: info.path().to_string_lossy().into_owned(),
            input_size,
            output_size,
            device_version: info.release_number(),
        };
        let mut session =
            Session::new(HidapiIo { device, input_size }, transport, interface, allow_live, allow_persistent);
        (session.model, session.product_id) = (model, product_id);
        Ok(session)
    }

    pub fn open(transport: Transport, access: Access) -> Result<Box<dyn Device>> {
        let mut session = session(transport, access.live, access.persistent)?;
        session.allow_select = access.select;
        Ok(Box::new(session))
    }

    /// A session that can read settings and, with `allow_write`, change them. No EQ writes.
    pub fn open_settings(transport: Transport, allow_write: bool) -> Result<Box<dyn Settings>> {
        let mut session = session(transport, false, false)?;
        check_settings_model(session.model)?;
        session.allow_settings = allow_write;
        Ok(Box::new(session))
    }

    /// A session that can read controls and, with `allow_write`, change them. No EQ writes.
    pub fn open_controls(transport: Transport, allow_write: bool) -> Result<Box<dyn Controls>> {
        let mut session = session(transport, false, false)?;
        check_controls_model(session.model)?;
        session.allow_controls = allow_write;
        Ok(Box::new(session))
    }
}

#[cfg(windows)]
mod windows {
    use super::{
        BUSY, Interface, ReportIo, Session, Transport, USAGE_PAGE, VENDOR_ID, check_controls_model,
        check_settings_model, select,
    };
    use crate::balance::Settings;
    use crate::controls::Controls;
    use crate::device::{Access, Device};
    use crate::{Error, Result};
    use std::ptr::{null, null_mut};
    use windows_sys::Win32::Devices::DeviceAndDriverInstallation::{
        DIGCF_DEVICEINTERFACE, DIGCF_PRESENT, SP_DEVICE_INTERFACE_DATA, SetupDiDestroyDeviceInfoList,
        SetupDiEnumDeviceInterfaces, SetupDiGetClassDevsW, SetupDiGetDeviceInterfaceDetailW,
    };
    use windows_sys::Win32::Devices::HumanInterfaceDevice::{
        HIDD_ATTRIBUTES, HIDP_CAPS, HidD_FreePreparsedData, HidD_GetAttributes, HidD_GetHidGuid, HidD_GetInputReport,
        HidD_GetPreparsedData, HidP_GetCaps,
    };
    use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE, INVALID_HANDLE_VALUE};
    use windows_sys::Win32::Storage::FileSystem::{CreateFileW, OPEN_EXISTING, WriteFile};
    use windows_sys::core::GUID;

    const ERROR_SHARING_VIOLATION: u32 = 32;
    const ERROR_NO_MORE_ITEMS: u32 = 259;

    fn os_error(code: u32) -> Error {
        Error::other(std::io::Error::from_raw_os_error(code as i32).to_string())
    }

    fn wide(text: &str) -> Vec<u16> {
        text.encode_utf16().chain(Some(0)).collect()
    }

    /// An opened control collection. The handle closes on drop.
    pub struct WinHid {
        handle: HANDLE,
        input_size: usize,
    }

    // The handle is owned by one session and only used from one thread at a time.
    unsafe impl Send for WinHid {}

    impl Drop for WinHid {
        fn drop(&mut self) {
            unsafe { CloseHandle(self.handle) };
        }
    }

    impl ReportIo for WinHid {
        fn input(&mut self) -> Result<Vec<u8>> {
            let mut report = vec![0u8; self.input_size];
            report[0] = 7;
            if !unsafe { HidD_GetInputReport(self.handle, report.as_mut_ptr().cast(), report.len() as u32) } {
                return Err(os_error(unsafe { GetLastError() }));
            }
            Ok(report)
        }

        fn write(&mut self, report: &[u8]) -> Result<bool> {
            let mut written = 0u32;
            let ok = unsafe { WriteFile(self.handle, report.as_ptr(), report.len() as u32, &mut written, null_mut()) };
            Ok(ok != 0 && written as usize == report.len())
        }
    }

    /// `CreateFileW(path, access, share, null, OPEN_EXISTING, 0, null)`, returning
    /// the handle or the last error. Tests substitute this.
    pub type Create<'a> = dyn Fn(&str, u32, u32) -> std::result::Result<HANDLE, u32> + 'a;

    pub fn create_file(path: &str, access: u32, share: u32) -> std::result::Result<HANDLE, u32> {
        let path = wide(path);
        let handle = unsafe { CreateFileW(path.as_ptr(), access, share, null(), OPEN_EXISTING, 0, null_mut()) };
        if handle == INVALID_HANDLE_VALUE { Err(unsafe { GetLastError() }) } else { Ok(handle) }
    }

    /// RACE replies are a device-wide byte stream: a shared handle lets HQ or
    /// another tool consume fragments, so the whole transaction owns the collection.
    pub fn open_exclusive(path: &str, create: &Create<'_>) -> Result<HANDLE> {
        match create(path, 0xC000_0000, 0) {
            Ok(handle) => Ok(handle),
            Err(ERROR_SHARING_VIOLATION) => Err(Error::other(BUSY)),
            Err(code) => Err(os_error(code)),
        }
    }

    /// The product ID and layout of a vendor control collection.
    fn probe(path: &str) -> Option<(u16, Interface)> {
        let handle = create_file(path, 0, 3).ok()?;
        let result = (|| {
            let mut attributes =
                HIDD_ATTRIBUTES { Size: size_of::<HIDD_ATTRIBUTES>() as u32, ..unsafe { std::mem::zeroed() } };
            if !unsafe { HidD_GetAttributes(handle, &mut attributes) } || attributes.VendorID != VENDOR_ID {
                return None;
            }
            let mut preparsed = 0;
            if !unsafe { HidD_GetPreparsedData(handle, &mut preparsed) } {
                return None;
            }
            let mut caps: HIDP_CAPS = unsafe { std::mem::zeroed() };
            let status = unsafe { HidP_GetCaps(preparsed, &mut caps) };
            unsafe { HidD_FreePreparsedData(preparsed) };
            let (input, output) = (usize::from(caps.InputReportByteLength), usize::from(caps.OutputReportByteLength));
            (status >= 0
                && caps.UsagePage == USAGE_PAGE
                && (62..=1024).contains(&input)
                && (62..=1024).contains(&output))
            .then(|| {
                let interface = Interface {
                    path: path.to_owned(),
                    input_size: input,
                    output_size: output,
                    device_version: attributes.VersionNumber,
                };
                (attributes.ProductID, interface)
            })
        })();
        unsafe { CloseHandle(handle) };
        result
    }

    fn interfaces() -> Result<Vec<(u16, Interface)>> {
        let mut guid: GUID = unsafe { std::mem::zeroed() };
        unsafe { HidD_GetHidGuid(&mut guid) };
        let devices = unsafe { SetupDiGetClassDevsW(&guid, null(), null_mut(), DIGCF_PRESENT | DIGCF_DEVICEINTERFACE) };
        if devices == -1 {
            return Err(os_error(unsafe { GetLastError() }));
        }
        let mut found = Vec::new();
        let result = (|| {
            for index in 0.. {
                let mut entry: SP_DEVICE_INTERFACE_DATA = unsafe { std::mem::zeroed() };
                entry.cbSize = size_of::<SP_DEVICE_INTERFACE_DATA>() as u32;
                if unsafe { SetupDiEnumDeviceInterfaces(devices, null(), &guid, index, &mut entry) } == 0 {
                    let code = unsafe { GetLastError() };
                    return if code == ERROR_NO_MORE_ITEMS { Ok(()) } else { Err(os_error(code)) };
                }
                let mut need = 0u32;
                unsafe { SetupDiGetDeviceInterfaceDetailW(devices, &entry, null_mut(), 0, &mut need, null_mut()) };
                if need < 8 {
                    continue;
                }
                // u32-aligned buffer: cbSize, then the NUL-terminated path at offset 4.
                let mut buffer = vec![0u32; (need as usize).div_ceil(4)];
                buffer[0] = if size_of::<usize>() == 8 { 8 } else { 6 };
                let ok = unsafe {
                    SetupDiGetDeviceInterfaceDetailW(
                        devices,
                        &entry,
                        buffer.as_mut_ptr().cast(),
                        need,
                        &mut need,
                        null_mut(),
                    )
                };
                if ok == 0 {
                    continue;
                }
                let units = unsafe {
                    std::slice::from_raw_parts(buffer.as_ptr().cast::<u16>().add(2), (need as usize - 4) / 2)
                };
                let path =
                    String::from_utf16_lossy(&units[..units.iter().position(|&u| u == 0).unwrap_or(units.len())]);
                found.extend(probe(&path));
            }
            Ok(())
        })();
        unsafe { SetupDiDestroyDeviceInfoList(devices) };
        result.map(|()| found)
    }

    /// Find exactly one supported Maxwell control collection and open it exclusively.
    fn session(transport: Transport, allow_live: bool, allow_persistent: bool) -> Result<Session<WinHid>> {
        let (model, product_id, interface) = select(interfaces()?, transport)?;
        let handle = open_exclusive(&interface.path, &create_file)?;
        let io = WinHid { handle, input_size: interface.input_size };
        let mut session = Session::new(io, transport, interface, allow_live, allow_persistent);
        (session.model, session.product_id) = (model, product_id);
        Ok(session)
    }

    pub fn open(transport: Transport, access: Access) -> Result<Box<dyn Device>> {
        let mut session = session(transport, access.live, access.persistent)?;
        session.allow_select = access.select;
        Ok(Box::new(session))
    }

    /// A session that can read settings and, with `allow_write`, change them. No EQ writes.
    pub fn open_settings(transport: Transport, allow_write: bool) -> Result<Box<dyn Settings>> {
        let mut session = session(transport, false, false)?;
        check_settings_model(session.model)?;
        session.allow_settings = allow_write;
        Ok(Box::new(session))
    }

    /// A session that can read controls and, with `allow_write`, change them. No EQ writes.
    pub fn open_controls(transport: Transport, allow_write: bool) -> Result<Box<dyn Controls>> {
        let mut session = session(transport, false, false)?;
        check_controls_model(session.model)?;
        session.allow_controls = allow_write;
        Ok(Box::new(session))
    }
}
