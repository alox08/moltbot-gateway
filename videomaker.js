const { execSync, exec } = require('child_process');
const fs = require('fs');
const https = require('https');
const http = require('http');

// ─── Завантажити файл за URL ────────────────────────────────────────────────

function downloadFile(url, dest, timeoutMs = 25000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Timeout 25s')), timeoutMs);

    const request = (reqUrl) => {
      const lib = reqUrl.startsWith('https') ? https : http;
      lib.get(reqUrl, res => {
        if (res.statusCode === 301 || res.statusCode === 302 || res.statusCode === 307) {
          return request(res.headers.location);
        }
        if (res.statusCode !== 200) {
          clearTimeout(timer);
          reject(new Error(`HTTP ${res.statusCode}`));
          return;
        }
        const file = fs.createWriteStream(dest);
        res.pipe(file);
        file.on('finish', () => { clearTimeout(timer); file.close(resolve); });
        file.on('error', err => { clearTimeout(timer); fs.unlink(dest, () => {}); reject(err); });
      }).on('error', err => {
        clearTimeout(timer);
        fs.unlink(dest, () => {});
        reject(err);
      });
    };
    request(url);
  });
}

function createFallbackImage(index, dest) {
  const colors = ['0x0d1b2a', '0x1b2838', '0x162032', '0x0a1628'];
  const color = colors[index % colors.length];
  // PNG формат — без JPEG артефактів
  const pngDest = dest.replace('.jpg', '.png');
  execSync(`ffmpeg -y -f lavfi -i "color=c=${color}:size=576x1024" -frames:v 1 "${pngDest}"`, { stdio: 'pipe' });
  console.log(`🎨 Fallback: кольоровий фон для зображення ${index}`);
  return pngDest;
}

// ─── Генерація зображень через Replicate (FLUX Schnell) ────────────────────

// ─── Генерація зображень через Pollinations.ai (безкоштовно, без API ключа) ─

async function generateImages(prompts) {
  const imageFiles = [];
  const limited = prompts.slice(0, 4);
  console.log(`🎨 Генерую ${limited.length} зображень через Pollinations.ai...`);

  for (let i = 0; i < limited.length; i++) {
    const dest = `/tmp/img_${i}.jpg`;
    try {
      const shortPrompt = limited[i].substring(0, 120);
      const encoded = encodeURIComponent(shortPrompt);
      const url = `https://image.pollinations.ai/prompt/${encoded}?width=576&height=1024&nologo=true&seed=${i + 1}`;
      console.log(`🎨 Завантажую зображення ${i + 1}/${limited.length}...`);
      await downloadFile(url, dest);
      console.log(`🎨 Зображення ${i + 1}/${limited.length} готове`);
    } catch (e) {
      console.warn(`🎨 Pollinations не відповів (${e.message.substring(0, 40)}), fallback...`);
      try {
        const fallbackDest = createFallbackImage(i, dest);
        imageFiles.push(fallbackDest);
      } catch (fe) {
        console.error(`🎨 Fallback теж не вдався:`, fe.message);
      }
      continue;
    }
    imageFiles.push(dest);
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
    'ffmpeg -y -loglevel error',
    `-f concat -safe 0 -i "${listFile}"`,
    `-i "${audioFile}"`,
    '-c:v libx264 -preset ultrafast -crf 28 -threads 1',
    '-c:a aac -shortest',
    '-vf "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280"',
    `"${outputFile}"`,
  ].join(' ');

  console.log('🎬 Монтую відео (720x1280, ultrafast)...');
  execSync(cmd, { stdio: 'pipe', timeout: 180000 });
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
