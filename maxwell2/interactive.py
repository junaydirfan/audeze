"""
Interactive live TUI dashboard and Custom EQ Studio for Audeze Maxwell 2.
Features full arrow-key navigation, slider tuning, preset switching,
and an interactive 10-band equalizer editor with hardware save capability.
Designed with a sleek, minimalist Studio Grayscale aesthetic.
"""

import sys
import tty
import termios
import select
import time
import copy
from typing import Optional, List, Dict, Any

from maxwell2.client import MaxwellClient
from maxwell2.protocol import PRESET_NAMES
from maxwell2.ui import render_banner, render_battery_bar, render_eq_spectrum

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.align import Align
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


# Quick curve profiles (10 bands from 32 Hz to 16 kHz)
CURVE_PROFILES = {
    "Flat": [0.0] * 10,
    "Harman Curve": [4.0, 3.5, 2.0, 0.5, 0.0, 0.5, 1.5, 2.5, 1.0, 0.5],
    "Bass Cannon": [6.0, 5.0, 4.0, 2.5, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "FPS Footsteps": [-3.0, -2.0, -1.0, 0.5, 2.0, 3.5, 4.0, 3.0, 1.5, 0.0],
    "V-Shape": [4.5, 3.5, 2.0, 0.0, -1.5, -1.0, 1.0, 2.5, 4.0, 4.5],
    "Warm Vocal": [0.5, 1.0, 1.5, 2.0, 2.5, 2.0, 1.0, 0.0, -1.0, -1.5],
}


class KeyReader:
    """Reads arrow keys and keystrokes non-blocking on POSIX terminals."""

    def __enter__(self):
        self.old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)

    def get_key(self, timeout_sec: float = 0.1) -> Optional[str]:
        r, _, _ = select.select([sys.stdin], [], [], timeout_sec)
        if not r:
            return None

        ch = sys.stdin.read(1)
        if ch == '\x1b':
            # Check for multi-byte escape sequence (arrow keys, etc.)
            r2, _, _ = select.select([sys.stdin], [], [], 0.04)
            if r2:
                seq = sys.stdin.read(2)
                if seq == '[A':
                    return 'UP'
                elif seq == '[B':
                    return 'DOWN'
                elif seq == '[C':
                    return 'RIGHT'
                elif seq == '[D':
                    return 'LEFT'
                elif seq in ('[Z',):  # Shift-Tab
                    return 'BTAB'
            return 'ESC'
        elif ch in ('\n', '\r'):
            return 'ENTER'
        elif ch == '\t':
            return 'TAB'
        elif ch == ' ':
            return 'SPACE'
        return ch


