const { Client, GatewayIntentBits } = require('discord.js');
const { QdrantClient } = require('@qdrant/js-client-rest');

// ─── Архіваріус ────────────────────────────────────────────────────────────

const COLLECTION = 'moltbot_memory';
const VECTOR_SIZE = 768; // розмір векторів Jina

const qdrant = new QdrantClient({
  url: process.env.QDRANT_URL,
  apiKey: process.env.QDRANT_API_KEY,
});

async function initCollection() {
  try {
    const collections = await qdrant.getCollections();
    const exists = collections.collections.some(c => c.name === COLLECTION);
    if (!exists) {
      await qdrant.createCollection(COLLECTION, {
        vectors: { size: VECTOR_SIZE, distance: 'Cosine' },
      });
      console.log(`📚 Архіваріус: колекцію "${COLLECTION}" створено`);
    } else {
      console.log(`📚 Архіваріус: колекція "${COLLECTION}" вже існує`);
    }
  } catch (e) {
    console.error('Архіваріус initCollection помилка:', e.message);
  }
}

async function getEmbedding(text) {
  const res = await fetch('https://api.jina.ai/v1/embeddings', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${process.env.JINA_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ model: 'jina-embeddings-v3', input: [text] }),
  });
  const data = await res.json();
  return data.data[0].embedding;
}

async function archiveSave(userId, userMsg, botReply) {
  try {
    const text = `Користувач: ${userMsg}\nМолтБот: ${botReply}`;
    const vector = await getEmbedding(text);
    await qdrant.upsert(COLLECTION, {
      points: [{
        id: Date.now(),
        vector,
        payload: { userId, userMsg, botReply, ts: new Date().toISOString() },
      }],
    });
  } catch (e) {
    console.error('Архіваріус save помилка:', e.message);
  }
}

async function archiveSearch(query, limit = 3) {
  try {
    const vector = await getEmbedding(query);
    const results = await qdrant.search(COLLECTION, { vector, limit, with_payload: true });
    return results.map(r => `[${r.payload.ts?.slice(0,10)}] ${r.payload.userMsg} → ${r.payload.botReply}`);
  } catch (e) {
    console.error('Архіваріус search помилка:', e.message);
    return [];
  }
}

// ─── Пам'ять розмови (in-memory, останні 10 повідомлень на канал) ──────────

const conversationHistory = new Map();

function getHistory(channelId) {
  if (!conversationHistory.has(channelId)) conversationHistory.set(channelId, []);
  return conversationHistory.get(channelId);
}

function addToHistory(channelId, role, content) {
  const history = getHistory(channelId);
  history.push({ role, content });
  if (history.length > 10) history.splice(0, history.length - 10);
}

// ─── Discord бот ───────────────────────────────────────────────────────────

const { Client: DiscordClient, GatewayIntentBits: Intents } = require('discord.js');

const bot = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
  ]
});

const ALLOWED_CHANNEL = process.env.DISCORD_CHANNEL || 'основной';

const SYSTEM_PROMPT = `Ти МолтБот 🎬 — творчий AI-компаньйон Олександра для YouTube.
Відповідай ТІЛЬКИ українською мовою. Без зайвих вступів типу "Звісно!" або "Чудове питання!".
Будь конкретним і корисним.
Спеціалізуєшся на YouTube Shorts (сценарії до 60с) і коротких оповіданнях (текст + озвучка + відео).
Якщо в секції [ПАМ'ЯТЬ] є релевантний контекст — використовуй його у відповіді.`;

const MODELS = [
  'nvidia/nemotron-3-super-120b-a12b:free',
  'meta-llama/llama-3.3-70b-instruct:free',
  'mistralai/mistral-7b-instruct:free',
];

async function callLLM(messages) {
  for (const model of MODELS) {
    try {
      const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${process.env.OPENROUTER_API_KEY}`,
          'Content-Type': 'application/json',
          'HTTP-Referer': 'https://moltbot.railway.app',
          'X-Title': 'MoltBot',
        },
        body: JSON.stringify({ model, messages, max_tokens: 1500 }),
      });
      const data = await res.json();
      if (data.choices && data.choices[0]) {
        console.log(`✅ Модель: ${model}`);
        return data.choices[0].message.content.trim();
      }
      console.warn(`⚠️ ${model} не відповів, перемикаю...`);
    } catch (e) {
      console.warn(`⚠️ ${model} помилка: ${e.message}, перемикаю...`);
    }
  }
  return null;
}

bot.on('ready', async () => {
  console.log(`✅ МолтБот запущений як ${bot.user.tag}`);
  console.log(`📺 Слухаю канал: #${ALLOWED_CHANNEL}`);
  await initCollection();
});

bot.on('messageCreate', async (message) => {
  if (message.author.bot) return;
  if (message.channel.name !== ALLOWED_CHANNEL) return;

  const userMessage = message.content.trim();
  if (!userMessage) return;

  console.log(`💬 [${message.author.username}]: ${userMessage}`);
  await message.channel.sendTyping();

  // 1. Шукаємо в пам'яті Архіваріуса
  const memories = await archiveSearch(userMessage);
  const memoryBlock = memories.length > 0
    ? `\n\n[ПАМ'ЯТЬ — схожі минулі розмови]:\n${memories.join('\n')}`
    : '';

  // 2. Будуємо повідомлення: system + пам'ять + історія + нове
  const channelId = message.channel.id;
  addToHistory(channelId, 'user', userMessage);

  const messages = [
    { role: 'system', content: SYSTEM_PROMPT + memoryBlock },
    ...getHistory(channelId),
  ];

  // 3. Викликаємо LLM з автоперемиканням моделей
  let reply = await callLLM(messages);

  if (!reply) {
    await message.reply('⚠️ Всі моделі недоступні. Спробуй пізніше.');
    return;
  }

  // Видаляємо <think> блоки
  reply = reply.replace(/<think>[\s\S]*?<\/think>/g, '').trim();

  if (!reply) {
    await message.reply('🤔 МолтБот думає... Спробуй ще раз.');
    return;
  }

  // Discord ліміт 2000 символів
  if (reply.length > 1990) reply = reply.substring(0, 1990) + '...';

  await message.reply(reply);
  console.log(`✅ Відповів: ${reply.substring(0, 80)}...`);

  // 4. Зберігаємо в пам'ять Архіваріуса і в локальну історію
  addToHistory(channelId, 'assistant', reply);
  archiveSave(message.author.id, userMessage, reply);
});

bot.login(process.env.DISCORD_TOKEN);
