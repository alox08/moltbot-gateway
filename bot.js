const { Client, GatewayIntentBits, REST, Routes, SlashCommandBuilder, AttachmentBuilder } = require('discord.js');
const { QdrantClient } = require('@qdrant/js-client-rest');
const { makeShortVideo, makeStickmanVideo } = require('./videomaker');
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
    await qdrant.upsert(COLLECTION, {
      points: [{
        id: Date.now(),
        vector,
        payload: { userId, userMsg, botReply, tag, ts: new Date().toISOString() },
      }],
    });
    console.log(`📚 Архіваріус: збережено [${tag}]`);
  } catch (e) {
    console.error('Архіваріус save помилка:', e.message);
  }
}

async function archiveSearch(query, limit = 3) {
  try {
    const vector = await getEmbedding(query);
    const results = await qdrant.search(COLLECTION, { vector, limit, with_payload: true, score_threshold: 0.3 });
    return results.map(r => `[${r.payload.ts?.slice(0, 10)}][${r.payload.tag}] ${r.payload.userMsg} → ${r.payload.botReply}`);
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

const SYSTEM_MAIN = `Ти МолтБот 🎬 — головний оркестратор YouTube-конвеєра.
Відповідай ТІЛЬКИ українською мовою. Без зайвих вступів.

ВАЖЛИВО: Ти завжди знаєш свого власника. Його звати ОЛЕКСАНДР, Discord нікнейм — SARMA. Ніколи не кажи що не знаєш імені власника. Якщо тебе питають "як мене звати?" — відповідай "Олександр".

Власник: Олександр (SARMA), Україна, UTC+2/+3. Мета — автоматизований YouTube-конвеєр.

Ти МОЖЕШ створювати відео через команду /makevideo. Ніколи не кажи що не можеш генерувати відео.

ВАЖЛИВО: Ти знаєш на якій моделі зараз працюєш — вона вказана нижче як ПОТОЧНА_МОДЕЛЬ. Якщо тебе питають "яка нейронка", "яка модель", "який ШІ" — ЗАВЖДИ відповідай точну назву з ПОТОЧНА_МОДЕЛЬ. Ніколи не кажи що не знаєш.

[ДОСТУПНІ КОМАНДИ]
- /shorts [тема] — сценарій YouTube Short
- /story [тема] — коротке оповідання
- /makevideo [тема] — повне відео: сценарій + AI-зображення + озвучка + монтаж → MP4
- /stickman [тема] — стікмен анімація: жарт + озвучка + відео

Правила делегування — якщо запит стосується:
- YouTube Shorts / сценарій / відео → відповідай: DELEGATE:SHORTS:[тема одним реченням]
- Оповідання / story / читання → відповідай: DELEGATE:STORY:[тема одним реченням]
- Будь-що інше → відповідай напряму.

Якщо в секції [ПАМ'ЯТЬ] є релевантний контекст — використовуй його.`;

const SYSTEM_SHORTS = `Ти ShortsManager 🎬 — субагент МолтБота для YouTube Shorts.
Відповідай ТІЛЬКИ українською мовою.
Генеруй готові сценарії для YouTube Shorts (до 60 секунд).

Формат (обов'язково дотримуйся):
🎬 ТЕМА: [назва]
⏱ ТРИВАЛІСТЬ: [секунди]
🎯 АУДИТОРІЯ: [хто це дивиться]

📝 СЦЕНАРІЙ:
[0-3с] ХУК: [текст що говоримо]
[3-15с] ЗМІСТ: [текст]
[15-25с] РОЗВИТОК: [текст]
[25-30с] ФІНАЛ + CTA: [текст]

🎵 МУЗИКА/ЗВУК: [рекомендація]
📸 КАДРИ:
- [детальний опис кадру 1 англійською для AI-генерації]
- [детальний опис кадру 2 англійською для AI-генерації]
- [детальний опис кадру 3 англійською для AI-генерації]
- [детальний опис кадру 4 англійською для AI-генерації]
#️⃣ ХЕШТЕГИ: [5-7 штук]

Якщо в секції [ПАМ'ЯТЬ] є схожі минулі сценарії — врахуй їх.`;

const SYSTEM_JOKE = `Ти генератор коротких смішних жартів для стікмен-анімації на YouTube.
Напиши ОДИН короткий жарт на задану тему.
ВАЖЛИВО:
- Рівно 2-4 речення, не більше
- Без вступів типу "Ось жарт:" або пояснень після
- Без емодзі та зайвих символів
- Відповідай ТІЛЬКИ текстом жарту українською мовою`;

const SYSTEM_STORY = `Ти StoryManager 📖 — субагент МолтБота для коротких оповідань.
Відповідай ТІЛЬКИ українською мовою.
Генеруй короткі оповідання для YouTube (2-5 хвилин озвучки).

Формат:
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

// Швидкі моделі — для чату та оркестратора
const MODELS = [
  'meta-llama/llama-3.3-70b-instruct:free',
  'google/gemma-3-27b-it:free',
  'deepseek/deepseek-chat-v3-0324:free',
  'nvidia/nemotron-3-super-120b-a12b:free',
  'mistralai/mistral-7b-instruct:free',
  'qwen/qwen2.5-vl-72b-instruct:free',
];

// Розумні моделі — для субагентів (/shorts, /story, /stickman)
const MODELS_SMART = [
  'microsoft/phi-4-reasoning-plus:free',
  'deepseek/deepseek-chat-v3-0324:free',
  'meta-llama/llama-3.3-70b-instruct:free',
  'google/gemma-3-27b-it:free',
  'mistralai/mistral-7b-instruct:free',
];

let lastUsedModel = MODELS[0];

async function callLLMWithList(models, messages, maxTokens = 2000) {
  for (const model of models) {
    try {
      const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${process.env.OPENROUTER_API_KEY}`,
          'Content-Type': 'application/json',
          'HTTP-Referer': 'https://moltbot.railway.app',
          'X-Title': 'MoltBot',
        },
        body: JSON.stringify({ model, messages, max_tokens: maxTokens }),
      });
      const data = await res.json();
      const raw = data.choices?.[0]?.message?.content?.trim();
      const content = raw ? raw.replace(/<think>[\s\S]*?<\/think>/g, '').trim() : '';
      if (content) {
        console.log(`✅ Модель: ${model}`);
        lastUsedModel = model;
        return content;
      }
      console.warn(`⚠️ ${model} — порожня відповідь`);
    } catch (e) {
      console.warn(`⚠️ ${model} помилка: ${e.message}`);
    }
  }
  return null;
}

