"""
Interactive live TUI dashboard for Audeze Maxwell 2.
Allows instant real-time preset switching, volume/mix adjustment, and live telemetry.
"""

import sys
import tty
import termios
import select
import time
from typing import Optional
from maxwell2.client import MaxwellClient
from maxwell2.protocol import PRESET_NAMES

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.align import Align
    from rich.layout import Layout
    from rich.live import Live
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class KeyReader:
    """Reads single keystrokes non-blocking on POSIX terminals."""

    def __enter__(self):
        self.old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, type, value, traceback):
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)

    def get_key(self, timeout_sec: float = 0.1) -> Optional[str]:
        r, _, _ = select.select([sys.stdin], [], [], timeout_sec)
        if r:
            return sys.stdin.read(1)
        return None


def run_interactive_dashboard(client: MaxwellClient):
    """Runs a real-time interactive terminal console dashboard."""
    if not RICH_AVAILABLE:
        print("Rich terminal library is required for interactive mode.")
        return

    console = Console()
    console.clear()

    status = client.get_status()
    message = "[bold green]Connected and ready. Press [cyan]1-0[/cyan] to switch presets, [cyan]q[/cyan] to exit.[/bold green]"

    with KeyReader() as reader:
        running = True
        while running:
            # Build TUI display
            console.clear()
            console.print(Align.center("[bold cyan]AUDEZE MAXWELL 2  •  INTERACTIVE CONTROL CONSOLE[/bold cyan]"))
            console.print()

            # Active Preset Highlight
            preset = status.get("preset", {})
            p_name = preset.get("name", "Unknown")
            p_idx = preset.get("index", 1)

            # Presets Grid Table
            p_table = Table(box=box.ROUNDED, expand=True, title="[bold white]PRESET MATRIX[/bold white]", border_style="cyan")
            p_table.add_column("Key", justify="center", style="bold yellow", width=6)
            p_table.add_column("Preset Name", style="white")
            p_table.add_column("State", justify="center", width=16)

            for i, name in enumerate(PRESET_NAMES, 1):
                key_label = "0" if i == 10 else str(i)
                if i == p_idx:
                    state_str = "[bold white on magenta] ▶ ACTIVE ◀ [/]"
                    name_str = f"[bold green]{name}[/]"
                else:
                    state_str = "[dim]·[/dim]"
                    name_str = name
                p_table.add_row(f"[{key_label}]", name_str, state_str)

            # Status Summary Table
            s_table = Table(box=box.ROUNDED, expand=True, title="[bold white]HARDWARE TELEMETRY[/bold white]", border_style="blue")
            s_table.add_column("Item", style="bold cyan", width=18)
            s_table.add_column("Value")

            # Battery
            batt = status.get("battery_percent")
            batt_bar = f"{batt}%" if batt is not None else "Unknown"
            s_table.add_row("Battery", f"[bold green]{batt_bar}[/]")

            # Mic
            mute = status.get("mic_muted")
            mic_str = "[bold red]MUTED[/]" if mute else "[bold green]UNMUTED / LIVE[/]"
            s_table.add_row("Microphone", mic_str)

            # Sidetone
            st = status.get("sidetone", {})
            st_on = "ON" if st.get("enabled") else "OFF"
            s_table.add_row("Sidetone", f"[bold]{st_on}[/] (Level {st.get('level', 0)}/{st.get('max_level', 31)})")

            # Game/Chat
            cm = status.get("chat_mix", {})
            s_table.add_row("Chat Mix", f"Game {cm.get('game_pct', 50)}% | Chat {cm.get('chat_pct', 50)}%")

            # Firmware
            fw = status.get("firmware", {}).get("firmware", "Unknown")
            s_table.add_row("Firmware", fw)

            # Print tables side by side or stacked
            console.print(p_table)
            console.print(s_table)
            console.print(Panel(message, title="Status Log", border_style="green", box=box.ROUNDED))
            console.print(
                "[bold white]Hotkeys:[/] [cyan]1-6[/] Factory Presets • [cyan]7-0[/] Custom Presets • "
                "[cyan]s[/] Toggle Sidetone • [cyan]r[/] Refresh • [cyan]q[/] Exit"
            )

            # Wait for keystroke
            key = reader.get_key(timeout_sec=1.0)
            if key:
                key = key.lower()
                if key in ('q', '\x1b'):  # 'q' or Esc
                    running = False
                    break
                elif key in ('1', '2', '3', '4', '5', '6', '7', '8', '9', '0'):
                    target_idx = 10 if key == '0' else int(key)
                    target_name = PRESET_NAMES[target_idx - 1]
                    message = f"[yellow]Switching to [{target_idx}] {target_name}...[/yellow]"
                    console.print(message)
                    try:
                        res = client.set_preset(target_idx)
                        status["preset"] = res["preset"]
                        message = f"[bold green]✔ Activated preset: [{target_idx}] {target_name}[/bold green]"
                    except Exception as e:
                        message = f"[bold red]Failed to switch preset: {e}[/bold red]"
                elif key == 's':
                    curr_st = status.get("sidetone", {}).get("enabled", False)
                    new_st = not curr_st
                    try:
                        res = client.set_sidetone(enabled=new_st)
                        status["sidetone"]["enabled"] = new_st
                        message = f"[bold green]Sidetone toggled {'ON' if new_st else 'OFF'}.[/bold green]"
                    except Exception as e:
                        message = f"[bold red]Failed to toggle sidetone: {e}[/bold red]"
                elif key == 'r':
                    try:
                        status = client.get_status()
                        message = "[bold green]Status refreshed from device.[/bold green]"
                    except Exception as e:
                        message = f"[bold red]Refresh failed: {e}[/bold red]"

    console.clear()
    console.print("[bold cyan]Exited Maxwell 2 Interactive Dashboard.[/bold cyan]")
