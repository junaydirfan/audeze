"""
audezeforlinux: Interactive live TUI dashboard and Custom EQ Studio.
Uses curses with alternate screen buffer and mouse support for zero scrollback,
rock-solid arrow key navigation, and real-time hardware synchronization.
Designed with a sleek, minimalist Studio Grayscale aesthetic.
"""

import os
import sys
import copy
import time
from typing import Optional, List, Dict, Any, Callable

# Prevent escape sequence delay for arrow keys
os.environ.setdefault("ESCDELAY", "25")

try:
    import curses
    CURSES_AVAILABLE = True
except ImportError:
    CURSES_AVAILABLE = False

from maxwell2.client import MaxwellClient
from maxwell2.protocol import PRESET_NAMES, build_write_control_command, SUB_NOISE_REDUCTION

STANDARD_FREQS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

CURVE_PROFILES: Dict[str, List[float]] = {
    "Flat": [0.0] * 10,
    "Harman Curve": [4.0, 3.5, 2.0, 0.5, 0.0, 0.5, 1.5, 2.5, 1.0, 0.5],
    "Bass Cannon": [6.0, 5.0, 4.0, 2.5, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "FPS Footsteps": [-3.0, -2.0, -1.0, 0.5, 2.0, 3.5, 4.0, 3.0, 1.5, 0.0],
    "V-Shape": [4.5, 3.5, 2.0, 0.0, -1.5, -1.0, 1.0, 2.5, 4.0, 4.5],
    "Warm Vocal": [0.5, 1.0, 1.5, 2.0, 2.5, 2.0, 1.0, 0.0, -1.0, -1.5],
}


class ClickableRegion:
    """Defines an interactive on-screen mouse-clickable bounding box."""
    def __init__(self, y: int, x1: int, x2: int, callback: Callable[[], None], desc: str = ""):
        self.y = y
        self.x1 = x1
        self.x2 = x2
        self.callback = callback
        self.desc = desc

    def hit_test(self, my: int, mx: int) -> bool:
        return self.y == my and self.x1 <= mx <= self.x2


def safe_addstr(stdscr, y: int, x: int, text: str, attr: int = 0):
    """Safely writes text to curses screen without throwing errors on boundary wrapping."""
    max_y, max_x = stdscr.getmaxyx()
    if y < 0 or y >= max_y or x < 0 or x >= max_x:
        return
    avail = max_x - x
    if avail <= 0:
        return
    if len(text) > avail:
        text = text[:avail]
    # Guard against bottom-right cell write error in some curses engines
    if y == max_y - 1 and len(text) == avail:
        text = text[:-1]
        if not text:
            return
    try:
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        pass


def draw_hline(stdscr, y: int, x: int, length: int, char: str = "─", attr: int = 0):
    """Draws a horizontal line safely."""
    safe_addstr(stdscr, y, x, char * length, attr)


class CursesTUI:
    """Full-featured curses TUI for audezeforlinux."""

    def __init__(self, stdscr, client: MaxwellClient):
        self.stdscr = stdscr
        self.client = client
        self.running = True

        # Active view: 0 = Dashboard & Controls, 1 = Custom EQ Studio
        self.active_tab = 0

        # Dashboard state
        self.selected_row = 0  # 0..9: presets, 10: sidetone, 11: chatmix, 12: noise_red
        self.TOTAL_ROWS = 13

        # EQ Studio state
        self.active_eq_slot = 0  # 0..3 (Presets 1..4)
        self.selected_band = 5   # 0..9 (default 1 kHz)
        self.current_eq_bands: List[Dict[str, Any]] = []
        self.eq_dirty = False
        self.profile_cycle_idx = 0
        self.active_curve_name = "Hardware Stored"

        # Telemetry & Status
        self.status: Dict[str, Any] = {}
        self.message = "Hardware connected. Use Arrow Keys to navigate, Enter or Mouse Click to activate."
        self.msg_attr = 0

        # Clickable regions registered during the last render
        self.click_regions: List[ClickableRegion] = []

        # Color pair indices
        self.C_NORMAL = 0
        self.C_HEADER = 0
        self.C_DIM = 0
        self.C_ACTIVE = 0
        self.C_WARN = 0
        self.C_SUCCESS = 0

    def init_curses_terminal(self):
        """Initializes terminal colors and settings."""
        curses.curs_set(0)  # Hide cursor
        self.stdscr.keypad(True)
        self.stdscr.timeout(1000)  # Non-blocking poll every 1s

        # Enable mouse events
        try:
            curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED | curses.BUTTON1_DOUBLE_CLICKED)
        except Exception:
            pass

        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_WHITE, -1)   # Normal
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE) # Reverse / Highlight
            curses.init_pair(3, curses.COLOR_WHITE, -1)   # Dim
            curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_WHITE) # Active indicator

            self.C_NORMAL = curses.color_pair(1)
            self.C_HEADER = curses.color_pair(2) | curses.A_BOLD
            self.C_DIM = curses.color_pair(3) | curses.A_DIM
            self.C_ACTIVE = curses.color_pair(2) | curses.A_BOLD
            self.C_WARN = curses.color_pair(1) | curses.A_BOLD
            self.C_SUCCESS = curses.color_pair(2) | curses.A_BOLD
        else:
            self.C_NORMAL = curses.A_NORMAL
            self.C_HEADER = curses.A_REVERSE | curses.A_BOLD
            self.C_DIM = curses.A_DIM
            self.C_ACTIVE = curses.A_REVERSE | curses.A_BOLD
            self.C_WARN = curses.A_BOLD
            self.C_SUCCESS = curses.A_REVERSE

    def load_initial_hardware_state(self):
        """Fetches full state from headset."""
        try:
            self.status = self.client.get_status()
        except Exception as e:
            self.status = {}
            self.message = f"Error querying status: {e}"

        try:
            raw_eq = self.client.read_custom_eq(self.active_eq_slot)
            self.current_eq_bands = copy.deepcopy(raw_eq.get("bands", []))
        except Exception:
            self.current_eq_bands = [
                {"band_index": 513, "frequency_hz": f, "gain_db": 0.0, "q": f / 2.0}
                for f in STANDARD_FREQS
            ]

    def run(self):
        """Main event loop."""
        self.init_curses_terminal()
        self.load_initial_hardware_state()

        while self.running:
            self.click_regions.clear()
            self.stdscr.erase()
            self.render()
            self.stdscr.refresh()

            try:
                ch = self.stdscr.getch()
            except KeyboardInterrupt:
                break

            if ch == -1:
                # 1-second timeout expired; continue loop
                continue

            self.handle_input(ch)

    # ==========================================================================
    # RENDERING ENGINE
    # ==========================================================================

    def render(self):
        """Draws current view based on terminal geometry."""
        max_y, max_x = self.stdscr.getmaxyx()

        if max_y < 22 or max_x < 76:
            msg1 = "AUDEZE FOR LINUX"
            msg2 = f"Please enlarge terminal (Current: {max_x}x{max_y}, Min: 76x22)"
            msg3 = "Press [q] to exit."
            safe_addstr(self.stdscr, max_y // 2 - 1, max(0, (max_x - len(msg1)) // 2), msg1, self.C_HEADER)
            safe_addstr(self.stdscr, max_y // 2, max(0, (max_x - len(msg2)) // 2), msg2, self.C_NORMAL)
            safe_addstr(self.stdscr, max_y // 2 + 1, max(0, (max_x - len(msg3)) // 2), msg3, self.C_DIM)
            return

        # 1. Top Title Banner
        self.render_header(max_y, max_x)

        # 2. View Tabs
        self.render_tab_bar(max_x, y=3)

        # 3. Main View Area
        if self.active_tab == 0:
            self.render_dashboard_view(max_y, max_x, start_y=5)
        else:
            self.render_eq_studio_view(max_y, max_x, start_y=5)

        # 4. Status Message & Bottom Help Bar
        self.render_footer(max_y, max_x)

    def render_header(self, max_y: int, max_x: int):
        """Renders sleek top telemetry bar."""
        fw = self.status.get("firmware", {}).get("firmware", "v1.0.5.7.4")
        batt = self.status.get("battery_percent", 94)
        mute = self.status.get("mic_muted", False)

        # Battery block
        pct = max(0, min(100, batt if batt is not None else 0))
        filled = int(pct / 10)
        batt_bar = f"[{'■' * filled}{'□' * (10 - filled)}] {pct}%"
        mic_tag = "MUTED" if mute else "LIVE"

        title_left = " AUDEZE FOR LINUX — STUDIO DASHBOARD "
        safe_addstr(self.stdscr, 0, 0, "┌" + "─" * (max_x - 2) + "┐", self.C_DIM)
        safe_addstr(self.stdscr, 1, 0, "│", self.C_DIM)
        safe_addstr(self.stdscr, 1, 2, title_left, self.C_HEADER)

        telemetry = f"FW: {fw}  •  Mic: {mic_tag}  •  Batt: {batt_bar} "
        telemetry_x = max(len(title_left) + 4, max_x - len(telemetry) - 2)
        safe_addstr(self.stdscr, 1, telemetry_x, telemetry, self.C_NORMAL)
        safe_addstr(self.stdscr, 1, max_x - 1, "│", self.C_DIM)
        safe_addstr(self.stdscr, 2, 0, "└" + "─" * (max_x - 2) + "┘", self.C_DIM)

    def render_tab_bar(self, max_x: int, y: int):
        """Renders view navigation tabs."""
        tab0_text = " [ 1. DASHBOARD & CONTROLS ] "
        tab1_text = " [ 2. CUSTOM EQ STUDIO ] "
        hint_text = "(Tab or Click to switch)"

        t0_attr = self.C_ACTIVE if self.active_tab == 0 else self.C_DIM
        t1_attr = self.C_ACTIVE if self.active_tab == 1 else self.C_DIM

        start_x = 4
        safe_addstr(self.stdscr, y, start_x, tab0_text, t0_attr)
        self.click_regions.append(ClickableRegion(y, start_x, start_x + len(tab0_text), lambda: self.set_tab(0), "Tab 0"))

        gap = 4
        t1_x = start_x + len(tab0_text) + gap
        safe_addstr(self.stdscr, y, t1_x, tab1_text, t1_attr)
        self.click_regions.append(ClickableRegion(y, t1_x, t1_x + len(tab1_text), lambda: self.set_tab(1), "Tab 1"))

        hint_x = t1_x + len(tab1_text) + 4
        if hint_x + len(hint_text) < max_x - 2:
            safe_addstr(self.stdscr, y, hint_x, hint_text, self.C_DIM)

    def set_tab(self, tab: int):
        self.active_tab = tab
        self.message = f"Switched to {'Custom EQ Studio' if tab == 1 else 'Dashboard & Controls'}."

    # --------------------------------------------------------------------------
    # VIEW 0: DASHBOARD & CONTROLS
    # --------------------------------------------------------------------------

    def render_dashboard_view(self, max_y: int, max_x: int, start_y: int):
        """Renders two-column layout: Presets matrix on left, hardware sliders on right."""
        mid_x = min(38, max_x // 2)

        # Left Column: Presets
        safe_addstr(self.stdscr, start_y, 2, "┌─ ONBOARD PRESET MATRIX ──────────┐", self.C_DIM)
        curr_preset = self.status.get("preset", {})
        curr_idx = curr_preset.get("index", 1)

        for i, name in enumerate(PRESET_NAMES, 1):
            row_y = start_y + 1 + (i - 1)
            is_active = (i == curr_idx)
            is_cursor = (self.selected_row == i - 1)

            cursor_marker = " > " if is_cursor else "   "
            num_str = f"[{i:02d}]"
            active_badge = " [ACTIVE]" if is_active else "         "

            name_display = name[:14].ljust(14)
            line = f"│{cursor_marker}{num_str} {name_display}{active_badge}│"

            if is_cursor:
                attr = self.C_ACTIVE
            elif is_active:
                attr = self.C_NORMAL | curses.A_BOLD
            else:
                attr = self.C_DIM

            safe_addstr(self.stdscr, row_y, 2, line, attr)

            # Register click on this preset row
            target_preset = i
            self.click_regions.append(
                ClickableRegion(row_y, 2, 2 + len(line), lambda p=target_preset: self.activate_preset(p), f"Preset {i}")
            )

        safe_addstr(self.stdscr, start_y + 11, 2, "└──────────────────────────────────┘", self.C_DIM)

        # Right Column: Controls & Sliders
        col2_x = 40
        col2_width = max(34, max_x - col2_x - 2)
        safe_addstr(self.stdscr, start_y, col2_x, "┌─ LIVE HARDWARE CONTROLS " + "─" * (col2_width - 26) + "┐", self.C_DIM)

        # Sidetone row (Row 10)
        st_y = start_y + 2
        st_cursor = " > " if self.selected_row == 10 else "   "
        st = self.status.get("sidetone", {})
        st_on = st.get("enabled", False)
        st_lvl = st.get("level", 5)
        st_bars = int((st_lvl / 31.0) * 10)
        st_slider = f"[{'■' * st_bars}{'□' * (10 - st_bars)}] {st_lvl:2d}/31"
        st_state = "ON " if st_on else "OFF"

        st_attr = self.C_ACTIVE if self.selected_row == 10 else self.C_NORMAL
        safe_addstr(self.stdscr, st_y, col2_x + 2, f"{st_cursor}Sidetone Monitor", st_attr)
        safe_addstr(self.stdscr, st_y + 1, col2_x + 6, f"State: [ {st_state} ]  Level: {st_slider}", self.C_NORMAL)

        # Sidetone click regions
        self.click_regions.append(
            ClickableRegion(st_y, col2_x + 2, col2_x + col2_width - 2, lambda: self.toggle_sidetone(), "Sidetone Toggle")
        )
        self.click_regions.append(
            ClickableRegion(st_y + 1, col2_x + 6, col2_x + 22, lambda: self.toggle_sidetone(), "Sidetone State Click")
        )

        # Game / Chat Balance row (Row 11)
        cm_y = start_y + 5
        cm_cursor = " > " if self.selected_row == 11 else "   "
        cm = self.status.get("chat_mix", {})
        game_p = cm.get("game_pct", 50)
        chat_p = cm.get("chat_pct", 50)
        cm_raw = cm.get("raw", 10)
        cm_bars = int((chat_p / 100.0) * 10)
        cm_slider = f"[{'□' * cm_bars}█{'□' * (10 - cm_bars)}]"

        cm_attr = self.C_ACTIVE if self.selected_row == 11 else self.C_NORMAL
        safe_addstr(self.stdscr, cm_y, col2_x + 2, f"{cm_cursor}Game / Chat Balance", cm_attr)
        safe_addstr(self.stdscr, cm_y + 1, col2_x + 6, f"Game {game_p:2d}%  {cm_slider}  {chat_p:2d}% Chat", self.C_NORMAL)

        self.click_regions.append(
            ClickableRegion(cm_y, col2_x + 2, col2_x + col2_width - 2, lambda: self.step_chatmix(1), "Chatmix Click")
        )

        # AI Noise Reduction Filter (Row 12)
        nr_y = start_y + 8
        nr_cursor = " > " if self.selected_row == 12 else "   "
        nr = self.status.get("noise_reduction", {}).get("name", "Low")
        nr_attr = self.C_ACTIVE if self.selected_row == 12 else self.C_NORMAL
        safe_addstr(self.stdscr, nr_y, col2_x + 2, f"{nr_cursor}AI Noise Reduction Filter", nr_attr)
        safe_addstr(self.stdscr, nr_y + 1, col2_x + 6, f"Active Profile: [ {nr.upper()} ]  (Click or ←/→ to cycle)", self.C_NORMAL)

        self.click_regions.append(
            ClickableRegion(nr_y, col2_x + 2, col2_x + col2_width - 2, lambda: self.cycle_noise_reduction(), "NR Click")
        )
        self.click_regions.append(
            ClickableRegion(nr_y + 1, col2_x + 6, col2_x + 36, lambda: self.cycle_noise_reduction(), "NR Click Profile")
        )

        safe_addstr(self.stdscr, start_y + 11, col2_x, "└" + "─" * (col2_width - 1) + "┘", self.C_DIM)

    # --------------------------------------------------------------------------
    # VIEW 1: CUSTOM EQ STUDIO (10-BAND GRAPHIC EQUALIZER)
    # --------------------------------------------------------------------------

    def render_eq_studio_view(self, max_y: int, max_x: int, start_y: int):
        """Renders 10-band interactive graphical equalizer with hardware save."""
        # Slot selector bar
        slot_y = start_y
        safe_addstr(self.stdscr, slot_y, 4, "Preset Slot: ", self.C_NORMAL | curses.A_BOLD)
        cur_x = 17

        for s in range(4):
            slot_name = f" [ Custom {s + 1} ] "
            is_cur_slot = (s == self.active_eq_slot)
            attr = self.C_ACTIVE if is_cur_slot else self.C_DIM
            safe_addstr(self.stdscr, slot_y, cur_x, slot_name, attr)

            target_slot = s
            self.click_regions.append(
                ClickableRegion(slot_y, cur_x, cur_x + len(slot_name), lambda s=target_slot: self.select_eq_slot(s), f"Slot {s+1}")
            )
            cur_x += len(slot_name) + 2

        # Spectrum Display Box
        box_y = start_y + 2
        box_height = 11  # Spectrum grid
        box_width = min(74, max_x - 4)

        safe_addstr(self.stdscr, box_y, 2, "┌─ 10-BAND GRAPHIC EQUALIZER " + "─" * (box_width - 29) + "┐", self.C_DIM)

        # Centerline row for 0 dB
        center_y = box_y + 5

        # Render 10 columns
        col_start_x = 14
        col_width = 5

        for band_idx in range(10):
            bx = col_start_x + (band_idx * col_width)
            gain = 0.0
            if band_idx < len(self.current_eq_bands):
                gain = self.current_eq_bands[band_idx].get("gain_db", 0.0)

            is_sel = (band_idx == self.selected_band)

            # Height mapping: +12dB (row -4) down to -12dB (row +4)
            # 1 row per 3 dB
            step = int(round(gain / 3.0))
            step = max(-4, min(4, step))

            # Vertical bar
            if step > 0:
                for r in range(1, step + 1):
                    safe_addstr(self.stdscr, center_y - r, bx, "█", self.C_ACTIVE if is_sel else self.C_NORMAL)
            elif step < 0:
                for r in range(1, abs(step) + 1):
                    safe_addstr(self.stdscr, center_y + r, bx, "█", self.C_ACTIVE if is_sel else self.C_NORMAL)

            # Centerline marker
            safe_addstr(self.stdscr, center_y, bx, "┼", self.C_DIM)

            # Selection marker at bottom of graph
            marker = "▲" if is_sel else " "
            marker_attr = self.C_ACTIVE if is_sel else self.C_DIM
            safe_addstr(self.stdscr, box_y + 9, bx, marker, marker_attr)

            # Click region on frequency column
            self.click_regions.append(
                ClickableRegion(box_y + 9, bx - 1, bx + 2, lambda b=band_idx: self.select_band(b), f"Band {band_idx}")
            )
            self.click_regions.append(
                ClickableRegion(center_y, bx - 1, bx + 2, lambda b=band_idx: self.select_band(b), f"Band {band_idx} center")
            )

        # Draw grid labels
        safe_addstr(self.stdscr, box_y + 1, 4, "+12dB ───", self.C_DIM)
        safe_addstr(self.stdscr, box_y + 3, 4, " +6dB ───", self.C_DIM)
        safe_addstr(self.stdscr, center_y, 4, "  0dB ───", self.C_NORMAL | curses.A_BOLD)
        safe_addstr(self.stdscr, box_y + 7, 4, " -6dB ───", self.C_DIM)
        safe_addstr(self.stdscr, box_y + 9, 4, "-12dB ───", self.C_DIM)

        safe_addstr(self.stdscr, box_y + 10, 2, "└" + "─" * (box_width - 2) + "┘", self.C_DIM)

        # Frequency Row & Gain Value Row
        freq_y = box_y + 11
        gain_y = box_y + 12

        safe_addstr(self.stdscr, freq_y, 4, "FREQ:", self.C_DIM)
        safe_addstr(self.stdscr, gain_y, 4, "GAIN:", self.C_DIM)

        for band_idx in range(10):
            bx = col_start_x + (band_idx * col_width)
            freq_val = STANDARD_FREQS[band_idx]
            freq_str = f"{freq_val//1000}k" if freq_val >= 1000 else f"{freq_val}"
            freq_str = freq_str.center(4)

            gain_val = 0.0
            if band_idx < len(self.current_eq_bands):
                gain_val = self.current_eq_bands[band_idx].get("gain_db", 0.0)
            gain_str = f"{gain_val:+.1f}".center(5)

            is_sel = (band_idx == self.selected_band)
            f_attr = self.C_ACTIVE if is_sel else self.C_NORMAL
            g_attr = self.C_ACTIVE if is_sel else self.C_DIM

            safe_addstr(self.stdscr, freq_y, bx - 1, freq_str, f_attr)
            safe_addstr(self.stdscr, gain_y, bx - 1, gain_str, g_attr)

            self.click_regions.append(
                ClickableRegion(freq_y, bx - 1, bx + 3, lambda b=band_idx: self.select_band(b), f"Band {band_idx}")
            )
            self.click_regions.append(
                ClickableRegion(gain_y, bx - 1, bx + 3, lambda b=band_idx: self.select_band(b), f"Band {band_idx}")
            )

        # Action Buttons Row
        act_y = box_y + 14
        btn1 = " [ S: SAVE TO HEADSET ] "
        btn2 = " [ P: CYCLE CURVE ] "
        btn3 = " [ F: FLATTEN (0dB) ] "
        btn4 = " [ +0.5dB (↑) ] "
        btn5 = " [ -0.5dB (↓) ] "

        cur_bx = 4
        safe_addstr(self.stdscr, act_y, cur_bx, btn1, self.C_ACTIVE)
        self.click_regions.append(ClickableRegion(act_y, cur_bx, cur_bx + len(btn1), lambda: self.save_custom_eq(), "Save"))
        cur_bx += len(btn1) + 2

        safe_addstr(self.stdscr, act_y, cur_bx, btn2, self.C_NORMAL | curses.A_BOLD)
        self.click_regions.append(ClickableRegion(act_y, cur_bx, cur_bx + len(btn2), lambda: self.cycle_curve_profile(), "Profile"))
        cur_bx += len(btn2) + 2

        safe_addstr(self.stdscr, act_y, cur_bx, btn3, self.C_NORMAL)
        self.click_regions.append(ClickableRegion(act_y, cur_bx, cur_bx + len(btn3), lambda: self.flatten_eq(), "Flatten"))
        cur_bx += len(btn3) + 2

        safe_addstr(self.stdscr, act_y, cur_bx, btn4, self.C_NORMAL)
        self.click_regions.append(ClickableRegion(act_y, cur_bx, cur_bx + len(btn4), lambda: self.adjust_gain(0.5), "+0.5dB"))
        cur_bx += len(btn4) + 1

        safe_addstr(self.stdscr, act_y, cur_bx, btn5, self.C_NORMAL)
        self.click_regions.append(ClickableRegion(act_y, cur_bx, cur_bx + len(btn5), lambda: self.adjust_gain(-0.5), "-0.5dB"))

    # --------------------------------------------------------------------------
    # FOOTER: STATUS PANEL & KEY HELP
    # --------------------------------------------------------------------------

    def render_footer(self, max_y: int, max_x: int):
        """Renders status message box and key shortcuts."""
        box_y = max_y - 3
        safe_addstr(self.stdscr, box_y, 0, "┌" + "─" * (max_x - 2) + "┐", self.C_DIM)

        status_text = f" {self.message[:max_x - 6]} "
        safe_addstr(self.stdscr, box_y + 1, 0, "│", self.C_DIM)
        safe_addstr(self.stdscr, box_y + 1, 2, status_text, self.C_NORMAL | curses.A_BOLD)
        safe_addstr(self.stdscr, box_y + 1, max_x - 1, "│", self.C_DIM)

        help_text = " [↑/↓/←/→] Navigate/Tune  •  [Enter/Click] Select  •  [Tab] Switch View  •  [s] Save  •  [q] Exit "
        safe_addstr(self.stdscr, box_y + 2, 0, "└" + "─" * (max_x - 2) + "┘", self.C_DIM)
        safe_addstr(self.stdscr, box_y + 2, max(0, (max_x - len(help_text)) // 2), help_text, self.C_DIM)

    # ==========================================================================
    # INPUT HANDLING (KEYBOARD & MOUSE)
    # ==========================================================================

    def handle_input(self, ch: int):
        """Handles keypresses and mouse clicks cleanly."""
        # Mouse click handling
        if ch == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                # Check all registered clickable regions
                for region in self.click_regions:
                    if region.hit_test(my, mx):
                        region.callback()
                        return
            except Exception:
                pass
            return

        # Global exit keys
        if ch in (ord('q'), ord('Q'), 27):  # 'q', 'Q', or Esc
            self.running = False
            return

        # Switch View Tab
        if ch in (ord('\t'), curses.KEY_BTAB):
            self.set_tab(1 if self.active_tab == 0 else 0)
            return

        # Refresh hardware status
        if ch in (ord('r'), ord('R')):
            self.refresh_telemetry()
            return

        # Window Resize
        if ch == curses.KEY_RESIZE:
            return

        # ----------------------------------------------------------------------
        # VIEW 0: DASHBOARD CONTROLS
        # ----------------------------------------------------------------------
        if self.active_tab == 0:
            if ch in (curses.KEY_UP, ord('k')):
                self.selected_row = (self.selected_row - 1) % self.TOTAL_ROWS
            elif ch in (curses.KEY_DOWN, ord('j')):
                self.selected_row = (self.selected_row + 1) % self.TOTAL_ROWS
            elif ch in (curses.KEY_ENTER, ord('\n'), ord('\r'), ord(' ')):
                if self.selected_row < 10:
                    self.activate_preset(self.selected_row + 1)
                elif self.selected_row == 10:
                    self.toggle_sidetone()
            elif ch in (curses.KEY_LEFT, ord('h')):
                if self.selected_row == 10:
                    self.step_sidetone(-1)
                elif self.selected_row == 11:
                    self.step_chatmix(-1)
                elif self.selected_row == 12:
                    self.cycle_noise_reduction(-1)
            elif ch in (curses.KEY_RIGHT, ord('l')):
                if self.selected_row == 10:
                    self.step_sidetone(1)
                elif self.selected_row == 11:
                    self.step_chatmix(1)
                elif self.selected_row == 12:
                    self.cycle_noise_reduction(1)

        # ----------------------------------------------------------------------
        # VIEW 1: CUSTOM EQ STUDIO
        # ----------------------------------------------------------------------
        elif self.active_tab == 1:
            if ch in (ord('1'), ord('2'), ord('3'), ord('4')):
                self.select_eq_slot(int(chr(ch)) - 1)
            elif ch in (curses.KEY_LEFT, ord('h')):
                self.selected_band = (self.selected_band - 1) % 10
            elif ch in (curses.KEY_RIGHT, ord('l')):
                self.selected_band = (self.selected_band + 1) % 10
            elif ch in (curses.KEY_UP, ord('k'), ord('+'), ord('=')):
                self.adjust_gain(0.5)
            elif ch in (curses.KEY_DOWN, ord('j'), ord('-'), ord('_')):
                self.adjust_gain(-0.5)
            elif ch in (ord('s'), ord('S')):
                self.save_custom_eq()
            elif ch in (ord('p'), ord('P')):
                self.cycle_curve_profile()
            elif ch in (ord('f'), ord('F')):
                self.flatten_eq()

    # ==========================================================================
    # HARDWARE ACTIONS
    # ==========================================================================

    def activate_preset(self, preset_idx: int):
        """Activates a preset on hardware."""
        p_name = PRESET_NAMES[preset_idx - 1]
        self.message = f"Activating [{preset_idx}] {p_name} on hardware..."
        try:
            res = self.client.set_preset(preset_idx)
            self.status["preset"] = res["preset"]
            self.message = f"✔ Preset switched to: [{preset_idx}] {p_name}"
        except Exception as e:
            self.message = f"Preset activation error: {e}"

    def toggle_sidetone(self):
        """Toggles hardware sidetone on/off."""
        curr = self.status.get("sidetone", {}).get("enabled", False)
        new_val = not curr
        try:
            self.client.set_sidetone(enabled=new_val)
            self.status["sidetone"]["enabled"] = new_val
            self.message = f"Sidetone switched {'ON' if new_val else 'OFF'}."
        except Exception as e:
            self.message = f"Sidetone toggle failed: {e}"

    def step_sidetone(self, delta: int):
        """Adjusts sidetone volume."""
        curr = self.status.get("sidetone", {}).get("level", 5)
        new_lvl = max(0, min(31, curr + delta))
        try:
            self.client.set_sidetone(level=new_lvl)
            self.status["sidetone"]["level"] = new_lvl
            self.message = f"Sidetone volume: {new_lvl}/31"
        except Exception as e:
            self.message = f"Sidetone volume failed: {e}"

    def step_chatmix(self, delta: int):
        """Adjusts game/chat balance."""
        cm = self.status.get("chat_mix", {})
        raw = cm.get("raw", 10)
        new_raw = max(0, min(20, raw + delta))
        try:
            self.client.set_chat_mix(new_raw)
            chat_p = int((new_raw / 20.0) * 100)
            self.status["chat_mix"]["raw"] = new_raw
            self.status["chat_mix"]["chat_pct"] = chat_p
            self.status["chat_mix"]["game_pct"] = 100 - chat_p
            self.message = f"Game/Chat Balance: {100 - chat_p}% Game / {chat_p}% Chat"
        except Exception as e:
            self.message = f"Chat mix failed: {e}"

    def cycle_noise_reduction(self, direction: int = 1):
        """Cycles AI noise reduction mode."""
        modes = ["Off", "Low", "High"]
        curr = self.status.get("noise_reduction", {}).get("code", 1)
        new_code = (curr + direction) % 3
        try:
            cmd = build_write_control_command(SUB_NOISE_REDUCTION, new_code)
            self.client.transport.write_race_packet(cmd)
            self.status["noise_reduction"]["code"] = new_code
            self.status["noise_reduction"]["name"] = modes[new_code]
            self.message = f"AI Noise Reduction set to {modes[new_code]}."
        except Exception as e:
            self.message = f"Noise reduction failed: {e}"

    def select_eq_slot(self, slot_idx: int):
        """Loads custom slot from hardware."""
        self.active_eq_slot = slot_idx
        try:
            raw_eq = self.client.read_custom_eq(self.active_eq_slot)
            self.current_eq_bands = copy.deepcopy(raw_eq.get("bands", []))
            self.eq_dirty = False
            self.message = f"Loaded Custom Preset {slot_idx + 1} from headset memory."
        except Exception as e:
            self.message = f"Failed to load slot {slot_idx + 1}: {e}"

    def select_band(self, band_idx: int):
        """Selects frequency band."""
        self.selected_band = band_idx
        f = STANDARD_FREQS[band_idx]
        f_str = f"{f//1000} kHz" if f >= 1000 else f"{f} Hz"
        g = self.current_eq_bands[band_idx].get("gain_db", 0.0)
        self.message = f"Selected band: {f_str} (Gain: {g:+.1f} dB)"

    def adjust_gain(self, delta: float):
        """Adjusts gain for currently selected band."""
        if not (0 <= self.selected_band < len(self.current_eq_bands)):
            return
        curr = self.current_eq_bands[self.selected_band].get("gain_db", 0.0)
        new_g = round(max(-12.0, min(12.0, curr + delta)), 1)
        self.current_eq_bands[self.selected_band]["gain_db"] = new_g
        self.eq_dirty = True
        f = STANDARD_FREQS[self.selected_band]
        f_str = f"{f//1000} kHz" if f >= 1000 else f"{f} Hz"
        self.message = f"Band {f_str}: {new_g:+.1f} dB (Unsaved. Press 's' to write to headset)."

    def flatten_eq(self):
        """Sets all 10 bands to 0.0 dB."""
        for b in self.current_eq_bands:
            b["gain_db"] = 0.0
        self.eq_dirty = True
        self.message = "EQ curve flattened to 0.0 dB. Press 's' to write to headset."

    def cycle_curve_profile(self):
        """Cycles through pre-tuned curve profiles."""
        curve_names = list(CURVE_PROFILES.keys())
        self.profile_cycle_idx = (self.profile_cycle_idx + 1) % len(curve_names)
        target_name = curve_names[self.profile_cycle_idx]
        gains = CURVE_PROFILES[target_name]
        for idx, g in enumerate(gains):
            if idx < len(self.current_eq_bands):
                self.current_eq_bands[idx]["gain_db"] = g
        self.eq_dirty = True
        self.message = f"Applied curve: '{target_name}'. Press 's' to write to headset."

    def save_custom_eq(self):
        """Saves current 10-band profile directly to headset hardware."""
        self.message = f"Saving Custom Preset {self.active_eq_slot + 1} to headset NVDM..."
        try:
            res = self.client.write_custom_eq(self.active_eq_slot, self.current_eq_bands, activate=True)
            self.eq_dirty = False
            self.message = f"✔ Saved & activated Custom Preset {self.active_eq_slot + 1} on headset!"
        except Exception as e:
            self.message = f"Save failed: {e}"

    def refresh_telemetry(self):
        """Re-reads telemetry from headset."""
        try:
            self.status = self.client.get_status()
            self.message = "Telemetry refreshed from headset."
        except Exception as e:
            self.message = f"Refresh failed: {e}"


def run_interactive_dashboard(client: MaxwellClient):
    """Entry point for live interactive curses TUI."""
    if not sys.stdin.isatty():
        print("[-] Interactive dashboard requires an interactive terminal (TTY).")
        return

    if not CURSES_AVAILABLE:
        print("[-] Python curses library is required for interactive mode.")
        return

    def _curses_main(stdscr):
        tui = CursesTUI(stdscr, client)
        tui.run()

    try:
        curses.wrapper(_curses_main)
    except Exception as e:
        print(f"[-] Interactive dashboard error: {e}")