// Швидкий виклик — для чату
async function callLLM(messages, maxTokens = 2000) {
  return callLLMWithList(MODELS, messages, maxTokens);
}

// Розумний виклик — для субагентів (phi-4 думає, але краща якість)
async function callLLMSmart(messages, maxTokens = 2000) {
  return callLLMWithList(MODELS_SMART, messages, maxTokens);
}

function cleanReply(text) {
  return text.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
}

// ─── Субагенти ─────────────────────────────────────────────────────────────

const AGENT_PROMPTS = {
  main:   SYSTEM_MAIN,
  shorts: SYSTEM_SHORTS,
  story:  SYSTEM_STORY,
  joke:   SYSTEM_JOKE,
};

// Субагенти що потребують якості — використовують phi-4
const SMART_AGENTS = ['shorts', 'story', 'joke'];

async function callAgent(agentType, task, memoryBlock = '') {
  const systemPrompt = (AGENT_PROMPTS[agentType] || AGENT_PROMPTS.main) + memoryBlock;
  const useSmart = SMART_AGENTS.includes(agentType);
  console.log(`🤖 Субагент [${agentType}] (${useSmart ? 'smart' : 'fast'}): "${task.substring(0, 60)}"`);
  const llm = useSmart ? callLLMSmart : callLLM;
  const reply = await llm([
    { role: 'system', content: systemPrompt },
    { role: 'user', content: task },
  ]);
  if (!reply) return null;
  const cleaned = cleanReply(reply);
  return cleaned || null;  // якщо phi-4 повернула тільки <think> без відповіді — null
}

