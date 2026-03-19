const { execSync, exec } = require('child_process');
const fs = require('fs');

// ─── Витягти сегменти сценарію (текст для слайдів) ─────────────────────────

function extractScriptSegments(script) {
  const segments = [];

  const hookMatch    = script.match(/ХУК[:\s]+([^\n\[]+)/);
  const zmistMatch   = script.match(/ЗМІСТ[:\s]+([^\n\[]+)/);
  const rozvMatch    = script.match(/РОЗВИТОК[:\s]+([^\n\[]+)/);
  const finalMatch   = script.match(/ФІНАЛ[^:\n]*[:\s]+([^\n\[]+)/);

  if (hookMatch)  segments.push(hookMatch[1].trim().substring(0, 80));
  if (zmistMatch) segments.push(zmistMatch[1].trim().substring(0, 80));
  if (rozvMatch)  segments.push(rozvMatch[1].trim().substring(0, 80));
  if (finalMatch) segments.push(finalMatch[1].trim().substring(0, 80));

  const defaults = ['Динозаври прокидаються', 'Мезозойська ера', 'Зустріч крізь час', 'Підписуйся!'];
  while (segments.length < 4) {
    segments.push(defaults[segments.length]);
  }

  return segments.slice(0, 4);
}

// ─── Створити слайд: кольоровий фон + текст через FFmpeg ───────────────────

function createTextSlide(text, index, dest) {
  const bgColors = ['0d1b2a', '1b0a2a', '0a2818', '2a1808'];
  const color = bgColors[index % bgColors.length];
  const pngDest = dest.replace('.jpg', '.png');
  const textFile = `/tmp/text_slide_${index}.txt`;

  // Перенос рядка кожні ~18 символів
  const words = text.split(' ');
  const lines = [];
  let line = '';
  for (const w of words) {
    if ((line + ' ' + w).trim().length > 18) {
      if (line) lines.push(line.trim());
      line = w;
    } else {
      line = (line + ' ' + w).trim();
    }
  }
  if (line) lines.push(line.trim());
  fs.writeFileSync(textFile, lines.slice(0, 6).join('\n'));

  const cmd = [
    'ffmpeg -y -loglevel error',
    `-f lavfi -i "color=c=${color}:size=720x1280"`,
    '-frames:v 1',
    `-vf "drawtext=textfile='${textFile}':fontcolor=white:fontsize=52:x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=20:shadowcolor=black@0.8:shadowx=3:shadowy=3"`,
    `"${pngDest}"`,
  ].join(' ');

  execSync(cmd, { stdio: 'pipe' });
  console.log(`🎨 Слайд ${index + 1} готовий`);
  return pngDest;
}

function createFallbackSlide(index, dest) {
  const colors = ['0x0d1b2a', '0x1b0a2a', '0x0a2818', '0x2a1808'];
  const color = colors[index % colors.length];
  const pngDest = dest.replace('.jpg', '.png');
  execSync(`ffmpeg -y -loglevel error -f lavfi -i "color=c=${color}:size=720x1280" -frames:v 1 "${pngDest}"`, { stdio: 'pipe' });
  return pngDest;
}

// ─── Генерація слайдів ──────────────────────────────────────────────────────

async function generateImages(segments) {
  const imageFiles = [];
  for (let i = 0; i < segments.length; i++) {
    const dest = `/tmp/img_${i}.jpg`;
    try {
      const slidePath = createTextSlide(segments[i], i, dest);
      imageFiles.push(slidePath);
    } catch (e) {
      console.warn(`⚠️ Слайд ${i + 1} не вдався (${e.message.substring(0, 40)}), fallback...`);
      try {
        imageFiles.push(createFallbackSlide(i, dest));
      } catch {}
    }
  }
  return imageFiles;
}

// ─── Озвучка через edge-tts ────────────────────────────────────────────────

async function generateVoice(text, outputFile) {
  return new Promise((resolve, reject) => {
    const safeText = text.substring(0, 400).replace(/"/g, "'").replace(/\n/g, ' ');
    const cmd = `edge-tts --voice uk-UA-OstapNeural --text "${safeText}" --write-media ${outputFile}`;
    console.log('🎙 Запускаю edge-tts...');
    exec(cmd, { timeout: 60000 }, (err, stdout, stderr) => {
      if (err) {
        console.error('TTS помилка:', err.message);
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
  if (imageFiles.length === 0) throw new Error('Немає слайдів для монтажу');

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
    '-pix_fmt yuv420p',
    '-c:a aac -shortest',
    '-vf "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280"',
    `"${outputFile}"`,
  ].join(' ');

  console.log('🎬 Монтую відео (720x1280, ultrafast)...');
  execSync(cmd, { stdio: 'pipe', timeout: 180000 });
  console.log('🎬 Відео готове!');
}

// ─── Парсинг тексту для озвучки ────────────────────────────────────────────

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

// ─── Головна функція ───────────────────────────────────────────────────────

async function makeShortVideo(script) {
  const workDir = `/tmp/short_${Date.now()}`;
  fs.mkdirSync(workDir, { recursive: true });

  try {
    const voiceText = extractVoiceText(script);
    const segments = extractScriptSegments(script);

    console.log(`📝 Текст озвучки (${voiceText.length} символів): ${voiceText.substring(0, 80)}...`);
    console.log(`🖼 Сегментів для слайдів: ${segments.length}`);

    const audioFile = `${workDir}/voice.mp3`;
    const [imageFiles] = await Promise.all([
      generateImages(segments),
      generateVoice(voiceText, audioFile),
    ]);

    if (imageFiles.length === 0) throw new Error('Не вдалось створити слайди');

    const outputFile = `${workDir}/short.mp4`;
    assembleVideo(imageFiles, audioFile, outputFile);

    return outputFile;
  } catch (e) {
    console.error('makeShortVideo помилка:', e.message);
    throw e;
  }
}

module.exports = { makeShortVideo };
