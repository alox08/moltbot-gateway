#!/usr/bin/env python3
"""
Cartoon mini-movie generator v3 — Loading Artist style + emotions + rich backgrounds
Usage: python3 cartoon.py --input /tmp/input.json --output /tmp/output.mp4

Input JSON:
{
  "scenes": [
    {
      "background": "місто",
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
Backgrounds: вулиця, місто, офіс, парк, ніч, магазин, кухня, пекло
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
S          = 0.72
EYE_SCALE  = 1.35
WALK_SPEED = 130

WHITE      = (255, 255, 255)
STICK_LINE = (25, 25, 25)
SKY_COL    = (135, 206, 235)
GROUND_COL = (60, 140, 60)
GROUND_LN  = (40, 100, 40)
SUN_COL    = (255, 215, 0)
BUBBLE_BG  = (255, 255, 255)
BUBBLE_BD  = (30, 30, 30)
TEXT_COL   = (20, 20, 20)

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

# ─── Хмара ────────────────────────────────────────────────────────────────────

def draw_cloud(draw, cx, cy, r):
    draw.ellipse([cx-r, cy-r//2, cx+r, cy+r//2], fill=WHITE)
    draw.ellipse([cx-r//2, cy-r*3//4, cx+r//2, cy+r//4], fill=WHITE)
    draw.ellipse([cx+r//3, cy-r*2//3, cx+r+6, cy+r//4-3], fill=WHITE)

# ─── Машина ───────────────────────────────────────────────────────────────────

def draw_car(draw, cx, cy, color, facing_right=True):
    """cx — центр, cy — низ машини."""
    cw, ch = 74, 28
    x1, x2 = cx - cw//2, cx + cw//2
    y1, y2 = cy - ch, cy

    # Тінь
    draw.rounded_rectangle([x1+4, y1+4, x2+4, y2+4], radius=6, fill=(100, 100, 100))
    # Корпус
    draw.rounded_rectangle([x1, y1, x2, y2], radius=6, fill=color, outline=STICK_LINE, width=2)

    # Кабіна (зміщена вперед)
    roof_off = 6 if facing_right else -6
    rx1 = cx - cw//4 + roof_off
    rx2 = cx + cw//4 + roof_off
    draw.rounded_rectangle([rx1, y1-17, rx2, y1+5], radius=5, fill=color, outline=STICK_LINE, width=2)

    # Вікна
    mid_r = (rx1 + rx2) // 2
    draw.rounded_rectangle([rx1+3, y1-14, mid_r-2, y1+2],
                            radius=3, fill=(200, 235, 255))
    draw.rounded_rectangle([mid_r+2, y1-14, rx2-3, y1+2],
                            radius=3, fill=(200, 235, 255))

    # Колеса
    for wx in [x1+13, x2-13]:
        draw.ellipse([wx-9, y2-9, wx+9, y2+7], fill=(30, 30, 30))
        draw.ellipse([wx-5, y2-6, wx+5, y2+4], fill=(80, 80, 80))

    # Фара
    fx = x2 - 5 if facing_right else x1 + 5
    draw.ellipse([fx-5, y1+7, fx+5, y1+15], fill=(255, 250, 180))

    # Задній ліхтар
    bx = x1 + 5 if facing_right else x2 - 5
    draw.ellipse([bx-4, y1+7, bx+4, y1+15], fill=(220, 60, 60))

# ─── Дерево ───────────────────────────────────────────────────────────────────

def draw_tree(draw, tx, gy, trunk_h=60, crown_r=38, sway=0):
    # Стовбур
    draw.polygon([
        (tx - 7, gy),
        (tx + 7, gy),
        (tx + 4 + sway, gy - trunk_h),
        (tx - 4 + sway, gy - trunk_h),
    ], fill=(110, 75, 35))
    # Тінь крони
    draw.ellipse([tx - crown_r + sway + 4, gy - trunk_h - int(crown_r*1.9) + 4,
                  tx + crown_r + sway + 4, gy - trunk_h + int(crown_r*0.3) + 4],
                 fill=(40, 120, 40))
    # Крона
    draw.ellipse([tx - crown_r + sway, gy - trunk_h - int(crown_r*1.9),
                  tx + crown_r + sway, gy - trunk_h + int(crown_r*0.3)],
                 fill=(65, 165, 60))
    # Відблиск
    draw.ellipse([tx - crown_r//2 + sway, gy - trunk_h - int(crown_r*1.7),
                  tx + sway,               gy - trunk_h - crown_r],
                 fill=(90, 190, 80))

# ─── Фони ─────────────────────────────────────────────────────────────────────

def bg_street(draw, fi):
    """Проста вулиця з сонцем і хмарами."""
    draw.rectangle([(0,0),(W,GROUND_Y)], fill=SKY_COL)
    draw.rectangle([(0,GROUND_Y),(W,H)], fill=GROUND_COL)
    draw.line([(0,GROUND_Y),(W,GROUND_Y)], fill=GROUND_LN, width=4)
    # Сонце
    draw.ellipse([W-85,18,W-18,85], fill=SUN_COL)
    sx, sy = W-52, 52
    for i in range(8):
        a = math.radians(i*45 + fi*0.6)
        draw.line([(sx+math.cos(a)*43, sy+math.sin(a)*43),
                   (sx+math.cos(a)*56, sy+math.sin(a)*56)], fill=(255,200,0), width=3)
    off = int(fi*0.35) % (W+160)
    draw_cloud(draw, 240-off, 70, 44)
    draw_cloud(draw, 60+W//2-off, 120, 30)

def bg_city(draw, fi):
    """Місто: будинки + тротуар + дорога + машини."""
    # Небо
    draw.rectangle([(0,0),(W, GROUND_Y-65)], fill=(165, 205, 235))

    # Будинки (фон)
    bldgs = [
        (  0, 155,  95, (148, 148, 158)),
        ( 90, 115,  82, (138, 143, 153)),
        (168, 175,  98, (158, 153, 148)),
        (260, 138,  88, (143, 148, 158)),
        (343, 162, 102, (153, 148, 153)),
        (440, 128,  60, (148, 152, 148)),
    ]
    for bx, bh, bw, bcol in bldgs:
        by = GROUND_Y - 65 - bh
        draw.rectangle([bx, by, bx+bw, GROUND_Y-65], fill=bcol)
        draw.line([(bx,by),(bx+bw,by)], fill=(100,104,112), width=2)
        draw.line([(bx,by),(bx,GROUND_Y-65)], fill=(110,114,122), width=1)
        draw.line([(bx+bw,by),(bx+bw,GROUND_Y-65)], fill=(110,114,122), width=1)
        # Вікна
        for wy in range(by+7, GROUND_Y-72, 24):
            for wx in range(bx+6, bx+bw-8, 19):
                lit = (fi//28 + wx//16 + wy//22) % 4 != 0
                wc  = (255, 238, 155) if lit else (70, 74, 84)
                draw.rectangle([wx, wy, wx+11, wy+14], fill=wc)

    # Тротуар
    sw = GROUND_Y - 65   # sidewalk top
    draw.rectangle([(0, sw),(W, GROUND_Y)], fill=(188, 183, 178))
    draw.line([(0,sw),(W,sw)], fill=(158,153,148), width=2)
    # Плитки тротуару
    for tx in range(0, W, 38):
        draw.line([(tx, sw),(tx, GROUND_Y)], fill=(172,167,162), width=1)
    for ty_t in range(sw+20, GROUND_Y, 20):
        draw.line([(0,ty_t),(W,ty_t)], fill=(172,167,162), width=1)

    # Дорога
    draw.rectangle([(0,GROUND_Y),(W,H)], fill=(78, 78, 82))
    # Розмітка
    dash, gap = 34, 26
    total_d   = dash + gap
    off_d     = int(fi * 2.5) % total_d
    for x in range(-total_d, W+total_d, total_d):
        xs = x - off_d
        draw.rectangle([xs, GROUND_Y+32, xs+dash, GROUND_Y+38], fill=(255,255,100))

    # Машини
    c1x = W + 90 - int(fi * 1.9) % (W + 180)
    c2x = int(fi * 1.5) % (W + 180) - 90
    draw_car(draw, c1x, GROUND_Y + 22, (200, 60, 60),  facing_right=False)
    draw_car(draw, c2x, GROUND_Y + 52, (60, 110, 210), facing_right=True)

def bg_park(draw, fi):
    """Парк: небо, трава, дерева, лавка, доріжка."""
    draw.rectangle([(0,0),(W,GROUND_Y)], fill=(155, 215, 245))
    draw.rectangle([(0,GROUND_Y),(W,H)], fill=(72, 158, 68))
    draw.line([(0,GROUND_Y),(W,GROUND_Y)], fill=(55, 132, 50), width=3)

    # Доріжка
    draw.ellipse([-50, GROUND_Y-12, W+50, GROUND_Y+28], fill=(200, 183, 158))

    # Сонце
    draw.ellipse([W-82,16,W-20,78], fill=SUN_COL)
    sx, sy = W-51, 47
    for i in range(8):
        a = math.radians(i*45 + fi*0.5)
        draw.line([(sx+math.cos(a)*40, sy+math.sin(a)*40),
                   (sx+math.cos(a)*52, sy+math.sin(a)*52)], fill=(255,200,0), width=2)

    # Хмари
    off = int(fi*0.28) % (W+160)
    draw_cloud(draw, 160-off, 50, 42)
    draw_cloud(draw, 55+W//2-off, 88, 26)

    # Дерева з похитуванням
    sw1 = int(math.sin(fi * 0.04) * 4)
    sw2 = int(math.sin(fi * 0.04 + 1.2) * 3)
    draw_tree(draw, 42,  GROUND_Y, 62, 38, sw1)
    draw_tree(draw, 132, GROUND_Y, 48, 29, sw2)
    draw_tree(draw, 375, GROUND_Y, 66, 42, sw1)
    draw_tree(draw, 455, GROUND_Y, 52, 33, sw2)

    # Лавка
    bx = 255
    for lx in [bx-24, bx+24]:
        draw.rectangle([lx-3, GROUND_Y-22, lx+3, GROUND_Y], fill=(128, 96, 52))
    draw.rounded_rectangle([bx-32, GROUND_Y-26, bx+32, GROUND_Y-16],
                            radius=3, fill=(158, 118, 68), outline=(118, 88, 46), width=2)
    draw.rounded_rectangle([bx-30, GROUND_Y-40, bx+30, GROUND_Y-30],
                            radius=3, fill=(158, 118, 68), outline=(118, 88, 46), width=2)

def bg_office(draw, fi):
    """Офіс з вікнами і столом з монітором."""
    draw.rectangle([(0,0),(W,H)], fill=(222, 212, 197))
    draw.rectangle([(0,H-140),(W,H)], fill=(182, 162, 132))
    draw.line([(0,H-140),(W,H-140)], fill=(152, 132, 102), width=3)
    # Вікна
    draw.rectangle([20,50,178,200], fill=(180,225,255), outline=STICK_LINE, width=4)
    draw.line([(99,50),(99,200)], fill=STICK_LINE, width=3)
    draw.line([(20,125),(178,125)], fill=STICK_LINE, width=3)
    draw.rectangle([262,50,420,200], fill=(180,225,255), outline=STICK_LINE, width=4)
    draw.line([(341,50),(341,200)], fill=STICK_LINE, width=3)
    draw.line([(262,125),(420,125)], fill=STICK_LINE, width=3)
    # Стіл
    desk_y = GROUND_Y - 72
    draw.rounded_rectangle([90, desk_y, 390, desk_y+14],
                            radius=4, fill=(160, 128, 88), outline=(128, 96, 64), width=2)
    # Ніжки столу
    for lx in [110, 370]:
        draw.rectangle([lx-5, desk_y+14, lx+5, GROUND_Y], fill=(140, 108, 72))
    # Монітор
    mx = 210
    draw.rounded_rectangle([mx, desk_y-88, mx+80, desk_y+2],
                            radius=4, fill=(30,30,30), outline=STICK_LINE, width=2)
    # Екран — мерехтить між зеленим і синім
    sc = (40, 200, 80) if (fi // 18) % 2 == 0 else (60, 130, 220)
    draw.rounded_rectangle([mx+5, desk_y-83, mx+75, desk_y-3], radius=2, fill=sc)
    # Підставка монітора
    draw.rounded_rectangle([mx+32, desk_y, mx+48, desk_y+12],
                            radius=2, fill=(50,50,50))
    draw.rounded_rectangle([mx+20, desk_y+10, mx+60, desk_y+14],
                            radius=2, fill=(50,50,50))
    # Клавіатура
    draw.rounded_rectangle([mx+90, desk_y-8, mx+170, desk_y+4],
                            radius=3, fill=(60,60,60), outline=(40,40,40), width=1)
    for ki in range(6):
        kx = mx+96 + ki*12
        draw.rounded_rectangle([kx, desk_y-6, kx+9, desk_y+2],
                                radius=1, fill=(80,80,80))

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
            x1_s = 8 + col*66
            c = colors[(row*4+col) % len(colors)]
            draw.rounded_rectangle([x1_s,sy+7,x1_s+50,sy+46],
                                    radius=4, fill=c, outline=STICK_LINE, width=2)

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

def bg_hell(draw, fi):
    """Пекло: темно-червоне небо, вогонь, скелі, тріщини."""
    # Небо
    draw.rectangle([(0,0),(W,GROUND_Y)], fill=(75, 14, 14))
    # Тло — туманний оранжевий градієнт знизу
    for i in range(60):
        alpha = i / 60
        c = int(75 + alpha * 60), int(14 + alpha * 20), int(14)
        draw.rectangle([(0, GROUND_Y-60+i), (W, GROUND_Y-59+i)], fill=c)

    # Земля
    draw.rectangle([(0,GROUND_Y),(W,H)], fill=(48, 18, 8))
    draw.line([(0,GROUND_Y),(W,GROUND_Y)], fill=(90, 30, 12), width=3)

    # Тріщини на землі з жаром
    cracks = [
        [(40,GROUND_Y),(65,GROUND_Y+28),(95,GROUND_Y+12)],
        [(200,GROUND_Y),(218,GROUND_Y+22),(245,GROUND_Y+8)],
        [(320,GROUND_Y),(340,GROUND_Y+30),(368,GROUND_Y+14)],
    ]
    for pts in cracks:
        draw.line(pts, fill=(220, 90, 20), width=3)

    # Скелі фону
    rocks = [(20,50,80), (110,65,70), (215,45,85), (335,72,80), (420,55,70)]
    for rx, rh, rw in rocks:
        draw.polygon([
            (rx, GROUND_Y), (rx+rw, GROUND_Y),
            (rx+rw-15, GROUND_Y-rh), (rx+15, GROUND_Y-rh)
        ], fill=(48, 20, 12))

    # Вогонь (анімований)
    flames = [30, 88, 150, 220, 295, 368, 435]
    for i, fx in enumerate(flames):
        phase = fi * 0.18 + i * 0.9
        fh    = int(50 + math.sin(phase) * 20)
        fw    = int(22 + math.sin(phase * 1.3) * 6)
        flick = int(math.sin(phase * 2.1) * 5)

        # Шари: зовнішній (темно-оранжевий) → середній → ядро (жовте)
        layers = [
            ((200, 50, 0),  fw,      fh),
            ((240, 120, 0), fw-5,    int(fh*0.75)),
            ((255, 210, 30),fw-11,   int(fh*0.45)),
        ]
        for col, w_f, h_f in layers:
            draw.ellipse([
                fx - w_f + flick, GROUND_Y - h_f,
                fx + w_f + flick, GROUND_Y + 5
            ], fill=col)

BG = {
    'вулиця':  bg_street,  'street':  bg_street,
    'місто':   bg_city,    'city':    bg_city,
    'офіс':    bg_office,  'office':  bg_office,
    'парк':    bg_park,    'park':    bg_park,
    'ніч':     bg_night,   'night':   bg_night,
    'магазин': bg_store,   'store':   bg_store,
    'кухня':   bg_kitchen, 'kitchen': bg_kitchen,
    'пекло':   bg_hell,    'hell':    bg_hell,
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

# ─── Обличчя (Loading Artist + 5 емоцій) ─────────────────────────────────────

def draw_face(draw, fi, cx, facing_right, emotion, talking):
    fs  = 8 if facing_right else -8
    ey  = HEAD_CY - int(8 * S)

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

    if emotion == 'surprised':
        er_l = int(er_l * 1.25)
        er_r = int(er_r * 1.25)
        pr_l = int(pr_l * 1.1)
        pr_r = int(pr_r * 1.1)

    # Очі
    draw.ellipse([el_cx-er_l, ey-er_l, el_cx+er_l, ey+er_l],
                 fill=WHITE, outline=STICK_LINE, width=3)
    draw.ellipse([el_cx-pr_l//2+1, ey-pr_l//2, el_cx+pr_l//2+1, ey+pr_l//2+1],
                 fill=STICK_LINE)
    draw.ellipse([el_cx-7, ey-int(er_l*0.5), el_cx, ey-int(er_l*0.15)], fill=WHITE)

    draw.ellipse([er_cx-er_r, ey-er_r, er_cx+er_r, ey+er_r],
                 fill=WHITE, outline=STICK_LINE, width=3)
    draw.ellipse([er_cx-pr_r//2+2, ey-pr_r//2, er_cx+pr_r//2+2, ey+pr_r//2+2],
                 fill=STICK_LINE)
    draw.ellipse([er_cx-8, ey-int(er_r*0.5), er_cx, ey-int(er_r*0.15)], fill=WHITE)

    # Брови
    by = ey - max(er_l, er_r) - 3
    if emotion == 'angry':
        draw.line([(el_cx-er_l+2, by+2), (el_cx+er_l-2, by+9)], fill=STICK_LINE, width=7)
        draw.line([(er_cx-er_r+2, by+9), (er_cx+er_r-2, by+2)], fill=STICK_LINE, width=7)
    elif emotion == 'sad':
        draw.line([(el_cx-er_l+2, by+9), (el_cx+er_l-2, by+2)], fill=STICK_LINE, width=7)
        draw.line([(er_cx-er_r+2, by+2), (er_cx+er_r-2, by+9)], fill=STICK_LINE, width=7)
    elif emotion == 'surprised':
        draw.arc([el_cx-er_l+2, by-10, el_cx+er_l-2, by+6], 200, 340, fill=STICK_LINE, width=6)
        draw.arc([er_cx-er_r+2, by-10, er_cx+er_r-2, by+6], 200, 340, fill=STICK_LINE, width=6)
    else:
        draw.line([(el_cx-er_l+2, by+5), (el_cx+er_l-2, by)], fill=STICK_LINE, width=6)
        draw.line([(er_cx-er_r+2, by), (er_cx+er_r-2, by+5)], fill=STICK_LINE, width=6)

    # Ніс
    nx = cx + fs//2
    draw.ellipse([nx-3, HEAD_CY+int(11*S), nx+3, HEAD_CY+int(18*S)], fill=(190,150,130))

    # Рот
    my = HEAD_CY + int(42*S)
    if emotion == 'surprised':
        draw.ellipse([cx-int(10*S)+fs//2, my-int(11*S),
                      cx+int(14*S)+fs//2, my+int(14*S)],
                     fill=(180,30,30), outline=STICK_LINE, width=3)
    elif emotion == 'angry':
        mx1 = cx - int(22*S) + fs//2
        mx2 = cx + int(26*S) + fs//2
        my1, my2 = my - int(5*S), my + int(10*S)
        draw.rectangle([mx1, my1, mx2, my2], fill=(180,30,30))
        draw.line([(mx1, my1+4), (mx2, my1+4)], fill=WHITE, width=3)
        draw.rectangle([mx1, my1, mx2, my2], outline=STICK_LINE, width=3)
    elif emotion == 'sad':
        draw.arc([cx-int(22*S)+fs//2, my-int(8*S),
                  cx+int(30*S)+fs//2, my+int(16*S)],
                 180, 360, fill=STICK_LINE, width=5)
        for drop_cx, drop_er in [(el_cx, er_l), (er_cx, er_r)]:
            draw.ellipse([drop_cx-4, ey+drop_er+2, drop_cx+4, ey+drop_er+11],
                         fill=(120, 170, 255))
    elif emotion in ('talking', 'normal') and talking and (fi//4) % 2 == 0:
        draw.ellipse([cx-int(26*S)+fs//2, my-int(13*S),
                      cx+int(30*S)+fs//2, my+int(18*S)], fill=(180,30,30))
        draw.rectangle([cx-int(18*S)+fs//2, my-int(11*S),
                        cx+int(22*S)+fs//2, my-2], fill=WHITE)
    else:
        draw.arc([cx-int(22*S)+fs//2, my-int(10*S),
                  cx+int(30*S)+fs//2, my+int(18*S)],
                 0, 180, fill=STICK_LINE, width=5)

# ─── Хвіст (Поліна) ───────────────────────────────────────────────────────────

def draw_ponytail(draw, cx, facing_right):
    HAIR_COL  = (200, 90, 30)
    HAIR_DARK = (155, 58, 12)
    side = -1 if facing_right else 1
    tx   = cx + side * (HEAD_RX - 4)
    ty   = HEAD_CY - HEAD_RY + int(12*S)
    thick = int(16*S)
    pts  = []
    n    = 14
    for i in range(n+1):
        f  = i / n
        px = tx + side * int(f * 20*S)
        py = ty + int((f**0.75) * 138*S)
        pts.append((px, py))
    for i in range(len(pts)-1):
        w = max(4, int(thick * (1 - i/n * 0.5)))
        _seg(draw, *pts[i], *pts[i+1], HAIR_COL, w)
        _seg(draw, *pts[i], *pts[i+1], HAIR_DARK, max(2, w-5))
    gx, gy = pts[n//2]
    draw.ellipse([gx-5, gy-5, gx+5, gy+5], fill=(220, 50, 50))

# ─── Персонаж ─────────────────────────────────────────────────────────────────

def draw_char(draw, fi, cx, char_id, walking=False, facing_right=True, talking=False, emotion='normal'):
    cfg   = CHAR_CFG[char_id % len(CHAR_CFG)]
    jcol  = cfg['jacket']
    tcol  = cfg['tie']
    hair  = cfg['hair']

    sway  = int(math.sin(fi * 0.04) * 2)
    cx    = cx + sway
    swing = math.sin(fi * 0.12) * 20
    fs    = 8 if facing_right else -8
    hip_w = SHIRT_W + int(14*S)
    arm_y = NECK_Y + int(28*S)

    if hair == 'ponytail':
        draw_ponytail(draw, cx, facing_right)

    # Руки
    for side in (-1, 1):
        sw   = side if facing_right else -side
        x_sh = cx + SHIRT_W * sw
        x_el = int(cx + SHIRT_W*sw + ARM_LEN*sw*0.45) + 5*sw
        x_h  = int(cx + SHIRT_W*sw + ARM_LEN*sw)
        y_sh = arm_y
        y_el = int(arm_y + ARM_LEN*0.35 + swing*0.5*sw)
        y_h  = int(arm_y + 60 + swing*sw)
        _limb(draw, [(x_sh,y_sh),(x_el,y_el),(x_h,y_h)], STICK_LINE, SLEEVE_W)

    # Куртка
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
    tx_t = cx + fs//3
    draw.polygon([
        (tx_t-4,v_d-2),(tx_t+4,v_d-2),
        (tx_t+7,v_d+int(38*S)),(tx_t,v_d+int(54*S)),(tx_t-7,v_d+int(38*S))
    ], fill=tcol, outline=STICK_LINE, width=2)

    # Ноги
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
        lknee = (cx - int(50*S), HIP_Y + int(88*S))
        lfoot = (cx - int(50*S), GROUND_Y)
        rknee = (cx + int(50*S), HIP_Y + int(88*S))
        rfoot = (cx + int(50*S), GROUND_Y)

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

    # Голова
    draw.ellipse([cx-HEAD_RX, HEAD_CY-HEAD_RY, cx+HEAD_RX, HEAD_CY+HEAD_RY],
                 fill=(195,200,210), outline=STICK_LINE, width=LW)
    shift = int(18*S) if facing_right else -int(18*S)
    draw.ellipse([cx-HEAD_RX+shift, HEAD_CY-HEAD_RY+4,
                  cx+HEAD_RX+int(shift*0.15), HEAD_CY+HEAD_RY-4], fill=WHITE)
    draw.ellipse([cx-HEAD_RX, HEAD_CY-HEAD_RY, cx+HEAD_RX, HEAD_CY+HEAD_RY],
                 outline=STICK_LINE, width=LW)

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
    bub_w  = min(185, W // max(n_slots, 1) + 40)
    bx1    = max(5, cx - bub_w//2)
    bx2    = min(W-5, bx1 + bub_w)
    if bx2 - bx1 < 80:
        bx1 = max(5, bx2-80)
    by1    = 16
    by2    = by1 + len(lines)*line_h + pad*2

    draw.rounded_rectangle([bx1+3, by1+3, bx2+3, by2+3], radius=13, fill=(160,160,160))
    draw.rounded_rectangle([bx1, by1, bx2, by2], radius=13,
                            fill=BUBBLE_BG, outline=BUBBLE_BD, width=3)
    tail_y  = HEAD_CY - HEAD_RY - 4
    mid_bub = (bx1 + bx2) // 2
    draw.polygon([(mid_bub-8,by2),(mid_bub+8,by2),(cx,tail_y)], fill=BUBBLE_BG)
    draw.line([(mid_bub-8,by2),(cx,tail_y)], fill=BUBBLE_BD, width=2)
    draw.line([(mid_bub+8,by2),(cx,tail_y)], fill=BUBBLE_BD, width=2)
    ty    = by1 + pad
    mid_x = (bx1+bx2)//2
    for line in lines:
        draw.text((mid_x, ty), line, font=font, fill=TEXT_COL, anchor='mt')
        ty += line_h

# ─── Рендер сцени ─────────────────────────────────────────────────────────────

def render_scene(scene_def, scene_idx, initial_chars, work_dir):
    bg_key  = scene_def.get('background', 'вулиця').lower()
    draw_bg = BG.get(bg_key, bg_street)

    entering_list = scene_def.get('enter', [])
    entering_dict = {e['char']: e.get('from', 'left') for e in entering_list}
    exiting_set   = {e['char'] for e in scene_def.get('exit', [])}

    present        = set(initial_chars.keys()) | set(entering_dict.keys())
    sorted_present = sorted(present)
    slots          = slot_positions(len(sorted_present))
    char_targets   = {cid: slots[i] for i, cid in enumerate(sorted_present)}

    char_starts   = {}
    arrival_times = {}
    for cid, side in entering_dict.items():
        start_x = -HEAD_RX*3 if side == 'left' else W + HEAD_RX*3
        char_starts[cid]   = start_x
        arrival_times[cid] = abs(char_targets[cid] - start_x) / WALK_SPEED
    for cid in initial_chars:
        start_x = initial_chars[cid]
        char_starts[cid]   = start_x
        dist = abs(char_targets[cid] - start_x)
        arrival_times[cid] = dist / WALK_SPEED if dist > 5 else 0.0

    enter_end = max(arrival_times.values()) if arrival_times else 0.0

    # Аудіо
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

    dialog_times = []
    t = enter_end + 0.3
    for dur in audio_durs:
        dialog_times.append((t, t+dur))
        t += dur + 0.25

    dialogs_end = dialog_times[-1][1] if dialog_times else (enter_end+0.3)
    exit_start  = dialogs_end + 0.2
    exit_data   = {}
    for cid in exiting_set:
        from_x = char_targets.get(cid, 240)
        to_x   = W + HEAD_RX*3
        dur    = abs(to_x - from_x) / WALK_SPEED
        exit_data[cid] = (from_x, to_x, dur)

    exit_end     = (exit_start + max(d[2] for d in exit_data.values())) if exit_data else exit_start
    total_dur    = exit_end + 0.4
    total_frames = int(total_dur * FPS)
    font         = load_font(21)

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
            t_cur        = fi / FPS
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
                    prog         = min(1.0, (t_cur-exit_start)/edur) if edur > 0 else 1.0
                    cx_f         = from_x + (to_x-from_x)*prog
                    walking      = prog < 0.999
                    facing_right = True
                    emo          = 'normal'
                elif arr_t > 0 and t_cur < arr_t:
                    prog         = t_cur / arr_t
                    cx_f         = start_x + (target_x-start_x)*prog
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
                        facing_right = target_x <= W//2
                    emo = bubble_emot if char_id == talking_char else 'normal'

                if cx_f < -HEAD_RX*2 or cx_f > W+HEAD_RX*2:
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

    # Мікс аудіо
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

# ─── Головна ──────────────────────────────────────────────────────────────────

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
