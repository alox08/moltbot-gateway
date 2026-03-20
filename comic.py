#!/usr/bin/env python3
"""
Comic video generator — animated comic shorts з двома персонажами
Usage: python3 comic.py --input /tmp/input.json --output /tmp/output.mp4
Input JSON: {"scenes": [{"background": "вулиця", "left": "текст", "right": "текст"}, ...]}
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

W, H    = 480, 854
FPS     = 25
VOICE_L = "uk-UA-OstapNeural"
VOICE_R = "uk-UA-PolinaNeural"

# Кольори
WHITE      = (255, 255, 255)
STICK_LINE = (25,  25,  25)
SKY_COL    = (135, 206, 235)
GROUND_COL = (60,  140, 60)
GROUND_LN  = (40,  100, 40)
SUN_COL    = (255, 215, 0)
SHIRT_COL  = (55,  115, 225)
PANTS_COL  = (40,  40,  110)
TIE_COL    = (200, 20,  20)
BUBBLE_BG  = (255, 255, 255)
BUBBLE_BD  = (30,  30,  30)
TEXT_COL   = (20,  20,  20)

# ─── Параметри (70% від stickman для двох в кадрі) ───────────────────────────

S          = 0.72
GROUND_Y   = H - 90
HEAD_RX    = int(98 * S)    # 70
HEAD_RY    = int(84 * S)    # 60
HEAD_CY    = GROUND_Y - int(420 * S)
NECK_Y     = HEAD_CY + HEAD_RY + 4
BODY_LEN   = int(165 * S)
HIP_Y      = NECK_Y + BODY_LEN
ARM_LEN    = int(90 * S)
LW         = 7
SHIRT_W    = int(62 * S)
SLEEVE_W   = int(17 * S)
LEG_W      = int(18 * S)
CX_L       = W // 4          # 120 — лівий персонаж
CX_R       = 3 * W // 4     # 360 — правий персонаж

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

# ─── Аудіо ────────────────────────────────────────────────────────────────────

async def gen_audio(text, voice, path):
    timings = []
    communicate = edge_tts.Communicate(text, voice)
    with open(path, 'wb') as f:
        async for chunk in communicate.stream():
            if chunk['type'] == 'audio':
                f.write(chunk['data'])
            elif chunk['type'] == 'WordBoundary':
                start = chunk['offset'] / 10_000_000
                dur   = chunk['duration'] / 10_000_000
                timings.append({'word': chunk['text'], 'start': start, 'end': start + dur})
    return timings

def get_duration(path):
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', path],
        capture_output=True, text=True)
    for s in json.loads(r.stdout).get('streams', []):
        if 'duration' in s:
            return float(s['duration'])
    return 3.0

def fallback_timings(text, duration):
    words = text.split()
    if not words:
        return []
    tpw = duration / len(words)
    return [{'word': w, 'start': i*tpw, 'end': (i+1)*tpw} for i, w in enumerate(words)]

def visible_words(timings, t, max_chars=24):
    spoken = [x for x in timings if x['start'] <= t]
    if not spoken:
        return ''
    out, chars = [], 0
    for x in reversed(spoken):
        w = x['word']
        if chars + len(w) + 1 > max_chars and out:
            break
        out.insert(0, w)
        chars += len(w) + 1
    return ' '.join(out)

def wrap_text(text, max_chars=15):
    if not text:
        return []
    words, lines, line = text.split(), [], ''
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

# ─── Фони ─────────────────────────────────────────────────────────────────────

def draw_cloud(draw, cx, cy, r):
    draw.ellipse([cx-r, cy-r//2, cx+r, cy+r//2], fill=WHITE)
    draw.ellipse([cx-r//2, cy-r*3//4, cx+r//2, cy+r//4], fill=WHITE)
    draw.ellipse([cx+r//3, cy-r*2//3, cx+r+6, cy+r//4-3], fill=WHITE)

def bg_street(draw, fi):
    draw.rectangle([(0,0),(W,GROUND_Y)], fill=SKY_COL)
    draw.rectangle([(0,GROUND_Y),(W,H)], fill=GROUND_COL)
    draw.line([(0,GROUND_Y),(W,GROUND_Y)], fill=GROUND_LN, width=4)
    draw.ellipse([W-85,18,W-18,85], fill=SUN_COL)
    sx, sy = W-52, 52
    for i in range(8):
        a = math.radians(i*45 + fi*0.6)
        draw.line([(sx+math.cos(a)*43, sy+math.sin(a)*43),
                   (sx+math.cos(a)*56, sy+math.sin(a)*56)], fill=(255,200,0), width=3)
    off = int(fi*0.35) % (W+160)
    draw_cloud(draw, 240-off, 70, 44)
    draw_cloud(draw, 60+W//2-off, 120, 30)

def bg_office(draw, fi):
    draw.rectangle([(0,0),(W,H)], fill=(220,210,195))
    draw.rectangle([(0,H-140),(W,H)], fill=(180,160,130))
    draw.line([(0,H-140),(W,H-140)], fill=(150,130,100), width=3)
    draw.rectangle([20,50,180,200], fill=(180,220,250), outline=STICK_LINE, width=4)
    draw.line([(100,50),(100,200)], fill=STICK_LINE, width=3)
    draw.line([(20,125),(180,125)], fill=STICK_LINE, width=3)
    draw.rectangle([260,50,420,200], fill=(180,220,250), outline=STICK_LINE, width=4)
    draw.line([(340,50),(340,200)], fill=STICK_LINE, width=3)
    draw.line([(260,125),(420,125)], fill=STICK_LINE, width=3)

def bg_night(draw, fi):
    draw.rectangle([(0,0),(W,GROUND_Y)], fill=(15,15,45))
    draw.rectangle([(0,GROUND_Y),(W,H)], fill=(30,50,30))
    draw.line([(0,GROUND_Y),(W,GROUND_Y)], fill=(20,40,20), width=4)
    draw.ellipse([W-85,18,W-18,85], fill=(240,235,180))
    draw.ellipse([W-68,12,W-8,72], fill=(15,15,45))
    stars = [(55,45),(110,28),(195,65),(275,38),(345,58),(395,32),(48,95),(315,85),(160,40)]
    for i,(sx,sy) in enumerate(stars):
        r = 3 + ((fi//14+i) % 2)
        draw.ellipse([sx-r,sy-r,sx+r,sy+r], fill=(255,255,200))
    draw.rectangle([W//2-3,GROUND_Y-160,W//2+3,GROUND_Y], fill=(180,170,100))
    draw.ellipse([W//2-22,GROUND_Y-172,W//2+22,GROUND_Y-150], fill=(255,240,150))

def bg_store(draw, fi):
    draw.rectangle([(0,0),(W,H)], fill=(240,235,220))
    draw.rectangle([(0,H-110),(W,H)], fill=(200,190,170))
    draw.line([(0,H-110),(W,H-110)], fill=(160,150,130), width=3)
    colors = [(220,80,80),(80,180,80),(80,80,220),(220,180,40),(180,80,220),(80,200,180)]
    for row, sy in enumerate([50,145,240]):
        draw.rectangle([(0,sy+48),(W,sy+54)], fill=(140,100,60))
        draw.rectangle([(0,sy),(4,sy+54)], fill=(140,100,60))
        draw.rectangle([(W-4,sy),(W,sy+54)], fill=(140,100,60))
        for col in range(7):
            x1 = 8 + col*66
            c = colors[(row*4+col) % len(colors)]
            draw.rounded_rectangle([x1,sy+7,x1+50,sy+46], radius=4, fill=c, outline=STICK_LINE, width=2)

def bg_kitchen(draw, fi):
    draw.rectangle([(0,0),(W,H)], fill=(250,245,230))
    draw.rectangle([(0,GROUND_Y),(W,H)], fill=(200,180,150))
    draw.rectangle([(0,GROUND_Y),(W,GROUND_Y+16)], fill=(160,140,110))
    draw.line([(0,GROUND_Y),(W,GROUND_Y)], fill=STICK_LINE, width=2)
    draw.rectangle([W//2-75,45,W//2+75,195], fill=(180,230,240), outline=STICK_LINE, width=4)
    draw.line([(W//2,45),(W//2,195)], fill=STICK_LINE, width=3)
    draw.line([(W//2-75,120),(W//2+75,120)], fill=STICK_LINE, width=3)
    draw.rounded_rectangle([8,55,95,205], radius=5, fill=(210,195,170), outline=STICK_LINE, width=3)
    draw.rounded_rectangle([W-95,55,W-8,205], radius=5, fill=(210,195,170), outline=STICK_LINE, width=3)

BG = {
    'вулиця': bg_street, 'street': bg_street,
    'офіс':   bg_office,  'office': bg_office,
    'ніч':    bg_night,   'night':  bg_night,
    'магазин':bg_store,   'store':  bg_store,
    'кухня':  bg_kitchen, 'kitchen':bg_kitchen,
}

# ─── Малювання персонажа ──────────────────────────────────────────────────────

def _seg(draw, x1, y1, x2, y2, color, w):
    dx, dy = x2-x1, y2-y1
    L = math.hypot(dx, dy)
    if L == 0: return
    nx, ny = -dy/L*w/2, dx/L*w/2
    draw.polygon([(x1+nx,y1+ny),(x1-nx,y1-ny),(x2-nx,y2-ny),(x2+nx,y2+ny)],
                 fill=color, outline=color)

def _limb(draw, pts, color, w):
    for i in range(len(pts)-1):
        _seg(draw, *pts[i], *pts[i+1], color, w)
    r = w//2+1
    for x,y in pts:
        draw.ellipse([x-r,y-r,x+r,y+r], fill=color)

def draw_char(draw, fi, cx, talking=True, facing_left=False):
    sway  = int(math.sin(fi * 0.04) * 2)
    cx    = cx + sway
    swing = math.sin(fi * 0.12) * 20
    fs    = -8 if facing_left else 8

    arm_y = NECK_Y + int(28*S)
    hip_w = SHIRT_W + int(14*S)

    # ── Руки (чорні) ──
    for side in (-1, 1):
        if (side == -1) != facing_left:
            sw = side * -1
        else:
            sw = side
        x_sh = cx + SHIRT_W * sw
        x_el = int(cx + SHIRT_W*sw + ARM_LEN*sw*0.45) + 5*sw
        x_h  = int(cx + SHIRT_W*sw + ARM_LEN*sw)
        y_sh = arm_y
        y_el = int(arm_y + ARM_LEN*0.35 + swing*0.5*sw)
        y_h  = int(arm_y + 60 + swing*sw)
        _limb(draw, [(x_sh,y_sh),(x_el,y_el),(x_h,y_h)], STICK_LINE, SLEEVE_W)

    # ── Куртка ──
    v_d = NECK_Y + int(72*S)
    draw.rounded_rectangle([cx-hip_w, NECK_Y+4, cx+hip_w, HIP_Y+8],
                            radius=int(20*S), fill=SHIRT_COL, outline=STICK_LINE, width=3)
    draw.polygon([(cx-int(20*S),NECK_Y+4),(cx+int(20*S),NECK_Y+4),(cx+fs//2,v_d)],
                 fill=WHITE)
    lw_s = int(35*S)
    draw.polygon([(cx-int(20*S),NECK_Y+4),(cx-lw_s,NECK_Y+int(28*S)),(cx-int(18*S),v_d-8),(cx+fs//2,v_d)],
                 fill=SHIRT_COL, outline=STICK_LINE, width=2)
    draw.polygon([(cx+int(20*S),NECK_Y+4),(cx+lw_s,NECK_Y+int(28*S)),(cx+int(18*S),v_d-8),(cx+fs//2,v_d)],
                 fill=SHIRT_COL, outline=STICK_LINE, width=2)
    draw.line([(cx-int(20*S),NECK_Y+4),(cx+fs//2,v_d)], fill=STICK_LINE, width=2)
    draw.line([(cx+int(20*S),NECK_Y+4),(cx+fs//2,v_d)], fill=STICK_LINE, width=2)
    # Краватка
    tx = cx + fs//3
    draw.polygon([(tx-4,v_d-2),(tx+4,v_d-2),(tx+7,v_d+int(38*S)),(tx,v_d+int(54*S)),(tx-7,v_d+int(38*S))],
                 fill=TIE_COL, outline=STICK_LINE, width=2)

    # ── Ноги ──
    leg_end = HIP_Y + int(88*S)
    _limb(draw, [(cx-hip_w//2,HIP_Y+6),(cx-int(50*S),leg_end)], STICK_LINE, LEG_W)
    _limb(draw, [(cx+hip_w//2,HIP_Y+6),(cx+int(50*S),leg_end)], STICK_LINE, LEG_W)
    _limb(draw, [(cx-int(50*S),leg_end),(cx-int(50*S),GROUND_Y)], STICK_LINE, LEG_W)
    _limb(draw, [(cx+int(50*S),leg_end),(cx+int(50*S),GROUND_Y)], STICK_LINE, LEG_W)
    r = int(6*S)
    draw.rounded_rectangle([cx-int(66*S),GROUND_Y-5,cx-int(26*S),GROUND_Y+11], radius=r, fill=STICK_LINE)
    draw.rounded_rectangle([cx+int(26*S),GROUND_Y-5,cx+int(66*S),GROUND_Y+11], radius=r, fill=STICK_LINE)

    # ── Голова ──
    draw.ellipse([cx-HEAD_RX,HEAD_CY-HEAD_RY,cx+HEAD_RX,HEAD_CY+HEAD_RY],
                 fill=(195,200,210), outline=STICK_LINE, width=LW)
    shift = -18 if facing_left else 18
    draw.ellipse([cx-HEAD_RX+shift,HEAD_CY-HEAD_RY+4,cx+HEAD_RX+int(shift*0.15),HEAD_CY+HEAD_RY-4],
                 fill=WHITE)
    draw.ellipse([cx-HEAD_RX,HEAD_CY-HEAD_RY,cx+HEAD_RX,HEAD_CY+HEAD_RY],
                 outline=STICK_LINE, width=LW)

    # ── Очі ──
    ey = HEAD_CY - int(8*S)
    if not facing_left:
        el_cx, er_cx = cx - int(26*S) + fs, cx + int(40*S) + fs//2
        er_l, pr_l = int(27*S), int(15*S)
        er_r, pr_r = int(33*S), int(19*S)
    else:
        el_cx, er_cx = cx - int(40*S) + fs//2, cx + int(26*S) + fs
        er_l, pr_l = int(33*S), int(19*S)
        er_r, pr_r = int(27*S), int(15*S)

    draw.ellipse([el_cx-er_l,ey-er_l,el_cx+er_l,ey+er_l], fill=WHITE, outline=STICK_LINE, width=3)
    draw.ellipse([el_cx-pr_l//2+1,ey-pr_l//2,el_cx+pr_l//2+1,ey+pr_l//2+1], fill=STICK_LINE)
    draw.ellipse([el_cx-7,ey-11,el_cx,ey-4], fill=WHITE)

    draw.ellipse([er_cx-er_r,ey-er_r,er_cx+er_r,ey+er_r], fill=WHITE, outline=STICK_LINE, width=3)
    draw.ellipse([er_cx-pr_r//2+2,ey-pr_r//2,er_cx+pr_r//2+2,ey+pr_r//2+2], fill=STICK_LINE)
    draw.ellipse([er_cx-8,ey-13,er_cx,ey-5], fill=WHITE)

    # Брови
    by = ey - max(er_l,er_r) - 2
    draw.line([(el_cx-er_l+2,by+4),(el_cx+er_l-2,by)], fill=STICK_LINE, width=5)
    draw.line([(er_cx-er_r+2,by),(er_cx+er_r-2,by+4)], fill=STICK_LINE, width=5)

    # Ніс
    nx = cx + fs//2
    draw.ellipse([nx-3,HEAD_CY+int(11*S),nx+3,HEAD_CY+int(18*S)], fill=(190,150,130))

    # Рот
    my = HEAD_CY + int(42*S)
    if talking and (fi//4) % 2 == 0:
        draw.ellipse([cx-int(26*S)+fs//2,my-int(13*S),cx+int(30*S)+fs//2,my+int(18*S)], fill=(180,30,30))
        draw.rectangle([cx-int(18*S)+fs//2,my-int(11*S),cx+int(22*S)+fs//2,my-2], fill=WHITE)
    else:
        draw.arc([cx-int(24*S)+fs//2,my-int(10*S),cx+int(32*S)+fs//2,my+int(18*S)],
                 0, 180, fill=STICK_LINE, width=5)

# ─── Хмаринка діалогу ─────────────────────────────────────────────────────────

def draw_bubble(draw, text, font, cx, side):
    lines = wrap_text(text) or ['...']
    line_h, pad = 36, 14
    if side == 'left':
        bx1, bx2 = 10, W//2 - 10
    else:
        bx1, bx2 = W//2 + 10, W - 10
    by1 = 28
    by2 = by1 + len(lines)*line_h + pad*2

    draw.rounded_rectangle([bx1+3,by1+3,bx2+3,by2+3], radius=16, fill=(170,170,170))
    draw.rounded_rectangle([bx1,by1,bx2,by2], radius=16, fill=BUBBLE_BG, outline=BUBBLE_BD, width=3)

    tail_y  = HEAD_CY - HEAD_RY - 4
    mid_bub = (bx1 + bx2) // 2
    draw.polygon([(mid_bub-10,by2),(mid_bub+10,by2),(cx,tail_y)], fill=BUBBLE_BG)
    draw.line([(mid_bub-10,by2),(cx,tail_y)], fill=BUBBLE_BD, width=3)
    draw.line([(mid_bub+10,by2),(cx,tail_y)], fill=BUBBLE_BD, width=3)

    ty = by1 + pad
    mid_x = (bx1+bx2)//2
    for line in lines:
        draw.text((mid_x,ty), line, font=font, fill=TEXT_COL, anchor='mt')
        ty += line_h

# ─── Рендер однієї сцени ──────────────────────────────────────────────────────

def render_scene(scene, al, ar, dur_l, dur_r, tim_l, tim_r, out_path, work_dir):
    PAUSE = 0.35
    off_r = dur_l + PAUSE
    total = dur_l + PAUSE + dur_r + 0.5
    frames = int(total * FPS)

    # Зсув таймінгів правого персонажа
    tim_r_s = [{'word': t['word'], 'start': t['start']+off_r, 'end': t['end']+off_r} for t in tim_r]

    # Конкатенація аудіо через filter_complex
    scene_audio = os.path.join(work_dir, f'saudio_{os.path.basename(out_path)}.aac')
    subprocess.run([
        'ffmpeg', '-y', '-loglevel', 'error',
        '-i', al, '-i', ar,
        '-filter_complex',
        f'[0:a]apad=pad_dur={PAUSE}[a0];[a0][1:a]concat=n=2:v=0:a=1[out]',
        '-map', '[out]', '-c:a', 'aac', scene_audio
    ], check=True)

    bg_key = scene.get('background', 'вулиця').lower()
    draw_bg = BG.get(bg_key, bg_street)
    font = load_font(24)

    silent = os.path.join(work_dir, f'sv_{os.path.basename(out_path)}')
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{W}x{H}', '-pix_fmt', 'rgb24',
        '-r', str(FPS), '-i', 'pipe:0',
        '-c:v', 'libx264', '-preset', 'ultrafast',
        '-crf', '26', '-pix_fmt', 'yuv420p', '-threads', '1',
        silent
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(frames):
            t = i / FPS
            l_talk = t <= dur_l
            r_talk = t >= off_r and t <= off_r + dur_r
            l_text = visible_words(tim_l,   t)    if l_talk else ''
            r_text = visible_words(tim_r_s, t)    if r_talk else ''

            img  = Image.new('RGB', (W, H))
            draw = ImageDraw.Draw(img)
            draw_bg(draw, i)
            draw_char(draw, i, CX_L, talking=l_talk, facing_left=False)
            draw_char(draw, i, CX_R, talking=r_talk, facing_left=True)
            if l_talk and l_text:
                draw_bubble(draw, l_text, font, CX_L, 'left')
            if r_talk and r_text:
                draw_bubble(draw, r_text, font, CX_R, 'right')
            proc.stdin.write(img.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()

    subprocess.run([
        'ffmpeg', '-y', '-loglevel', 'error',
        '-i', silent, '-i', scene_audio,
        '-c:v', 'copy', '-c:a', 'copy', '-shortest', out_path
    ], check=True)
    os.unlink(silent)
    os.unlink(scene_audio)

# ─── Головна функція ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',  required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    scenes   = data['scenes']
    work_dir = os.path.dirname(os.path.abspath(args.output))
    clips    = []

    for idx, scene in enumerate(scenes):
        print(f'🎬 Сцена {idx+1}/{len(scenes)}: {scene.get("background","вулиця")}', flush=True)
        text_l = scene.get('left',  'Привіт!')
        text_r = scene.get('right', 'Привіт!')

        al = os.path.join(work_dir, f'al_{idx}.mp3')
        ar = os.path.join(work_dir, f'ar_{idx}.mp3')

        tim_l = asyncio.run(gen_audio(text_l, VOICE_L, al))
        tim_r = asyncio.run(gen_audio(text_r, VOICE_R, ar))

        dur_l = get_duration(al)
        dur_r = get_duration(ar)

        if not tim_l: tim_l = fallback_timings(text_l, dur_l)
        if not tim_r: tim_r = fallback_timings(text_r, dur_r)

        clip = os.path.join(work_dir, f'scene_{idx}.mp4')
        render_scene(scene, al, ar, dur_l, dur_r, tim_l, tim_r, clip, work_dir)
        clips.append(clip)
        print(f'✅ Сцена {idx+1} готова ({dur_l:.1f}+{dur_r:.1f}с)', flush=True)

    print('🎞 Фінальна склейка...', flush=True)
    lst = os.path.join(work_dir, 'scenes.txt')
    with open(lst, 'w') as f:
        f.write('\n'.join(f"file '{c}'" for c in clips))

    subprocess.run([
        'ffmpeg', '-y', '-loglevel', 'error',
        '-f', 'concat', '-safe', '0', '-i', lst,
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26',
        '-c:a', 'aac', '-pix_fmt', 'yuv420p', '-threads', '1',
        args.output
    ], check=True)
    print(f'✅ Готово: {args.output}', flush=True)

if __name__ == '__main__':
    main()
