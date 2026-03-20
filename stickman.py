#!/usr/bin/env python3
"""
Stickman video generator v3 — karaoke text sync + colorful background
Usage: python3 stickman.py --input /tmp/input.json --output /tmp/output.mp4
Input JSON: {"text": "Ukrainian text here"}
"""

import sys, json, math, subprocess, argparse, asyncio, os

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Pillow not installed", file=sys.stderr)
    sys.exit(1)

try:
    import edge_tts
except ImportError:
    print("ERROR: edge-tts not installed", file=sys.stderr)
    sys.exit(1)

# ─── Налаштування ─────────────────────────────────────────────────────────────

W, H  = 480, 854
FPS   = 25
VOICE = "uk-UA-OstapNeural"

SKY_COL    = (135, 206, 235)
GROUND_COL = (60, 140, 60)
GROUND_LN  = (40, 100, 40)
SUN_COL    = (255, 215, 0)
WHITE      = (255, 255, 255)
STICK_LINE = (25,  25,  25)
BUBBLE_BG  = (255, 255, 255)
BUBBLE_BD  = (30,  30,  30)
TEXT_COL   = (20,  20,  20)
SHIRT_COL  = (50,  110, 220)   # Синя сорочка
PANTS_COL  = (40,  40,  110)   # Темно-сині штани
BELT_COL   = (70,  40,  15)    # Коричневий пояс
BUCKLE_COL = (200, 160, 30)    # Золота пряжка

# Comic стиль — приплюснута голова (oval)
CX         = W // 2
GROUND_Y   = H - 90
HEAD_RX    = 98   # горизонтальний радіус (ширший)
HEAD_RY    = 84   # вертикальний радіус (приплюснута)
HEAD_CY    = GROUND_Y - 430
NECK_Y     = HEAD_CY + HEAD_RY + 4
BODY_LEN   = 130
HIP_Y      = NECK_Y + BODY_LEN
ARM_LEN    = 90
LW         = 9
SHIRT_W    = 54   # ширина плечей сорочки
SLEEVE_W   = 10   # товщина рукавів (тонші)

# ─── Шрифти ───────────────────────────────────────────────────────────────────

def load_font(size):
    for path in [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

# ─── Аудіо + тайминги слів ────────────────────────────────────────────────────

async def generate_audio_with_timings(text, audio_path):
    """Генерує аудіо та повертає тайминги кожного слова (WordBoundary)."""
    timings = []
    communicate = edge_tts.Communicate(text, VOICE)

    with open(audio_path, 'wb') as f:
        async for chunk in communicate.stream():
            if chunk['type'] == 'audio':
                f.write(chunk['data'])
            elif chunk['type'] == 'WordBoundary':
                start = chunk['offset'] / 10_000_000      # 100ns → секунди
                dur   = chunk['duration'] / 10_000_000
                timings.append({
                    'word':  chunk['text'],
                    'start': start,
                    'end':   start + dur,
                })

    return timings


def make_fallback_timings(text, duration):
    """Якщо edge-tts не дав WordBoundary — розподіляємо слова рівномірно."""
    words = text.split()
    if not words:
        return []
    time_per_word = duration / len(words)
    return [
        {'word': w, 'start': i * time_per_word, 'end': (i + 1) * time_per_word}
        for i, w in enumerate(words)
    ]


def get_audio_duration(audio_path):
    result = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', audio_path],
        capture_output=True, text=True
    )
    info = json.loads(result.stdout)
    for stream in info.get('streams', []):
        if 'duration' in stream:
            return float(stream['duration'])
    return 10.0

# ─── Karaoke: які слова показувати зараз ──────────────────────────────────────

def get_current_words(timings, current_time, max_chars=30):
    """
    Повертає рядок слів що зараз вимовляються.
    Показує вікно ~30 символів: останні вимовлені слова.
    """
    spoken = [t for t in timings if t['start'] <= current_time]
    if not spoken:
        return ''

    # Беремо слова з кінця поки не перевищимо max_chars
    visible = []
    chars = 0
    for t in reversed(spoken):
        w = t['word']
        if chars + len(w) + 1 > max_chars and visible:
            break
        visible.insert(0, w)
        chars += len(w) + 1

    return ' '.join(visible)


def wrap_text(text, max_chars=19):
    if not text:
        return []
    words = text.split()
    lines, line = [], ''
    for w in words:
        test = (line + ' ' + w).strip()
        if len(test) > max_chars:
            if line:
                lines.append(line.strip())
            line = w
        else:
            line = test
    if line:
        lines.append(line.strip())
    return lines[:3]

