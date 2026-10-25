"""
Immersive rich terminal UI components for Audeze Maxwell 2 CLI & TUI.
Provides modern visual gauges, spectrum graphs, status badges, and interactive dashboard.
"""

import sys
import time
from typing import Dict, Any, List, Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.columns import Columns
    from rich.align import Align
    from rich import box
    from rich.style import Style
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


def create_console() -> "Console":
    if RICH_AVAILABLE:
        return Console()
    return None


def render_banner() -> str:
    return (
        "[bold cyan]   ___   __  ______  _______ ____ ____ [/bold cyan]\n"
        "[bold cyan]  / _ | / / / / _  \\/ __/_ // __//_  / [/bold cyan]\n"
        "[bold cyan] / __ |/ /_/ / // // _/  / // _/  / /_ [/bold cyan]\n"
        "[bold cyan]/_/ |_|\\____/____/___/  /___/___//___/ [/bold cyan]\n"
        "[dim]  M A X W E L L  2  •  L I N U X  C O N T R O L[/dim]"
    )


def render_battery_bar(percent: Optional[int], width: int = 16) -> str:
    """Renders a colorful visual battery bar with color gradient based on percentage."""
    if percent is None:
        return "[dim red][ ???????????????? ] Disconnected[/dim red]"

    filled_len = int((percent / 100.0) * width)
    unfilled_len = width - filled_len

    if percent >= 60:
        color = "green"
        state = "High"
    elif percent >= 25:
        color = "yellow"
        state = "Good"
    elif percent >= 15:
        color = "dark_orange"
        state = "Low"
    else:
        color = "red"
        state = "CRITICAL"

    bar = f"[{color}]" + "█" * filled_len + "[/]" + "[dim]░[/dim]" * unfilled_len
    return f"[bold {color}]{percent}%[/] [{bar}] [dim]({state})[/dim]"


def render_slider_bar(value: int, max_val: int = 20, width: int = 20, left_label: str = "Game", right_label: str = "Chat") -> str:
    """Renders a center-notched crossfader slider bar."""
    ratio = max(0.0, min(1.0, value / float(max_val)))
    pos = int(ratio * width)

    bar_chars = []
    mid = width // 2
    for i in range(width + 1):
        if i == pos:
            bar_chars.append("[bold cyan]◆[/bold cyan]")
        elif i == mid:
            bar_chars.append("[white]│[/white]")
        elif i < pos:
            bar_chars.append("[cyan]━[/cyan]")
        else:
            bar_chars.append("[dim]─[/dim]")

    slider_str = "".join(bar_chars)
    left_pct = int((1.0 - ratio) * 100)
    right_pct = int(ratio * 100)
    return f"[bold]{left_label}[/] {left_pct}% [{slider_str}] {right_pct}% [bold]{right_label}[/]"


def render_sidetone_bar(level: int, max_level: int = 31, enabled: bool = True, width: int = 15) -> str:
    """Renders visual level meter for sidetone."""
    if not enabled:
        return "[dim]● OFF (Muted)[/dim]"
    ratio = max(0.0, min(1.0, level / float(max_level)))
    filled = int(ratio * width)
    unfilled = width - filled
    bar = "[bold green]" + "■" * filled + "[/]" + "[dim]░[/dim]" * unfilled
    return f"[bold green]● ON[/] [{bar}] [bold]{level}[/][dim]/{max_level}[/dim]"