def run_interactive_dashboard(client: MaxwellClient):
    """
    Runs the full-featured interactive TUI:
    - Tab 0: Device Dashboard & Controls (Arrow-key navigation)
    - Tab 1: Custom EQ Studio (10-band spectrum tuner with hardware save)
    """
    if not RICH_AVAILABLE:
        print("Rich library is required for interactive mode.")
        return

    console = Console()
    active_tab = 0  # 0: Dashboard, 1: EQ Studio

    # Dashboard state
    selected_row = 0  # 0..9: presets, 10: sidetone, 11: chatmix, 12: noise_red
    TOTAL_ROWS = 13

    # EQ Studio state
    active_eq_slot = 0  # 0..3 (Presets 1..4)
    selected_band = 5   # 0..9 (default 1 kHz)
    current_eq_bands: List[Dict[str, Any]] = []
    eq_dirty = False
    profile_cycle_idx = 0

    # Fetch initial hardware state
    status = client.get_status()
    try:
        raw_eq = client.read_custom_eq(active_eq_slot)
        current_eq_bands = copy.deepcopy(raw_eq.get("bands", []))
    except Exception:
        STANDARD_FREQS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
        current_eq_bands = [{"band_index": 513, "frequency_hz": f, "gain_db": 0.0, "q": f / 2.0} for f in STANDARD_FREQS]

    message = "[bold white]Live hardware connected. Use [bold underline]Arrow Keys[/] to navigate & tune, [bold underline]Tab[/] to switch view.[/]"

    with KeyReader() as reader:
        running = True
        while running:
            console.clear()

            # View Navigation Tabs Header
            tab0_title = "[bold black on white]  1. DASHBOARD & CONTROLS  [/]" if active_tab == 0 else "[dim white]  1. Dashboard & Controls  [/]"
            tab1_title = "[bold black on white]  2. CUSTOM EQ STUDIO  [/]" if active_tab == 1 else "[dim white]  2. Custom EQ Studio  [/]"
            tabs_bar = f"{tab0_title}    {tab1_title}    [dim](Press Tab to switch view)[/dim]"
            console.print()
            console.print(Align.center(tabs_bar))
            console.print()

            # ==================================================================
            # VIEW 0: DASHBOARD
            # ==================================================================
            if active_tab == 0:
                curr_preset = status.get("preset", {})
                curr_idx = curr_preset.get("index", 1)

                # 1. Presets Matrix
                p_table = Table(box=box.ROUNDED, expand=True, title="[bold white]ONBOARD PRESET SELECTION[/bold white]", border_style="white")
                p_table.add_column("Nav", justify="center", width=5)
                p_table.add_column("No.", justify="center", width=5)
                p_table.add_column("Preset Mode", style="white")
                p_table.add_column("Hardware State", justify="center", width=18)

                for i, name in enumerate(PRESET_NAMES, 1):
                    is_active = (i == curr_idx)
                    is_cursor = (selected_row == i - 1)

                    nav_marker = "[bold black on white] > [/]" if is_cursor else "   "
                    num_label = f"[{i:2d}]"

                    if is_active:
                        state_badge = "[bold black on white] ● ACTIVE [/]"
                        p_name_styled = f"[bold white]{name.upper()}[/]"
                    else:
                        state_badge = "[dim]·[/dim]"
                        p_name_styled = f"[white]{name}[/]" if is_cursor else f"[grey70]{name}[/]"

                    p_table.add_row(nav_marker, num_label, p_name_styled, state_badge)

                # 2. Controls Table
                c_table = Table(box=box.ROUNDED, expand=True, title="[bold white]LIVE HARDWARE CONTROLS[/bold white]", border_style="white")
                c_table.add_column("Nav", justify="center", width=5)
                c_table.add_column("Control Item", width=20, style="bold white")
                c_table.add_column("Value & Live Slider")

                # Sidetone Row (Row 10)
                st_cursor = "[bold black on white] > [/]" if selected_row == 10 else "   "
                st = status.get("sidetone", {})
                st_on = st.get("enabled", False)
                st_lvl = st.get("level", 0)
                st_val = f"[bold white]{'ON' if st_on else 'OFF'}[/] • Level [bold white]{st_lvl}/31[/] [dim]([Enter] Toggle, [←/→] Adjust)[/dim]"
                c_table.add_row(st_cursor, "Sidetone Monitor", st_val)

                # Game/Chat Row (Row 11)
                cm_cursor = "[bold black on white] > [/]" if selected_row == 11 else "   "
                cm = status.get("chat_mix", {})
                game_p = cm.get("game_pct", 50)
                chat_p = cm.get("chat_pct", 50)
                cm_val = f"Game {game_p}% | Chat {chat_p}%  [dim]([←/→] Crossfade)[/dim]"
                c_table.add_row(cm_cursor, "Game / Chat Mix", cm_val)

                # Noise Reduction Row (Row 12)
                nr_cursor = "[bold black on white] > [/]" if selected_row == 12 else "   "
                nr = status.get("noise_reduction", {}).get("name", "Unknown")
                c_table.add_row(nr_cursor, "AI Noise Filter", f"[bold white]{nr}[/] [dim]([←/→] Cycle)[/dim]")

                # Battery & Info
                batt = status.get("battery_percent")
                fw = status.get("firmware", {}).get("firmware", "Unknown")
                mute = status.get("mic_muted")
                mic_str = "[bold black on white] MUTED [/]" if mute else "[bold white]LIVE / UNMUTED[/]"
                c_table.add_row("   ", "Battery", render_battery_bar(batt))
                c_table.add_row("   ", "Microphone Switch", mic_str)
                c_table.add_row("   ", "Firmware", f"Audeze Maxwell 2 • {fw}")

                console.print(p_table)
                console.print(c_table)

            # ==================================================================
            # VIEW 1: CUSTOM EQ STUDIO
            # ==================================================================
            elif active_tab == 1:
                # Slot Bar
                slot_buttons = []
                for s in range(4):
                    slot_name = f"Custom Preset {s + 1}"
                    if s == active_eq_slot:
                        slot_buttons.append(f"[bold black on white] [ {slot_name.upper()} ] [/]")
                    else:
                        slot_buttons.append(f"[dim white] [ {slot_name} ] [/]")
                console.print(Align.center("    ".join(slot_buttons)))
                console.print()

                # Spectrum Analyzer Table
                console.print(render_eq_spectrum(current_eq_bands, selected_band_idx=selected_band))
                console.print()

                # Action Bar
                dirty_tag = "[bold yellow]● MODIFIED (UNSAVED)[/]" if eq_dirty else "[bold green]✔ SYNCHRONIZED TO HEADSET[/]"
                console.print(Align.center(dirty_tag))
                console.print(
                    Align.center(
                        "[bold white][←/→][/] Select Band  •  "
                        "[bold white][↑/↓][/] Adjust Gain (±0.5dB)  •  "
                        "[bold white][s][/] [bold underline]SAVE TO HEADSET[/]  •  "
                        "[bold white][p][/] Cycle Curve  •  "
                        "[bold white][f][/] Flatten (0dB)"
                    )
                )

            # Bottom Status Message & Help
            console.print()
            console.print(Panel(message, title="Status", border_style="white", box=box.ROUNDED))
            console.print("[dim white]Navigation: [↑/↓/←/→] Navigate/Adjust • [Enter] Select/Toggle • [Tab] Switch View • [r] Refresh • [q/Esc] Exit[/dim white]")

            # Wait for User Keystroke
            key = reader.get_key(timeout_sec=1.5)
            if not key:
                continue

            # Global keys
            if key in ('q', 'ESC'):
                running = False
                break
            elif key == 'TAB':
                active_tab = 1 if active_tab == 0 else 0
                message = f"[bold white]Switched to {'Custom EQ Studio' if active_tab == 1 else 'Dashboard'}.[/]"
                continue
            elif key == 'r':
                try:
                    status = client.get_status()
                    message = "[bold white]Telemetry refreshed from hardware.[/]"
                except Exception as e:
                    message = f"[dim]Refresh failed: {e}[/]"
                continue

            # ==================================================================
            # INPUT HANDLING - DASHBOARD
            # ==================================================================
            if active_tab == 0:
                if key == 'UP':
                    selected_row = (selected_row - 1) % TOTAL_ROWS
                elif key == 'DOWN':
                    selected_row = (selected_row + 1) % TOTAL_ROWS
                elif key in ('ENTER', 'SPACE'):
                    if selected_row < 10:  # Presets 1..10
                        target_idx = selected_row + 1
                        p_name = PRESET_NAMES[target_idx - 1]
                        message = f"Activating [{target_idx}] {p_name}..."
                        try:
                            res = client.set_preset(target_idx)
                            status["preset"] = res["preset"]
                            message = f"[bold white]✔ Activated preset: [{target_idx}] {p_name}[/]"
                        except Exception as e:
                            message = f"[dim]Preset activation failed: {e}[/]"
                    elif selected_row == 10:  # Toggle Sidetone
                        curr_st = status.get("sidetone", {}).get("enabled", False)
                        new_st = not curr_st
                        try:
                            client.set_sidetone(enabled=new_st)
                            status["sidetone"]["enabled"] = new_st
                            message = f"[bold white]Sidetone turned {'ON' if new_st else 'OFF'}.[/]"
                        except Exception as e:
                            message = f"[dim]Sidetone toggle failed: {e}[/]"
                elif key in ('LEFT', 'RIGHT'):
                    if selected_row == 10:  # Adjust Sidetone Volume
                        curr_lvl = status.get("sidetone", {}).get("level", 5)
                        new_lvl = max(0, min(31, curr_lvl + (-1 if key == 'LEFT' else 1)))
                        try:
                            client.set_sidetone(level=new_lvl)
                            status["sidetone"]["level"] = new_lvl
                            message = f"[bold white]Sidetone volume set to {new_lvl}/31.[/]"
                        except Exception as e:
                            message = f"[dim]Sidetone volume adjust failed: {e}[/]"
                    elif selected_row == 11:  # Game/Chat balance
                        cm = status.get("chat_mix", {})
                        curr_raw = cm.get("raw", 10)
                        new_raw = max(0, min(20, curr_raw + (-1 if key == 'LEFT' else 1)))
                        try:
                            client.set_chat_mix(new_raw)
                            chat_p = int((new_raw / 20.0) * 100)
                            status["chat_mix"]["raw"] = new_raw
                            status["chat_mix"]["chat_pct"] = chat_p
                            status["chat_mix"]["game_pct"] = 100 - chat_p
                            message = f"[bold white]Game/Chat mix: {100 - chat_p}% Game / {chat_p}% Chat.[/]"
                        except Exception as e:
                            message = f"[dim]Chat mix adjust failed: {e}[/]"
                    elif selected_row == 12:  # AI Noise reduction
                        modes = ["Off", "Low", "High"]
                        curr_code = status.get("noise_reduction", {}).get("code", 1)
                        new_code = (curr_code + (-1 if key == 'LEFT' else 1)) % 3
                        try:
                            # CMD_SETTING_WRITE SUB_NOISE_REDUCTION (0x24)
                            from maxwell2.protocol import build_write_control_command, SUB_NOISE_REDUCTION
                            client.transport.write_race_packet(build_write_control_command(SUB_NOISE_REDUCTION, new_code))
                            status["noise_reduction"]["code"] = new_code
                            status["noise_reduction"]["name"] = modes[new_code]
                            message = f"[bold white]AI Noise filter set to {modes[new_code]}.[/]"
                        except Exception as e:
                            message = f"[dim]Noise reduction failed: {e}[/]"

            # ==================================================================
            # INPUT HANDLING - CUSTOM EQ STUDIO
            # ==================================================================
            elif active_tab == 1:
                if key in ('1', '2', '3', '4'):
                    # Switch slot
                    new_slot = int(key) - 1
                    active_eq_slot = new_slot
                    try:
                        raw_eq = client.read_custom_eq(active_eq_slot)
                        current_eq_bands = copy.deepcopy(raw_eq.get("bands", []))
                        eq_dirty = False
                        message = f"[bold white]Loaded Custom Preset {active_eq_slot + 1} from headset.[/]"
                    except Exception as e:
                        message = f"[dim]Failed to read slot: {e}[/]"
                elif key == 'LEFT':
                    selected_band = (selected_band - 1) % 10
                elif key == 'RIGHT':
                    selected_band = (selected_band + 1) % 10
                elif key == 'UP':
                    current_eq_bands[selected_band]["gain_db"] = min(12.0, current_eq_bands[selected_band]["gain_db"] + 0.5)
                    eq_dirty = True
                elif key == 'DOWN':
                    current_eq_bands[selected_band]["gain_db"] = max(-12.0, current_eq_bands[selected_band]["gain_db"] - 0.5)
                    eq_dirty = True
                elif key == 'f':  # Flatten
                    for b in current_eq_bands:
                        b["gain_db"] = 0.0
                    eq_dirty = True
                    message = "[bold white]EQ curve flattened to 0.0 dB across all bands.[/]"
                elif key == 'p':  # Cycle Preset Curves
                    curve_names = list(CURVE_PROFILES.keys())
                    profile_cycle_idx = (profile_cycle_idx + 1) % len(curve_names)
                    target_name = curve_names[profile_cycle_idx]
                    gains = CURVE_PROFILES[target_name]
                    for idx, g in enumerate(gains):
                        current_eq_bands[idx]["gain_db"] = g
                    eq_dirty = True
                    message = f"[bold white]Applied curve profile: '{target_name}' (Press 's' to save to headset).[/]"
                elif key == 's':  # Save to headset
                    message = f"Saving Custom Preset {active_eq_slot + 1} to Maxwell 2 hardware..."
                    try:
                        res = client.write_custom_eq(active_eq_slot, current_eq_bands, activate=True)
                        eq_dirty = False
                        message = f"[bold white]✔ Custom Preset {active_eq_slot + 1} saved and activated on headset! Backup: {res['backup_file']}[/]"
                    except Exception as e:
                        message = f"[dim]Save failed: {e}[/]"

    console.clear()
    console.print("[bold white]Exited Maxwell 2 Interactive Studio.[/bold white]")
