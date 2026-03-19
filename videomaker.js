const { execSync, exec } = require('child_process');
const fs = require('fs');
const https = require('https');

// ─── Генерація зображень через Stability AI ────────────────────────────────

async function generateImageStability(prompt, dest) {
  const apiKey = process.env.STABILITY_API_KEY;
  const shortPrompt = prompt.substring(0, 200);

  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      text_prompts: [
        { text: shortPrompt, weight: 1 },
        { text: 'blurry, low quality, text, watermark', weight: -1 },
      ],
      cfg_scale: 7,
      height: 1024,
      width: 576,
      samples: 1,
      steps: 30,
    });

    const options = {
      hostname: 'api.stability.ai',
      path: '/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': `Bearer ${apiKey}`,
      },
    };

    const req = https.request(options, res => {
      let data = '';
      res.on('data', chunk => { data += chunk; });
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          if (json.artifacts && json.artifacts[0]) {
            const imgBuffer = Buffer.from(json.artifacts[0].base64, 'base64');
            fs.writeFileSync(dest, imgBuffer);
            resolve();
          } else {
            reject(new Error(json.message || JSON.stringify(json).substring(0, 100)));
          }
        } catch (e) {
          reject(new Error(`Parse error: ${e.message}`));
        }
      });
    });

    req.on('error', reject);
    req.setTimeout(60000, () => { req.destroy(); reject(new Error('Timeout 60s')); });
    req.write(body);
    req.end();
  });
}

async function generateImages(prompts) {
  const imageFiles = [];
  const limited = prompts.slice(0, 4);
  console.log(`🎨 Генерую ${limited.length} зображень через Stability AI...`);

  for (let i = 0; i < limited.length; i++) {
    const dest = `/tmp/img_${i}.png`;
    try {
      console.log(`🎨 Зображення ${i + 1}/${limited.length}...`);
      await generateImageStability(limited[i], dest);
      console.log(`🎨 Зображення ${i + 1} готове`);
      imageFiles.push(dest);
    } catch (e) {
      console.warn(`⚠️ Stability AI помилка (${e.message.substring(0, 60)}), fallback...`);
      try {
        const fallback = createFallbackImage(i, dest);
        imageFiles.push(fallback);
      } catch {}
    }
  }
  return imageFiles;
}

// ─── Fallback: кольоровий фон ──────────────────────────────────────────────

function createFallbackImage(index, dest) {
  const colors = ['0x0d1b2a', '0x1b0a2a', '0x0a2818', '0x2a1808'];
  const color = colors[index % colors.length];
  const pngDest = dest.replace('.jpg', '.png');
  execSync(`ffmpeg -y -loglevel error -f lavfi -i "color=c=${color}:size=576x1024" -frames:v 1 "${pngDest}"`, { stdio: 'pipe' });
  console.log(`🎨 Fallback фон для зображення ${index + 1}`);
  return pngDest;
}

// ─── Озвучка через edge-tts ────────────────────────────────────────────────

