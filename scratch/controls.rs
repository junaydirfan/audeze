//! Everyday headset controls and onboard preset switching, decoded from
//! Audeze HQ 1.2.48: chat mix, volume limiter, sidetone, noise reduction,
//! voice prompts, auto shutdown, battery, mic mute and firmware versions.
//!
//! Like balance, each write changes the headset at once and is read back.
//! Runs report the value they replaced. `glance` reads only what the tray
//! shows: the active preset, mic mute and battery.

use crate::hid::{Transport, connect};
use crate::json::{get, object};
use crate::protocol::{
    AMP_GAIN, AUTO_OFF, AUTO_OFF_SECONDS, CHAT_MIX, LIMITER_OFF, LIMITER_ON, MAX_CHAT_MIX, MAX_SIDETONE,
    MAX_VOICE_PROMPT, MIC_MUTE, NOISE_REDUCTION, PRESET_INDEX, SIDETONE_LEVEL, SIDETONE_ON, VOICE_PROMPT,
};
use crate::{Error, Result};
use serde_json::{Value, json};

pub const OPERATIONS: [&str; 3] = ["controls_read", "control_write", "glance"];

/// Onboard presets by index. 7..=10 are the four custom slots.
pub const PRESETS: [&str; 10] =
    ["Audeze", "Treble Boost", "Bass Boost", "Immersive", "Competition", "Footsteps", "EQ 1", "EQ 2", "EQ 3", "EQ 4"];

/// The headset controls a run needs.
pub trait Controls {
    /// One read, as the headset answers it.
    fn read_control(&mut self, sub: u8) -> Result<u16>;
    /// Write, then read back until the headset holds `value`. Returns the raw
    /// write reply when one arrived.
    fn write_control(&mut self, sub: u8, value: u16) -> Result<Option<Vec<u8>>>;
    /// Battery level as the headset reports it.
    fn battery(&mut self) -> Result<u8>;
    /// The headset's firmware version, or with `dongle` the dongle's own.
    fn firmware(&mut self, dongle: bool) -> Result<String>;
}

/// `open(allow_write, transport)`; production uses [`crate::hid::open_controls`].
pub type OpenControls<'a> = dyn FnMut(bool, Transport) -> Result<Box<dyn Controls>> + 'a;

/// How far a run got; reported with any error.
#[derive(Debug, Default, Clone, PartialEq)]
pub struct Progress {
    pub write_started: bool,
    pub previous: Option<Value>,
}

/// The controls a page can change, by request name.
fn control(name: &str) -> Option<u8> {
    Some(match name {
        "preset" => PRESET_INDEX,
        "chat_mix" => CHAT_MIX,
        "volume_limiter" => AMP_GAIN,
        "sidetone" => SIDETONE_ON,
        "sidetone_level" => SIDETONE_LEVEL,
        "noise_reduction" => NOISE_REDUCTION,
        "voice_prompt" => VOICE_PROMPT,
        "auto_off" => AUTO_OFF,
        _ => return None,
    })
}

fn preset_json(index: u16) -> Value {
    let name = usize::from(index).checked_sub(1).and_then(|i| PRESETS.get(i));
    object([
        ("index", json!(index)),
        ("name", name.map_or(Value::Null, |name| json!(name))),
        ("custom", json!((7..=10).contains(&index))),
    ])
}

/// The page value for a raw reading.
fn shown(sub: u8, raw: u16) -> Value {
    match sub {
        PRESET_INDEX => preset_json(raw),
        AMP_GAIN => json!(raw <= u16::from(LIMITER_ON)),
        SIDETONE_ON => json!(raw == 1),
        _ => json!(raw),
    }
}

/// The raw value to write for a page value.
fn requested(sub: u8, value: &Value, sidetone_max: u16) -> Result<u16> {
    let invalid = |text: &str| Error::value(text.to_owned());
    match sub {
        AMP_GAIN => match value.as_bool() {
            Some(true) => Ok(u16::from(LIMITER_ON)),
            Some(false) => Ok(u16::from(LIMITER_OFF)),
            None => Err(invalid("Turn the volume limiter on or off.")),
        },
        SIDETONE_ON => value.as_bool().map(u16::from).ok_or_else(|| invalid("Turn sidetone on or off.")),
        _ => {
            let number = value.as_u64().and_then(|n| u16::try_from(n).ok());
            let (range, message) = match sub {
                PRESET_INDEX => (1..=10, "Choose one of the ten onboard presets."),
                CHAT_MIX => (0..=u16::from(MAX_CHAT_MIX), "Chat mix runs from 0 to 20."),
                NOISE_REDUCTION => (0..=2, "Choose off, low or high noise reduction."),
                VOICE_PROMPT => (0..=u16::from(MAX_VOICE_PROMPT), "Voice prompt volume runs from 0 to 15."),
                SIDETONE_LEVEL => (0..=sidetone_max, "That sidetone level is above the headset's maximum."),
                _ => (0..=u16::MAX, ""),
            };
            match number {
                Some(n) if sub == AUTO_OFF && AUTO_OFF_SECONDS.contains(&n) => Ok(n),
                _ if sub == AUTO_OFF => Err(invalid("Choose one of the auto shutdown times.")),
                Some(n) if range.contains(&n) => Ok(n),
                _ => Err(invalid(message)),
            }
        }
    }
}

