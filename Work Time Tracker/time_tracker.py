#!/usr/bin/env python3
"""
Work Time Tracker
─────────────────
Track daily/weekly work hours with break reminders.
Data is stored in ~/.time_tracker/data.json

Features
--------
• Punch in / punch out (with optional time override)
• 15 / 30-minute break timers with real-time alerts
• Daily summary  (punches, breaks, totals)
• Weekly summary (39-hour target + progress bars)
• Log days as: work | off | weekend | holiday | sick
• Interactive REPL or one-shot CLI mode
"""

import json
import sys
import threading
from datetime import datetime, date, timedelta
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.prompt import Prompt

console = Console()

# ── Config ────────────────────────────────────────────────────────────────────
WEEKLY_TARGET_HOURS = 39.0
DATA_DIR = Path.home() / ".time_tracker"
DATA_FILE = DATA_DIR / "data.json"
BREAK_WARN_MINS = 2          # warn this many minutes before break expires

DAY_TYPES = {
    "work":    "💼  Work",
    "off":     "🏖️   Day Off",
    "weekend": "🎉  Weekend",
    "holiday": "🎊  Public Holiday",
    "sick":    "🤒  Sick Day",
}

# ── Data layer ────────────────────────────────────────────────────────────────

def load_data() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {"days": {}}


def save_data(data: dict) -> None:
    DATA_FILE.write_text(json.dumps(data, indent=2))


def get_day(data: dict, d: date | None = None) -> dict:
    key = (d or date.today()).isoformat()
    if key not in data["days"]:
        data["days"][key] = {
            "status": "work",
            "punches": [],
            "breaks": [],
            "notes": "",
        }
    return data["days"][key]


# ── Calculation helpers ───────────────────────────────────────────────────────

def work_seconds(day: dict, d: date | None = None) -> float:
    """Total work seconds for a day. Open sessions are counted up to now (today only)."""
    d = d or date.today()
    total = 0.0
    pending = None
    for p in day.get("punches", []):
        t = datetime.combine(d, datetime.strptime(p["time"], "%H:%M:%S").time())
        if p["type"] == "in":
            pending = t
        elif p["type"] == "out" and pending is not None:
            total += (t - pending).total_seconds()
            pending = None
    if pending is not None and d == date.today():
        total += (datetime.now() - pending).total_seconds()
    return total


def break_seconds(day: dict, d: date | None = None) -> float:
    """Total break seconds for a day. Active break counted up to now (today only)."""
    d = d or date.today()
    total = 0.0
    for b in day.get("breaks", []):
        start = datetime.combine(d, datetime.strptime(b["start"], "%H:%M:%S").time())
        if b.get("end"):
            end = datetime.combine(d, datetime.strptime(b["end"], "%H:%M:%S").time())
            total += (end - start).total_seconds()
        elif d == date.today():
            total += (datetime.now() - start).total_seconds()
    return total


def active_break(day: dict) -> dict | None:
    """Return the currently open break, or None."""
    for b in day.get("breaks", []):
        if not b.get("end"):
            return b
    return None


def is_punched_in(day: dict) -> bool:
    punches = day.get("punches", [])
    return bool(punches) and punches[-1]["type"] == "in"


# ── Formatting helpers ────────────────────────────────────────────────────────

def fmt(seconds: float) -> str:
    """Convert seconds → 'Xh YYm' or 'Ym ZZs'."""
    seconds = max(0.0, seconds)
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def progress_bar(pct: float, width: int = 20) -> str:
    filled = int(min(pct, 100) / 100 * width)
    color = "green" if pct >= 100 else "yellow" if pct >= 60 else "red"
    return f"[{color}]{'█' * filled}{'░' * (width - filled)}[/]"


def parse_date(s: str) -> date:
    if s == "today":
        return date.today()
    if s == "yesterday":
        return date.today() - timedelta(days=1)
    return date.fromisoformat(s)   # raises ValueError for bad formats


def parse_time(s: str) -> str:
    """Validate and normalise a time string to HH:MM:SS."""
    for fmt_str in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt_str).strftime("%H:%M:%S")
        except ValueError:
            pass
    raise ValueError(f"Invalid time '{s}'. Use HH:MM or HH:MM:SS.")


# ── Break timer (background thread for interactive mode) ──────────────────────

_break_stop = threading.Event()
_break_thread: threading.Thread | None = None