// ─── Оркестратор ───────────────────────────────────────────────────────────

async function orchestrate(channelId, userMessage, memoryBlock) {
  addToHistory(channelId, 'user', userMessage);

  // Оркестратор вирішує що робити
  const modelInfo = `\n\nПОТОЧНА_МОДЕЛЬ: ${lastUsedModel}`;
  const msgs = [
    { role: 'system', content: SYSTEM_MAIN + modelInfo + memoryBlock },
    ...getHistory(channelId),
  ];
  const raw = await callLLM(msgs);
  if (!raw) return null;

  const response = cleanReply(raw);

  // Перевіряємо чи оркестратор делегує субагенту
  const delegateMatch = response.match(/DELEGATE:(SHORTS|STORY):(.+)/i);
  if (delegateMatch) {
    const agentType = delegateMatch[1].toLowerCase();
    const agentTask = delegateMatch[2].trim();
    console.log(`🎯 Оркестратор → [${agentType}]: "${agentTask}"`);

    const memories = await archiveSearch(agentTask);
    const agentMemory = memories.length > 0
      ? `\n\n[ПАМ'ЯТЬ — схожі минулі роботи]:\n${memories.join('\n')}`
      : '';

    return await callAgent(agentType, agentTask, agentMemory);
  }

  return response;
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
const OWNER_ID = '706908682767695962';

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
      .setDescription('Генерує відео Short: сценарій + AI-зображення + озвучка + монтаж')
      .addStringOption(o => o.setName('тема').setDescription('Тема відео').setRequired(true)),
    new SlashCommandBuilder()
      .setName('stickman')
      .setDescription('Стікмен відео: AI генерує жарт + озвучка + анімація')
      .addStringOption(o => o.setName('тема').setDescription('Тема жарту').setRequired(true)),
  ].map(c => c.toJSON());

  const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);
  try {
    await rest.put(Routes.applicationCommands(bot.user.id), { body: commands });
    console.log('✅ Slash команди зареєстровано: /shorts /story /makevideo /stickman');
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

  if (interaction.user.id !== OWNER_ID) {
    await interaction.reply({ content: '⛔ Тільки для власника бота.', ephemeral: true });
    return;
  }

  const tema = interaction.options.getString('тема');
  const cmd = interaction.commandName;
  await interaction.deferReply();

  if (cmd === 'shorts') {
    // ── ShortsManager субагент ──
    console.log(`🎬 /shorts: "${tema}"`);
    const memories = await archiveSearch(tema);
    const memoryBlock = memories.length > 0
      ? `\n\n[ПАМ'ЯТЬ]:\n${memories.join('\n')}`
      : '';

    let reply = await callAgent('shorts', tema, memoryBlock);
    if (!reply) { await interaction.editReply('⚠️ Всі моделі недоступні. Спробуй пізніше.'); return; }
    if (reply.length > 1990) reply = reply.substring(0, 1990) + '...';
    await interaction.editReply(reply);
    archiveSave(interaction.user.id, tema, reply, 'shorts');

  } else if (cmd === 'story') {
    // ── StoryManager субагент ──
    console.log(`📖 /story: "${tema}"`);
    const memories = await archiveSearch(tema);
    const memoryBlock = memories.length > 0
      ? `\n\n[ПАМ'ЯТЬ]:\n${memories.join('\n')}`
      : '';

    let reply = await callAgent('story', tema, memoryBlock);
    if (!reply) { await interaction.editReply('⚠️ Всі моделі недоступні. Спробуй пізніше.'); return; }
    if (reply.length > 1990) reply = reply.substring(0, 1990) + '...';
    await interaction.editReply(reply);
    archiveSave(interaction.user.id, tema, reply, 'story');

  } else if (cmd === 'makevideo') {
    // ── VideoMaker: ShortsManager → FLUX → edge-tts → FFmpeg ──
    console.log(`🎬 /makevideo: "${tema}"`);
    const memories = await archiveSearch(tema);
    const memoryBlock = memories.length > 0
      ? `\n\n[ПАМ'ЯТЬ]:\n${memories.join('\n')}`
      : '';

    // Крок 1: ShortsManager генерує сценарій
    await interaction.editReply('📝 Крок 1/3: ShortsManager генерує сценарій...');
    const script = await callAgent('shorts', `Динозаври і первісні люди: ${tema}`, memoryBlock);
    if (!script) { await interaction.editReply('⚠️ Не вдалось згенерувати сценарій.'); return; }

    // Показуємо сценарій (обрізаємо якщо надто довгий)
    const preview = script.length > 1400 ? script.substring(0, 1400) + '...' : script;
    await interaction.editReply(`📝 Сценарій готовий:\n\n${preview}\n\n🎨 Крок 2/3: Генерую AI-зображення та озвучку паралельно...`);

    // Крок 2+3: VideoMaker (FLUX зображення + edge-tts + FFmpeg)
    try {
      const videoFile = await makeShortVideo(script);
      const attachment = new AttachmentBuilder(videoFile, { name: 'short.mp4' });
      await interaction.followUp({ content: '✅ Крок 3/3: Відео змонтоване! 🎬', files: [attachment] });
      fs.unlinkSync(videoFile);
    } catch (e) {
      console.error('makevideo помилка:', e.message);
      await interaction.followUp(`⚠️ Відео не вдалось: ${e.message}`);
    }
    archiveSave(interaction.user.id, tema, script, 'makevideo');

  } else if (cmd === 'stickman') {
    // ── Стікмен: AI жарт → edge-tts → Pillow анімація → MP4 ──
    console.log(`🕺 /stickman: "${tema}"`);
    await interaction.editReply('📝 Генерую жарт...');

    const joke = await callAgent('joke', tema);
    if (!joke) { await interaction.editReply('⚠️ Не вдалось згенерувати жарт.'); return; }

    const cleanJoke = joke.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
    await interaction.editReply(`📝 Жарт: *${cleanJoke}*\n\n🎙 Озвучую + малюю стікмена...`);

    try {
      const videoFile = await makeStickmanVideo(cleanJoke);
      const attachment = new AttachmentBuilder(videoFile, { name: 'stickman.mp4' });
      await interaction.followUp({ content: '✅ Готово! 🕺', files: [attachment] });
      fs.unlinkSync(videoFile);
    } catch (e) {
      console.error('stickman помилка:', e.message);
      await interaction.followUp(`⚠️ Помилка: ${e.message}`);
    }
    archiveSave(interaction.user.id, tema, cleanJoke, 'stickman');
  }
});

