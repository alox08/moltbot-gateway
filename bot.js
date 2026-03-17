const { Client, GatewayIntentBits, REST, Routes, SlashCommandBuilder, AttachmentBuilder } = require('discord.js');
const { QdrantClient } = require('@qdrant/js-client-rest');
const { makeShortVideo } = require('./videomaker');
const fs = require('fs');

// ─── Архіваріус ────────────────────────────────────────────────────────────

const COLLECTION = 'moltbot_memory';
const VECTOR_SIZE = 1024;

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
      console.log(`📚 Архіваріус: колекція "${COLLECTION}" готова`);
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

async function archiveSave(userId, userMsg, botReply, tag = 'chat') {
  try {
    const text = `Користувач: ${userMsg}\nМолтБот: ${botReply}`;
    const vector = await getEmbedding(text);
    console.log(`📚 Архіваріус: зберігаю [${tag}] вектор ${vector.length}d`);
    await qdrant.upsert(COLLECTION, {
      points: [{
        id: Date.now(),
        vector,
        payload: { userId, userMsg, botReply, tag, ts: new Date().toISOString() },
      }],
    });
    console.log(`📚 Архіваріус: збережено`);
  } catch (e) {
    console.error('Архіваріус save помилка:', e.message);
  }
}

async function archiveSearch(query, limit = 3) {
  try {
    const vector = await getEmbedding(query);
    const results = await qdrant.search(COLLECTION, { vector, limit, with_payload: true, score_threshold: 0.3 });
    console.log(`📚 Архіваріус: знайдено ${results.length} спогадів`);
    return results.map(r => `[${r.payload.ts?.slice(0,10)}][${r.payload.tag}] ${r.payload.userMsg} → ${r.payload.botReply}`);
  } catch (e) {
    console.error('Архіваріус search помилка:', e.message);
    return [];
  }
}

// ─── Пам'ять розмови (in-memory, останні 10 повідомлень) ───────────────────

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

// ─── Системні промпти субагентів ───────────────────────────────────────────

const SYSTEM_MAIN = `Ти МолтБот 🎬 — творчий AI-компаньйон Олександра для YouTube.
Відповідай ТІЛЬКИ українською мовою. Без зайвих вступів типу "Звісно!" або "Чудове питання!".
Будь конкретним і корисним.
Спеціалізуєшся на YouTube Shorts (сценарії до 60с) і коротких оповіданнях (текст + озвучка + відео).
Якщо в секції [ПАМ'ЯТЬ] є релевантний контекст — використовуй його у відповіді.`;

const SYSTEM_SHORTS = `Ти ShortsManager 🎬 — субагент МолтБота для YouTube Shorts.
Відповідай ТІЛЬКИ українською мовою.
Твоє завдання: генерувати готові сценарії для YouTube Shorts (до 60 секунд).

Формат сценарію:
🎬 ТЕМА: [назва]
⏱ ТРИВАЛІСТЬ: [секунди]
🎯 АУДИТОРІЯ: [хто це дивиться]

📝 СЦЕНАРІЙ:
[0-3с] ХУК: [що показуємо/говоримо]
[3-15с] ЗМІСТ: [основна частина]
[15-25с] РОЗВИТОК: [деталі]
[25-30с] ФІНАЛ + CTA: [заклик до дії]

🎵 МУЗИКА/ЗВУК: [рекомендація]
📸 КАДРИ: [що знімати]
#️⃣ ХЕШТЕГИ: [5-7 штук]

Якщо в секції [ПАМ'ЯТЬ] є схожі минулі сценарії — врахуй їх.`;

const SYSTEM_STORY = `Ти StoryManager 📖 — субагент МолтБота для коротких оповідань.
Відповідай ТІЛЬКИ українською мовою.
Твоє завдання: генерувати короткі оповідання для YouTube (2-5 хвилин озвучки).

Формат оповідання:
📖 НАЗВА: [назва]
🎭 ЖАНР: [жанр]
⏱ ТРИВАЛІСТЬ ОЗВУЧКИ: [хвилини]
🎯 АУДИТОРІЯ: [хто це слухає]

📝 ТЕКСТ ОПОВІДАННЯ:
[Повний текст, розбитий на абзаци]

🎵 МУЗИЧНИЙ СУПРОВІД: [рекомендація по настрою]
🖼 ЗОБРАЖЕННЯ/ВІДЕО: [що показувати під час озвучки]
🎙 ПОРАДИ ДЛЯ ОЗВУЧКИ: [темп, інтонація]

Якщо в секції [ПАМ'ЯТЬ] є схожі минулі оповідання — врахуй стиль.`;

// ─── LLM виклик з автоперемиканням ────────────────────────────────────────

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
        body: JSON.stringify({ model, messages, max_tokens: 2000 }),
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

function cleanReply(text) {
  return text.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
}

// ─── Discord бот ───────────────────────────────────────────────────────────