async function generateVoice(text, outputFile) {
  return new Promise((resolve, reject) => {
    const safeText = text.substring(0, 400).replace(/"/g, "'").replace(/\n/g, ' ');
    const cmd = `edge-tts --voice uk-UA-OstapNeural --text "${safeText}" --write-media ${outputFile}`;
    console.log('🎙 Запускаю edge-tts...');
    exec(cmd, { timeout: 60000 }, (err) => {
      if (err) { reject(new Error(`edge-tts: ${err.message}`)); }
      else { console.log('🎙 Озвучка готова'); resolve(); }
    });
  });
}

// ─── Монтаж з Ken Burns ефектом ────────────────────────────────────────────

function getAudioDuration(audioFile) {
  try {
    const result = execSync(
      `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "${audioFile}"`
    ).toString().trim();
    return parseFloat(result) || 30;
  } catch { return 30; }
}

function assembleVideo(imageFiles, audioFile, outputFile) {
  if (imageFiles.length === 0) throw new Error('Немає зображень для монтажу');

  const audioDuration = getAudioDuration(audioFile);
  const imgDuration = Math.max(3, audioDuration / imageFiles.length);
  const fps = 25;
  const frames = Math.ceil(imgDuration * fps);

  // Ken Burns ефекти: zoom in, pan right, zoom out, pan left
  const kenBurns = [
    `scale=8000:-1,zoompan=z='min(zoom+0.0015,1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=${frames}:s=720x1280:fps=${fps}`,
    `scale=8000:-1,zoompan=z='1.3':x='if(lte(on,1),0,x+1.5)':y='ih/2-(ih/zoom/2)':d=${frames}:s=720x1280:fps=${fps}`,
    `scale=8000:-1,zoompan=z='max(zoom-0.001,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=${frames}:s=720x1280:fps=${fps}`,
    `scale=8000:-1,zoompan=z='1.2':x='if(lte(on,1),iw,x-1.5)':y='ih/2-(ih/zoom/2)':d=${frames}:s=720x1280:fps=${fps}`,
  ];

  // Генеруємо кожен кліп з Ken Burns окремо
  const clipFiles = [];
  for (let i = 0; i < imageFiles.length; i++) {
    const clipFile = `/tmp/clip_${i}.mp4`;
    const effect = kenBurns[i % kenBurns.length];
    const cmd = [
      'ffmpeg -y -loglevel error',
      `-loop 1 -i "${imageFiles[i]}"`,
      `-vf "${effect}"`,
      `-c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p`,
      `-t ${imgDuration.toFixed(2)} -threads 1`,
      `"${clipFile}"`,
    ].join(' ');
    execSync(cmd, { stdio: 'pipe', timeout: 120000 });
    clipFiles.push(clipFile);
    console.log(`🎬 Кліп ${i + 1}/${imageFiles.length} з Ken Burns готовий`);
  }

  // Склеюємо кліпи
  const listFile = '/tmp/clips.txt';
  fs.writeFileSync(listFile, clipFiles.map(f => `file '${f}'`).join('\n'));

  const cmd = [
    'ffmpeg -y -loglevel error',
    `-f concat -safe 0 -i "${listFile}"`,
    `-i "${audioFile}"`,
    '-c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p',
    '-c:a aac -shortest -threads 1',
    `"${outputFile}"`,
  ].join(' ');

  console.log('🎬 Фінальний монтаж...');
  execSync(cmd, { stdio: 'pipe', timeout: 180000 });
  console.log('🎬 Відео готове!');
}

// ─── Парсинг сценарію ──────────────────────────────────────────────────────

function extractVoiceText(script) {
  const lines = script.split('\n');
  const voiceLines = lines.filter(l => {
    const clean = l.trim();
    return clean.length > 10
      && !clean.startsWith('#')
      && !clean.startsWith('🎵')
      && !clean.startsWith('📸')
      && !clean.startsWith('🎬')
      && !clean.startsWith('⏱')
      && !clean.startsWith('🎯')
      && !clean.startsWith('🎭')
      && !clean.startsWith('📖')
      && !clean.startsWith('#️⃣')
      && !clean.startsWith('[')
      && !clean.match(/^\d+-\d+с/);
  });
  return voiceLines.join(' ').replace(/\*\*/g, '').replace(/\*/g, '').trim();
}

function extractImagePrompts(script) {
  const baseStyle = 'cinematic, photorealistic, 8k, dramatic lighting, vertical format 9:16';
  const prompts = [];

  const cadryMatch = script.match(/📸[^:]*:([\s\S]*?)(?=🎵|#️⃣|$)/);
  if (cadryMatch) {
    const lines = cadryMatch[1].split('\n').filter(l => l.trim().length > 5);
    lines.slice(0, 4).forEach(line => {
      const clean = line.trim().replace(/^[-•*]\s*/, '');
      prompts.push(`${clean}, ${baseStyle}`);
    });
  }

  const dinoDefaults = [
    `T-Rex roaring in dense jungle at sunset, small primitive humans watching from distance, ${baseStyle}`,
    `primitive humans running from stampede of triceratops, dramatic sky, ${baseStyle}`,
    `Velociraptor pack hunting near river, early humans hiding in tall grass, ${baseStyle}`,
    `massive Brachiosaurus herd crossing river at golden hour, breathtaking landscape, ${baseStyle}`,
  ];

  while (prompts.length < 4) {
    prompts.push(dinoDefaults[prompts.length % dinoDefaults.length]);
  }

  return prompts.slice(0, 4);
}

// ─── Головна функція ───────────────────────────────────────────────────────

async function makeShortVideo(script) {
  const workDir = `/tmp/short_${Date.now()}`;
  fs.mkdirSync(workDir, { recursive: true });

  try {
    const voiceText = extractVoiceText(script);
    const imagePrompts = extractImagePrompts(script);

    console.log(`📝 Текст озвучки (${voiceText.length} символів): ${voiceText.substring(0, 80)}...`);
    console.log(`🖼 Промптів: ${imagePrompts.length}`);

    const audioFile = `${workDir}/voice.mp3`;
    const [imageFiles] = await Promise.all([
      generateImages(imagePrompts),
      generateVoice(voiceText, audioFile),
    ]);

    if (imageFiles.length === 0) throw new Error('Не вдалось згенерувати зображення');

    const outputFile = `${workDir}/short.mp4`;
    assembleVideo(imageFiles, audioFile, outputFile);

    return outputFile;
  } catch (e) {
    console.error('makeShortVideo помилка:', e.message);
    throw e;
  }
}

module.exports = { makeShortVideo };
