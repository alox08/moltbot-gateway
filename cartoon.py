#!/usr/bin/env python3
"""
Cartoon mini-movie generator v2 — Loading Artist style + emotions
Usage: python3 cartoon.py --input /tmp/input.json --output /tmp/output.mp4

Input JSON:
{
  "scenes": [
    {
      "background": "вулиця",
      "enter": [{"char": 0, "from": "left"}, {"char": 1, "from": "right"}],
      "exit": [],
      "dialogs": [
        {"char": 0, "text": "Привіт!", "emotion": "normal"},
        {"char": 1, "text": "Привіт!", "emotion": "surprised"}
      ]
    }
  ]
}

Chars: 0=Остап(синій), 1=Поліна(рожевий), 2=Микола(зелений)
Emotions: normal, talking, surprised, angry, sad
Backgrounds: вулиця, офіс, ніч, магазин, кухня
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

W, H       = 480, 854
FPS        = 25
S          = 0.72          # масштаб персонажів (збільшено для Loading Artist)
EYE_SCALE  = 1.35          # очі більші відносно голови (Loading Artist)
WALK_SPEED = 130           # px/s

WHITE      = (255, 255, 255)
STICK_LINE = (25, 25, 25)
SKY_COL    = (135, 206, 235)
GROUND_COL = (60, 140, 60)
GROUND_LN  = (40, 100, 40)
SUN_COL    = (255, 215, 0)
BUBBLE_BG  = (255, 255, 255)
BUBBLE_BD  = (30, 30, 30)
TEXT_COL   = (20, 20, 20)

# Конфіг персонажів
# char_id: 0=Остап(синій), 1=Поліна(рожевий), 2=Микола(зелений)
CHAR_CFG = [
    {'jacket': (55, 115, 225),  'tie': (200, 20, 20),   'voice': 'uk-UA-OstapNeural',  'hair': None},
    {'jacket': (220, 80, 150),  'tie': (255, 220, 50),  'voice': 'uk-UA-PolinaNeural', 'hair': 'ponytail'},
    {'jacket': (50, 170, 80),   'tie': (255, 140, 0),   'voice': 'uk-UA-OstapNeural',  'hair': None},
]

GROUND_Y = H - 90
HEAD_RX  = int(98 * S)
HEAD_RY  = int(84 * S)
HEAD_CY  = GROUND_Y - int(420 * S)
NECK_Y   = HEAD_CY + HEAD_RY + 4
HIP_Y    = NECK_Y + int(165 * S)
ARM_LEN  = int(90 * S)
LW       = max(5, int(9 * S))
SHIRT_W  = int(62 * S)
SLEEVE_W = max(8, int(17 * S))
LEG_W    = max(8, int(18 * S))

# ─── Слоти позицій ────────────────────────────────────────────────────────────

def slot_positions(n):
    if n == 1: return [240]
    if n == 2: return [130, 350]
    return [90, 240, 390]

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
    communicate = edge_tts.Communicate(text, voice)
    with open(path, 'wb') as f:
        async for chunk in communicate.stream():
            if chunk['type'] == 'audio':
                f.write(chunk['data'])

def get_duration(path):
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', path],
        capture_output=True, text=True)
    for s in json.loads(r.stdout).get('streams', []):
        if 'duration' in s:
            return float(s['duration'])
    return 2.0

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
    for i, (sx, sy) in enumerate(stars):
        r = 3 + ((fi//14+i) % 2)
        draw.ellipse([sx-r,sy-r,sx+r,sy+r], fill=(255,255,200))

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
    'вулиця': bg_street,  'street':  bg_street,
    'офіс':   bg_office,  'office':  bg_office,
    'ніч':    bg_night,   'night':   bg_night,
    'магазин':bg_store,   'store':   bg_store,
    'кухня':  bg_kitchen, 'kitchen': bg_kitchen,
}

# ─── Допоміжні ────────────────────────────────────────────────────────────────

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
    for x, y in pts:
        draw.ellipse([x-r, y-r, x+r, y+r], fill=color)

# ─── Малювання обличчя (Loading Artist стиль + 5 емоцій) ──────────────────────

def draw_face(draw, fi, cx, facing_right, emotion, talking):
    """
    emotion: 'normal' | 'talking' | 'surprised' | 'angry' | 'sad'
    talking: bool — для анімації рота (normal/talking)
    """
    fs  = 8 if facing_right else -8
    ey  = HEAD_CY - int(8 * S)

    # ── Очі (Loading Artist: великі, займають ~45% ширини голови) ──
    if facing_right:
        el_cx = cx - int(26*S) + fs
        er_cx = cx + int(40*S) + fs//2
        er_l  = int(int(27*S) * EYE_SCALE)
        pr_l  = int(int(15*S) * EYE_SCALE)
        er_r  = int(int(33*S) * EYE_SCALE)
        pr_r  = int(int(19*S) * EYE_SCALE)
    else:
        el_cx = cx - int(40*S) + fs//2
        er_cx = cx + int(26*S) + fs
        er_l  = int(int(33*S) * EYE_SCALE)
        pr_l  = int(int(19*S) * EYE_SCALE)
        er_r  = int(int(27*S) * EYE_SCALE)
        pr_r  = int(int(15*S) * EYE_SCALE)

    # Для здивування — ще більші очі
    if emotion == 'surprised':
        er_l  = int(er_l  * 1.25)
        er_r  = int(er_r  * 1.25)
        pr_l  = int(pr_l  * 1.1)
        pr_r  = int(pr_r  * 1.1)

    # Малюємо очі
    draw.ellipse([el_cx-er_l, ey-er_l, el_cx+er_l, ey+er_l],
                 fill=WHITE, outline=STICK_LINE, width=3)
    draw.ellipse([el_cx-pr_l//2+1, ey-pr_l//2, el_cx+pr_l//2+1, ey+pr_l//2+1],
                 fill=STICK_LINE)
    draw.ellipse([el_cx-7, ey-int(er_l*0.5), el_cx, ey-int(er_l*0.15)],
                 fill=WHITE)  # відблиск

    draw.ellipse([er_cx-er_r, ey-er_r, er_cx+er_r, ey+er_r],
                 fill=WHITE, outline=STICK_LINE, width=3)
    draw.ellipse([er_cx-pr_r//2+2, ey-pr_r//2, er_cx+pr_r//2+2, ey+pr_r//2+2],
                 fill=STICK_LINE)
    draw.ellipse([er_cx-8, ey-int(er_r*0.5), er_cx, ey-int(er_r*0.15)],
                 fill=WHITE)  # відблиск

    # ── Брови (залежать від емоції) ──
    by = ey - max(er_l, er_r) - 3

    if emotion == 'angry':
        # Злі: V-форма, надброви знизуються до центру
        draw.line([(el_cx-er_l+2, by+2), (el_cx+er_l-2, by+9)], fill=STICK_LINE, width=7)
        draw.line([(er_cx-er_r+2, by+9), (er_cx+er_r-2, by+2)], fill=STICK_LINE, width=7)
    elif emotion == 'sad':
        # Сумні: надброви опускаються зовнішніми кутами
        draw.line([(el_cx-er_l+2, by+9), (el_cx+er_l-2, by+2)], fill=STICK_LINE, width=7)
        draw.line([(er_cx-er_r+2, by+2), (er_cx+er_r-2, by+9)], fill=STICK_LINE, width=7)
    elif emotion == 'surprised':
        # Здивовані: дугою вгору (підняті)
        draw.arc([el_cx-er_l+2, by-10, el_cx+er_l-2, by+6], 200, 340, fill=STICK_LINE, width=6)
        draw.arc([er_cx-er_r+2, by-10, er_cx+er_r-2, by+6], 200, 340, fill=STICK_LINE, width=6)
    else:
        # Normal / talking: трохи нахилені (природні)
        draw.line([(el_cx-er_l+2, by+5), (el_cx+er_l-2, by)], fill=STICK_LINE, width=6)
        draw.line([(er_cx-er_r+2, by), (er_cx+er_r-2, by+5)], fill=STICK_LINE, width=6)

    # ── Ніс ──
    nx = cx + fs//2
    draw.ellipse([nx-3, HEAD_CY+int(11*S), nx+3, HEAD_CY+int(18*S)], fill=(190,150,130))

    # ── Рот (залежить від емоції) ──
    my = HEAD_CY + int(42*S)

    if emotion == 'surprised':
        # О-рот
        draw.ellipse([cx-int(10*S)+fs//2, my-int(11*S),
                      cx+int(14*S)+fs//2, my+int(14*S)],
                     fill=(180,30,30), outline=STICK_LINE, width=3)

    elif emotion == 'angry':
        # Зціплені зуби — прямокутник з лінією зубів
        mx1 = cx - int(22*S) + fs//2
        mx2 = cx + int(26*S) + fs//2
        my1 = my - int(5*S)
        my2 = my + int(10*S)
        draw.rectangle([mx1, my1, mx2, my2], fill=(180,30,30))
        draw.line([(mx1, my1+4), (mx2, my1+4)], fill=WHITE, width=3)  # зуби
        draw.rectangle([mx1, my1, mx2, my2], outline=STICK_LINE, width=3)

    elif emotion == 'sad':
        # Перевернута дуга (сумна гримаса)
        draw.arc([cx-int(22*S)+fs//2, my-int(8*S),
                  cx+int(30*S)+fs//2, my+int(16*S)],
                 180, 360, fill=STICK_LINE, width=5)
        # Сльози
        drop_l = (el_cx, ey + er_l + 2)
        drop_r = (er_cx, ey + er_r + 2)
        for dx, dy in [drop_l, drop_r]:
            draw.ellipse([dx-4, dy, dx+4, dy+10], fill=(120,170,255))

    elif emotion in ('talking', 'normal') and talking and (fi//4) % 2 == 0:
        # Відкритий рот (анімація розмови)
        draw.ellipse([cx-int(26*S)+fs//2, my-int(13*S),
                      cx+int(30*S)+fs//2, my+int(18*S)], fill=(180,30,30))
        draw.rectangle([cx-int(18*S)+fs//2, my-int(11*S),
                        cx+int(22*S)+fs//2, my-2], fill=WHITE)  # зуби

    else:
        # Звичайна усмішка
        draw.arc([cx-int(22*S)+fs//2, my-int(10*S),
                  cx+int(30*S)+fs//2, my+int(18*S)],
                 0, 180, fill=STICK_LINE, width=5)

# ─── Малювання хвоста (Поліна) ────────────────────────────────────────────────

def draw_ponytail(draw, cx, facing_right):
    """Рудий хвіст збоку голови (Поліна)."""
    HAIR_COL   = (200, 90, 30)   # руда
    HAIR_DARK  = (160, 60, 15)

    if facing_right:
        # Хвіст позаду (ліворуч від голови)
        tx = cx - HEAD_RX + 4
    else:
        tx = cx + HEAD_RX - 4

    ty_top = HEAD_CY - HEAD_RY + int(10 * S)

    # Основний хвіст — дуга що звисає вниз
    pts = []
    n   = 12
    for i in range(n + 1):
        frac = i / n
        # Параболічна крива: від tx, ty_top вниз і трохи вбік
        side = -1 if facing_right else 1
        px = tx + side * int(frac * 22 * S)
        py = ty_top + int((frac ** 0.8) * 130 * S)
        pts.append((px, py))

    thick = int(16 * S)
    for i in range(len(pts)-1):
        w = max(4, int(thick * (1 - i / n * 0.5)))
        _seg(draw, *pts[i], *pts[i+1], HAIR_COL, w)

    # Темна обводка (тінь)
    for i in range(len(pts)-1):
        w = max(2, int(thick * (1 - i / n * 0.5)) - 4)
        _seg(draw, *pts[i], *pts[i+1], HAIR_DARK, w - 2 if w > 4 else 1)

    # Гумка на хвості
    gx, gy = pts[n//2]
    draw.ellipse([gx-5, gy-5, gx+5, gy+5], fill=(220, 50, 50))

# ─── Малювання персонажа ──────────────────────────────────────────────────────

def draw_char(draw, fi, cx, char_id, walking=False, facing_right=True, talking=False, emotion='normal'):
    cfg   = CHAR_CFG[char_id % len(CHAR_CFG)]
    jcol  = cfg['jacket']
    tcol  = cfg['tie']
    hair  = cfg['hair']

    sway   = int(math.sin(fi * 0.04) * 2)
    cx     = cx + sway
    swing  = math.sin(fi * 0.12) * 20
    fs     = 8 if facing_right else -8
    hip_w  = SHIRT_W + int(14 * S)
    arm_y  = NECK_Y + int(28 * S)

    # ── Хвіст позаду голови (малюємо ПЕРШ ніж голову) ──
    if hair == 'ponytail':
        draw_ponytail(draw, cx, facing_right)

    # ── Руки ──
    for side in (-1, 1):
        sw   = side if facing_right else -side
        x_sh = cx + SHIRT_W * sw
        x_el = int(cx + SHIRT_W*sw + ARM_LEN*sw*0.45) + 5*sw
        x_h  = int(cx + SHIRT_W*sw + ARM_LEN*sw)
        y_sh = arm_y
        y_el = int(arm_y + ARM_LEN*0.35 + swing*0.5*sw)
        y_h  = int(arm_y + 60 + swing*sw)
        _limb(draw, [(x_sh,y_sh),(x_el,y_el),(x_h,y_h)], STICK_LINE, SLEEVE_W)

    # ── Куртка ──
    v_d  = NECK_Y + int(72*S)
    lw_s = int(35*S)
    draw.rounded_rectangle([cx-hip_w, NECK_Y+4, cx+hip_w, HIP_Y+8],
                            radius=int(20*S), fill=jcol, outline=STICK_LINE, width=3)
    draw.polygon([(cx-int(20*S),NECK_Y+4),(cx+int(20*S),NECK_Y+4),(cx+fs//2,v_d)], fill=WHITE)
    draw.polygon([(cx-int(20*S),NECK_Y+4),(cx-lw_s,NECK_Y+int(28*S)),
                  (cx-int(18*S),v_d-8),(cx+fs//2,v_d)],
                 fill=jcol, outline=STICK_LINE, width=2)
    draw.polygon([(cx+int(20*S),NECK_Y+4),(cx+lw_s,NECK_Y+int(28*S)),
                  (cx+int(18*S),v_d-8),(cx+fs//2,v_d)],
                 fill=jcol, outline=STICK_LINE, width=2)
    draw.line([(cx-int(20*S),NECK_Y+4),(cx+fs//2,v_d)], fill=STICK_LINE, width=2)
    draw.line([(cx+int(20*S),NECK_Y+4),(cx+fs//2,v_d)], fill=STICK_LINE, width=2)
    tx = cx + fs//3
    draw.polygon([
        (tx-4, v_d-2), (tx+4, v_d-2),
        (tx+7, v_d+int(38*S)), (tx, v_d+int(54*S)), (tx-7, v_d+int(38*S))
    ], fill=tcol, outline=STICK_LINE, width=2)

    # ── Ноги з анімацією ходьби ──
    if walking:
        phase  = fi * 0.22
        dir_m  = 1 if facing_right else -1
        stride = int(42*S)
        lift   = int(18*S)
        l_sw   = math.sin(phase) * stride * dir_m
        l_li   = max(0, math.sin(phase)) * lift
        r_sw   = math.sin(phase + math.pi) * stride * dir_m
        r_li   = max(0, math.sin(phase + math.pi)) * lift
        lknee  = (cx - int(50*S) + int(l_sw*0.5), HIP_Y + int(88*S) - int(l_li*0.5))
        lfoot  = (cx - int(50*S) + int(l_sw),     GROUND_Y - int(l_li))
        rknee  = (cx + int(50*S) + int(r_sw*0.5), HIP_Y + int(88*S) - int(r_li*0.5))
        rfoot  = (cx + int(50*S) + int(r_sw),     GROUND_Y - int(r_li))
    else:
        lknee  = (cx - int(50*S), HIP_Y + int(88*S))
        lfoot  = (cx - int(50*S), GROUND_Y)
        rknee  = (cx + int(50*S), HIP_Y + int(88*S))
        rfoot  = (cx + int(50*S), GROUND_Y)

    lhip = (cx - hip_w//2, HIP_Y + 6)
    rhip = (cx + hip_w//2, HIP_Y + 6)
    _limb(draw, [lhip, lknee], STICK_LINE, LEG_W)
    _limb(draw, [lknee, lfoot], STICK_LINE, LEG_W)
    _limb(draw, [rhip, rknee], STICK_LINE, LEG_W)
    _limb(draw, [rknee, rfoot], STICK_LINE, LEG_W)

    shoe  = int(36*S)
    r_sh  = int(5*S)
    draw.rounded_rectangle([lfoot[0]-shoe, lfoot[1]-4, lfoot[0]+shoe//3, lfoot[1]+9],
                            radius=r_sh, fill=STICK_LINE)
    draw.rounded_rectangle([rfoot[0]-shoe//3, rfoot[1]-4, rfoot[0]+shoe, rfoot[1]+9],
                            radius=r_sh, fill=STICK_LINE)

    # ── Голова (тінь-серп зліва) ──
    draw.ellipse([cx-HEAD_RX, HEAD_CY-HEAD_RY, cx+HEAD_RX, HEAD_CY+HEAD_RY],
                 fill=(195,200,210), outline=STICK_LINE, width=LW)
    shift = int(18*S) if facing_right else -int(18*S)
    draw.ellipse([cx-HEAD_RX+shift, HEAD_CY-HEAD_RY+4,
                  cx+HEAD_RX+int(shift*0.15), HEAD_CY+HEAD_RY-4], fill=WHITE)
    draw.ellipse([cx-HEAD_RX, HEAD_CY-HEAD_RY, cx+HEAD_RX, HEAD_CY+HEAD_RY],
                 outline=STICK_LINE, width=LW)

    # ── Обличчя (Loading Artist стиль + емоція) ──
    draw_face(draw, fi, cx, facing_right, emotion, talking)

# ─── Хмаринка діалогу ─────────────────────────────────────────────────────────

def wrap_text(text, max_chars=13):
    words, lines, line = text.split(), [], ''
    for w in words:
        test = (line + ' ' + w).strip()
        if len(test) > max_chars and line:
            lines.append(line.strip())
            line = w
        else:
            line = test
    if line:
        lines.append(line.strip())
    return lines[:3]

def draw_bubble(draw, text, font, cx, slot_i, n_slots):
    lines  = wrap_text(text) or ['...']
    line_h = 30
    pad    = 11

    bub_w = min(185, W // max(n_slots, 1) + 40)
    bx1   = max(5, cx - bub_w // 2)
    bx2   = min(W-5, bx1 + bub_w)
    if bx2 - bx1 < 80:
        bx1 = max(5, bx2-80)
    by1   = 16
    by2   = by1 + len(lines) * line_h + pad * 2

    draw.rounded_rectangle([bx1+3, by1+3, bx2+3, by2+3], radius=13, fill=(160,160,160))
    draw.rounded_rectangle([bx1, by1, bx2, by2], radius=13,
                            fill=BUBBLE_BG, outline=BUBBLE_BD, width=3)

    tail_y  = HEAD_CY - HEAD_RY - 4
    mid_bub = (bx1 + bx2) // 2
    draw.polygon([(mid_bub-8, by2),(mid_bub+8, by2),(cx, tail_y)], fill=BUBBLE_BG)
    draw.line([(mid_bub-8, by2),(cx, tail_y)], fill=BUBBLE_BD, width=2)
    draw.line([(mid_bub+8, by2),(cx, tail_y)], fill=BUBBLE_BD, width=2)

    ty    = by1 + pad
    mid_x = (bx1 + bx2) // 2
    for line in lines:
        draw.text((mid_x, ty), line, font=font, fill=TEXT_COL, anchor='mt')
        ty += line_h

# ─── Рендер сцени ─────────────────────────────────────────────────────────────

def render_scene(scene_def, scene_idx, initial_chars, work_dir):
    """
    initial_chars: {char_id: x} — де були персонажі після попередньої сцени
    Returns: (mp4_path, final_chars: {char_id: x})
    """
    bg_key  = scene_def.get('background', 'вулиця').lower()
    draw_bg = BG.get(bg_key, bg_street)

    entering_list = scene_def.get('enter', [])
    entering_dict = {e['char']: e.get('from', 'left') for e in entering_list}
    exiting_set   = {e['char'] for e in scene_def.get('exit', [])}

    present        = set(initial_chars.keys()) | set(entering_dict.keys())
    sorted_present = sorted(present)

    slots        = slot_positions(len(sorted_present))
    char_targets = {cid: slots[i] for i, cid in enumerate(sorted_present)}

    char_starts   = {}
    arrival_times = {}

    for cid, side in entering_dict.items():
        start_x = -HEAD_RX * 3 if side == 'left' else W + HEAD_RX * 3
        char_starts[cid]   = start_x
        dist = abs(char_targets[cid] - start_x)
        arrival_times[cid] = dist / WALK_SPEED

    for cid in initial_chars:
        start_x = initial_chars[cid]
        char_starts[cid]  = start_x
        dist = abs(char_targets[cid] - start_x)
        arrival_times[cid] = dist / WALK_SPEED if dist > 5 else 0.0

    enter_end = max(arrival_times.values()) if arrival_times else 0.0

    # ── Генеруємо аудіо ──
    dialogs     = scene_def.get('dialogs', [])
    audio_paths = []
    audio_durs  = []
    for i, dlg in enumerate(dialogs):
        cid   = dlg['char']
        voice = CHAR_CFG[cid % len(CHAR_CFG)]['voice']
        path  = os.path.join(work_dir, f'd_{scene_idx}_{i}.mp3')
        asyncio.run(gen_audio(dlg['text'], voice, path))
        audio_paths.append(path)
        audio_durs.append(get_duration(path))

    # ── Тайм-лайн діалогів ──
    dialog_times = []
    t = enter_end + 0.3
    for dur in audio_durs:
        dialog_times.append((t, t + dur))
        t += dur + 0.25

    dialogs_end = dialog_times[-1][1] if dialog_times else (enter_end + 0.3)

    # ── Вихід персонажів ──
    exit_start = dialogs_end + 0.2
    exit_data  = {}
    for cid in exiting_set:
        from_x = char_targets.get(cid, 240)
        to_x   = W + HEAD_RX * 3
        dur    = abs(to_x - from_x) / WALK_SPEED
        exit_data[cid] = (from_x, to_x, dur)

    exit_end     = (exit_start + max(d[2] for d in exit_data.values())) if exit_data else exit_start
    total_dur    = exit_end + 0.4
    total_frames = int(total_dur * FPS)

    font = load_font(21)

    # ── Рендер відео ──
    silent = os.path.join(work_dir, f'sil_{scene_idx}.mp4')
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{W}x{H}', '-pix_fmt', 'rgb24',
        '-r', str(FPS), '-i', 'pipe:0',
        '-c:v', 'libx264', '-preset', 'ultrafast',
        '-crf', '26', '-pix_fmt', 'yuv420p', '-threads', '1', silent
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for fi in range(total_frames):
            t_cur = fi / FPS

            talking_char = -1
            bubble_text  = ''
            bubble_emot  = 'normal'
            for di, dlg in enumerate(dialogs):
                dt_s, dt_e = dialog_times[di]
                if dt_s <= t_cur <= dt_e:
                    talking_char = dlg['char']
                    bubble_text  = dlg['text']
                    bubble_emot  = dlg.get('emotion', 'normal')
                    break

            img  = Image.new('RGB', (W, H))
            draw = ImageDraw.Draw(img)
            draw_bg(draw, fi)

            for char_id in sorted(present, key=lambda c: char_targets.get(c, 240)):
                target_x = char_targets[char_id]
                start_x  = char_starts[char_id]
                arr_t    = arrival_times.get(char_id, 0.0)

                if char_id in exiting_set and t_cur >= exit_start:
                    from_x, to_x, edur = exit_data[char_id]
                    prog         = min(1.0, (t_cur - exit_start) / edur) if edur > 0 else 1.0
                    cx_f         = from_x + (to_x - from_x) * prog
                    walking      = prog < 0.999
                    facing_right = True
                    emo          = 'normal'

                elif arr_t > 0 and t_cur < arr_t:
                    prog         = t_cur / arr_t
                    cx_f         = start_x + (target_x - start_x) * prog
                    walking      = True
                    facing_right = target_x > start_x
                    emo          = 'normal'

                else:
                    cx_f    = float(target_x)
                    walking = False
                    if talking_char >= 0 and talking_char != char_id and talking_char in char_targets:
                        facing_right = char_targets[talking_char] > target_x
                    elif char_id in entering_dict:
                        facing_right = entering_dict[char_id] == 'left'
                    else:
                        facing_right = target_x <= W // 2

                    # Емоція: якщо цей персонаж говорить — беремо з діалогу
                    if char_id == talking_char:
                        emo = bubble_emot
                    else:
                        emo = 'normal'

                if cx_f < -HEAD_RX * 2 or cx_f > W + HEAD_RX * 2:
                    continue

                is_talking = (char_id == talking_char)
                draw_char(draw, fi, int(cx_f), char_id,
                          walking=walking, facing_right=facing_right,
                          talking=is_talking, emotion=emo)

                if is_talking and bubble_text:
                    slot_i = sorted_present.index(char_id)
                    draw_bubble(draw, bubble_text, font, int(cx_f), slot_i, len(sorted_present))

            proc.stdin.write(img.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()

    # ── Мікшуємо аудіо ──
    scene_out = os.path.join(work_dir, f'scene_{scene_idx}.mp4')
    if audio_paths:
        inputs_cmd   = []
        filter_parts = []
        for i, path in enumerate(audio_paths):
            delay_ms = int(dialog_times[i][0] * 1000)
            inputs_cmd += ['-i', path]
            filter_parts.append(f'[{i}:a]adelay={delay_ms}|{delay_ms}[a{i}]')
        mix_str = ''.join(f'[a{i}]' for i in range(len(audio_paths)))
        fc = ';'.join(filter_parts) + f';{mix_str}amix=inputs={len(audio_paths)}:dropout_transition=0[out]'

        scene_audio = os.path.join(work_dir, f'aud_{scene_idx}.aac')
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error',
            *inputs_cmd, '-filter_complex', fc,
            '-map', '[out]', '-c:a', 'aac', '-t', str(total_dur), scene_audio
        ], check=True)
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error',
            '-i', silent, '-i', scene_audio,
            '-c:v', 'copy', '-c:a', 'copy', '-shortest', scene_out
        ], check=True)
        os.unlink(silent)
        os.unlink(scene_audio)
    else:
        os.rename(silent, scene_out)

    final_chars = {cid: char_targets[cid] for cid in present if cid not in exiting_set}
    return scene_out, final_chars

# ─── Головна функція ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',  required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    scenes        = data.get('scenes', [])
    work_dir      = os.path.dirname(os.path.abspath(args.output))
    clips         = []
    current_chars = {}

    for idx, scene in enumerate(scenes):
        print(f'🎬 Сцена {idx+1}/{len(scenes)}: {scene.get("background","вулиця")}', flush=True)
        clip, current_chars = render_scene(scene, idx, current_chars, work_dir)
        clips.append(clip)
        print(f'✅ Сцена {idx+1} готова', flush=True)

    print('🎞 Фінальна склейка...', flush=True)
    lst = os.path.join(work_dir, 'list.txt')
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