def _start_break_timer(planned_mins: int) -> None:
    global _break_thread
    _stop_break_timer()
    _break_stop.clear()
    warn_after = max(0, (planned_mins - BREAK_WARN_MINS) * 60)
    overtime_after = planned_mins * 60

    def _run():
        # ── first checkpoint: warn N minutes before expiry ──────────────────
        if not _break_stop.wait(warn_after):
            console.print(
                f"\n[bold yellow]⚡  BREAK ALERT — only {BREAK_WARN_MINS} min left![/]\n"
            )
        # ── second checkpoint: break is now over ─────────────────────────────
        remaining = overtime_after - warn_after
        if not _break_stop.wait(remaining):
            console.print(
                "\n[bold red]🚨  BREAK OVER — time to get back to work![/]\n"
            )

    _break_thread = threading.Thread(target=_run, daemon=True, name="break-timer")
    _break_thread.start()


def _stop_break_timer() -> None:
    _break_stop.set()


def check_break_overrun(day: dict) -> None:
    """Print a warning if an active break is running overtime or nearly over."""
    ab = active_break(day)
    if not ab:
        return
    start = datetime.combine(
        date.today(), datetime.strptime(ab["start"], "%H:%M:%S").time()
    )
    elapsed_m = (datetime.now() - start).total_seconds() / 60
    planned_m = ab.get("planned_mins", 0)
    over = elapsed_m - planned_m
    if over > 0:
        console.print(
            f"[bold red]⚠️   You are {over:.1f} min over your {planned_m}-min break![/]"
        )
    elif planned_m - elapsed_m <= BREAK_WARN_MINS:
        console.print(
            f"[bold yellow]⚡  Break ending in {planned_m - elapsed_m:.1f} min![/]"
        )


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_punch(data: dict, direction: str, time_str: str | None = None) -> None:
    day = get_day(data)
    try:
        now = parse_time(time_str) if time_str else datetime.now().strftime("%H:%M:%S")
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        return

    if direction == "in":
        # Auto-close any active break
        ab = active_break(day)
        if ab:
            ab["end"] = now
            _stop_break_timer()
            console.print("[yellow]Active break ended automatically.[/]")

        if is_punched_in(day):
            console.print("[red]Already punched in! Punch out first.[/]")
            return

        day["punches"].append({"type": "in", "time": now})
        save_data(data)
        console.print(
            Panel(f"[bold green]✅  Punched IN at {now}[/]", border_style="green")
        )

    elif direction == "out":
        # Auto-close any active break
        ab = active_break(day)
        if ab:
            ab["end"] = now
            _stop_break_timer()
            console.print("[yellow]Active break ended automatically.[/]")

        if not is_punched_in(day):
            console.print("[red]Not punched in! Punch in first.[/]")
            return

        day["punches"].append({"type": "out", "time": now})
        total = work_seconds(day)
        save_data(data)
        console.print(
            Panel(
                f"[bold red]🚪  Punched OUT at {now}\n"
                f"Work today so far: {fmt(total)}[/]",
                border_style="red",
            )
        )


def cmd_break_start(data: dict, planned_mins: int) -> None:
    day = get_day(data)
    if active_break(day):
        console.print("[red]A break is already active. End it first.[/]")
        return

    now = datetime.now().strftime("%H:%M:%S")
    day["breaks"].append({"start": now, "end": None, "planned_mins": planned_mins})
    save_data(data)

    alert_in = planned_mins - BREAK_WARN_MINS
    console.print(
        Panel(
            f"[bold yellow]☕  Break started at {now}\n"
            f"Planned: {planned_mins} min  |  Alert in {alert_in} min[/]",
            border_style="yellow",
        )
    )
    _start_break_timer(planned_mins)   # real-time alert in interactive mode


def cmd_break_end(data: dict) -> None:
    day = get_day(data)
    ab = active_break(day)
    if not ab:
        console.print("[red]No active break to end.[/]")
        return

    _stop_break_timer()
    now = datetime.now().strftime("%H:%M:%S")
    ab["end"] = now

    d = date.today()
    start = datetime.combine(d, datetime.strptime(ab["start"], "%H:%M:%S").time())
    end = datetime.combine(d, datetime.strptime(now, "%H:%M:%S").time())
    actual_m = (end - start).total_seconds() / 60
    planned_m = ab.get("planned_mins", 0)
    over = actual_m - planned_m
    result = (
        f"[red]+{over:.1f}m overtime ⚠️[/]" if over > 0 else "[green]On time ✅[/]"
    )

    save_data(data)
    console.print(
        Panel(
            f"[bold cyan]🔔  Break ended at {now}\n"
            f"Actual: {actual_m:.1f}m  /  Planned: {planned_m}m  →  {result}[/]",
            border_style="cyan",
        )
    )


