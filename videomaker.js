const { execSync, exec } = require('child_process');
const fs = require('fs');
const https = require('https');
const http = require('http');

// ─── Стікмен відео (edge-tts + Pillow + FFmpeg) ────────────────────────────

async function makeStickmanVideo(jokeText) {
  const workDir = `/tmp/stickman_${Date.now()}`;
  fs.mkdirSync(workDir, { recursive: true });

  const inputFile  = `${workDir}/input.json`;
  const outputFile = `${workDir}/final.mp4`;

  fs.writeFileSync(inputFile, JSON.stringify({ text: jokeText }));
  console.log(`🎬 stickman.py: "${jokeText.substring(0, 60)}..."`);

  execSync(`python3 /app/stickman.py --input "${inputFile}" --output "${outputFile}"`, {
    stdio: 'pipe',
    timeout: 240000,
  });

  return outputFile;
}

// ─── Завантажити файл за URL ───────────────────────────────────────────────

function downloadFile(url, dest, timeoutMs = 60000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Timeout 60s')), timeoutMs);
    const request = (reqUrl) => {
      const lib = reqUrl.startsWith('https') ? https : http;
      lib.get(reqUrl, res => {
        if ([301, 302, 307].includes(res.statusCode)) return request(res.headers.location);
        if (res.statusCode !== 200) { clearTimeout(timer); reject(new Error(`HTTP ${res.statusCode}`)); return; }
        const file = fs.createWriteStream(dest);
        res.pipe(file);
        file.on('finish', () => { clearTimeout(timer); file.close(resolve); });
        file.on('error', err => { clearTimeout(timer); fs.unlink(dest, () => {}); reject(err); });
      }).on('error', err => { clearTimeout(timer); reject(err); });
    };
    request(url);
  });
}

// ─── Pexels: пошук і завантаження відео ───────────────────────────────────

async function searchPexelsVideos(query, count = 4) {
  return new Promise((resolve, reject) => {
    const encoded = encodeURIComponent(query);
    const options = {
      hostname: 'api.pexels.com',
      path: `/videos/search?query=${encoded}&per_page=${count}&size=medium`,
      headers: { 'Authorization': process.env.PEXELS_API_KEY },
    };
    https.get(options, res => {
      let data = '';
      res.on('data', chunk => { data += chunk; });
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          resolve(json.videos || []);
        } catch (e) { reject(e); }
      });
    }).on('error', reject);
  });
}

function getBestVideoUrl(video) {
  const files = (video.video_files || [])
    .filter(f => f.width && f.height)
    .sort((a, b) => b.height - a.height);
  const hd = files.find(f => f.quality === 'hd' && f.height <= 1920) || files[0];
  return hd ? hd.link : null;
}

async function downloadPexelsClips(keywords, count = 4) {
  const clips = [];
  console.log(`🎬 Шукаю відео на Pexels: "${keywords}"...`);

  try {
    const videos = await searchPexelsVideos(keywords, count * 2); // беремо більше про запас
    console.log(`🎬 Знайдено ${videos.length} відео`);

    for (let i = 0; i < Math.min(videos.length, count); i++) {
      const url = getBestVideoUrl(videos[i]);
      if (!url) continue;
      const dest = `/tmp/pexels_${i}.mp4`;
      try {
        console.log(`⬇️ Завантажую кліп ${i + 1}...`);
        await downloadFile(url, dest);
        clips.push(dest);
        console.log(`✅ Кліп ${i + 1} завантажено`);
      } catch (e) {
        console.warn(`⚠️ Кліп ${i + 1} не завантажився: ${e.message}`);
      }
    }
  } catch (e) {
    console.error('Pexels помилка:', e.message);
  }

  return clips;
}

// ─── Обробка кліпу: обрізати до потрібної тривалості + кроп 9:16 + текст ──

