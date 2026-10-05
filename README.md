# Study Room Bot

Automates UCF LibCal **large study room** bookings from LibCal cookies, then posts check-in codes to Google Calendar via board Outlook.

Designed for an **always-on Mac mini** (launchd). The **member UI** lives on the chapter website (`academic board` → `/academic/study-rooms`); this repo is the API + booking workers.

- LaunchAgent morning window Fri–Tue → books **Mon–Fri** rooms, 3 days ahead
- Cap-10 rooms, **12:00pm–10:00pm**, rotating cookie accounts
- **No UCF passwords** — cookies only
- Patrons forward LibCal mail → board Outlook → calendar events with check-in codes

## Quick start

```bash
./setup.sh
./onboard.sh                              # service account, Outlook auth, schedule
./scripts/install-intake-launchd.sh       # API on :8790
```

In the **academic board** site:

```bash
# .env.local
STUDY_ROOM_INTAKE_URL=http://127.0.0.1:8790
npm run dev
```

Open http://localhost:3000/academic/study-rooms

## What runs in production

| Piece | Where |
|-------|--------|
| Member UI | Chapter site `/academic/study-rooms` (Vercel) |
| Intake API | Mac `:8790` — `./scripts/install-intake-launchd.sh` |
| Daily booking | `./install-launchd.sh` → `./run-bot.sh` |
| Check-in codes | `./scripts/install-outlook-scrape-launchd.sh` |
| Calendar | `config/service-account.json` + `STUDY_ROOMS_CALENDAR_ID` |

Vercel rewrites `/study-room-api/*` → Mac API (`STUDY_ROOM_INTAKE_URL`). For production, point that env at a Tailscale Funnel HTTPS URL so Vercel can reach the Mac.

## Commands

| Command | Purpose |
|---------|---------|
| `./start-intake.sh` | Intake API only (`:8790`) |
| `./start.sh` | Ops menu |
| `./onboard.sh` | First-time wizard |
| `./setup.sh` | venv + Playwright |
| `./import-cookies.sh` | CLI cookie import |
| `./remove-account.sh` | Delete account + cookies |
| `./run-bot.sh` | Scheduled/logged booking |
| `./run-bot.sh --now` | Book now (live terminal) |
| `./scrape-outlook.sh` | Board Outlook → Google Calendar |
| `./sign-in.sh <id>` | Refresh LibCal cookies if expired |
| `./install-launchd.sh` | Install booking schedule |
| `./uninstall-launchd.sh` | Remove booking schedule |
| `./scripts/install-intake-launchd.sh` | Keep API always on |
| `./scripts/install-outlook-scrape-launchd.sh` | Poll Outlook every 5 min |
| `./scripts/smoke-host.sh` | Health check |

## Layout

```
study_room_bot/
├── start-intake.sh / start.sh / onboard.sh / setup.sh
├── run-bot.sh / scrape-outlook.sh / import-cookies.sh …
├── api/          # FastAPI intake API (no UI)
├── bot/          # booking + Outlook scrape
├── shared/       # config, accounts, calendar auth
├── scripts/      # launchd helpers + smoke test
├── data/         # accounts, storage_states, profiles (runtime)
└── config/       # secrets (gitignored)
```

## Flow

1. Members open **chapter site → Study Rooms** and connect LibCal cookies
2. Launchd books rooms with those cookies
3. Brothers forward `alerts@mail.libcal.com` → board Outlook
4. Outlook scrape upserts check-in code/link on Google Calendar