def cmd_status(data: dict) -> None:
    day = get_day(data)
    check_break_overrun(day)

    ab = active_break(day)
    punched = is_punched_in(day)

    if ab:
        start = datetime.combine(
            date.today(), datetime.strptime(ab["start"], "%H:%M:%S").time()
        )
        elapsed_m = (datetime.now() - start).total_seconds() / 60
        state = f"☕  ON BREAK ({elapsed_m:.0f}/{ab.get('planned_mins','?')} min)"
        colour = "yellow"
    elif punched:
        state = "🟢  PUNCHED IN"
        colour = "green"
    else:
        state = "🔴  PUNCHED OUT"
        colour = "red"

    ws = work_seconds(day)
    bs = break_seconds(day)
    day_type = DAY_TYPES.get(day.get("status", "work"), day.get("status", "work"))

    console.print(
        Panel(
            f"[{colour}]{state}[/]\n"
            f"Day type : {day_type}\n"
            f"Work     : [bold green]{fmt(ws)}[/]   "
            f"Breaks: [bold yellow]{fmt(bs)}[/]",
            title=f"📊  {date.today().strftime('%A, %B %d %Y')}",
            border_style="cyan",
        )
    )


def cmd_daily(data: dict, d: date | None = None) -> None:
    d = d or date.today()
    if d == date.today():
        check_break_overrun(get_day(data))

    key = d.isoformat()
    day = data["days"].get(key)
    if not day:
        console.print(f"[yellow]No data recorded for {key}.[/]")
        return

    # ── Punches table ─────────────────────────────────────────────────────────
    ptable = Table(
        title=f"⏰  Punches — {d.strftime('%A, %B %d %Y')}", box=box.ROUNDED
    )
    ptable.add_column("#", style="dim", width=4)
    ptable.add_column("Type", style="bold", width=9)
    ptable.add_column("Time")
    ptable.add_column("Session", justify="right")

    prev_in = None
    for i, p in enumerate(day.get("punches", []), 1):
        colour = "green" if p["type"] == "in" else "red"
        label = "→ IN" if p["type"] == "in" else "← OUT"
        t = datetime.combine(d, datetime.strptime(p["time"], "%H:%M:%S").time())
        session_dur = ""
        if p["type"] == "in":
            prev_in = t
        elif p["type"] == "out" and prev_in:
            session_dur = fmt((t - prev_in).total_seconds())
            prev_in = None
        ptable.add_row(str(i), f"[{colour}]{label}[/]", p["time"], session_dur)

    console.print(ptable)

    # ── Breaks table ──────────────────────────────────────────────────────────
    breaks = day.get("breaks", [])
    if breaks:
        btable = Table(title="☕  Breaks", box=box.ROUNDED)
        btable.add_column("Start")
        btable.add_column("End")
        btable.add_column("Planned", justify="right")
        btable.add_column("Actual", justify="right")
        btable.add_column("Status")

        for b in breaks:
            start = datetime.combine(
                d, datetime.strptime(b["start"], "%H:%M:%S").time()
            )
            planned_m = b.get("planned_mins", 0)
            if b.get("end"):
                end = datetime.combine(
                    d, datetime.strptime(b["end"], "%H:%M:%S").time()
                )
                actual_m = (end - start).total_seconds() / 60
                over = actual_m - planned_m
                status_str = (
                    "[green]✅[/]"
                    if over <= 0
                    else f"[red]⚠️  +{over:.1f}m[/]"
                )
                btable.add_row(
                    b["start"], b["end"],
                    f"{planned_m}m", f"{actual_m:.1f}m", status_str
                )
            else:
                elapsed_m = (datetime.now() - start).total_seconds() / 60
                btable.add_row(
                    b["start"], "—",
                    f"{planned_m}m", f"[yellow]{elapsed_m:.1f}m[/]",
                    "[yellow]active[/]"
                )

        console.print(btable)

    # ── Daily summary ─────────────────────────────────────────────────────────
    ws = work_seconds(day, d)
    bs = break_seconds(day, d)
    notes = day.get("notes", "")
    day_type = DAY_TYPES.get(day.get("status", "work"), day.get("status", ""))

    console.print(
        Panel(
            f"Type   : {day_type}\n"
            f"Work   : [bold green]{fmt(ws)}[/]   "
            f"Breaks : [bold yellow]{fmt(bs)}[/]"
            + (f"\nNotes  : {notes}" if notes else ""),
            title="📋  Daily Summary",
            border_style="green",
        )
    )


