const { execSync, exec } = require('child_process');
const fs = require('fs');
const https = require('https');
const http = require('http');

// ─── Завантажити файл за URL ────────────────────────────────────────────────

function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    const lib = url.startsWith('https') ? https : http;
    lib.get(url, res => {
      if (res.statusCode !== 200) {
        reject(new Error(`HTTP ${res.statusCode} для ${url}`));
        return;
      }
      res.pipe(file);
      file.on('finish', () => file.close(resolve));
    }).on('error', err => {
      fs.unlink(dest, () => {});
      reject(err);
    });
  });
}

// ─── Генерація зображень через Replicate (FLUX Schnell) ────────────────────

// ─── Генерація зображень через Pollinations.ai (безкоштовно, без API ключа) ─

async function generateImages(prompts) {
  const imageFiles = [];
  const limited = prompts.slice(0, 4);
  console.log(`🎨 Генерую ${limited.length} зображень через Pollinations.ai...`);

  for (let i = 0; i < limited.length; i++) {
    try {
      const encoded = encodeURIComponent(limited[i]);
      const url = `https://image.pollinations.ai/prompt/${encoded}?width=576&height=1024&nologo=true&seed=${Date.now() + i}`;
      const dest = `/tmp/img_${i}.jpg`;
      console.log(`🎨 Завантажую зображення ${i + 1}/${limited.length}...`);
      await downloadFile(url, dest);
      imageFiles.push(dest);
      console.log(`🎨 Зображення ${i + 1}/${limited.length} готове`);
    } catch (e) {
      console.error(`🎨 Помилка зображення ${i}:`, e.message);
    }
  }
  return imageFiles;
}

// ─── Озвучка через edge-tts (Python CLI) ──────────────────────────────────

async function generateVoice(text, outputFile) {
  return new Promise((resolve, reject) => {
    // Обрізаємо текст до розумного розміру для TTS
    const safeText = text.substring(0, 400).replace(/"/g, "'").replace(/\n/g, ' ');
    const cmd = `edge-tts --voice uk-UA-OstapNeural --text "${safeText}" --write-media ${outputFile}`;
    console.log('🎙 Запускаю edge-tts...');
    exec(cmd, { timeout: 60000 }, (err, stdout, stderr) => {
      if (err) {
        console.error('TTS помилка:', err.message);
        console.error('TTS stderr:', stderr);
        reject(new Error(`edge-tts: ${err.message}`));
      } else {
        console.log('🎙 Озвучка готова');
        resolve();
      }
    });
  });
}

// ─── Монтаж відео через FFmpeg ─────────────────────────────────────────────

function getAudioDuration(audioFile) {
  try {
    const result = execSync(
      `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "${audioFile}"`
    ).toString().trim();
    return parseFloat(result) || 30;
  } catch {
    return 30;
  }
}

function assembleVideo(imageFiles, audioFile, outputFile) {
  if (imageFiles.length === 0) throw new Error('Немає зображень для монтажу');

  const audioDuration = getAudioDuration(audioFile);
  const imgDuration = Math.max(2, audioDuration / imageFiles.length);

  const listFile = '/tmp/images.txt';
  const listContent = imageFiles.map(f => `file '${f}'\nduration ${imgDuration.toFixed(2)}`).join('\n');
  fs.writeFileSync(listFile, listContent);

  const cmd = [
    'ffmpeg -y',
    `-f concat -safe 0 -i "${listFile}"`,
    `-i "${audioFile}"`,
    '-c:v libx264 -c:a aac -shortest',
    '-vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"',
    `"${outputFile}"`,
  ].join(' ');

  console.log('🎬 Монтую відео...');
  execSync(cmd, { stdio: 'pipe', timeout: 120000 });
  console.log('🎬 Відео готове!');
}

// ─── Головна функція ───────────────────────────────────────────────────────

async function makeShortVideo(script) {
  const workDir = `/tmp/short_${Date.now()}`;
  fs.mkdirSync(workDir, { recursive: true });

  try {
    const voiceText = extractVoiceText(script);
    const imagePrompts = extractImagePrompts(script);

    console.log(`📝 Текст озвучки (${voiceText.length} символів): ${voiceText.substring(0, 80)}...`);
    console.log(`🖼 Промптів для зображень: ${imagePrompts.length}`);

    // Паралельно генеруємо зображення і озвучку
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

// ─── Парсинг скрипту ───────────────────────────────────────────────────────

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
  const dinoTheme = `prehistoric era, dinosaurs and early humans, ${baseStyle}`;
  const prompts = [];

  // Шукаємо секцію КАДРИ (📸)
  const cadryMatch = script.match(/📸[^:]*:([\s\S]*?)(?=🎵|#️⃣|$)/);
  if (cadryMatch) {
    const lines = cadryMatch[1].split('\n').filter(l => l.trim().length > 5);
    lines.slice(0, 6).forEach(line => {
      const clean = line.trim().replace(/^[-•*]\s*/, '');
      prompts.push(`${clean}, ${baseStyle}`);
    });
  }

  // Дефолтні кадри для теми динозаврів і первісних людей
  const dinoDefaults = [
    `T-Rex roaring in dense jungle, small humans watching from distance, ${baseStyle}`,
    `primitive humans running from stampede of triceratops, sunset, ${baseStyle}`,
    `cave dwellers painting dinosaurs on cave walls by firelight, ${baseStyle}`,
    `breathtaking landscape with pterodactyls flying over river valley, ${baseStyle}`,
    `Velociraptor pack hunting, early humans hiding in tall grass, ${baseStyle}`,
    `massive Brachiosaurus herd crossing a river at golden hour, ${baseStyle}`,
  ];

  while (prompts.length < 4) {
    prompts.push(dinoDefaults[prompts.length % dinoDefaults.length]);
  }

  return prompts.slice(0, 6);
}

module.exports = { makeShortVideo };
