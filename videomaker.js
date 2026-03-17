const Replicate = require('replicate');
const { execSync, exec } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');

const replicate = new Replicate({ auth: process.env.REPLICATE_API_KEY });

// ─── Завантажити файл за URL ────────────────────────────────────────────────

function downloadFile(url, dest) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    const lib = url.startsWith('https') ? https : http;
    lib.get(url, res => {
      res.pipe(file);
      file.on('finish', () => file.close(resolve));
    }).on('error', err => {
      fs.unlink(dest, () => {});
      reject(err);
    });
  });
}

// ─── Генерація зображень через Replicate (FLUX) ────────────────────────────

async function generateImages(prompts) {
  const imageFiles = [];
  console.log(`🎨 Генерую ${prompts.length} зображень...`);

  for (let i = 0; i < prompts.length; i++) {
    try {
      const output = await replicate.run(
        'black-forest-labs/flux-schnell',
        { input: { prompt: prompts[i], num_outputs: 1, aspect_ratio: '9:16' } }
      );
      const url = Array.isArray(output) ? output[0] : output;
      const dest = `/tmp/img_${i}.jpg`;
      await downloadFile(url.url ? url.url() : url, dest);
      imageFiles.push(dest);
      console.log(`🎨 Зображення ${i + 1}/${prompts.length} готове`);
    } catch (e) {
      console.error(`🎨 Помилка зображення ${i}:`, e.message);
    }
  }
  return imageFiles;
}

// ─── Озвучка через edge-tts ────────────────────────────────────────────────

async function generateVoice(text, outputFile) {
  return new Promise((resolve, reject) => {
    // Використовуємо edge-tts через CLI якщо доступний, інакше через npm
    const cmd = `npx edge-tts --voice uk-UA-OstapNeural --text "${text.replace(/"/g, "'")}" --write-media ${outputFile}`;
    exec(cmd, (err) => {
      if (err) {
        console.error('TTS помилка:', err.message);
        reject(err);
      } else {
        console.log('🎙 Озвучка готова');
        resolve();
      }
    });
  });
}

// ─── Монтаж відео через FFmpeg ─────────────────────────────────────────────

function assembleVideo(imageFiles, audioFile, outputFile) {
  if (imageFiles.length === 0) throw new Error('Немає зображень для монтажу');

  // Тривалість кожного зображення = загальна тривалість / кількість зображень
  const audioDuration = getAudioDuration(audioFile);
  const imgDuration = Math.max(2, audioDuration / imageFiles.length);

  // Створюємо список зображень для FFmpeg
  const listFile = '/tmp/images.txt';
  const listContent = imageFiles.map(f => `file '${f}'\nduration ${imgDuration.toFixed(2)}`).join('\n');
  fs.writeFileSync(listFile, listContent);

  const cmd = `ffmpeg -y -f concat -safe 0 -i ${listFile} -i ${audioFile} -c:v libx264 -c:a aac -shortest -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" ${outputFile}`;
  console.log('🎬 Монтую відео...');
  execSync(cmd, { stdio: 'pipe' });
  console.log('🎬 Відео готове!');
}

function getAudioDuration(audioFile) {
  try {
    const result = execSync(`ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 ${audioFile}`).toString().trim();
    return parseFloat(result) || 30;
  } catch {
    return 30;
  }
}

// ─── Головна функція ───────────────────────────────────────────────────────

async function makeShortVideo(script) {
  const workDir = `/tmp/short_${Date.now()}`;
  fs.mkdirSync(workDir, { recursive: true });

  try {
    // 1. Витягуємо текст для озвучки і промпти для зображень з скрипту
    const voiceText = extractVoiceText(script);
    const imagePrompts = extractImagePrompts(script);

    console.log(`📝 Текст озвучки: ${voiceText.substring(0, 100)}...`);
    console.log(`🖼 Промптів для зображень: ${imagePrompts.length}`);

    // 2. Генеруємо зображення
    const imageFiles = await generateImages(imagePrompts);
    if (imageFiles.length === 0) throw new Error('Не вдалось згенерувати зображення');

    // 3. Генеруємо озвучку
    const audioFile = `${workDir}/voice.mp3`;
    await generateVoice(voiceText, audioFile);

    // 4. Монтуємо відео
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
  // Витягуємо текст між секціями сценарію (без технічних міток)
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
      && !clean.startsWith('[')
      && !clean.match(/^\d+-\d+с/);
  });
  return voiceLines.join(' ').replace(/\*\*/g, '').substring(0, 500);
}

function extractImagePrompts(script) {
  // Генеруємо промпти на основі теми скрипту
  // Базові промпти + специфічні з секції 📸
  const baseStyle = 'cinematic, photorealistic, 8k, dramatic lighting, vertical format 9:16';
  const prompts = [];

  // Шукаємо секцію КАДРИ
  const cadryMatch = script.match(/📸[^:]*:([\s\S]*?)(?=🎵|#️⃣|$)/);
  if (cadryMatch) {
    const cadryText = cadryMatch[1];
    const lines = cadryText.split('\n').filter(l => l.trim().length > 5);
    lines.slice(0, 6).forEach(line => {
      prompts.push(`${line.trim()}, ${baseStyle}`);
    });
  }

  // Якщо промптів мало — додаємо загальні
  while (prompts.length < 4) {
    prompts.push(`prehistoric scene, dinosaurs, ancient world, ${baseStyle}`);
  }

  return prompts.slice(0, 8);
}

module.exports = { makeShortVideo };