def cmd_weekly(data: dict, ref: date | None = None) -> None:
    d = ref or date.today()
    if d == date.today():
        check_break_overrun(get_day(data))

    monday = d - timedelta(days=d.weekday())
    week_days = [monday + timedelta(i) for i in range(7)]

    # Daily target based on a 5-day working week
    target_daily_secs = (WEEKLY_TARGET_HOURS / 5) * 3600

    table = Table(
        title=(
            f"📅  Week {d.isocalendar()[1]} — "
            f"{monday.strftime('%B %d')} to "
            f"{(monday + timedelta(6)).strftime('%B %d, %Y')}"
        ),
        box=box.ROUNDED,
    )
    table.add_column("Day", style="bold")
    table.add_column("Date", width=8)
    table.add_column("Type")
    table.add_column("Work", justify="right")
    table.add_column("Breaks", justify="right")
    table.add_column("Progress", width=22)

    total_work = 0.0

    for wd in week_days:
        key = wd.isoformat()
        day_d = data["days"].get(key, {})
        default_status = "weekend" if wd.weekday() >= 5 else "work"
        status = day_d.get("status", default_status)

        ws = work_seconds(day_d, wd) if day_d else 0.0
        bs = break_seconds(day_d, wd) if day_d else 0.0
        total_work += ws

        is_today = wd == date.today()
        is_future = wd > date.today()

        day_label = wd.strftime("%A")
        if is_today:
            day_label = f"[bold cyan]► {day_label}[/]"

        icon = {
            "work": "💼", "off": "🏖️", "weekend": "🎉",
            "holiday": "🎊", "sick": "🤒",
        }.get(status, "❓")

        if is_future:
            table.add_row(day_label, wd.strftime("%d/%m"), icon, "—", "—", "")
        else:
            pct = ws / target_daily_secs * 100 if target_daily_secs else 0
            w_colour = "green" if ws >= target_daily_secs else "yellow"
            table.add_row(
                day_label,
                wd.strftime("%d/%m"),
                f"{icon} {status}",
                f"[{w_colour}]{fmt(ws)}[/]",
                fmt(bs) if bs else "—",
                progress_bar(pct, 16),
            )

    console.print(table)

    # ── Weekly summary ────────────────────────────────────────────────────────
    weekly_target_secs = WEEKLY_TARGET_HOURS * 3600
    remaining = weekly_target_secs - total_work
    pct = total_work / weekly_target_secs * 100
    colour = "green" if pct >= 100 else "yellow"

    console.print(
        Panel(
            f"Total    : [{colour}]{fmt(total_work)}[/]  /  {WEEKLY_TARGET_HOURS}h target\n"
            + (
                "Status   : [bold green]✅  Weekly target reached![/]"
                if remaining <= 0
                else f"Remaining: [bold]{fmt(remaining)}[/]"
            )
            + f"\nProgress : {progress_bar(pct, 28)} {pct:.1f}%",
            title="📊  Weekly Summary",
            border_style="blue",
        )
    )


def cmd_log(
    data: dict, target: date, status: str, note: str = ""
) -> None:
    if status not in DAY_TYPES:
        console.print(
            f"[red]Unknown status '{status}'. "
            f"Choose from: {', '.join(DAY_TYPES.keys())}[/]"
        )
        return

    day = get_day(data, target)
    day["status"] = status
    if note:
        day["notes"] = note
    save_data(data)

    console.print(
        Panel(
            f"[bold]{target.isoformat()}[/] → {DAY_TYPES[status]}"
            + (f"\nNote: {note}" if note else ""),
            border_style="blue",
        )
    )