# ─── Фон ──────────────────────────────────────────────────────────────────────

def draw_cloud(draw, cx, cy, r):
    draw.ellipse([cx - r,      cy - r // 2,     cx + r,      cy + r // 2],     fill=WHITE)
    draw.ellipse([cx - r // 2, cy - r * 3 // 4, cx + r // 2, cy + r // 4],     fill=WHITE)
    draw.ellipse([cx + r // 3, cy - r * 2 // 3, cx + r + 10, cy + r // 4 - 5], fill=WHITE)

def draw_background(draw, frame_idx):
    draw.rectangle([(0, 0),        (W, GROUND_Y)], fill=SKY_COL)
    draw.rectangle([(0, GROUND_Y), (W, H)],        fill=GROUND_COL)
    draw.line([(0, GROUND_Y), (W, GROUND_Y)], fill=GROUND_LN, width=4)

    # Сонце з обертовими променями
    draw.ellipse([W - 95, 18, W - 18, 95], fill=SUN_COL)
    sun_cx, sun_cy = W - 56, 56
    for i in range(8):
        angle = math.radians(i * 45 + frame_idx * 0.6)
        x1 = sun_cx + math.cos(angle) * 43
        y1 = sun_cy + math.sin(angle) * 43
        x2 = sun_cx + math.cos(angle) * 58
        y2 = sun_cy + math.sin(angle) * 58
        draw.line([(x1, y1), (x2, y2)], fill=(255, 200, 0), width=3)

    # Хмари
    offset = int(frame_idx * 0.35) % (W + 160)
    draw_cloud(draw, 260 - offset,         80, 52)
    draw_cloud(draw, 70 + W // 2 - offset, 135, 36)

# ─── Хмаринка діалогу ─────────────────────────────────────────────────────────

def draw_speech_bubble(draw, text, font):
    lines = wrap_text(text)
    if not lines:
        # Порожня хмаринка (між словами)
        lines = ['...']

    line_h  = 44
    pad     = 20
    bx1, bx2 = 28, W - 28
    by1      = 38
    by2      = by1 + len(lines) * line_h + pad * 2

    # Тінь
    draw.rounded_rectangle([bx1+4, by1+4, bx2+4, by2+4],
                            radius=22, fill=(180, 180, 180))
    # Хмаринка
    draw.rounded_rectangle([bx1, by1, bx2, by2],
                            radius=22, fill=BUBBLE_BG, outline=BUBBLE_BD, width=3)

    # Хвіст
    tail_tip_y  = HEAD_CY - HEAD_RY - 4
    tail_base_y = by2
    draw.polygon([(CX-16, tail_base_y), (CX+16, tail_base_y), (CX, tail_tip_y)],
                 fill=BUBBLE_BG)
    draw.line([(CX-16, tail_base_y), (CX, tail_tip_y)], fill=BUBBLE_BD, width=3)
    draw.line([(CX+16, tail_base_y), (CX, tail_tip_y)], fill=BUBBLE_BD, width=3)

    # Текст
    ty = by1 + pad
    for line in lines:
        draw.text((CX, ty), line, font=font, fill=TEXT_COL, anchor='mt')
        ty += line_h

# ─── Стікмен ──────────────────────────────────────────────────────────────────

def _thick_arm(draw, x1, y1, x2, y2, color, w):
    """Малює товстий рукав як залитий полігон."""
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return
    nx, ny = -dy / length * w / 2, dx / length * w / 2
    pts = [(x1+nx, y1+ny), (x1-nx, y1-ny), (x2-nx, y2-ny), (x2+nx, y2+ny)]
    draw.polygon(pts, fill=color, outline=STICK_LINE, width=3)


def draw_stickman(draw, frame_idx, talking=True):
    sway  = int(math.sin(frame_idx * 0.04) * 2)
    cx    = CX + sway
    swing = math.sin(frame_idx * 0.12) * 20
    fs    = 12   # face_shift — 3/4 поворот голови вправо

    arm_y  = NECK_Y + 30
    hip_w  = SHIRT_W + 16

    # ── Сорочка (трапеція) ──
    shirt_pts = [
        (cx - SHIRT_W, NECK_Y + 6),
        (cx + SHIRT_W, NECK_Y + 6),
        (cx + hip_w,   HIP_Y),
        (cx - hip_w,   HIP_Y),
    ]
    draw.polygon(shirt_pts, fill=SHIRT_COL, outline=STICK_LINE, width=LW)

    # Комір — V-подібний
    draw.polygon([
        (cx - 22, NECK_Y + 6),
        (cx + fs,  NECK_Y + 48),
        (cx + 22, NECK_Y + 6),
    ], fill=WHITE, outline=STICK_LINE, width=3)

    # Кишенька на грудях
    px, py = cx - SHIRT_W + 14, NECK_Y + 52
    draw.rectangle([px, py, px + 22, py + 20], fill=SHIRT_COL, outline=STICK_LINE, width=3)

    # ── Рукави з ЛІКТЕМ (два сегменти) ──
    # Ліва рука
    slx, sly = cx - SHIRT_W, arm_y
    lx2 = int(cx - SHIRT_W - ARM_LEN)
    ly2 = int(arm_y + 72 + swing)
    elx = (slx + lx2) // 2 - 12
    ely = (sly + ly2) // 2 + int(swing * 0.15) - 6
    _thick_arm(draw, slx, sly, elx, ely, SHIRT_COL, SLEEVE_W)
    _thick_arm(draw, elx, ely, lx2, ly2, SHIRT_COL, SLEEVE_W - 1)

    # Права рука
    srx, sry = cx + SHIRT_W, arm_y
    rx2 = int(cx + SHIRT_W + ARM_LEN)
    ry2 = int(arm_y + 72 - swing)
    erx = (srx + rx2) // 2 + 12
    ery = (sry + ry2) // 2 - int(swing * 0.15) - 6
    _thick_arm(draw, srx, sry, erx, ery, SHIRT_COL, SLEEVE_W)
    _thick_arm(draw, erx, ery, rx2, ry2, SHIRT_COL, SLEEVE_W - 1)

    # Кулаки (кружечки на кінцях рук)
    draw.ellipse([lx2-8, ly2-8, lx2+8, ly2+8], fill=WHITE, outline=STICK_LINE, width=3)
    draw.ellipse([rx2-8, ry2-8, rx2+8, ry2+8], fill=WHITE, outline=STICK_LINE, width=3)

    # ── Пояс ──
    draw.rectangle([cx - hip_w, HIP_Y,      cx + hip_w, HIP_Y + 18],
                   fill=BELT_COL, outline=STICK_LINE, width=3)
    draw.rectangle([cx - 11,    HIP_Y - 2,  cx + 11,    HIP_Y + 20],
                   fill=BUCKLE_COL, outline=STICK_LINE, width=2)

    # ── Штани (дві ноги) ──
    mid_hip = HIP_Y + 20
    leg_end  = mid_hip + 88
    draw.rectangle([cx - hip_w, mid_hip, cx - 5,    leg_end],
                   fill=PANTS_COL, outline=STICK_LINE, width=LW)
    draw.rectangle([cx + 5,     mid_hip, cx + hip_w, leg_end],
                   fill=PANTS_COL, outline=STICK_LINE, width=LW)

    # Гомілки
    draw.line([(cx - hip_w // 2, leg_end), (cx - 52, GROUND_Y)], fill=STICK_LINE, width=LW)
    draw.line([(cx + hip_w // 2, leg_end), (cx + 52, GROUND_Y)], fill=STICK_LINE, width=LW)

    # ── Приплюснута овальна голова ──
    draw.ellipse([cx - HEAD_RX, HEAD_CY - HEAD_RY,
                  cx + HEAD_RX, HEAD_CY + HEAD_RY],
                 fill=WHITE, outline=STICK_LINE, width=LW)

    # ── Легка тінь по лівому краю (вузька смужка) ──
    draw.ellipse([cx - HEAD_RX + 4,  HEAD_CY - HEAD_RY + 8,
                  cx - HEAD_RX + 38, HEAD_CY + HEAD_RY - 8],
                 fill=(220, 220, 225))
    # Перемалювати контур поверх тіні
    draw.ellipse([cx - HEAD_RX, HEAD_CY - HEAD_RY,
                  cx + HEAD_RX, HEAD_CY + HEAD_RY],
                 outline=STICK_LINE, width=LW)

    # ── Очі (3/4 поворот: ліве менше, праве більше) ──
    ey = HEAD_CY - 8

    # Ліве oko (ближче до центру, менше — ефект перспективи)
    el_cx = cx - 28 + fs
    er_l, pr_l = 26, 14
    draw.ellipse([el_cx-er_l, ey-er_l, el_cx+er_l, ey+er_l],
                 fill=WHITE, outline=STICK_LINE, width=4)
    draw.ellipse([el_cx-pr_l//2+2, ey-pr_l//2, el_cx+pr_l//2+2, ey+pr_l//2+2],
                 fill=STICK_LINE)
    draw.ellipse([el_cx-9, ey-14, el_cx, ey-5], fill=WHITE)

    # Праве oko (більше — ближче до глядача)
    er_cx = cx + 42 + fs // 2
    er_r, pr_r = 33, 19
    draw.ellipse([er_cx-er_r, ey-er_r, er_cx+er_r, ey+er_r],
                 fill=WHITE, outline=STICK_LINE, width=4)
    draw.ellipse([er_cx-pr_r//2+3, ey-pr_r//2, er_cx+pr_r//2+3, ey+pr_r//2+3],
                 fill=STICK_LINE)
    draw.ellipse([er_cx-10, ey-16, er_cx, ey-6], fill=WHITE)

    # ── Брови ──
    brow_y = ey - er_r - 4
    draw.line([(el_cx - 22, brow_y+6), (el_cx + 22, brow_y)], fill=STICK_LINE, width=8)
    draw.line([(er_cx - 26, brow_y),   (er_cx + 28, brow_y+6)], fill=STICK_LINE, width=8)

    # ── Ніс (маленька крапка) ──
    nx = cx + fs + 6
    draw.ellipse([nx-4, HEAD_CY+14, nx+5, HEAD_CY+22], fill=(190, 150, 130))

    # ── Рот ──
    my = HEAD_CY + 46
    if talking and (frame_idx // 4) % 2 == 0:
        draw.ellipse([cx-30+fs, my-16, cx+38+fs, my+24], fill=(180, 30, 30))
        draw.rectangle([cx-22+fs, my-14, cx+30+fs, my-3], fill=WHITE)
        draw.line([(cx+fs, my-14), (cx+fs, my-3)], fill=(210, 180, 180), width=3)
    else:
        draw.arc([cx-28+fs, my-12, cx+40+fs, my+24], 0, 180, fill=STICK_LINE, width=7)

# ─── Генерація відео ──────────────────────────────────────────────────────────

def generate_silent_video(timings, duration, silent_path):
    total_frames = int(duration * FPS)
    font = load_font(32)

    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{W}x{H}', '-pix_fmt', 'rgb24',
        '-r', str(FPS), '-i', 'pipe:0',
        '-c:v', 'libx264', '-preset', 'ultrafast',
        '-crf', '26', '-pix_fmt', 'yuv420p',
        '-threads', '1', silent_path
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(total_frames):
            current_time = i / FPS
            current_text = get_current_words(timings, current_time)
            talking       = bool(current_text and current_text != '...')

            img  = Image.new('RGB', (W, H), SKY_COL)
            draw = ImageDraw.Draw(img)
            draw_background(draw, i)
            draw_stickman(draw, i, talking=talking)
            draw_speech_bubble(draw, current_text, font)
            proc.stdin.write(img.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()

# ─── Головна функція ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',  required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)
    text = data['text']

    work_dir    = os.path.dirname(os.path.abspath(args.output))
    audio_path  = os.path.join(work_dir, 'audio.mp3')
    silent_path = os.path.join(work_dir, 'silent.mp4')

    print(f'🎙 Озвучка + тайминги: "{text[:60]}..."', flush=True)
    timings = asyncio.run(generate_audio_with_timings(text, audio_path))
    print(f'📝 Отримано таймінгів слів: {len(timings)}', flush=True)

    duration = get_audio_duration(audio_path) + 0.8

    if not timings:
        print('⚠️ WordBoundary не отримано — використовую рівномірний розподіл', flush=True)
        timings = make_fallback_timings(text, duration - 0.8)
    print(f'⏱ Тривалість: {duration:.1f}с ({int(duration * FPS)} кадрів)', flush=True)

    print('🎨 Малюю стікмена з karaoke...', flush=True)
    generate_silent_video(timings, duration, silent_path)

    print('🎞 Склеюю відео + аудіо...', flush=True)
    subprocess.run([
        'ffmpeg', '-y', '-loglevel', 'error',
        '-i', silent_path, '-i', audio_path,
        '-c:v', 'copy', '-c:a', 'aac', '-shortest',
        args.output
    ], check=True)

    print(f'✅ Готово: {args.output}', flush=True)

if __name__ == '__main__':
    main()