/// The mic mute reading: 0 is muted, 0xFF is live, anything else unknown.
fn mic_muted(raw: u16) -> Value {
    match raw {
        0 => json!(true),
        0xFF => json!(false),
        _ => Value::Null,
    }
}

/// Status readings fail on some firmware; the controls still work without them.
fn optional<T: Into<Value>>(reading: Result<T>) -> Value {
    reading.map_or(Value::Null, Into::into)
}

fn read_all(device: &mut dyn Controls, transport: Transport) -> Result<Value> {
    let mut read = |sub| device.read_control(sub);
    let preset = read(PRESET_INDEX)?;
    let chat_mix = read(CHAT_MIX)?;
    let amp_gain = read(AMP_GAIN)?;
    let sidetone = read(SIDETONE_ON)?;
    let sidetone_level = read(SIDETONE_LEVEL)?;
    let sidetone_max = read(MAX_SIDETONE)?;
    let noise_reduction = read(NOISE_REDUCTION)?;
    let voice_prompt = read(VOICE_PROMPT)?;
    let auto_off = read(AUTO_OFF)?;
    let mic = read(MIC_MUTE)?;
    let dongle_firmware = if transport == Transport::Dongle { optional(device.firmware(true)) } else { Value::Null };
    Ok(object([
        ("preset", shown(PRESET_INDEX, preset)),
        ("chat_mix", json!(chat_mix)),
        ("volume_limiter", shown(AMP_GAIN, amp_gain)),
        ("amp_gain", json!(amp_gain)),
        ("sidetone", shown(SIDETONE_ON, sidetone)),
        ("sidetone_level", json!(sidetone_level)),
        ("sidetone_max", json!(sidetone_max)),
        ("noise_reduction", json!(noise_reduction)),
        ("voice_prompt", json!(voice_prompt)),
        ("auto_off", json!(auto_off)),
        ("mic_muted", mic_muted(mic)),
        ("battery", optional(device.battery())),
        ("firmware", object([("headset", optional(device.firmware(false))), ("dongle", dongle_firmware)])),
        ("transport", json!(transport.name())),
    ]))
}

fn glance(device: &mut dyn Controls, transport: Transport) -> Result<Value> {
    let preset = device.read_control(PRESET_INDEX)?;
    let mic = device.read_control(MIC_MUTE)?;
    Ok(object([
        ("preset", shown(PRESET_INDEX, preset)),
        ("mic_muted", mic_muted(mic)),
        ("battery", optional(device.battery())),
        ("transport", json!(transport.name())),
    ]))
}

pub fn execute(request: &Value, open: &mut OpenControls, progress: &mut Progress) -> Result<Value> {
    *progress = Progress::default();
    let requested_transport = crate::hid::requested(request)?;
    match get(request, "operation").and_then(Value::as_str) {
        Some("controls_read") => {
            let (mut device, transport) = connect(requested_transport, |transport| open(false, transport))?;
            return read_all(device.as_mut(), transport);
        }
        Some("glance") => {
            let (mut device, transport) = connect(requested_transport, |transport| open(false, transport))?;
            return glance(device.as_mut(), transport);
        }
        Some("control_write") => {}
        _ => return Err(Error::value("Unsupported device operation.")),
    }
    let name = get(request, "control").and_then(Value::as_str).unwrap_or_default();
    let sub = control(name).ok_or_else(|| Error::value("Unknown headset control."))?;
    let value = get(request, "value").ok_or_else(|| Error::value("Expected a value for the control."))?;
    // Check what can be checked before opening the headset.
    if sub != SIDETONE_LEVEL {
        requested(sub, value, 0)?;
    }
    let (mut device, transport) = connect(requested_transport, |transport| open(true, transport))?;
    let max = if sub == SIDETONE_LEVEL { device.read_control(MAX_SIDETONE)? } else { 0 };
    let raw = requested(sub, value, max)?;
    let before = device.read_control(sub)?;
    progress.previous = Some(shown(sub, before));
    let mut replies = Vec::new();
    // The limiter reads as a range, so compare what the page shows.
    if shown(sub, before) != shown(sub, raw) {
        progress.write_started = true;
        if let Some(reply) = device.write_control(sub, raw)? {
            replies.push(json!(hex::encode(reply)));
        }
    }
    let after = device.read_control(sub)?;
    Ok(object([
        ("control", json!(name)),
        ("value", shown(sub, after)),
        ("raw", json!(after)),
        ("previous", shown(sub, before)),
        ("changed", json!(progress.write_started)),
        ("write_replies_hex", Value::Array(replies)),
        ("transport", json!(transport.name())),
    ]))
}

/// The worker's stdout on failure.
pub fn failure(error: &Error, progress: &Progress) -> Value {
    let mut message = error.to_string();
    if !progress.write_started && !message.contains("was changed") {
        message.push_str(" Nothing on the headset was changed.");
    }
    object([
        ("error", json!(message)),
        ("write_started", json!(progress.write_started)),
        ("previous", progress.previous.clone().unwrap_or(Value::Null)),
    ])
}

/// Run one request against the real headset.
pub fn run(request: &Value) -> (Value, bool) {
    let mut progress = Progress::default();
    let mut open = |write, transport| crate::hid::open_controls(transport, write);
    match execute(request, &mut open, &mut progress) {
        Ok(result) => (result, true),
        Err(error) => (failure(&error, &progress), false),
    }
}
