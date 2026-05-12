# Hermes Hooks (Custom Extensions)

Hooks are event handlers that run when Hermes gateway emits lifecycle events
(agent:start, agent:end, gateway:startup, etc).

This directory contains **custom hooks** for AnpassenAI. They are kept in this
repo (instead of `~/.hermes/hooks/`) so they can be version-controlled, shared,
and deployed via Git.

## Setup

Hermes scans `~/.hermes/hooks/` at startup. To make this repo's hooks visible
without copying files, the setup scripts create symlinks (Linux/macOS) or
junctions (Windows) from `~/.hermes/hooks/` into this directory.

### Linux / macOS (VPS)

```bash
./hooks/setup.sh
```

### Windows (development)

```powershell
.\hooks\setup.ps1
```

After running setup, restart Hermes gateway:

```bash
python -m hermes_cli.main gateway run
```

The log should show:

```
[hooks] Loaded hook 'intent-detector' for events: [...]
```

## Architecture

```
This repo (Git tracked)              ~/.hermes (user data, NOT in Git)
─────────────────────────            ─────────────────────────────────
hooks/intent-detector/  ←─── link ───  hooks/intent-detector/
  HOOK.yaml                            (symlink only — Hermes reads here)
  handler.py                           
                                       intent_queue.json   (state)
                                       intent_last_seen.json (state)
                                       memories/MEMORY.md    (state)
                                       .env                  (secrets)
```

Edit hook code in this repo. State files stay in `~/.hermes/`.

## Available Hooks

### intent-detector

Detects unresolved tasks/concerns from user conversations and sends follow-up
Telegram reminders. Uses a small LLM to filter false positives.

**Events:**
- `agent:end` — analyze conversation, save pending intents
- `agent:start` — if user returns after 1h+ idle, send follow-up before agent replies
- `gateway:startup` — start background inactivity watcher (checks every 30 min)

**Required env vars:**
- `OPENROUTER_API_KEY` — for LLM intent analysis
- `TELEGRAM_BOT_TOKEN` — for sending follow-up messages

**State files:**
- `~/.hermes/intent_queue.json` — pending follow-ups
- `~/.hermes/intent_last_seen.json` — user activity timestamps
- `~/.hermes/memories/MEMORY.md` — agent-readable context

## Deploying to a new machine (e.g. VPS)

```bash
git clone <your-repo-url> AnpassenAI
cd AnpassenAI
./hooks/setup.sh
# Set env vars in ~/.hermes/.env (OPENROUTER_API_KEY, TELEGRAM_BOT_TOKEN, etc.)
python -m hermes_cli.main gateway run
```
