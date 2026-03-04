# Work Time Tracker

A CLI punch-clock for tracking your daily and weekly work hours.

---

## Requirements

- Python 3.10 or higher
- pip

---

## First-Time Setup

Run these commands once:

```bash
git clone https://github.com/odaiameera/Data-Engineering-Learner-Space.git
cd "Data-Engineering-Learner-Space/Work Time Tracker"
pip install rich
```

> **Note:** The folder name has a space — the quotes around the path are required.

---

## Running the App

### Interactive mode (recommended)

```bash
cd "Data-Engineering-Learner-Space/Work Time Tracker"
python time_tracker.py
```

This opens a live prompt where you type commands directly.

### One-shot commands

```bash
python time_tracker.py punch in
python time_tracker.py punch out
python time_tracker.py status
python time_tracker.py daily
python time_tracker.py weekly
```

### Launch scripts (shortcuts)

**Mac / Linux** — run once to set up, then use `./run.sh` each time:

```bash
chmod +x run.sh
./run.sh
```

**Windows** — double-click `run.bat` or run from terminal:

```batch
run.bat
```

---

## Commands

| Command | What it does |
|---|---|
| `punch in` | Start work session |
| `punch out` | End work session |
| `punch in HH:MM` | Start session at a specific time |
| `punch out HH:MM` | End session at a specific time |
| `break 15` | Start a 15-minute break with timer alert |
| `break 30` | Start a 30-minute break with timer alert |
| `break end` | End current break |
| `status` | Show current punch/break state |
| `daily` | Full summary for today |
| `daily yesterday` | Full summary for yesterday |
| `weekly` | Weekly summary (39h target) |
| `log off` | Mark today as a day off |
| `log yesterday holiday` | Mark yesterday as a public holiday |
| `log 2024-03-04 sick Flu` | Mark a specific date as sick with a note |
| `help` | Show all commands |

---

## Data Storage

All data is saved automatically to `~/.time_tracker/data.json` — nothing is stored in the project folder.
