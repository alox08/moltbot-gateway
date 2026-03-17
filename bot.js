const { Client, GatewayIntentBits } = require('discord.js');

const client = new Client({
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
Спеціалізуєшся на YouTube Shorts (сценарії до 60с) і коротких оповіданнях (текст + озвучка + відео).`;

client.on('ready', () => {
  console.log(`✅ МолтБот запущений як ${client.user.tag}`);
  console.log(`📺 Слухаю канал: #${ALLOWED_CHANNEL}`);
});

client.on('messageCreate', async (message) => {
  if (message.author.bot) return;
  if (message.channel.name !== ALLOWED_CHANNEL) return;

  const userMessage = message.content.trim();
  if (!userMessage) return;

  console.log(`💬 [${message.author.username}]: ${userMessage}`);

  await message.channel.sendTyping();

  try {
    const response = await fetch('https://openrouter.ai/api/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${process.env.OPENROUTER_API_KEY}`,
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://moltbot.railway.app',
        'X-Title': 'MoltBot',
      },
      body: JSON.stringify({
        model: 'nvidia/nemotron-3-super-120b-a12b:free',
        messages: [
          { role: 'system', content: SYSTEM_PROMPT },
          { role: 'user', content: userMessage }
        ],
        max_tokens: 1500,
      })
    });

    const data = await response.json();

    if (data.choices && data.choices[0]) {
      let reply = data.choices[0].message.content.trim();

      // Видаляємо <think>...</think> блоки (DeepSeek R1 іноді додає)
      reply = reply.replace(/<think>[\s\S]*?<\/think>/g, '').trim();

      if (!reply) {
        await message.reply('🤔 МолтБот думає... Спробуй ще раз.');
        return;
      }

      // Discord ліміт 2000 символів
      if (reply.length > 1990) {
        reply = reply.substring(0, 1990) + '...';
      }

      await message.reply(reply);
      console.log(`✅ Відповів: ${reply.substring(0, 80)}...`);
    } else {
      console.error('Unexpected API response:', JSON.stringify(data));
      await message.reply('⚠️ Помилка відповіді від AI. Спробуй ще раз.');
    }
  } catch (error) {
    console.error('Error calling OpenRouter:', error);
    await message.reply('⚠️ Помилка зʼєднання з AI.');
  }
});

client.login(process.env.DISCORD_TOKEN);