function processClip(inputFile, outputFile, duration, text, index) {
  const textFile = `/tmp/clip_text_${index}.txt`;

  // Перенос рядків кожні ~20 символів
  const words = text.split(' ');
  const lines = [];
  let line = '';
  for (const w of words) {
    if ((line + ' ' + w).trim().length > 20) {
      if (line) lines.push(line.trim());
      line = w;
    } else {
      line = (line + ' ' + w).trim();
    }
  }
  if (line) lines.push(line.trim());
  fs.writeFileSync(textFile, lines.slice(0, 4).join('\n'));

  // Crop до 9:16, обрізати до потрібної тривалості, накласти текст
  const vf = [
    `scale=480:854:force_original_aspect_ratio=increase`,
    `crop=480:854`,
    `drawtext=textfile='${textFile}':fontcolor=white:fontsize=38:x=(w-text_w)/2:y=h-150:line_spacing=12:shadowcolor=black@0.9:shadowx=2:shadowy=2`,
  ].join(',');

  const cmd = [
    'ffmpeg -y -loglevel error',
    `-i "${inputFile}"`,
    `-t ${duration.toFixed(2)}`,
    `-vf "${vf}"`,
    '-c:v libx264 -preset ultrafast -crf 33 -pix_fmt yuv420p',
    '-an -threads 1',
    `"${outputFile}"`,
  ].join(' ');

  execSync(cmd, { stdio: 'pipe', timeout: 120000 });
}

// ─── Парсинг сценарію ──────────────────────────────────────────────────────

