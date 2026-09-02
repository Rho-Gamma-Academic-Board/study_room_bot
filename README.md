# Study Room Bot

Automates UCF LibCal **large study room** bookings, rotates across multiple UCF accounts, and adds events to Google Calendar.

Designed for **Linux / Raspberry Pi** (cron, headless). Also runs on macOS.

- Runs **8:00 AM Fri–Tue** via cron (books **Mon–Fri** rooms, 3 days ahead)
- Skips **Saturday and Sunday** study room dates
- Books **3 days ahead**
- Targets **12:00pm–10:00pm** on one **capacity-10** room (360H → 360F → other cap-10)
- Uses a **different account** per time block (12–4, 4–8, 8–10)

## Requirements

- **Linux** (Raspberry Pi 4/5 recommended, 4 GB+ RAM) or macOS
- **Python 3.10+** and `python3-venv`
- **Playwright** + Chromium
- **UCF account(s)** — `accounts/<name>.env` per person
- **Google Calendar OAuth** — `credentials.json` + `token.json`
- Pi **on at 8:00 AM** on run days (Fri, Sat, Sun, Mon, Tue)
- **Browser + RDP/SSH** for `./add-account.sh` (enter SMS 2FA manually on Linux)

### Raspberry Pi OS packages

```bash
sudo apt update
sudo apt install python3 python3-venv git
```

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

Or run setup manually:

```bash
./setup.sh
sudo ./venv/bin/playwright install-deps chromium
```

Copy secrets onto the Pi (not in git):

| File | Purpose |
|------|---------|
| `ucf_credentials.env` | Calendar name, shared settings (`ucf_credentials.env.example`) |
| `credentials.json` | Google OAuth Desktop client |
| `accounts/<name>.env` | Per-person UCF login (`accounts/example.env`) |

Then:

```bash
./add-account.sh              # repeat per person (RDP + browser)
./venv/bin/python3 auth_google_calendar.py
./install-cron.sh             # 8 AM Fri–Tue (weekday rooms)
./run-bot.sh                  # test once
```

Access the Pi over **Tailscale** for RDP/SSH when adding accounts.

## One-liner scripts

| Script | What it does |
|--------|----------------|
| `install.sh` | One-line remote installer (clone + setup + menu) |
| `./start.sh` | Interactive menu (setup, accounts, cron, run bot) |
| `./setup.sh` | Create venv, install deps, install Chromium |
| `./add-account.sh` | Create account + browser sign-in |
| `./sign-in.sh <id>` | Re-auth saved session |
| `./remove-account.sh <id>` | Remove account + profile |
| `./install-cron.sh` | Schedule 8 AM runs (Fri–Tue → Mon–Fri bookings) |
| `./uninstall-cron.sh` | Remove cron job |
| `./run-bot.sh` | Run bot once (headless, logs to file) |

## Manual run

```bash
RUN_HEADLESS=1 ./venv/bin/python3 study_room_bot.py
```

Force one account:

```bash
ACCOUNT_ID=josh RUN_HEADLESS=1 ./venv/bin/python3 study_room_bot.py
```

Logs: `study_room_bot.log`, `study_room_bot_error.log`

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

Git ignores: `venv/`, `accounts/*.env`, `playwright-profiles/`, `ucf_credentials.env`, `credentials.json`, `token.json`, `*.log`

## macOS (optional)

Same scripts work on Mac. Set `USE_IMESSAGE_2FA=1` to auto-read SMS from iMessage during sign-in. Use `./install-cron.sh` or run manually.
