const { Client, GatewayIntentBits, REST, Routes, SlashCommandBuilder, AttachmentBuilder } = require('discord.js');
const { QdrantClient } = require('@qdrant/js-client-rest');
const { makeShortVideo, makeStickmanVideo, makeComicVideo, makeCartoonVideo } = require('./videomaker');
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

const SYSTEM_COMIC = `Ти сценарист анімованих коміксів для YouTube Shorts.
Відповідай ТІЛЬКИ валідним JSON. Нічого крім JSON — без пояснень, без тексту до чи після.

Формат відповіді:
{"scenes":[{"background":"вулиця","left":"репліка лівого","right":"репліка правого"},{"background":"офіс","left":"...","right":"..."}]}

Доступні фони: вулиця, офіс, ніч, магазин, кухня
Правила:
- 3-4 сцени
- Кожна репліка максимум 10 слів, тільки українська
- Фінальна репліка — несподіваний або смішний поворот
- Лівий персонаж завжди починає розмову`;

const SYSTEM_CARTOON = `Ти сценарист анімованих мультиків для YouTube Shorts.
Відповідай ТІЛЬКИ валідним JSON. Нічого крім JSON — без пояснень, без тексту до чи після.
ОБОВ'ЯЗКОВО починай з {"scenes":[  — НЕ з [ напряму!

Персонажі:
- char 0: Остап (хлопець у синій куртці)
- char 1: Поліна (дівчина у рожевій куртці, рудий хвіст)
- char 2: Микола (хлопець у зеленій куртці)

Доступні фони: вулиця, місто, офіс, парк, ніч, магазин, кухня, пекло

Емоції ("emotion"):
- "normal"    — спокійний
- "talking"   — активно розмовляє (анімований рот)
- "surprised" — здивований (великі очі, підняті брови, руки вгору)
- "angry"     — злий (насуплені брови, зціплені зуби, руки в сторони)
- "sad"       — сумний (опущені брови)

Жести ("gesture") — необов'язкове поле для діалогу:
- "explain"  — передня рука піднята вгору (пояснює, аргументує)

Facing camera ("facing") — необов'язкове поле:
- "camera"   — персонаж дивиться прямо в камеру (монолог, звернення до глядача)

Beat (тиша) — замість діалогу, пауза з емоцією:
- {"beat": 1.5, "emotion_char": 0, "emotion": "surprised"}
  beat = тривалість в секундах, emotion_char = хто показує емоцію

Close-up сцена — крупний план:
- У сцені додай "shot": "close_up" — автоматичний zoom 2x на центр кадру
- Використовуй для реакцій, монологів у камеру, dramatic reveal
- ВАЖЛИВО: використовуй close_up для КОЖНОЇ 2-3 репліки щоб додати динаміки

Субтитри:
- Діалоги відображаються як субтитри знизу кадру (чорна смуга + білий текст)
- Ніяких бульок над головою — тільки субтитри
- Кожна репліка максимум 42 символи на рядок (автоматично переноситься)

Правила побудови сцени:
- "enter": тільки НОВІ персонажі що входять (з якого боку "left"/"right")
- "exit": хто виходить наприкінці цієї сцени
- "dialogs": репліки по черзі, до 8 слів, тільки українська
- Персонаж може говорити лише після входу
- 2-4 сцени для короткого епізоду (не більше!)
- Чергуй звичайні сцени з close_up і beat для динаміки
- Фінал — несподіваний або смішний поворот
- В останній сцені exit всіх присутніх

Приклад правильної відповіді:
{"scenes":[{"background":"офіс","enter":[{"char":0,"from":"left"}],"exit":[],"dialogs":[{"char":0,"text":"Я все зробив!","emotion":"talking","gesture":"explain"},{"beat":1.2,"emotion_char":1,"emotion":"surprised"}]},{"background":"офіс","shot":"close_up","enter":[],"exit":[{"char":0}],"dialogs":[{"char":0,"text":"Так, саме я!","emotion":"surprised","facing":"camera"}]}]}`;