function extractScriptSegments(script) {
  const segments = [];
  const hookMatch  = script.match(/ХУК[:\s]+([^\n\[]+)/);
  const zmistMatch = script.match(/ЗМІСТ[:\s]+([^\n\[]+)/);
  const rozvMatch  = script.match(/РОЗВИТОК[:\s]+([^\n\[]+)/);
  const finalMatch = script.match(/ФІНАЛ[^:\n]*[:\s]+([^\n\[]+)/);

  if (hookMatch)  segments.push(hookMatch[1].trim().substring(0, 80));
  if (zmistMatch) segments.push(zmistMatch[1].trim().substring(0, 80));
  if (rozvMatch)  segments.push(rozvMatch[1].trim().substring(0, 80));
  if (finalMatch) segments.push(finalMatch[1].trim().substring(0, 80));

  const defaults = ['Динозаври прокидаються', 'Мезозойська ера', 'Зустріч крізь час', 'Підписуйся!'];
  while (segments.length < 4) segments.push(defaults[segments.length]);
  return segments.slice(0, 4);
}

function extractSearchQuery(script) {
  // Беремо перші слова першого англійського промпту (до коми або 3 слова)
  const imageMatch = script.match(/📸[^:]*:([\s\S]*?)(?=🎵|#️⃣|$)/);
  if (imageMatch) {
    const firstLine = imageMatch[1].split('\n').find(l => l.trim().length > 10);
    if (firstLine) {
      const clean = firstLine.trim().replace(/^[-•*]\s*/, '');
      // Беремо перші 3 слова
      const words = clean.split(/[\s,]+/).slice(0, 3).join(' ');
      if (words.length > 3) return words;
    }
  }
  return 'dinosaur prehistoric';
}

// ─── Fallback: кольоровий фон + текст ─────────────────────────────────────

function createFallbackClip(text, index, outputFile, duration) {
  const bgColors = ['0d1b2a', '1b0a2a', '0a2818', '2a1808'];
  const color = bgColors[index % bgColors.length];
  const textFile = `/tmp/fallback_text_${index}.txt`;

  const words = text.split(' ');
  const lines = [];
  let line = '';
  for (const w of words) {
    if ((line + ' ' + w).trim().length > 20) {
      if (line) lines.push(line.trim());
      line = w;
    } else {
      line = (line + ' ' + w).trim();
    }
  }
  if (line) lines.push(line.trim());
  fs.writeFileSync(textFile, lines.slice(0, 4).join('\n'));

  const cmd = [
    'ffmpeg -y -loglevel error',
    `-f lavfi -i "color=c=${color}:size=480x854:rate=25"`,
    `-t ${duration.toFixed(2)}`,
    `-vf "drawtext=textfile='${textFile}':fontcolor=white:fontsize=52:x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=15:shadowcolor=black@0.8:shadowx=3:shadowy=3"`,
    '-c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p',
    '-an -threads 1',
    `"${outputFile}"`,
  ].join(' ');

  execSync(cmd, { stdio: 'pipe', timeout: 60000 });
  console.log(`🎨 Fallback кліп ${index + 1} готовий`);
}

// ─── Головна функція ───────────────────────────────────────────────────────

async function makeShortVideo(script) {
  const workDir = `/tmp/short_${Date.now()}`;
  fs.mkdirSync(workDir, { recursive: true });

  const CLIP_DURATION = 6; // секунд на кліп (4 кліпи = 24 сек)
  const CLIP_COUNT = 4;

  try {
    const segments = extractScriptSegments(script);
    const searchQuery = extractSearchQuery(script);

    console.log(`🔍 Пошуковий запит: "${searchQuery}"`);
    console.log(`📝 Сегментів тексту: ${segments.length}`);

    // Завантажуємо відео з Pexels
    const pexelsClips = await downloadPexelsClips(searchQuery, CLIP_COUNT);
    console.log(`📦 Завантажено ${pexelsClips.length} кліпів з Pexels`);

    // Обробляємо кожен кліп: кроп + текст
    const processedClips = [];
    for (let i = 0; i < CLIP_COUNT; i++) {
      const outputClip = `${workDir}/clip_${i}.mp4`;
      const text = segments[i] || segments[0];

      if (pexelsClips[i]) {
        try {
          processClip(pexelsClips[i], outputClip, CLIP_DURATION, text, i);
          processedClips.push(outputClip);
          console.log(`✂️ Кліп ${i + 1}/${CLIP_COUNT} оброблено`);
        } catch (e) {
          console.warn(`⚠️ Обробка кліпу ${i + 1} не вдалась: ${e.message}, fallback...`);
          createFallbackClip(text, i, outputClip, CLIP_DURATION);
          processedClips.push(outputClip);
        }
      } else {
        createFallbackClip(text, i, outputClip, CLIP_DURATION);
        processedClips.push(outputClip);
      }
    }

    // Склеюємо всі кліпи
    const listFile = `${workDir}/clips.txt`;
    fs.writeFileSync(listFile, processedClips.map(f => `file '${f}'`).join('\n'));

    const outputFile = `${workDir}/short.mp4`;
    const cmd = [
      'ffmpeg -y -loglevel error',
      `-f concat -safe 0 -i "${listFile}"`,
      '-c:v libx264 -preset ultrafast -crf 28 -pix_fmt yuv420p',
      '-threads 1',
      `"${outputFile}"`,
    ].join(' ');

    console.log('🎬 Фінальний монтаж...');
    execSync(cmd, { stdio: 'pipe', timeout: 180000 });
    console.log('🎬 Відео готове!');

    return outputFile;
  } catch (e) {
    console.error('makeShortVideo помилка:', e.message);
    throw e;
  }
}

// ─── Comic відео (два персонажі + декорації) ──────────────────────────────

async function makeComicVideo(scenesJson) {
  const workDir = `/tmp/comic_${Date.now()}`;
  fs.mkdirSync(workDir, { recursive: true });

  const inputFile  = `${workDir}/input.json`;
  const outputFile = `${workDir}/comic.mp4`;

  fs.writeFileSync(inputFile, scenesJson);
  console.log(`🎭 comic.py: ${JSON.parse(scenesJson).scenes.length} сцен`);

  execSync(`python3 /app/comic.py --input "${inputFile}" --output "${outputFile}"`, {
    stdio: 'pipe',
    timeout: 600000,
  });

  return outputFile;
}

// ─── Cartoon відео (3 персонажі + анімація ходьби) ────────────────────────────

async function makeCartoonVideo(scenesJson) {
  const workDir = `/tmp/cartoon_${Date.now()}`;
  fs.mkdirSync(workDir, { recursive: true });

  const inputFile  = `${workDir}/input.json`;
  const outputFile = `${workDir}/cartoon.mp4`;

  fs.writeFileSync(inputFile, scenesJson);
  const scenesCount = JSON.parse(scenesJson).scenes?.length ?? '?';
  console.log(`🎬 cartoon.py: ${scenesCount} сцен`);

  execSync(`python3 /app/cartoon.py --input "${inputFile}" --output "${outputFile}"`, {
    stdio: 'pipe',
    timeout: 600000,
  });

  return outputFile;
}

module.exports = { makeShortVideo, makeStickmanVideo, makeComicVideo, makeCartoonVideo };