const bot = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
  ]
});

const ALLOWED_CHANNEL = process.env.DISCORD_CHANNEL || 'основной';

// Реєстрація slash команд
async function registerCommands() {
  const commands = [
    new SlashCommandBuilder()
      .setName('shorts')
      .setDescription('Генерує сценарій для YouTube Short')
      .addStringOption(o => o.setName('тема').setDescription('Тема відео').setRequired(true)),
    new SlashCommandBuilder()
      .setName('story')
      .setDescription('Генерує коротке оповідання для YouTube')
      .addStringOption(o => o.setName('тема').setDescription('Тема оповідання').setRequired(true)),
    new SlashCommandBuilder()
      .setName('makevideo')
      .setDescription('Генерує відео Short (зображення + озвучка + монтаж)')
      .addStringOption(o => o.setName('тема').setDescription('Тема відео').setRequired(true)),
  ].map(c => c.toJSON());

  const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);
  try {
    await rest.put(Routes.applicationCommands(bot.user.id), { body: commands });
    console.log('✅ Slash команди зареєстровано: /shorts, /story');
  } catch (e) {
    console.error('Помилка реєстрації команд:', e.message);
  }
}

bot.on('ready', async () => {
  console.log(`✅ МолтБот запущений як ${bot.user.tag}`);
  console.log(`📺 Слухаю канал: #${ALLOWED_CHANNEL}`);
  await initCollection();
  await registerCommands();
});

// ─── Slash команди ─────────────────────────────────────────────────────────

bot.on('interactionCreate', async (interaction) => {
  if (!interaction.isChatInputCommand()) return;

  const tema = interaction.options.getString('тема');
  await interaction.deferReply();

  const memories = await archiveSearch(tema);
  const memoryBlock = memories.length > 0
    ? `\n\n[ПАМ'ЯТЬ — схожі минулі роботи]:\n${memories.join('\n')}`
    : '';

  let systemPrompt, tag;
  if (interaction.commandName === 'shorts') {
    systemPrompt = SYSTEM_SHORTS + memoryBlock;
    tag = 'shorts';
    console.log(`🎬 /shorts: "${tema}"`);
  } else {
    systemPrompt = SYSTEM_STORY + memoryBlock;
    tag = 'story';
    console.log(`📖 /story: "${tema}"`);
  }

  const messages = [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: tema },
  ];

  let reply = await callLLM(messages);
  if (!reply) {
    await interaction.editReply('⚠️ Всі моделі недоступні. Спробуй пізніше.');
    return;
  }

  reply = cleanReply(reply);
  if (reply.length > 1990) reply = reply.substring(0, 1990) + '...';

  await interaction.editReply(reply);
  archiveSave(interaction.user.id, tema, reply, tag);

  // /makevideo — генерація відео
  if (interaction.commandName === 'makevideo') {
    await interaction.followUp('🎬 Генерую відео... це займе 2-3 хвилини');
    try {
      const videoFile = await makeShortVideo(reply);
      const attachment = new AttachmentBuilder(videoFile, { name: 'short.mp4' });
      await interaction.followUp({ content: '✅ Відео готове!', files: [attachment] });
      fs.unlinkSync(videoFile);
    } catch (e) {
      console.error('makevideo помилка:', e.message);
      await interaction.followUp(`⚠️ Помилка генерації відео: ${e.message}`);
    }
  }
});

// ─── Звичайні повідомлення ─────────────────────────────────────────────────

bot.on('messageCreate', async (message) => {
  if (message.author.bot) return;
  if (message.channel.name !== ALLOWED_CHANNEL) return;

  const userMessage = message.content.trim();
  if (!userMessage) return;

  console.log(`💬 [${message.author.username}]: ${userMessage}`);
  await message.channel.sendTyping();

  const memories = await archiveSearch(userMessage);
  const memoryBlock = memories.length > 0
    ? `\n\n[ПАМ'ЯТЬ — схожі минулі розмови]:\n${memories.join('\n')}`
    : '';

  const channelId = message.channel.id;
  addToHistory(channelId, 'user', userMessage);

  const msgs = [
    { role: 'system', content: SYSTEM_MAIN + memoryBlock },
    ...getHistory(channelId),
  ];

  let reply = await callLLM(msgs);
  if (!reply) {
    await message.reply('⚠️ Всі моделі недоступні. Спробуй пізніше.');
    return;
  }

  reply = cleanReply(reply);
  if (!reply) {
    await message.reply('🤔 МолтБот думає... Спробуй ще раз.');
    return;
  }
  if (reply.length > 1990) reply = reply.substring(0, 1990) + '...';

  await message.reply(reply);
  console.log(`✅ Відповів: ${reply.substring(0, 80)}...`);

  addToHistory(channelId, 'assistant', reply);
  archiveSave(message.author.id, userMessage, reply, 'chat');
});

bot.login(process.env.DISCORD_TOKEN);
