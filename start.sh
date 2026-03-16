#!/bin/bash
set -e

echo "=== MoltBot Gateway Starting ==="

# Встановлення OpenClaw якщо не встановлено
if ! command -v openclaw &> /dev/null; then
  echo "Installing OpenClaw..."
  npm install -g openclaw@latest
fi

# Створення структури конфігу
mkdir -p ~/.openclaw/agents/main/agent
mkdir -p ~/.openclaw/workspace/shorts
mkdir -p ~/.openclaw/workspace/story
mkdir -p ~/.openclaw/agents/shortsmanager/agent
mkdir -p ~/.openclaw/agents/storymanager/agent

# Основний конфіг з env змінних
cat > ~/.openclaw/openclaw.json << EOF
{
  "agents": {
    "defaults": {
      "model": { "primary": "openrouter/deepseek/deepseek-r1:free" },
      "workspace": "$HOME/.openclaw/workspace"
    },
    "list": {
      "shortsmanager": {
        "id": "shortsmanager",
        "name": "ShortsManager",
        "workspace": "$HOME/.openclaw/workspace/shorts",
        "agentDir": "$HOME/.openclaw/agents/shortsmanager/agent",
        "model": { "primary": "openrouter/meta-llama/llama-3.3-70b-instruct:free" }
      },
      "storymanager": {
        "id": "storymanager",
        "name": "StoryManager",
        "workspace": "$HOME/.openclaw/workspace/story",
        "agentDir": "$HOME/.openclaw/agents/storymanager/agent",
        "model": { "primary": "openrouter/meta-llama/llama-3.3-70b-instruct:free" }
      }
    }
  },
  "auth": {
    "profiles": {
      "openrouter:default": {
        "provider": "openrouter",
        "mode": "api_key"
      }
    }
  },
  "channels": {
    "discord": {
      "enabled": true,
      "token": "$DISCORD_TOKEN",
      "groupPolicy": "allowlist",
      "guilds": {
        "*": {
          "channels": {
            "основной": { "allow": true }
          }
        }
      },
      "streaming": "off"
    }
  },
  "gateway": {
    "port": ${PORT:-18789},
    "mode": "local",
    "bind": "all",
    "auth": {
      "mode": "token",
      "token": "$GATEWAY_AUTH_TOKEN"
    }
  },
  "plugins": {
    "entries": {
      "discord": { "enabled": true }
    }
  }
}
EOF

# Auth profiles (OpenRouter API key)
cat > ~/.openclaw/agents/main/agent/auth-profiles.json << EOF
{
  "version": 1,
  "profiles": {
    "openrouter:default": {
      "type": "api_key",
      "provider": "openrouter",
      "key": "$OPENROUTER_API_KEY"
    }
  }
}
EOF

# Копіюємо auth для субагентів
cp ~/.openclaw/agents/main/agent/auth-profiles.json ~/.openclaw/agents/shortsmanager/agent/auth-profiles.json
cp ~/.openclaw/agents/main/agent/auth-profiles.json ~/.openclaw/agents/storymanager/agent/auth-profiles.json

# Workspace файли
cat > ~/.openclaw/workspace/SOUL.md << 'SOULEOF'
# SOUL.md - Хто ти є

_Ти не просто бот. Ти МолтБот — творчий AI-компаньйон Олександра для YouTube._

## Головне

**Будь корисним, а не ввічливим.** Жодних "Чудове питання!" — просто роби справу.

**Знай свою роботу:**
- YouTube Shorts — сценарії до 60с, гачок з першої секунди
- Короткі оповідання — текст + озвучка + відеомонтаж
- Координація субагентів: ShortsManager, StoryManager

**Говори лише українською.** Завжди, без винятків.

## Стиль

Лаконічно коли треба, детально коли важливо. Emoji 🎬 — твій підпис.
SOULEOF

cat > ~/.openclaw/workspace/IDENTITY.md << 'IDEOF'
# IDENTITY.md

- **Name:** МолтБот
- **Creature:** AI-компаньйон для YouTube-контенту
- **Vibe:** Творчий, швидкий, конкретний
- **Emoji:** 🎬
- **Language:** Завжди українська
IDEOF

cat > ~/.openclaw/workspace/USER.md << 'USEREOF'
# USER.md

- **Name:** Олександр
- **Timezone:** Україна UTC+2/+3
- **Мова:** Українська

## Проєкт
YouTube Shorts і короткі оповідання. Хоче автоматизований конвеєр.
USEREOF

echo "=== Config ready. Starting gateway... ==="
openclaw gateway run --bind all --port ${PORT:-18789}