def render_eq_spectrum(bands: List[Dict[str, Any]], height: int = 9) -> Table:
    """
    Renders an ASCII/Unicode graphic equalizer spectrum analyzer display.
    """
    table = Table(
        box=box.ROUNDED,
        title="[bold cyan]10-BAND GRAPHIC EQUALIZER SPECTRUM[/bold cyan]",
        title_justify="center",
        border_style="cyan",
        header_style="bold magenta",
    )

    table.add_column("Level", justify="right", style="dim", no_wrap=True, width=8)
    labels = ["32", "64", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
    for lbl in labels:
        table.add_column(lbl, justify="center", width=6)

    # Gains range: +12 dB down to -12 dB in discrete steps
    db_steps = [12.0, 9.0, 6.0, 3.0, 0.0, -3.0, -6.0, -9.0, -12.0]
    gains = [b.get("gain_db", 0.0) for b in bands]
    while len(gains) < 10:
        gains.append(0.0)

    for db_level in db_steps:
        row = [f"{db_level:+2.0f}dB" if db_level != 0 else " 0dB"]
        for g in gains:
            if db_level == 0.0:
                if g == 0.0:
                    row.append("[cyan]─┼─[/cyan]")
                else:
                    row.append("[bold cyan]│█│[/bold cyan]")
            elif db_level > 0:
                if g >= db_level:
                    row.append("[bold green] █ [/bold green]")
                elif g >= db_level - 1.5:
                    row.append("[green] ▄ [/green]")
                else:
                    row.append("[dim] · [/dim]")
            else:  # db_level < 0
                if g <= db_level:
                    row.append("[bold yellow] █ [/bold yellow]")
                elif g <= db_level + 1.5:
                    row.append("[yellow] ▀ [/yellow]")
                else:
                    row.append("[dim] · [/dim]")
        table.add_row(*row)

    # Add numeric gain values at bottom
    num_row = ["[bold white]Gain[/]"]
    for g in gains:
        color = "green" if g > 0 else ("yellow" if g < 0 else "dim")
        num_row.append(f"[{color}]{g:+.1f}[/]")
    table.add_row(*num_row)

    return table


def print_rich_status(status: Dict[str, Any]):
    """Renders the complete rich device dashboard view."""
    if not RICH_AVAILABLE:
        # Fallback will be handled by caller
        return

    console = Console()

    # Device header panel
    banner_text = render_banner()
    console.print(Align.center(banner_text))
    console.print()

    # Active preset badge
    preset = status.get("preset", {})
    p_name = preset.get("name", "Unknown")
    p_idx = preset.get("index", 1)
    is_custom = preset.get("is_custom", False)

    if is_custom:
        slot_num = preset.get("slot", 0) + 1
        preset_badge = f"[bold white on blue]  ▶ ACTIVE PRESET: [{p_idx}] {p_name.upper()} (CUSTOM {slot_num})  [/]"
    else:
        preset_badge = f"[bold white on magenta]  ▶ ACTIVE PRESET: [{p_idx}] {p_name.upper()}  [/]"

    console.print(Align.center(preset_badge))
    console.print()

    # Main Status Table
    status_table = Table(box=box.ROUNDED, expand=True, border_style="bright_blue")
    status_table.add_column("Category", style="bold cyan", width=22)
    status_table.add_column("Live Telemetry & Hardware Control", style="white")

    # Battery
    batt = status.get("battery_percent")
    status_table.add_row("Battery", render_battery_bar(batt))

    # Mic Mute
    mute = status.get("mic_muted")
    if mute is True:
        mic_str = "[bold white on red] ● MUTED [/] [dim](Physical boom mic switch is muted)[/dim]"
    elif mute is False:
        mic_str = "[bold white on green] ● LIVE / UNMUTED [/] [dim](Microphone active)[/dim]"
    else:
        mic_str = "[dim]Unknown[/dim]"
    status_table.add_row("Microphone", mic_str)

    # Sidetone
    st = status.get("sidetone", {})
    st_str = render_sidetone_bar(st.get("level", 0), st.get("max_level", 31), st.get("enabled", False))
    status_table.add_row("Sidetone Monitor", st_str)

    # Game / Chat Mix
    cm = status.get("chat_mix", {})
    cm_str = render_slider_bar(cm.get("raw", 10), max_val=20)
    status_table.add_row("Game / Chat Balance", cm_str)

    # Noise Reduction
    nr = status.get("noise_reduction", {}).get("name", "Unknown")
    nr_colors = {"Off": "dim", "Low": "cyan", "High": "bold green"}
    nr_color = nr_colors.get(nr, "white")
    status_table.add_row("AI Noise Filter", f"[{nr_color}]● {nr}[/]")

    # Limiter
    lim = status.get("limiter", {}).get("enabled")
    if lim:
        lim_str = "[bold green]Active (85 dB)[/] [dim](Hearing safety cap enabled)[/dim]"
    else:
        lim_str = "[yellow]Inactive[/] [dim](Full dynamic volume headroom)[/dim]"
    status_table.add_row("Volume Limiter", lim_str)

    # Firmware & Dongle Info
    fw = status.get("firmware", {}).get("firmware", "Unknown")
    status_table.add_row("Device Info", f"[cyan]Audeze Maxwell 2 Xbox Dongle[/] • Firmware: [bold green]{fw}[/]")

    console.print(Panel(status_table, title="[bold white]HARDWARE TELEMETRY & CONTROLS[/bold white]", border_style="blue"))
    console.print()


def print_rich_preset_success(preset: Dict[str, Any], backup_file: str, dry_run: bool = False):
    """Renders a stylish toast panel when a preset changes."""
    if not RICH_AVAILABLE:
        return

    console = Console()
    idx = preset.get("index", "?")
    name = preset.get("name", "Unknown")
    dry = " [bold yellow](DRY-RUN - SIMULATED)[/]" if dry_run else ""

    text = Text()
    text.append("✔ ", style="bold green")
    text.append(f"Successfully activated preset [{idx}] ", style="bold white")
    text.append(f"{name.upper()}{dry}\n", style="bold cyan")
    text.append(f"  Safety rollback snapshot saved to: {backup_file}", style="dim")

    console.print(Panel(text, border_style="green", box=box.ROUNDED))