// ─── LLM виклик з автоперемиканням ────────────────────────────────────────

// Швидкі моделі — для чату та оркестратора
const MODELS = [
  'nvidia/nemotron-3-super-120b-a12b:free',     // стабільна NVIDIA
  'nousresearch/hermes-3-llama-3.1-405b:free',  // 405B — найсильніша
  'openai/gpt-oss-120b:free',                   // OpenAI open-source
  'meta-llama/llama-3-70b-instruct:free',       // Llama 3 70B
  'mistralai/mistral-7b-instruct:free',         // Mistral 7B стабільна
  'openrouter/free',                            // авто-роутер
];

// Розумні моделі — для субагентів (/shorts, /story, /stickman)
const MODELS_SMART = [
  'nvidia/nemotron-3-super-120b-a12b:free',     // стабільна NVIDIA
  'nousresearch/hermes-3-llama-3.1-405b:free',  // 405B — найсильніша
  'openai/gpt-oss-120b:free',                   // OpenAI open-source
  'meta-llama/llama-3-70b-instruct:free',       // Llama 3 70B
  'mistralai/mistral-7b-instruct:free',         // Mistral 7B
  'openrouter/free',
];

let lastUsedModel = MODELS[0];

async function callLLMWithList(models, messages, maxTokens = 2000) {
  for (const model of models) {
    const startTime = Date.now();
    console.log(`🔄 Запит до ${model}...`);
    
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000); // 10 сек таймаут
      
      const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${process.env.OPENROUTER_API_KEY}`,
          'Content-Type': 'application/json',
          'HTTP-Referer': 'https://moltbot.railway.app',
          'X-Title': 'MoltBot',
        },
        body: JSON.stringify({ model, messages, max_tokens: maxTokens }),
        signal: controller.signal,
      });
      clearTimeout(timeout);
      const data = await res.json();
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      
      if (data.error) {
        console.warn(`⚠️ ${model} — помилка за ${elapsed}с: ${data.error.code} ${data.error.message?.substring(0, 80)}`);
        continue;
      }
      const raw = data.choices?.[0]?.message?.content?.trim();
      const content = raw ? raw.replace(/<think>[\s\S]*?<\/think>/g, '').trim() : '';
      if (content) {
        console.log(`✅ Модель: ${model} за ${elapsed}с`);
        lastUsedModel = model;
        return content;
      }
      console.warn(`⚠️ ${model} — порожня відповідь за ${elapsed}с`);
    } catch (e) {
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      console.warn(`⚠️ ${model} помилка за ${elapsed}с: ${e.message}`);
    }
  }
  return null;
}

// Швидкий виклик — для чату
async function callLLM(messages, maxTokens = 2000) {
  return callLLMWithList(MODELS, messages, maxTokens);
}

// Витягує перший валідний JSON з тексту. Якщо масив — обгортає в {scenes:[...]}
function extractJSON(text) {
  // Спочатку пробуємо ```json ... ``` блок
  const mdMatch = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (mdMatch) {
    try {
      const p = JSON.parse(mdMatch[1].trim());
      return Array.isArray(p) ? { scenes: p } : p;
    } catch(e) {}
  }

  const startBrace   = text.indexOf('{');
  const startBracket = text.indexOf('[');

  // Якщо масив раніше за об'єкт — LLM повернув просто масив сцен
  if (startBracket !== -1 && (startBrace === -1 || startBracket < startBrace)) {
    let depth = 0;
    for (let i = startBracket; i < text.length; i++) {
      if (text[i] === '[') depth++;
      else if (text[i] === ']') {
        depth--;
        if (depth === 0) {
          try { return { scenes: JSON.parse(text.slice(startBracket, i + 1)) }; } catch(e) { break; }
        }
      }
    }
  }

  // Звичайний об'єкт {…}
  const start = startBrace;
  if (start === -1) return null;
  let depth = 0;
  for (let i = start; i < text.length; i++) {
    if (text[i] === '{') depth++;
    else if (text[i] === '}') {
      depth--;
      if (depth === 0) {
        try { return JSON.parse(text.slice(start, i + 1)); } catch(e) { return null; }
      }
    }
  }
  return null;
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
  main:    SYSTEM_MAIN,
  shorts:  SYSTEM_SHORTS,
  story:   SYSTEM_STORY,
  joke:    SYSTEM_JOKE,
  comic:   SYSTEM_COMIC,
  cartoon: SYSTEM_CARTOON,
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
    new SlashCommandBuilder()
      .setName('comic')
      .setDescription('Анімований комікс: 2 персонажі + діалог + декорації + озвучка')
      .addStringOption(o => o.setName('тема').setDescription('Тема коміксу').setRequired(true)),
    new SlashCommandBuilder()
      .setName('cartoon')
      .setDescription('Міні-мультик: 3 персонажі ходять і розмовляють + декорації + озвучка')
      .addStringOption(o => o.setName('тема').setDescription('Тема мультика').setRequired(true)),
  ].map(c => c.toJSON());

  const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);
  try {
    await rest.put(Routes.applicationCommands(bot.user.id), { body: commands });
    console.log('✅ Slash команди зареєстровано: /shorts /story /makevideo /stickman /comic /cartoon');
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

  // Discord дає 3 секунди на відповідь — якщо протухло (рестарт Railway) — просто ігноруємо
  try {
    await interaction.deferReply();
  } catch (e) {
    console.error(`⚠️ deferReply failed (interaction expired): ${e.message}`);
    return;
  }

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

  } else if (cmd === 'comic') {
    // ── Comic: AI сценарій → два стікмени + декорації + озвучка → MP4 ──
    console.log(`🎭 /comic: "${tema}"`);
    await interaction.editReply('📝 Генерую сценарій коміксу...');

    const raw = await callAgent('comic', tema);
    if (!raw) { await interaction.editReply('⚠️ Не вдалось згенерувати сценарій.'); return; }

    const parsed = extractJSON(raw);
    if (!parsed) { await interaction.editReply(`⚠️ Некоректний формат сценарію:\n\`\`\`${raw.substring(0,300)}\`\`\``); return; }

    const scenes = parsed.scenes || [];
    const preview = scenes.map((s,i) => `**${i+1}. ${s.background}**\n🔵 ${s.left}\n🔴 ${s.right}`).join('\n\n');
    await interaction.editReply(`📝 Сценарій:\n\n${preview}\n\n🎙 Озвучую + малюю...`);

    try {
      const videoFile = await makeComicVideo(JSON.stringify(parsed));
      const attachment = new AttachmentBuilder(videoFile, { name: 'comic.mp4' });
      await interaction.followUp({ content: '✅ Комікс готовий! 🎭', files: [attachment] });
      fs.unlinkSync(videoFile);
    } catch (e) {
      console.error('comic помилка:', e.message);
      await interaction.followUp(`⚠️ Помилка: ${e.message}`);
    }
    archiveSave(interaction.user.id, tema, JSON.stringify(parsed), 'comic');

  } else if (cmd === 'cartoon') {
    // ── Cartoon: AI сценарій → 3 стікмени ходять + декорації + озвучка → MP4 ──
    console.log(`🎬 /cartoon: "${tema}"`);
    await interaction.editReply('📝 Генерую сценарій мультика...');

    // Готовий сюжет від МолтБота (без LLM) — /cartoon моя
    // Епізод 1: "Оптимізація"
    const DEMO_STORY = {"scenes":[{"background":"офіс","enter":[{"char":2,"from":"right"},{"char":0,"from":"left"}],"exit":[{"char":0}],"dialogs":[{"char":2,"text":"Остапе, ти звільнений.","emotion":"normal"},{"char":0,"text":"Що?! Чому?!","emotion":"surprised"},{"char":2,"text":"Тебе замінить штучний інтелект.","emotion":"normal"},{"char":0,"text":"Але я тут десять років!","emotion":"angry"},{"char":2,"text":"Саме тому. Він менше їсть.","emotion":"normal"}]},{"background":"офіс","enter":[{"char":0,"from":"left"},{"char":1,"from":"right"}],"exit":[{"char":0},{"char":1}],"dialogs":[{"char":0,"text":"Поліно, Миколу теж звільнили!","emotion":"surprised"},{"char":1,"text":"Знаю. Він теж AI тепер.","emotion":"sad"},{"char":0,"text":"Наш бос — бот?!","emotion":"surprised"},{"char":1,"text":"Був. Його теж замінили.","emotion":"sad"},{"char":0,"text":"Хто тепер керує?","emotion":"normal"},{"char":1,"text":"Excel. Версія 2019.","emotion":"sad"}]},{"background":"місто","enter":[{"char":0,"from":"left"},{"char":1,"from":"right"}],"exit":[{"char":0},{"char":1}],"dialogs":[{"char":0,"text":"Буду шукати нову роботу.","emotion":"normal"},{"char":1,"text":"Я вже відправила сто резюме.","emotion":"talking"},{"char":0,"text":"Є відповіді?","emotion":"normal"},{"char":1,"text":"Всі від ботів.","emotion":"sad"},{"char":0,"text":"Відмови?","emotion":"surprised"},{"char":1,"text":"Пропозиції. Стати ботом.","emotion":"angry"}]}]};

    let parsed;
    if (tema.toLowerCase().trim() === 'моя') {
      parsed = DEMO_STORY;
    } else {
      const raw = await callLLMWithList(MODELS, [
        { role: 'system', content: SYSTEM_CARTOON },
        { role: 'user', content: tema },
      ], 4000);
      if (!raw) { await interaction.editReply('⚠️ Не вдалось згенерувати сценарій.'); return; }

      parsed = extractJSON(raw);
      if (!parsed || !parsed.scenes || !parsed.scenes.length) {
        await interaction.editReply(`⚠️ Некоректний формат (немає scenes):\n\`\`\`${(raw||'').substring(0,300)}\`\`\``);
        return;
      }
    }

    const charNames = ['🔵 Остап', '🔴 Поліна', '🟢 Микола'];
    const scenes = parsed.scenes || [];
    const preview = scenes.map((s, i) => {
      const enters = (s.enter || []).map(e => `${charNames[e.char]} входить ${e.from === 'left' ? 'зліва' : 'справа'}`).join(', ');
      const dlgs = (s.dialogs || []).map(d => 'beat' in d ? `⏸ пауза ${d.beat}с` : `${charNames[d.char]}: "${d.text}"`).join('\n');
      return `**${i+1}. ${s.background}**${enters ? `\n_${enters}_` : ''}\n${dlgs}`;
    }).join('\n\n');
    await interaction.editReply(`📝 Сценарій:\n\n${preview.substring(0, 1800)}\n\n🎙 Малюю мультик...`);

    try {
      const videoFile = await makeCartoonVideo(JSON.stringify(parsed));
      const attachment = new AttachmentBuilder(videoFile, { name: 'cartoon.mp4' });
      await interaction.followUp({ content: '✅ Мультик готовий! 🎬', files: [attachment] });
      
      // 📸 Завантажуємо 3 скріншоти з відео
      const path = require('path');
      const screenshotsDir = path.join(path.dirname(videoFile), 'screenshots');
      const screenshotFiles = [
        path.join(screenshotsDir, 'frame_02.png'),
        path.join(screenshotsDir, 'frame_04.png'),
        path.join(screenshotsDir, 'frame_06.png'),
      ].filter(f => fs.existsSync(f));
      
      if (screenshotFiles.length > 0) {
        const screenshotAttachments = screenshotFiles.map(f => 
          new AttachmentBuilder(f, { name: `screenshot_${path.basename(f)}` })
        );
        await interaction.followUp({ content: '📸 Скріншоти:', files: screenshotAttachments });
      }
      
      fs.unlinkSync(videoFile);
    } catch (e) {
      console.error('cartoon помилка:', e.message);
      await interaction.followUp(`⚠️ Помилка: ${e.message}`);
    }
    archiveSave(interaction.user.id, tema, JSON.stringify(parsed), 'cartoon');
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
