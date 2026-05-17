# 🌸 Mikasa Bot

A fully-featured AI Telegram group manager built with Python (aiogram 3.x) and Groq AI (LLaMA). Handles moderation, fun commands, games, and AI chat in Hinglish/English.

**Bot:** [@Ig_MikasaBot](https://t.me/Ig_MikasaBot)

---

## Features

- **AI Chat** — Replies in casual Indian Gen Z Hinglish/English with conversation memory (last 5 turns)
- **Group Moderation** — Ban, kick, mute, unmute, warn system, anti-spam
- **Fun Commands** — `/couple`, `/ship`, `/roast`, `/compliment`, `/8ball`, `/truth`, `/dare`
- **Word Scramble Game** — `/game` with AI-generated words (Easy / Medium / Hard), multiplayer scoring, hints
- **Spam Command** — `/spam N text @user` with proper mention pinging
- **Welcome Messages** — Video welcome with button for new members
- **Search** — `/search` powered by Groq AI
- **Sticker Reactions** — Random sticker replies from Telegram sticker pack

---

## Project Structure

```
mikasa-bot/
├── bot/
│   ├── mikasa_bot.py          # Main bot file
│   └── assets/
│       ├── couple/            # Couple command images
│       │   ├── couple_1.jpeg
│       │   ├── couple_2.jpeg
│       │   ├── couple_3.jpeg
│       │   ├── couple_4.jpeg
│       │   └── couple_5.jpeg
│       └── welcome/           # Welcome videos (sent to new members)
│           ├── welcome_1.mp4
│           ├── welcome_2.mp4
│           └── welcome_3.mp4
├── Dockerfile
├── render.yaml
├── requirements.txt
└── .env.example
```

> **The welcome videos and couple images are required.** Without them those features silently skip sending media.

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/mikasa-bot.git
cd mikasa-bot
```

### 2. Get your API keys

| Key | Where to get it |
|-----|----------------|
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) on Telegram — create a new bot |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) — free account, free API key |

### 3. Set environment variables

Copy the example file and fill in your keys:

```bash
cp .env.example .env
# Edit .env and add your BOT_TOKEN and GROQ_API_KEY
```

### 4. Run locally

```bash
pip install -r requirements.txt
python3 bot/mikasa_bot.py
```

---

## Deploy on Render

### Option A — One-click via render.yaml (recommended)

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → **New** → **Blueprint**
3. Connect your GitHub repo — Render will detect `render.yaml` automatically
4. Add your environment variables in the Render dashboard:
   - `BOT_TOKEN`
   - `GROQ_API_KEY`
5. Click **Apply** — Render builds the Docker image and starts the bot

### Option B — Manual setup

1. Go to [render.com](https://render.com) → **New** → **Background Worker**
2. Connect your GitHub repo
3. Set:
   - **Runtime:** Docker
   - **Dockerfile path:** `./Dockerfile`
4. Add environment variables:
   - `BOT_TOKEN` — your Telegram bot token
   - `GROQ_API_KEY` — your Groq API key
5. Click **Create Worker**

---

## Commands

### Admin commands (admins only)
| Command | Description |
|---------|-------------|
| `/ban @user` | Ban a user |
| `/kick @user` | Kick a user |
| `/mute @user` | Mute a user |
| `/unmute @user` | Unmute a user |
| `/warn @user` | Warn a user (3 warns = auto ban) |
| `/clearwarn @user` | Clear warnings |
| `/promote @user` | Promote to admin |
| `/demote @user` | Demote from admin |
| `/setmode cute/romantic/rude` | Change Mikasa's personality mode |
| `/setlang hinglish/english` | Change language |

### Fun commands (everyone)
| Command | Description |
|---------|-------------|
| `/couple` | Random couple from group members |
| `/ship @user1 @user2` | Ship two people |
| `/roast @user` | AI roast |
| `/compliment @user` | AI compliment |
| `/8ball question` | Magic 8-ball |
| `/truth` | Random truth question |
| `/dare` | Random dare |
| `/game` | Start Word Scramble game |
| `/spam N text` | Spam N times |
| `/stop` | Stop active spam |
| `/search query` | AI-powered search |

---

## Notes

- Make Mikasa **admin** in your group for moderation commands (ban, kick, mute) to work
- Stickers are fetched from the `hamsterset` Telegram sticker pack at startup — no local files needed
- Conversation memory resets on bot restart (in-memory only)
- The bot only replies in groups when directly mentioned, replied to, or when her name is used
