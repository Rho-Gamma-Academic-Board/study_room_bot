# Study Room Bot

Automates UCF LibCal **large study room** bookings, rotates across multiple UCF accounts, and adds events to Google Calendar.

Designed for **Linux / Raspberry Pi** (cron, headless). Also runs on macOS.

- Runs on a **randomized morning window** Fri–Tue via cron (books **Mon–Fri** rooms, 3 days ahead)
- Skips **Saturday and Sunday** study room dates
- Books **3 days ahead**
- Targets **12:00pm–10:00pm** on one **capacity-10** room (360H → 360F → other cap-10)
- Uses a **different account** per time block (12–4, 4–8, 8–10)

## Requirements

- **Linux** (Raspberry Pi 4/5 recommended, 4 GB+ RAM) or macOS
- **UCF account(s)** — `data/accounts/<nickname>.env` per person
- **Google Calendar OAuth** — `config/credentials.json` + `config/token.json`
- Pi **on during the morning run window** on run days (Fri, Sat, Sun, Mon, Tue) — typically ~7:25–8:35 AM
- **Browser + RDP/SSH** for `./add-account.sh` (enter SMS 2FA manually on Linux)

The curl installer automatically installs **git**, **Python 3**, **venv**, **Playwright**, and **Chromium** on Raspberry Pi OS / Debian. You may be prompted for your **sudo password** once during setup — no manual `apt install` needed.

## Quick start (GitHub → Pi)

One line, from a fresh Pi:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Rho-Gamma-Academic-Board/study_room_bot/main/install.sh)"
```

This clones to `~/study_room_bot`, runs setup, and opens the menu. Re-running it pulls the latest code instead of re-cloning. Override the target with `INSTALL_DIR=/opt/study_room_bot`.

Or clone it yourself:

```bash
git clone https://github.com/Rho-Gamma-Academic-Board/study_room_bot.git
cd study_room_bot
./start.sh
```

`./start.sh` shows the banner, offers first-time setup, then an interactive menu (accounts, cron, run bot, etc.).

**New install?** Run the guided wizard instead of doing each step manually:

```bash
./onboard.sh
```

Or run setup manually:

```bash
./setup.sh
```

Copy secrets onto the Pi (not in git):

| File | Purpose |
|------|---------|
| `config/ucf_credentials.env` | Calendar name, shared settings (`config/ucf_credentials.env.example`) |
| `config/credentials.json` | Google OAuth Desktop client (paste via `./import-google-credentials.sh`) |
| `data/accounts/<nickname>.env` | Per-person UCF login (`data/accounts/example.env`) |

Then:

```bash
./add-account.sh              # repeat per person (RDP + browser)
./venv/bin/python3 bot/auth_google_calendar.py
./install-cron.sh             # randomized morning window Fri–Tue (weekday rooms)
./run-bot.sh                  # test once
```

Access the Pi over **Tailscale** for RDP/SSH when adding accounts.

## One-liner scripts

| Script | What it does |
|--------|----------------|
| `install.sh` | One-line remote installer (clone + setup + menu) |
| `./start.sh` | Interactive menu (setup, accounts, cron, run bot) |
| `./onboard.sh` | Guided wizard — calendar, accounts, cron in one flow |
| `./setup.sh` | Create venv, install deps, install Chromium |
| `./import-google-credentials.sh` | Paste or import Google OAuth `credentials.json` |
| `./add-account.sh` | Create account + browser sign-in |
| `./sign-in.sh <id>` | Re-auth saved session |
| `./remove-account.sh <id>` | Remove account + profile |
| `./install-cron.sh` | Schedule randomized morning runs (Fri–Tue → Mon–Fri bookings) |
| `./uninstall-cron.sh` | Remove cron job |
| `./run-bot.sh` | Run bot once (headless, logs to file) |

## Project layout

```
study_room_bot/
├── start.sh              # interactive menu (main entry)
├── install.sh            # one-line remote installer
├── setup.sh              # venv + dependencies
├── add-account.sh        # shortcuts → scripts/
├── bot/                  # Python application
│   ├── study_room_bot.py
│   ├── auth_ucf_account.py
│   └── auth_google_calendar.py
├── shared/               # shared Python modules
├── scripts/              # shell scripts (called by root wrappers)
├── data/
│   ├── accounts/         # UCF logins (gitignored except example.env)
│   └── profiles/         # browser sessions (gitignored)
├── config/               # secrets + templates (real files gitignored)
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

## 2FA on Linux / Pi

iMessage auto-2FA is **macOS only**. On the Pi:

1. RDP in with a desktop session
2. Run `./add-account.sh` (browser opens visibly — do **not** set `RUN_HEADLESS`)
3. Enter the SMS code in the browser or type it in the terminal when prompted

Scheduled `./run-bot.sh` runs headless and relies on **saved cookies**. Re-run `./sign-in.sh <id>` if a session expires.

## How booking works

1. **Discover** — find a cap-10 room with full (or best) 12pm–10pm availability (360H first)
2. **Book** — three slots on that room, rotating accounts
3. **Calendar** — events on **Academic Board - Study Rooms**

**3 accounts** needed for full 12pm–10pm coverage per day.

## What not to commit

Git ignores: `venv/`, `data/accounts/*.env`, `data/profiles/`, `config/ucf_credentials.env`, `config/cron.env`, `config/credentials.json`, `config/token.json`, `logs/`

## Cron schedule

`./install-cron.sh` picks a random cron minute (7:25–7:44 AM) and adds up to 50 minutes of extra delay when the job runs, so bookings don't always fire at exactly 8:00 AM. Re-run `./install-cron.sh` to reshuffle. Manual `./run-bot.sh` runs immediately with no delay.

## macOS (optional)

Same scripts work on Mac. Set `USE_IMESSAGE_2FA=1` to auto-read SMS from iMessage during sign-in. Use `./install-cron.sh` or run manually.