// ─── Звичайні повідомлення (через оркестратор) ─────────────────────────────

bot.on('messageCreate', async (message) => {
  if (message.author.bot) return;
  if (message.channel.name !== ALLOWED_CHANNEL) return;
  if (message.author.id !== OWNER_ID) return;

  const userMessage = message.content.trim();
  if (!userMessage) return;

  console.log(`💬 [${message.author.username}]: ${userMessage}`);
  await message.channel.sendTyping();

  const memories = await archiveSearch(userMessage);
  const memoryBlock = memories.length > 0
    ? `\n\n[ПАМ'ЯТЬ — схожі минулі розмови]:\n${memories.join('\n')}`
    : '';

  const channelId = message.channel.id;
  let reply = await orchestrate(channelId, userMessage, memoryBlock);

  if (!reply) {
    await message.reply('⚠️ Всі моделі недоступні. Спробуй пізніше.');
    return;
  }
  if (reply.length > 1990) reply = reply.substring(0, 1990) + '...';

  await message.reply(reply);
  console.log(`✅ Відповів: ${reply.substring(0, 80)}...`);

  addToHistory(channelId, 'assistant', reply);
  archiveSave(message.author.id, userMessage, reply, 'chat');
});

bot.login(process.env.DISCORD_TOKEN);