def cmd_help() -> None:
    t = Table(title="📖  Work Time Tracker — Commands", box=box.ROUNDED)
    t.add_column("Command", style="bold cyan", min_width=30)
    t.add_column("Description")

    rows = [
        ("punch in",                   "Punch in now (start work)"),
        ("punch in HH:MM",             "Punch in at a specific time"),
        ("punch out",                  "Punch out now (end work)"),
        ("punch out HH:MM",            "Punch out at a specific time"),
        ("",                           ""),
        ("break 15",                   "Start a 15-minute break (timer + alerts)"),
        ("break 30",                   "Start a 30-minute break (timer + alerts)"),
        ("break <N>",                  "Start a custom N-minute break"),
        ("break end",                  "End the current break"),
        ("",                           ""),
        ("status",                     "Show current punch/break status"),
        ("daily",                      "Show today's full summary"),
        ("daily yesterday",            "Show yesterday's summary"),
        ("daily YYYY-MM-DD",           "Show any day's summary"),
        ("weekly",                     "Show this week (39h target)"),
        ("",                           ""),
        ("log off",                    "Mark today as day off"),
        ("log weekend",                "Mark today as weekend"),
        ("log holiday",                "Mark today as public holiday"),
        ("log sick",                   "Mark today as sick day"),
        ("log work",                   "Reset today to a working day"),
        ("log yesterday off",          "Mark yesterday as day off"),
        ("log YYYY-MM-DD holiday",     "Mark any date as public holiday"),
        ("log YYYY-MM-DD off Note…",   "Mark a date with an optional note"),
        ("",                           ""),
        ("help",                       "Show this help"),
        ("quit / exit",                "Exit the tracker"),
    ]
    for cmd_str, desc in rows:
        if not cmd_str and not desc:
            t.add_row("", "")
        else:
            t.add_row(cmd_str, desc)

    console.print(t)


# ── Command dispatcher ────────────────────────────────────────────────────────

def dispatch(data: dict, args: list[str]) -> None:
    if not args:
        cmd_status(data)
        return

    cmd = args[0].lower()

    # ── punch ─────────────────────────────────────────────────────────────────
    if cmd == "punch":
        direction = args[1].lower() if len(args) > 1 else ""
        if direction not in ("in", "out"):
            console.print("[red]Usage: punch in|out [HH:MM][/]")
            return
        time_str = args[2] if len(args) > 2 else None
        cmd_punch(data, direction, time_str)

    # ── break ─────────────────────────────────────────────────────────────────
    elif cmd == "break":
        action = args[1].lower() if len(args) > 1 else ""
        if action == "end":
            cmd_break_end(data)
        elif action.isdigit():
            cmd_break_start(data, int(action))
        else:
            console.print("[red]Usage: break 15|30|<mins>|end[/]")

    # ── status ────────────────────────────────────────────────────────────────
    elif cmd == "status":
        cmd_status(data)

    # ── daily ─────────────────────────────────────────────────────────────────
    elif cmd == "daily":
        d = None
        if len(args) > 1:
            try:
                d = parse_date(args[1])
            except ValueError:
                console.print(f"[red]Invalid date '{args[1]}'. Use YYYY-MM-DD, today, or yesterday.[/]")
                return
        cmd_daily(data, d)

    # ── weekly ────────────────────────────────────────────────────────────────
    elif cmd == "weekly":
        cmd_weekly(data)

    # ── log ───────────────────────────────────────────────────────────────────
    elif cmd == "log":
        if len(args) < 2:
            console.print("[red]Usage: log [date] <status> [note…][/]")
            return

        idx = 1
        target = date.today()

        # Optional date argument
        try:
            target = parse_date(args[idx])
            idx += 1
        except (ValueError, IndexError):
            pass   # no date provided — use today

        if idx >= len(args):
            console.print("[red]Missing status. Use: work | off | weekend | holiday | sick[/]")
            return

        status = args[idx].lower()
        note = " ".join(args[idx + 1:]) if idx + 1 < len(args) else ""
        cmd_log(data, target, status, note)

    # ── help ──────────────────────────────────────────────────────────────────
    elif cmd in ("help", "?", "h"):
        cmd_help()

    # ── quit ──────────────────────────────────────────────────────────────────
    elif cmd in ("quit", "exit", "q"):
        console.print("[bold]Goodbye! 👋[/]")
        sys.exit(0)

    else:
        console.print(
            f"[red]Unknown command '{cmd}'. Type 'help' for available commands.[/]"
        )


# ── Entry points ──────────────────────────────────────────────────────────────

def interactive(data: dict) -> None:
    console.print(
        Panel(
            "[bold cyan]Work Time Tracker[/]\n"
            f"[dim]Weekly target: {WEEKLY_TARGET_HOURS}h  |  "
            "Break alerts: 15 & 30 min  |  Type 'help' for commands[/]",
            border_style="cyan",
        )
    )
    cmd_status(data)

    while True:
        try:
            raw = Prompt.ask("\n[bold cyan]>[/]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[bold]Goodbye! 👋[/]")
            break

        if not raw:
            continue

        dispatch(data, raw.split())


def main() -> None:
    data = load_data()
    if len(sys.argv) > 1:
        # One-shot CLI mode: python time_tracker.py punch in
        dispatch(data, sys.argv[1:])
    else:
        # Interactive REPL
        interactive(data)


if __name__ == "__main__":
    main()
