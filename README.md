# Study Room Bot

Automates UCF LibCal **large study room** bookings, rotates across multiple UCF accounts, and adds events to Google Calendar.

Designed for an **always-on Mac mini** using **launchd** for scheduling.

- Runs on a **randomized morning window** Fri–Tue via LaunchAgent (books **Mon–Fri** rooms, 3 days ahead)
- Skips **Saturday and Sunday** study room dates
- Books **3 days ahead**
- Targets **12:00pm–10:00pm** on **capacity-10** rooms (360H → 360F → other cap-10), falling back across rooms when one room cannot cover the full day
- Uses a **different account** per time block (12–4, 4–8, 8–10)
- **iMessage 2FA** — reads UCF SMS codes automatically during sign-in

## Requirements

- **macOS** on an always-on Mac mini (or MacBook)
- **UCF account(s)** — `data/accounts/<nickname>.env` per person
- **Google Calendar OAuth** — `config/credentials.json` + `config/token.json`

The curl installer sets up **git**, **Python 3**, **Playwright**, and **Chromium** automatically (Homebrew used when needed).

## Quick start

One line on a fresh Mac:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Rho-Gamma-Academic-Board/study_room_bot/main/install.sh)"
```

This clones to `~/study_room_bot`, runs setup, and opens the setup wizard. Re-running pulls the latest code. Override the install path with `INSTALL_DIR=~/path`.

Or clone manually:

```bash
git clone https://github.com/Rho-Gamma-Academic-Board/study_room_bot.git
cd study_room_bot
./start.sh
```

`./start.sh` shows the banner, offers first-time setup, then an interactive menu.

**New install?** Run the guided wizard:

```bash
./onboard.sh
```

The wizard walks you through:
1. Pasting Google OAuth JSON into the terminal
2. Calendar settings + Google sign-in
3. Adding UCF accounts (browser + iMessage 2FA)
4. Installing the LaunchAgent schedule

## Scripts

| Script | What it does |
|--------|----------------|
| `install.sh` | One-line remote installer (macOS only) |
| `./start.sh` | Interactive menu |
| `./onboard.sh` | Guided wizard — calendar, accounts, schedule |
| `./setup.sh` | Create venv, install deps, install Chromium |
| `./import-google-credentials.sh` | Paste or import Google OAuth `credentials.json` |
| `./add-account.sh` | Create account + browser sign-in |
| `./sign-in.sh <id>` | Re-auth saved session |
| `./remove-account.sh <id>` | Remove account + profile |
| `./install-launchd.sh` | Install LaunchAgent (Fri–Tue → Mon–Fri bookings) |
| `./uninstall-launchd.sh` | Remove LaunchAgent |
| `./run-bot.sh` | Run bot once (headless, logs to file) |

## Project layout

```
study_room_bot/
├── start.sh              # interactive menu (main entry)
├── install.sh            # one-line remote installer
├── setup.sh              # venv + dependencies
├── install-launchd.sh    # schedule auto-booking
├── bot/                  # Python application
├── shared/               # shared Python modules
├── scripts/              # shell scripts
├── data/
│   ├── accounts/         # UCF logins (gitignored)
│   └── profiles/         # browser sessions (gitignored)
├── config/               # secrets + templates (gitignored)
└── logs/                 # run output (gitignored)
```

## Manual run

```bash
RUN_HEADLESS=1 ./venv/bin/python3 bot/study_room_bot.py
```

Force one account:

```bash
ACCOUNT_ID=josh RUN_HEADLESS=1 ./venv/bin/python3 bot/study_room_bot.py
```

Logs: `logs/study_room_bot.log`, `logs/study_room_bot_error.log`

## 2FA

UCF SMS codes are read automatically from **iMessage** during `./add-account.sh` and `./sign-in.sh`.

Grant **Full Disk Access** to Terminal (or iTerm) in **System Settings → Privacy & Security** if 2FA polling fails.

Scheduled `./run-bot.sh` runs headless and relies on **saved cookies**. Re-run `./sign-in.sh <id>` if a session expires.

## How booking works

1. **Discover** — prefer one cap-10 room for full 12pm–10pm (360H/360F first); if only part of the day is open, fill remaining windows on other large rooms. End times shorten to LibCal’s library-hours dropdown when the ideal block isn’t offered (e.g. Friday 4pm→7pm instead of 4–8).
2. **Book** — each planned window, rotating accounts
3. **Calendar** — events on your shared study rooms calendar

**3 accounts** needed for full 12pm–10pm coverage per day.

## What not to commit

Git ignores: `venv/`, `data/accounts/*.env`, `data/profiles/`, `config/ucf_credentials.env`, `config/schedule.env`, `config/credentials.json`, `config/token.json`, `logs/`

## Schedule

`./install-launchd.sh` installs a LaunchAgent that fires between **7:25–7:44 AM** on Fri–Tue, then adds up to **50 minutes** of random delay before booking. Re-run to reshuffle. Manual `./run-bot.sh` runs immediately with no delay.

Plist location: `~/Library/LaunchAgents/com.otstudyrooms.bot.plist`

Check status: `launchctl print gui/$(id -u)/com.otstudyrooms.bot`
