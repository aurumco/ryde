# Ryde: Discord To Telegram Monitor

- DMs to your Discord are forwarded to Telegram.
- Friend changes (status/profile/remove) are reported.
- Voice activity for tracked users is reported (join/leave, who is with them).
- Runs on GitHub Actions every 5 minutes.

## Quick Setup

1) Requirements
```bash
python -m pip install -r requirements.txt
```

2) Configure `config.yaml` (or use env in Actions)

3) Configure GitHub Actions secrets/vars
- Secrets: `DISCORD_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Vars (optional): `TELEGRAM_ALLOWED_USER_IDS`, `DISCORD_TRACKED_USERS`, `TIMEZONE`, `VOICE_MONITORING_DURATION`, `DM_CHECK_DURATION`

4) Run
```bash
python main.py
```

## Notes
- Env fallbacks are used if `config.yaml` fields are empty.
- Telegram allowlist blocks unauthorized recipients with a short notice.
- Using self-bots violates Discord ToS. Use at your own risk.

A Python-based monitoring system that tracks Discord activities and forwards notifications to Telegram. Designed to run automatically via GitHub Actions every 5 minutes.

## Features

### 1. Direct Message Monitoring
- Receives notifications for all incoming DMs
- Tracks message edits and deletions
- Monitors reactions on DM messages
- Displays sender information and timestamps (Asia/Tehran timezone)

### 2. Friend Activity Tracking
- Online/offline status changes
- Profile updates (avatar, bio, username)
- Friend removal notifications
- Configurable user tracking list

### 3. Voice Channel Monitoring
- Tracks when friends join/leave voice channels
- Shows which server and channel they're in
- Lists other members in the voice channel
- Extended monitoring duration when voice activity is detected

## Project Structure

```
Discord/
├── .github/
│   └── workflows/
│       └── monitor.yml          # GitHub Actions workflow
├── src/
│   ├── __init__.py
│   ├── config_loader.py         # Configuration management
│   ├── discord_monitor.py       # Discord client implementation
│   ├── state_manager.py         # State persistence
│   └── telegram_notifier.py     # Telegram notification service
├── main.py                      # Application entry point
├── config.yaml                  # Configuration file
├── requirements.txt             # Python dependencies
├── .gitignore
└── README.md
```

## Setup

### 1. Local Setup

1. Clone the repository:
```bash
git clone https://github.com/aurumco/ryde.git
cd ryde
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run locally:
```bash
python main.py
```

## License

This project is for educational purposes only. Use at your own risk.
