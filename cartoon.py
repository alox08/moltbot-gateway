#!/usr/bin/env python3
"""
Cartoon mini-movie generator v4 — 1280x720 (16:9) South Park proportions
Usage: python3 cartoon.py --input /tmp/input.json --output /tmp/output.mp4

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

# ─── Розміри кадру ─────────────────────────────────────────────────────────────
#
#   1280 × 720 (16:9) — стандарт мультиків (South Park, Family Guy...)
#   Персонажі ~35% висоти кадру — пропорційні будівлям на фоні
#    VERSION: 2026-04-05-proper-walk-cycle
#
W, H       = 1280, 720
FPS        = 25
S          = 0.72          # масштаб персонажів (збільшено для medium shot)
WALK_SPEED = 50            # px/s (суттєво сповільнена хода)

# ─── Кольори ──────────────────────────────────────────────────────────────────

WHITE      = (255, 255, 255)
STICK_LINE = (20,  20,  20)
SKY_COL    = (130, 200, 235)
GROUND_COL = (65,  148,  60)
GROUND_LN  = (45,  118,  40)
SUN_COL    = (255, 215,   0)
BUBBLE_BG  = (255, 255, 255)
BUBBLE_BD  = (25,  25,   25)
TEXT_COL   = (15,  15,   15)

# ─── Конфіг персонажів ────────────────────────────────────────────────────────

CHAR_CFG = [
    {'jacket': (55, 115, 225),  'tie': (200, 20, 20),   'voice': 'uk-UA-OstapNeural',  'hair': None},
    {'jacket': (220, 80, 150),  'tie': (255, 220, 50),  'voice': 'uk-UA-PolinaNeural', 'hair': 'ponytail'},
    {'jacket': (50, 170, 80),   'tie': (255, 140, 0),   'voice': 'uk-UA-OstapNeural',  'hair': None},
]

# ─── Розміри персонажів ────────────────────────────────────────────────────────
#
#   GROUND_Y = 560 → 560..720 = 160px для дороги/трави під персонажами
#   Персонаж зростом ~250px з 720 = 35% кадру — пропорційні будівлям
#

GROUND_Y = 560
HEAD_RX  = int(98  * S)   # = 47
HEAD_RY  = int(84  * S)   # = 40
HEAD_CY  = GROUND_Y - int(420 * S)   # = 560-201 = 359
NECK_Y   = HEAD_CY + HEAD_RY + 4     # = 403
HIP_Y    = NECK_Y  + int(165 * S)    # = 482
ARM_LEN  = int(90  * S)   # = 43
SHIRT_W  = int(62  * S)   # = 29
SLEEVE_W = max(8,  int(17 * S))   # = 8
HIP_W    = int(70 * S)    # = 34 (ширина розташування стегон)
LEG_W    = max(12, int(24 * S))   # зменшено товщину
LW       = max(5,  int(9 * S))    # м'якший контур


# ─── Слоти позицій (1280px) ───────────────────────────────────────────────────

def slot_positions(n):
    if n == 1: return [640]
    if n == 2: return [380, 900]
    return [230, 640, 1050]

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
    # Додаємо -show_format, оскільки для MP3 файлів тривалість часто лежить у format, а не у streams
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', path],
        capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
        if 'format' in data and 'duration' in data['format']:
            return float(data['format']['duration'])
        for s in data.get('streams', []):
            if 'duration' in s:
                return float(s['duration'])
    except Exception as e:
        pass
    return 2.0

# ─── Допоміжні ────────────────────────────────────────────────────────────────

def draw_cloud(draw, cx, cy, r):
    draw.ellipse([cx-r, cy-r//2, cx+r, cy+r//2], fill=WHITE)
    draw.ellipse([cx-r//2, cy-r*3//4, cx+r//2, cy+r//4], fill=WHITE)
    draw.ellipse([cx+r//3, cy-r*2//3, cx+r+8, cy+r//4-4], fill=WHITE)

def draw_car(draw, cx, cy, color, facing_right=True, cw=100, ch=38):
    """cx=центр, cy=низ машини."""
    x1, x2 = cx - cw//2, cx + cw//2
    y1, y2 = cy - ch, cy
    # Тінь
    draw.rounded_rectangle([x1+5, y1+5, x2+5, y2+5], radius=8, fill=(90,90,90))
    # Корпус
    draw.rounded_rectangle([x1, y1, x2, y2], radius=8, fill=color, outline=STICK_LINE, width=3)
    # Кабіна (зміщена вперед залежно від напрямку)
    roof_off = 8 if facing_right else -8
    rx1 = cx - cw//4 + roof_off
    rx2 = cx + cw//4 + roof_off
    draw.rounded_rectangle([rx1, y1-22, rx2, y1+6], radius=7, fill=color, outline=STICK_LINE, width=3)
    # Вікна
    mid_r = (rx1 + rx2) // 2
    draw.rounded_rectangle([rx1+4, y1-18, mid_r-3, y1+3],
                            radius=4, fill=(195, 230, 255))
    draw.rounded_rectangle([mid_r+3, y1-18, rx2-4, y1+3],
                            radius=4, fill=(195, 230, 255))
    # Колеса
    for wx in [x1+16, x2-16]:
        draw.ellipse([wx-12, y2-11, wx+12, y2+9], fill=(25,25,25))
        draw.ellipse([wx-7,  y2-7,  wx+7,  y2+5], fill=(75,75,75))
    # Фара / задній ліхтар
    fx = x2-6 if facing_right else x1+6
    draw.ellipse([fx-7, y1+9, fx+7, y1+20], fill=(255,250,180))
    bx = x1+6 if facing_right else x2-6
    draw.ellipse([bx-5, y1+9, bx+5, y1+20], fill=(220,55,55))

def draw_tree(draw, tx, sway=0, scale=1.0):
    h = int(80 * scale)
    r = int(52 * scale)
    # Стовбур
    draw.polygon([
        (tx-9, GROUND_Y),
        (tx+9, GROUND_Y),
        (tx+5+sway, GROUND_Y-h),
        (tx-5+sway, GROUND_Y-h),
    ], fill=(108, 72, 30))
    # Тінь крони
    draw.ellipse([tx-r+sway+6, GROUND_Y-h-int(r*1.85)+6,
                  tx+r+sway+6, GROUND_Y-h+int(r*0.3)+6], fill=(38,115,38))
    # Крона
    draw.ellipse([tx-r+sway, GROUND_Y-h-int(r*1.85),
                  tx+r+sway, GROUND_Y-h+int(r*0.3)], fill=(62,158,55))
    # Відблиск
    draw.ellipse([tx-r//2+sway, GROUND_Y-h-int(r*1.7),
                  tx+sway,      GROUND_Y-h-r], fill=(85, 185, 75))

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

def draw_thick_leg(draw, hip_pt, knee_pt, foot_pt, color, width):
    """Малює ногу як дві товстіші трубки замість _limb()."""
    # Стегно від стегнової кістки до колена
    draw.line([hip_pt, knee_pt], fill=color, width=width)
    # Гомілка від коліна до стопи
    draw.line([knee_pt, foot_pt], fill=color, width=width)
    # Суглоби (скруглені)
    r = width // 2
    draw.ellipse([hip_pt[0]-r, hip_pt[1]-r, hip_pt[0]+r, hip_pt[1]+r], fill=color)
    draw.ellipse([knee_pt[0]-r, knee_pt[1]-r, knee_pt[0]+r, knee_pt[1]+r], fill=color)

def draw_foot(draw, knee_pt, foot_pt, color, shoe_len=50, facing_right=True):
    """Малює черевик — носок вказує у напрямку ходьби."""
    fx, fy = foot_pt

    h = int(shoe_len * 0.20)   # висота ~10px (компактний)

    # Носок — видовжений у напрямку ходьби
    toe_front = int(shoe_len * 0.55)   # ~27px вперед
    # П'ята — компактна
    heel_back = int(shoe_len * 0.20)   # ~10px назад

    if facing_right:
        # Дивиться вправо — носок праворуч
        x1 = fx - heel_back
        y1 = fy - h
        x2 = fx + toe_front
        y2 = fy
    else:
        # Дивиться вліво — носок ліворуч (дзеркально)
        x1 = fx - toe_front
        y1 = fy - h
        x2 = fx + heel_back
        y2 = fy

    draw.rounded_rectangle([x1, y1, x2, y2], radius=3, fill=color, outline=STICK_LINE, width=2)

# ─── Фони ─────────────────────────────────────────────────────────────────────

def bg_street(draw, fi):
    draw.rectangle([(0,0),(W,GROUND_Y)], fill=SKY_COL)
    draw.rectangle([(0,GROUND_Y),(W,H)], fill=GROUND_COL)
    draw.line([(0,GROUND_Y),(W,GROUND_Y)], fill=GROUND_LN, width=5)
    # Сонце
    draw.ellipse([W-110,20,W-20,110], fill=SUN_COL)
    sx, sy = W-65, 65
    for i in range(8):
        a = math.radians(i*45 + fi*0.6)
        draw.line([(sx+math.cos(a)*58, sy+math.sin(a)*58),
                   (sx+math.cos(a)*75, sy+math.sin(a)*75)], fill=(255,200,0), width=4)
    off = int(fi*0.45) % (W+200)
    draw_cloud(draw, 320-off, 85, 60)
    draw_cloud(draw, 700-off, 50, 42)
    draw_cloud(draw, 1050-off, 95, 52)

def draw_pine_tree(draw, tx, ty, h=100, w=62):
    """Смерека South Park стиль — 3 шари трикутників."""
    trunk_h = int(h * 0.20)
    # Стовбур
    draw.rectangle([tx-5, ty-trunk_h, tx+5, ty], fill=(95, 58, 24))
    # 3 шари крони (знизу широкий → вгорі вузький)
    for layer in range(3):
        f   = layer / 2.0
        lw  = int(w * (1.0 - f * 0.38))
        base_y = ty - trunk_h - int(h * 0.50 * f)
        top_y  = base_y - int(h * (0.50 - f * 0.12))
        gcol   = (32 + layer*14, 82 + layer*22, 32 + layer*12)
        draw.polygon([
            (tx - lw//2, base_y),
            (tx + lw//2, base_y),
            (tx, top_y),
        ], fill=gcol, outline=(18, 52, 18), width=1)


def draw_building_sp(draw, fi, bx, sw_top, bw, bh, color, style='flat'):
    """Будівля South Park стиль: теплі кольори, вікна з рамами, двері, дах."""
    by   = sw_top - bh
    dark = tuple(max(0, c - 48) for c in color)
    mid  = tuple(max(0, c - 22) for c in color)

    # Тінь
    draw.rectangle([bx+5, by+5, bx+bw+5, sw_top+5], fill=(65, 65, 68))

    # Основне тіло
    draw.rectangle([bx, by, bx+bw, sw_top], fill=color)
    draw.line([(bx, by), (bx+bw, by)],       fill=dark, width=3)
    draw.line([(bx, by), (bx, sw_top)],       fill=mid,  width=2)
    draw.line([(bx+bw, by), (bx+bw, sw_top)], fill=dark, width=2)

    # Дах
    if style == 'peaked':
        peak_h = int(bw * 0.30)
        roof_col = tuple(max(0, c - 55) for c in color)
        draw.polygon([
            (bx - 4,    by + 4),
            (bx + bw+4, by + 4),
            (bx + bw//2, by - peak_h),
        ], fill=roof_col, outline=dark, width=2)
        # Труба
        cx_ch = bx + bw // 3
        draw.rectangle([cx_ch-7, by-peak_h+8, cx_ch+7, by-peak_h+36], fill=dark)
        draw.rectangle([cx_ch-9, by-peak_h+6, cx_ch+9, by-peak_h+14], fill=mid)
    else:
        # Плаский дах — парапет
        draw.rectangle([bx-2, by-10, bx+bw+2, by+4], fill=mid)
        draw.line([(bx-2, by-10), (bx+bw+2, by-10)], fill=dark, width=2)
        # Труба
        cx_ch = bx + bw * 3 // 4
        draw.rectangle([cx_ch-7, by-32, cx_ch+7, by-8], fill=dark)
        draw.rectangle([cx_ch-9, by-34, cx_ch+9, by-26], fill=mid)

    # Вікна з хрестоподібними рамами
    win_w, win_h = 32, 40
    gap_x, gap_y = 16, 22
    cols = max(1, (bw - 28) // (win_w + gap_x))
    total_wx = cols * win_w + (cols-1) * gap_x
    wx0  = bx + (bw - total_wx) // 2
    rows = min(4, (bh - 68) // (win_h + gap_y))

    for row in range(rows):
        wy = by + 22 + row * (win_h + gap_y)
        for col in range(cols):
            wx = wx0 + col * (win_w + gap_x)
            # Рама
            draw.rectangle([wx-3, wy-3, wx+win_w+3, wy+win_h+3], fill=dark)
            # Скло
            lit = (fi // 38 + col*3 + row*7) % 6 != 0
            wc  = (205, 225, 248) if lit else (52, 62, 78)
            draw.rectangle([wx, wy, wx+win_w, wy+win_h], fill=wc)
            # Хрест рами
            draw.line([(wx+win_w//2, wy), (wx+win_w//2, wy+win_h)],
                      fill=dark, width=2)
            draw.line([(wx, wy+win_h//2), (wx+win_w, wy+win_h//2)],
                      fill=dark, width=2)
            # Підвіконня
            draw.rectangle([wx-4, wy+win_h+2, wx+win_w+4, wy+win_h+6],
                            fill=mid)

    # Двері
    dw, dh = 28, 46
    dx = bx + bw//2 - dw//2
    dy = sw_top - dh
    draw.rectangle([dx, dy, dx+dw, sw_top], fill=(65, 40, 18))
    draw.rounded_rectangle([dx+2, dy+2, dx+dw-2, dy+dh//2+6],
                            radius=10, fill=(88, 55, 26))
    draw.ellipse([dx+dw-9, dy+dh//2+2, dx+dw-3, dy+dh//2+10],
                 fill=(195, 162, 48))
    # Козирок
    draw.polygon([
        (dx-14, dy-2), (dx+dw+14, dy-2),
        (dx+dw+8, dy+12), (dx-8, dy+12),
    ], fill=dark)


def bg_city(draw, fi):
    """Місто South Park стиль: гори, кольорові будівлі, смереки, машини."""
    sw_top = GROUND_Y - 80   # верх тротуару = 480

    # 1. Небо
    draw.rectangle([(0, 0), (W, sw_top)], fill=(152, 195, 232))

    # 2. Гори на горизонті (зелені пагорби + сніжні вершини)
    hill_pts = [
        (0, sw_top), (0, 360),
        (90, 235), (195, 345), (305, 188),
        (445, 322), (545, 215), (665, 355),
        (755, 225), (875, 318),
        (968, 195), (1085, 340),
        (1162, 238), (1280, 305),
        (1280, sw_top),
    ]
    # Тінь пагорбів
    shadow_pts = [(x, y+8) for x, y in hill_pts]
    draw.polygon(shadow_pts, fill=(78, 105, 82))
    # Пагорби
    draw.polygon(hill_pts, fill=(88, 128, 88))
    # Снігові шапки
    snow_peaks = [(305,188),(545,215),(755,225),(968,195),(1162,238)]
    for px, py in snow_peaks:
        draw.polygon([(px-26, py+38), (px+26, py+38), (px, py)],
                     fill=(235, 240, 250))

    # 3. Хмари (невеликі, над горами)
    off = int(fi * 0.32) % (W + 200)
    draw_cloud(draw, 240-off, 80, 48)
    draw_cloud(draw, 650-off, 55, 36)
    draw_cloud(draw, 1050-off, 70, 44)

    # 4. Будівлі South Park стиль (7 штук, теплі кольори) — збільшено на 15%
    # (bx, bw, bh, color, style)
    buildings = [
        (   0, 221, 339, (192, 162, 128), 'peaked'),   # беж (192→221, 295→339)
        ( 186, 196, 259, (168,  68,  62), 'peaked'),   # червоний (170→196, 225→259)
        ( 350, 221, 377, ( 68,  98, 142), 'flat'),     # синій (192→221, 328→377)
        ( 536, 247, 297, (128, 152,  96), 'peaked'),   # оливковий (215→247, 258→297)
        ( 745, 207, 334, (152, 118,  80), 'flat'),     # коричневий (180→207, 290→334)
        ( 918, 223, 305, (178,  98,  75), 'flat'),     # теракотовий (194→223, 265→305)
        (1105, 201, 282, (208, 198, 175), 'peaked'),   # кремовий (175→201, 245→282)
    ]
    for bx, bw, bh, col, style in buildings:
        draw_building_sp(draw, fi, bx, sw_top, bw, bh, col, style)

    # 5. Смереки між будівлями (South Park характерні дерева)
    pine_positions = [182, 346, 532, 741, 914, 1101]
    for tx in pine_positions:
        draw_pine_tree(draw, tx, sw_top, h=118, w=68)

    # 6. Тротуар
    draw.rectangle([(0, sw_top), (W, GROUND_Y)], fill=(182, 177, 170))
    draw.line([(0, sw_top), (W, sw_top)], fill=(152, 147, 140), width=2)
    for tx in range(0, W, 55):
        draw.line([(tx, sw_top), (tx, GROUND_Y)], fill=(165, 160, 153), width=1)
    for ty_t in range(sw_top+28, GROUND_Y, 28):
        draw.line([(0, ty_t), (W, ty_t)], fill=(165, 160, 153), width=1)

    # Бордюр
    draw.rectangle([(0, GROUND_Y-8), (W, GROUND_Y+4)], fill=(115, 110, 105))

    # 7. Дорога (2 смуги)
    draw.rectangle([(0, GROUND_Y), (W, H)], fill=(65, 65, 68))

    # Розмітка між смугами
    dash, gap = 58, 42
    total_d   = dash + gap
    off_d     = int(fi * 4.2) % total_d
    lane_y    = GROUND_Y + 78
    for x in range(-total_d, W + total_d, total_d):
        xs = x - off_d
        draw.rectangle([xs, lane_y-5, xs+dash, lane_y+5], fill=(255, 255, 100))

    # 8. Машини (великі, South Park пропорції) — збільшено на 20%
    c1x = W + 200 - int(fi * 3.2) % (W + 400)
    c2x = int(fi * 2.5) % (W + 400) - 200
    c3x = W // 3 + 260 - int(fi * 1.8) % (W + 400)
    draw_car(draw, c1x, GROUND_Y + 52,  (198, 52, 52),  facing_right=False, cw=190, ch=65)
    draw_car(draw, c2x, GROUND_Y + 120, (52, 102, 202), facing_right=True,  cw=190, ch=65)
    draw_car(draw, c3x, GROUND_Y + 52,  (52, 175, 75),  facing_right=False, cw=178, ch=60)

def bg_park(draw, fi):
    """Парк з деревами, лавкою, доріжкою."""
    draw.rectangle([(0,0),(W,GROUND_Y)], fill=(148,212,242))
    draw.rectangle([(0,GROUND_Y),(W,H)], fill=(68,155,62))
    draw.line([(0,GROUND_Y),(W,GROUND_Y)], fill=(50,128,45), width=5)
    # Доріжка
    draw.ellipse([-80, GROUND_Y-18, W+80, GROUND_Y+42], fill=(195,178,152))
    # Сонце
    draw.ellipse([W-110,20,W-20,110], fill=SUN_COL)
    sx, sy = W-65, 65
    for i in range(8):
        a = math.radians(i*45 + fi*0.5)
        draw.line([(sx+math.cos(a)*55, sy+math.sin(a)*55),
                   (sx+math.cos(a)*72, sy+math.sin(a)*72)], fill=(255,200,0), width=3)
    # Хмари
    off = int(fi*0.35) % (W+200)
    draw_cloud(draw, 200-off, 65, 55)
    draw_cloud(draw, 580-off, 40, 38)
    draw_cloud(draw, 950-off, 75, 48)
    # Дерева (8 штук, різного розміру)
    sw1 = int(math.sin(fi*0.04)*5)
    sw2 = int(math.sin(fi*0.04+1.3)*4)
    draw_tree(draw, 50,   sw1, 1.0)
    draw_tree(draw, 148,  sw2, 0.75)
    draw_tree(draw, 258,  sw1, 0.85)
    draw_tree(draw, 980,  sw2, 0.9)
    draw_tree(draw, 1085, sw1, 1.1)
    draw_tree(draw, 1180, sw2, 0.8)
    draw_tree(draw, 430,  sw1, 0.6)
    draw_tree(draw, 870,  sw2, 0.65)
    # Лавка
    for bx in [560, 740]:
        for lx in [bx-30, bx+30]:
            draw.rectangle([lx-4, GROUND_Y-28, lx+4, GROUND_Y], fill=(120,90,46))
        draw.rounded_rectangle([bx-42, GROUND_Y-32, bx+42, GROUND_Y-20],
                                radius=4, fill=(152,112,62), outline=(112,82,40), width=2)
        draw.rounded_rectangle([bx-40, GROUND_Y-50, bx+40, GROUND_Y-36],
                                radius=4, fill=(152,112,62), outline=(112,82,40), width=2)

def bg_office(draw, fi):
    """Офіс: кімната з вікнами, стіл з монітором."""
    draw.rectangle([(0,0),(W,H)], fill=(218,208,192))
    draw.rectangle([(0,H-155),(W,H)], fill=(178,158,128))
    draw.line([(0,H-155),(W,H-155)], fill=(148,128,98), width=3)
    # 4 вікна
    for wx in [40, 300, 720, 980]:
        draw.rectangle([wx, 40, wx+200, 220], fill=(175,222,255), outline=STICK_LINE, width=4)
        draw.line([(wx+100,40),(wx+100,220)], fill=STICK_LINE, width=3)
        draw.line([(wx,130),(wx+200,130)], fill=STICK_LINE, width=3)
    # Стіл
    desk_y = GROUND_Y - 82
    draw.rounded_rectangle([180, desk_y, 1100, desk_y+16],
                            radius=5, fill=(155,122,84), outline=(122,92,60), width=2)
    for lx in [220, 1060]:
        draw.rectangle([lx-6, desk_y+16, lx+6, GROUND_Y], fill=(135,102,68))
    # 2 монітори
    for mx in [340, 820]:
        draw.rounded_rectangle([mx, desk_y-100, mx+100, desk_y+4],
                                radius=5, fill=(28,28,28), outline=STICK_LINE, width=2)
        sc = (38,195,75) if (fi//20) % 2 == 0 else (55,125,215)
        draw.rounded_rectangle([mx+6, desk_y-94, mx+94, desk_y-6], radius=3, fill=sc)
        draw.rounded_rectangle([mx+42, desk_y+4, mx+58, desk_y+16],
                                radius=2, fill=(45,45,45))
        draw.rounded_rectangle([mx+28, desk_y+15, mx+72, desk_y+19],
                                radius=2, fill=(45,45,45))
        # Клавіатура
        draw.rounded_rectangle([mx+108, desk_y-10, mx+220, desk_y+7],
                                radius=4, fill=(55,55,55), outline=(35,35,35), width=1)
        for ki in range(7):
            draw.rounded_rectangle([mx+114+ki*14, desk_y-7, mx+126+ki*14, desk_y+3],
                                    radius=1, fill=(75,75,75))

def bg_night(draw, fi):
    draw.rectangle([(0,0),(W,GROUND_Y)], fill=(12,12,42))
    draw.rectangle([(0,GROUND_Y),(W,H)], fill=(28,48,28))
    draw.line([(0,GROUND_Y),(W,GROUND_Y)], fill=(18,38,18), width=5)
    draw.ellipse([W-110,20,W-20,110], fill=(238,232,175))
    draw.ellipse([W-88,14,W-10,88], fill=(12,12,42))
    stars = [
        (62,42),(115,26),(198,60),(275,35),(348,55),(398,28),
        (48,92),(312,82),(158,38),(480,48),(620,25),(750,65),
        (880,40),(1020,30),(1150,55),(1240,45),(540,88),(790,22),
    ]
    for i, (sx_s, sy_s) in enumerate(stars):
        r = 3 + ((fi//16+i) % 2)
        draw.ellipse([sx_s-r,sy_s-r,sx_s+r,sy_s+r], fill=(255,255,198))

def bg_store(draw, fi):
    draw.rectangle([(0,0),(W,H)], fill=(238,232,218))
    draw.rectangle([(0,H-130),(W,H)], fill=(198,188,168))
    draw.line([(0,H-130),(W,H-130)], fill=(158,148,128), width=3)
    colors = [(220,80,80),(80,180,80),(80,80,220),(220,180,40),(180,80,220),(80,200,180)]
    for row, sy in enumerate([40,138,236]):
        draw.rectangle([(0,sy+56),(W,sy+64)], fill=(138,98,55))
        draw.rectangle([(0,sy),(5,sy+64)], fill=(138,98,55))
        draw.rectangle([(W-5,sy),(W,sy+64)], fill=(138,98,55))
        for col in range(12):
            x1_s = 10 + col*105
            c = colors[(row*5+col) % len(colors)]
            draw.rounded_rectangle([x1_s,sy+8,x1_s+78,sy+55],
                                    radius=5, fill=c, outline=STICK_LINE, width=2)

def bg_kitchen(draw, fi):
    draw.rectangle([(0,0),(W,H)], fill=(248,242,228))
    draw.rectangle([(0,GROUND_Y),(W,H)], fill=(198,178,148))
    draw.rectangle([(0,GROUND_Y),(W,GROUND_Y+20)], fill=(158,138,108))
    draw.line([(0,GROUND_Y),(W,GROUND_Y)], fill=STICK_LINE, width=2)
    draw.rectangle([W//2-100,42,W//2+100,238], fill=(178,228,242), outline=STICK_LINE, width=5)
    draw.line([(W//2,42),(W//2,238)], fill=STICK_LINE, width=3)
    draw.line([(W//2-100,140),(W//2+100,140)], fill=STICK_LINE, width=3)
    draw.rounded_rectangle([10,52,120,242], radius=6, fill=(208,192,168), outline=STICK_LINE, width=3)
    draw.rounded_rectangle([W-120,52,W-10,242], radius=6, fill=(208,192,168), outline=STICK_LINE, width=3)

def bg_hell(draw, fi):
    draw.rectangle([(0,0),(W,GROUND_Y)], fill=(72,12,12))
    for i in range(80):
        alpha = i / 80
        c = (int(72+alpha*65), int(12+alpha*22), 12)
        draw.rectangle([(0,GROUND_Y-80+i),(W,GROUND_Y-79+i)], fill=c)
    draw.rectangle([(0,GROUND_Y),(W,H)], fill=(45,16,8))
    draw.line([(0,GROUND_Y),(W,GROUND_Y)], fill=(88,28,10), width=4)
    # Тріщини
    cracks = [
        [(55,GROUND_Y),(85,GROUND_Y+38),(122,GROUND_Y+18)],
        [(320,GROUND_Y),(345,GROUND_Y+32),(378,GROUND_Y+12)],
        [(640,GROUND_Y),(660,GROUND_Y+40),(695,GROUND_Y+20)],
        [(900,GROUND_Y),(928,GROUND_Y+35),(958,GROUND_Y+14)],
        [(1180,GROUND_Y),(1205,GROUND_Y+38),(1238,GROUND_Y+18)],
    ]
    for pts in cracks:
        draw.line(pts, fill=(218,85,18), width=4)
    # Скелі
    rocks = [(20,70,110),(165,88,95),(380,65,110),(600,82,100),(840,72,95),(1060,90,110),(1210,68,100)]
    for rx, rh, rw in rocks:
        draw.polygon([
            (rx,GROUND_Y),(rx+rw,GROUND_Y),
            (rx+rw-18,GROUND_Y-rh),(rx+18,GROUND_Y-rh)
        ], fill=(44,18,10))
    # Вогонь (12 джерел)
    flames_x = [35, 95, 175, 265, 360, 480, 610, 730, 860, 980, 1100, 1215]
    for i, fx in enumerate(flames_x):
        phase = fi*0.18 + i*0.85
        fh    = int(65 + math.sin(phase)*26)
        fw    = int(28 + math.sin(phase*1.3)*8)
        flick = int(math.sin(phase*2.2)*7)
        for col, w_f, h_f in [
            ((198,48,0),  fw,    fh),
            ((238,118,0), fw-6,  int(fh*0.72)),
            ((255,205,28),fw-14, int(fh*0.42)),
        ]:
            draw.ellipse([fx-w_f+flick, GROUND_Y-h_f, fx+w_f+flick, GROUND_Y+6], fill=col)

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

# ─── Обличчя ──────────────────────────────────────────────────────────────────

def draw_face(draw, fi, cx, facing_right, emotion, talking, facing_camera=False):
    """
    Класичні об'єднані коміксні очі (як одна ціла маска) з красивим накладанням.
    Рот розташовується безпосередньо під очима.
    """
    is_profile = not facing_camera
    
    er = int(24*S)  # Оптимальний коміксний розмір
    pr = int(8*S)   # Зіниці
    ey = HEAD_CY - int(12*S)
    
    if emotion == 'surprised':
        er = int(er * 1.2)
        pr = int(pr * 1.2)
        
    if facing_camera:
        el_cx = cx - int(14*S)
        er_cx = cx + int(14*S)
        
        # 1. Чорні дуги навколо (овали з контуром)
        draw.ellipse([el_cx-er, ey-er, el_cx+er, ey+er], fill=WHITE, outline=STICK_LINE, width=LW)
        draw.ellipse([er_cx-er, ey-er, er_cx+er, ey+er], fill=WHITE, outline=STICK_LINE, width=LW)
        # 2. Центр замальовуємо білим, щоб очі з'єднались в єдине ціле
        draw.rectangle([cx-er//2, ey-er+LW+1, cx+er//2, ey+er-LW-1], fill=WHITE)
        
        # Зіниці
        px_off = int(6*S) if facing_right else -int(6*S)
        draw.ellipse([el_cx+px_off-pr, ey-pr, el_cx+px_off+pr, ey+pr], fill=STICK_LINE)
        draw.ellipse([er_cx+px_off-pr, ey-pr, er_cx+px_off+pr, ey+pr], fill=STICK_LINE)
    else:
        # Профіль: очі висунуті і зліплені
        dir_mult = 1 if facing_right else -1
        near_eye_cx = cx + dir_mult * int(HEAD_RX * 0.65)
        far_eye_cx = near_eye_cx + dir_mult * int(18*S)
        
        # Малюємо дальнє, потім ближнє
        draw.ellipse([far_eye_cx-er, ey-er, far_eye_cx+er, ey+er], fill=WHITE, outline=STICK_LINE, width=LW)
        draw.ellipse([near_eye_cx-er, ey-er, near_eye_cx+er, ey+er], fill=WHITE, outline=STICK_LINE, width=LW)
        # Об'єднуємо
        overlap_x1 = min(near_eye_cx, far_eye_cx)
        overlap_x2 = max(near_eye_cx, far_eye_cx)
        draw.rectangle([overlap_x1, ey-er+LW+1, overlap_x2, ey+er-LW-1], fill=WHITE)
        
        # Зіниці
        px_off = int(6*S) * dir_mult
        draw.ellipse([far_eye_cx+px_off-pr, ey-pr, far_eye_cx+px_off+pr, ey+pr], fill=STICK_LINE)
        draw.ellipse([near_eye_cx+px_off-pr, ey-pr, near_eye_cx+px_off+pr, ey+pr], fill=STICK_LINE)
    
    # ── Рот (кумедний, високо біля очей) ──
    my = ey + er + int(10*S)
    mx_off = 0 if facing_camera else int(HEAD_RX * 0.65) * (1 if facing_right else -1)
    
    if emotion == 'surprised' or (talking and (fi//4) % 2 == 0):
        mw = int(12*S)
        mh = int(18*S)
        rx1, ry1 = cx - mw + mx_off, my - mh//2
        rx2, ry2 = cx + mw + mx_off, my + mh//2
        draw.chord([rx1, ry1, rx2, ry2], 0, 180, fill=(220, 80, 80), outline=STICK_LINE, width=LW)
    elif emotion == 'angry' or emotion == 'sad':
        draw.arc([cx-int(10*S)+mx_off, my-int(6*S), cx+int(10*S)+mx_off, my+int(10*S)], 180, 360, fill=STICK_LINE, width=LW)
    else:
        draw.arc([cx-int(10*S)+mx_off, my-int(6*S), cx+int(10*S)+mx_off, my+int(10*S)], 0, 180, fill=STICK_LINE, width=LW)

# ─── Хвіст Поліни (Loading Artist стиль) ───────────────────────────────────────

def draw_ponytail(draw, cx, facing_right, draw_base=False):
    HAIR_COL = (255, 225, 40)
    # Зміщуємо шапочку волосся так само, як малюється голова
    is_profile = getattr(draw, '_current_is_profile', False)
    head_cx = cx + (int(6*S)//2 if facing_right else -int(6*S)//2) if is_profile else cx
    
    # Якщо draw_base, малюємо передню "шапочку" волосся під очима
    if draw_base:
        hw = HEAD_RY + int(4*S) if is_profile else HEAD_RX + int(4*S)
        hh = HEAD_RY + int(4*S)
        # Малюємо шапочку БЕЗ контуру, щоб не розрізати обличчя лінією
        draw.chord([head_cx-hw, HEAD_CY-hh, head_cx+hw, HEAD_CY+hh], 170, 370, fill=HAIR_COL)
        # Малюємо тільки верхню дугу
        draw.arc([head_cx-hw, HEAD_CY-hh, head_cx+hw, HEAD_CY+hh], 170, 370, fill=STICK_LINE, width=LW)
        return

    # Задній хвіст
    side = -1 if facing_right else 1
    root_x = head_cx + side * (HEAD_RX - 15)
    root_y = HEAD_CY - 5
    end_x = root_x + side * int(45*S)
    end_y = root_y + int(110*S)
    ctrl_x = root_x + side * int(80*S)
    
    pts = [
        (root_x, root_y - 15),
        (ctrl_x, root_y + 30),
        (end_x, end_y),
        (ctrl_x - side*30, root_y + 40),
        (root_x, root_y + 15)
    ]
    draw.polygon(pts, fill=HAIR_COL, outline=STICK_LINE, width=LW)
    # Гумка
    draw.ellipse([root_x-8, root_y-15, root_x+10, root_y+15], fill=(240, 50, 150), outline=STICK_LINE, width=LW)

def draw_fingers(draw, x, y, facing_right, color):
    """Малює кілька тоненьких ліній від кисті (пальців) без 'шаріків'."""
    dir_x = 1 if facing_right else -1
    for i in [-1, 1]:  # два маленькі пальчики
        fy = y + i * int(3*S)
        draw.line([(x, y), (x + dir_x*int(7*S), fy)], fill=color, width=max(1, int(2*S)))

# ─── Персонаж — South Park стиль (ходьба боком) ──────────────────────────────

def draw_char(draw, fi, cx, char_id, walking=False, direction=0, talking=False, emotion='normal', gesture=None, facing_camera=False):
    """
    direction: 0=фронтально, 1=праворуч (профіль), 2=ліворуч (профіль)
    South Park стиль: персонажі ходять боком, повертаються на 90°
    """
    cfg   = CHAR_CFG[char_id % len(CHAR_CFG)]
    jcol  = cfg['jacket']
    tcol  = cfg['tie']
    hair  = cfg['hair']

    # Гойдання тільки при ходьбі
    sway  = int(math.sin(fi*0.04)*2) if walking else 0
    cx    = cx + sway
    # Розмах рук тільки при ходьбі (повільніше для природності)
    swing = math.sin(fi*0.08)*16 if walking else 0
    
    # Визначаємо профіль чи ні
    is_profile = (direction == 1 or direction == 2)  # боком
    facing_right = (direction == 1)  # 1=праворуч, 2=ліворуч
    fs    = int(6*S) if facing_right else (-int(6*S) if direction == 2 else 0)
    hip_w = SHIRT_W + int(14*S)
    jacket_w = int(hip_w * 0.5)  # вужче в 2 рази для профілю
    # Плечо — верх куртки (одразу нижче шиї)
    arm_y = NECK_Y  + int(10*S)   # точка плеча (вище, ближче до шиї)

    # Руки в протифазі з ногами при ходьбі
    # walk_phase: 0→1 за 24 кадри (єдине джерело фази для рук і ніг)
    walk_phase   = (fi % 24) / 24.0
    arm_phase    = 0.0
    if walking:
        # Руки в ПРОТИФАЗІ з ногами: -cos дає правильну опозицію
        # walk_phase=0 → права нога СПЕРЕДУ → права рука ЗЗАДУ
        _wd_arm  = 1 if facing_right else -1
        arm_phase = -math.cos(walk_phase * 2 * math.pi) * _wd_arm

    # Хвіст (перед головою — голова перекриє)
    if hair == 'ponytail':
        draw_ponytail(draw, cx, facing_right)

    # Функція розрахунку точок руки (плече, контрольна ліктя, кисть)
    def calc_arm(is_far_arm=False, side_frontal=1):
        AL = int(ARM_LEN * 1.25)  # Трохи зменшив видовження
        
        if is_profile:
            dir_x = front_sw
            # Зміщуємо плече ближче до центру тіла
            x_sh = cx + int(jacket_w * 0.15 * front_sw)
        else:
            dir_x = side_frontal
            x_sh = cx + int(SHIRT_W * 0.8 * side_frontal)
            
        y_sh = arm_y

        # Фаза для цієї руки. Дальня рука рухається в протифазі
        cur_phase = -arm_phase if is_far_arm else arm_phase
        
        if emotion == 'surprised':
            x_el = int(x_sh + dir_x * AL * 0.3)
            y_el = int(y_sh - AL * 0.4)
            x_h  = int(x_sh + dir_x * AL * 0.3)
            y_h  = int(y_sh - AL * 1.0)
        elif emotion == 'angry':
            x_el = int(x_sh + dir_x * AL * 0.5)
            y_el = int(y_sh + AL * 0.1)
            x_h  = int(x_sh + dir_x * AL * 1.0)
            y_h  = int(y_sh - AL * 0.1)
        elif gesture == 'explain' and not is_far_arm:
            x_el = int(x_sh + dir_x * AL * 0.4)
            y_el = int(y_sh - AL * 0.1)
            x_h  = int(x_sh + dir_x * AL * 0.7)
            y_h  = int(y_sh - AL * 0.7)
        else:
            if is_profile:
                # ЗМЕНШЕНИЙ РОЗМАХ (0.5 замість 0.8) для спокійнішої ходьби
                swing_f = cur_phase * 0.5
                shoulder_angle = swing_f * 0.6
                
                # Менший ліктьовий згин для плавності
                elbow_bend = 0.05 if swing_f <= 0 else 0.05 + swing_f * 0.8
                elbow_angle = shoulder_angle + elbow_bend
            else:
                swing_f = cur_phase * 0.3 * side_frontal
                shoulder_angle = swing_f * 0.5
                elbow_bend = 0.1 if swing_f <= 0 else 0.1 + swing_f * 0.4
                elbow_angle = shoulder_angle + elbow_bend * dir_x

            U = AL * 0.5
            L = AL * 0.5
            x_el = int(x_sh + math.sin(shoulder_angle) * dir_x * U)
            y_el = int(y_sh + math.cos(shoulder_angle) * U)
            
            if not is_profile:
                x_el += int(0.15 * dir_x * U)
                
            x_h = int(x_el + math.sin(elbow_angle) * dir_x * L)
            y_h = int(y_el + math.cos(elbow_angle) * L)
            
            if not is_profile:
                x_h += int(0.15 * dir_x * L)

        return x_sh, y_sh, x_el, y_el, x_h, y_h

    # ── Задня рука (Дальня) малюється ДО куртки ──
    front_sw = 1 if facing_right else -1

    if is_profile:
        x_sh, y_sh, x_el, y_el, x_h, y_h = calc_arm(is_far_arm=True)
        # Гладка лінія з двох сегментів (плече-лікоть, лікоть-кисть)
        col = (45, 45, 45) # трохи темніша рука
        _limb(draw, [(x_sh, y_sh), (x_el, y_el), (x_h, y_h)], col, SLEEVE_W)
        draw_fingers(draw, x_h, y_h, front_sw > 0, col)
    else:
        # У фронтальному вигляді ми просто малюємо обидві руки ПІСЛЯ куртки
        pass

    # ── Тіло (М'якший коміксний стиль) ──
    # Polina (char_id == 1) має рожеву сукню-трапецію
    # Хлопці (char_id == 0, 2) мають акуратні заокруглені куртки
    
    body_w = jacket_w if is_profile else hip_w
    b_cx = cx - (int(8*S) if facing_right else -int(8*S)) if is_profile else cx
    
    if char_id == 1:
        # А-силует для Поліни
        top_w = int(body_w * 0.7)
        bot_w = int(body_w * 1.3)
        draw.polygon([
            (b_cx - top_w, NECK_Y), (b_cx + top_w, NECK_Y),
            (b_cx + bot_w, HIP_Y + 10), (b_cx - bot_w, HIP_Y + 10)
        ], fill=jcol, outline=STICK_LINE, width=LW)
    else:
        # Нормальне заокруглене тіло для хлопців
        draw.rounded_rectangle([b_cx-body_w, NECK_Y, b_cx+body_w, HIP_Y+8],
                                radius=int(18*S), fill=jcol, outline=STICK_LINE, width=LW)
        # Біла смуга футболки посередині
        if is_profile:
            sw = int(10*S)
            sx = b_cx + (int(2*S) if facing_right else -int(10*S) - int(2*S))
            draw.rectangle([sx, NECK_Y, sx+sw, HIP_Y+6], fill=WHITE, outline=STICK_LINE, width=max(2, int(LW*0.6)))
        else:
            sw = int(14*S)
            draw.rectangle([cx-sw, NECK_Y, cx+sw, HIP_Y+6], fill=WHITE, outline=STICK_LINE, width=max(2, int(LW*0.6)))

    # ── Передня рука (Ближня) малюється ПІСЛЯ куртки ──
    if is_profile:
        x_sh, y_sh, x_el, y_el, x_h, y_h = calc_arm(is_far_arm=False)
        # Передня рука (колір STICK_LINE)
        _limb(draw, [(x_sh, y_sh), (x_el, y_el), (x_h, y_h)], STICK_LINE, SLEEVE_W)
        draw_fingers(draw, x_h, y_h, front_sw > 0, STICK_LINE)
    else:
        # Фронтально — дві руки
        for side in (-1, 1):
            x_sh, y_sh, x_el, y_el, x_h, y_h = calc_arm(is_far_arm=False, side_frontal=side)
            _limb(draw, [(x_sh, y_sh), (x_el, y_el), (x_h, y_h)], STICK_LINE, SLEEVE_W)
            draw_fingers(draw, x_h, y_h, side > 0, STICK_LINE)

    # ── Ноги — ПРАВИЛЬНИЙ walk cycle (4 ключові пози) ──
    if walking:
        #
        # Contact (t=0.0): права нога СПЕРЕДУ (+stride), ліва ЗЗАДУ (-stride), обидві на землі
        # Down    (t=0.125): вага переходить на передню ногу, тіло ОПУСКАЄТЬСЯ
        # Passing (t=0.25):  ліва нога проходить через центр (найвища точка тіла)
        # Up      (t=0.375): ліва нога летить вперед, тіло ПІДНІМАЄТЬСЯ
        # (потім зеркально для лівої ноги)
        #
        # Ground phase (t 0→0.5): нога СТОЇТЬ на землі і ковзає назад
        # Swing  phase (t 0.5→1): нога ЛЕТИТЬ параболічною дугою вперед
        #

        stride  = int(65 * S)   # половина довжини кроку (px)
        lift_h  = int(28 * S)   # максимальна висота підйому стопи (px)
        bob_amp = int(8  * S)   # амплітуда вертикального гойдання тіла (px)

        wd = 1 if facing_right else -1  # напрямок: +1=вправо, -1=вліво

        if is_profile:
            # Body bob: тіло ВГОРІ на Passing (t=0.25,0.75), ВНИЗУ на Contact (t=0, 0.5)
            # Два підйоми за повний цикл (один на крок)
            body_rise = abs(math.sin(walk_phase * math.pi * 2))
            hip_y = HIP_Y + 6 + int((1.0 - body_rise) * bob_amp)
            hip_x = cx

            legs = []
            for leg_offset in (0.0, 0.5):   # нога 0=права, нога 1=ліва
                t = (walk_phase + leg_offset) % 1.0

                if t < 0.5:
                    # GROUND PHASE: стопа НА ЗЕМЛІ, рухається ззаду наперед
                    # t=0 → стопа СПЕРЕДУ (cx+stride), t=0.5 → стопа ЗЗАДУ (cx-stride)
                    gf    = t / 0.5          # 0→1
                    foot_x = int(cx + wd * stride * (1.0 - 2.0 * gf))
                    foot_y = GROUND_Y
                else:
                    # SWING PHASE: стопа ЛЕТИТЬ параболічною дугою
                    # t=0.5 → стопа ЗЗАДУ (cx-stride), t=1.0 → стопа СПЕРЕДУ (cx+stride)
                    sf    = (t - 0.5) / 0.5  # 0→1
                    foot_x = int(cx + wd * stride * (2.0 * sf - 1.0))
                    # Парабола: пік на sf=0.5 (середина маху)
                    foot_y = GROUND_Y - int(math.sin(sf * math.pi) * lift_h)

                # Коліно: завжди гнеться ВПЕРЕД по напрямку ходьби
                mid_x   = (hip_x + foot_x) / 2.0
                mid_y   = (hip_y  + foot_y) / 2.0
                dx      = foot_x - hip_x
                dy      = foot_y - hip_y
                seg_half = math.hypot(dx, dy) / 2.0
                thigh   = int(88 * S)
                push_sq = max(0.0, thigh * thigh - seg_half * seg_half)
                push    = math.sqrt(push_sq) if push_sq > 0 else int(16 * S)
                fwd_push = min(push, int(28 * S))
                knee_x  = int(mid_x + wd * fwd_push)
                knee_y  = int(mid_y + int(5 * S))

                legs.append({'knee': (knee_x, knee_y), 'foot': (foot_x, foot_y)})

            # legs[0]=права нога (offset=0), legs[1]=ліва (offset=0.5)
            rknee, rfoot = legs[0]['knee'], legs[0]['foot']
            lknee, lfoot = legs[1]['knee'], legs[1]['foot']

        else:
            # Фронтально — та сама логіка але ноги в сторони (±48*S від центру)
            legs_f = []
            for leg_offset in (0.0, 0.5):
                t = (walk_phase + leg_offset) % 1.0
                if t < 0.5:
                    gf = t / 0.5
                    sw_x = int(stride * (1.0 if facing_right else -1.0) * (1.0 - 2.0 * gf))
                    sw_y = 0
                else:
                    sf = (t - 0.5) / 0.5
                    sw_x = int(stride * (1.0 if facing_right else -1.0) * (2.0 * sf - 1.0))
                    sw_y = int(math.sin(sf * math.pi) * lift_h)
                legs_f.append((sw_x, sw_y))
            rknee = (cx+int(48*S)+legs_f[0][0]//2, HIP_Y+int(85*S)-legs_f[0][1]//2)
            rfoot = (cx+int(48*S)+legs_f[0][0],    GROUND_Y-legs_f[0][1])
            lknee = (cx-int(48*S)+legs_f[1][0]//2, HIP_Y+int(85*S)-legs_f[1][1]//2)
            lfoot = (cx-int(48*S)+legs_f[1][0],    GROUND_Y-legs_f[1][1])
    else:
        if is_profile:
            # Профіль стоячи — ТІЛЬКИ ОДНА нога (передня) з ЦЕНТРУ
            if facing_right:
                rknee  = (cx, HIP_Y+int(85*S))
                rfoot  = (cx, GROUND_Y)
                lknee = None  # задня нога не малюється
                lfoot = None
            else:
                lknee  = (cx, HIP_Y+int(85*S))
                lfoot  = (cx, GROUND_Y)
                rknee = None  # задня нога не малюється
                rfoot = None
        else:
            # Фронтально — ноги на ширині плечей
            lknee = (cx-int(48*S), HIP_Y+int(85*S))
            lfoot = (cx-int(48*S), GROUND_Y)
            rknee = (cx+int(48*S), HIP_Y+int(85*S))
            rfoot = (cx+int(48*S), GROUND_Y)

    # ── Малювання ніг — спочатку задня, потім передня ──
    shoe  = int(50*S)    # = 36 (збільшено розмір черевика)
    r_sh  = max(3, int(4*S))
    
    if is_profile and walking:
        # Для профілю визначаємо яка нога попереду по X координаті стопи
        # Персонаж йде в напрямку facing_right — попереду та нога що далі в тому напрямку
        if facing_right:
            front_leg = 'right' if rfoot[0] > lfoot[0] else 'left'
        else:
            front_leg = 'left' if lfoot[0] < rfoot[0] else 'right'

        # Задня нога — трохи темніша (в тіні)
        back_col = (35, 35, 35)  # темніший за STICK_LINE
        front_col = STICK_LINE

        # Малюємо спочатку задню ногу, потім передню
        if front_leg == 'right':
            # Ліва нога позаду — малюємо першою
            lhip_pt = (cx, HIP_Y + 6)
            draw_thick_leg(draw, lhip_pt, lknee, lfoot, back_col, LEG_W)
            draw_foot(draw, lknee, lfoot, back_col, shoe, facing_right)
            # Права нога попереду — малюємо другою
            rhip_pt = (cx, HIP_Y + 6)
            draw_thick_leg(draw, rhip_pt, rknee, rfoot, front_col, LEG_W)
            draw_foot(draw, rknee, rfoot, front_col, shoe, facing_right)
        else:
            # Права нога позаду — малюємо першою
            rhip_pt = (cx, HIP_Y + 6)
            draw_thick_leg(draw, rhip_pt, rknee, rfoot, back_col, LEG_W)
            draw_foot(draw, rknee, rfoot, back_col, shoe, facing_right)
            # Ліва нога попереду — малюємо другою
            lhip_pt = (cx, HIP_Y + 6)
            draw_thick_leg(draw, lhip_pt, lknee, lfoot, front_col, LEG_W)
            draw_foot(draw, lknee, lfoot, front_col, shoe, facing_right)
    else:
        # Фронтально або стоячи — малюємо обидві ноги
        if is_profile:
            # Профіль стоячи — тільки одна нога (передня)
            if facing_right:
                rhip_pt = (cx, HIP_Y + 6)
                draw_thick_leg(draw, rhip_pt, rknee, rfoot, STICK_LINE, LEG_W)
                draw_foot(draw, rknee, rfoot, STICK_LINE, shoe, facing_right)
            else:
                lhip_pt = (cx, HIP_Y + 6)
                draw_thick_leg(draw, lhip_pt, lknee, lfoot, STICK_LINE, LEG_W)
                draw_foot(draw, lknee, lfoot, STICK_LINE, shoe, facing_right)
        else:
            # Фронтально — ноги на ширині плечей
            lhip = (cx-hip_w//2, HIP_Y+6)
            rhip = (cx+hip_w//2, HIP_Y+6)
            draw_thick_leg(draw, lhip, lknee, lfoot, STICK_LINE, LEG_W)
            draw_thick_leg(draw, rhip, rknee, rfoot, STICK_LINE, LEG_W)
            draw_foot(draw, lknee, lfoot, STICK_LINE, shoe, True)
            draw_foot(draw, rknee, rfoot, STICK_LINE, shoe, True)

    # ── Голова і Базове волосся ──
    draw._current_is_profile = is_profile
    
    if is_profile:
        # Профіль — голова більш кругла
        head_w = int(HEAD_RX * 0.9)  # майже коло
        head_h = HEAD_RY
        head_cx = cx + fs//2
        draw.ellipse([head_cx-head_w, HEAD_CY-head_h, head_cx+head_w, HEAD_CY+head_h],
                     fill=WHITE, outline=STICK_LINE, width=LW)
    else:
        # Фронтально — широкий овал
        draw.ellipse([cx-HEAD_RX, HEAD_CY-HEAD_RY, cx+HEAD_RX, HEAD_CY+HEAD_RY],
                     fill=WHITE, outline=STICK_LINE, width=LW)

    # База волосся (Поліна) малюється ДО очей, щоб очі накладались зверху
    if hair == 'ponytail':
        draw_ponytail(draw, cx, facing_right, draw_base=True)

    # ── Обличчя ──
    draw_face(draw, fi, cx, facing_right, emotion, talking, facing_camera=facing_camera)

# ─── Субтитри знизу (South Park стиль) ────────────────────────────────────────

def wrap_subtitle(text, max_chars=42):
    """Розбиває текст на рядки для субтитрів (макс 2 рядки)."""
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
    return lines[:2]

def draw_subtitle(draw, text, font):
    """Малює субтитри: чорна смуга + білий текст знизу кадру."""
    lines = wrap_subtitle(text) or ['...']
    line_h = 24
    pad_y = 4
    pad_x = 20

    # Обчислюємо ширину смуги — 100% кадру (від краю до краю)
    max_line = max(len(line) for line in lines)
    strip_w = W  # весь кадр
    strip_x = 0

    # Чорна смуга
    strip_h = len(lines) * line_h + pad_y * 2
    strip_y = H - strip_h
    draw.rectangle([strip_x, strip_y, strip_x + strip_w, strip_y + strip_h], fill=(0, 0, 0))
    
    # Текст
    ty = strip_y + pad_y
    for line in lines:
        draw.text((W // 2, ty), line, font=font, fill=WHITE, anchor='mt')
        ty += line_h

# ─── Рендер сцени ─────────────────────────────────────────────────────────────

def render_scene(scene_def, scene_idx, initial_chars, work_dir):
    bg_key  = scene_def.get('background', 'вулиця').lower()
    draw_bg = BG.get(bg_key, bg_street)

    entering_list = scene_def.get('enter', [])
    entering_dict = {e['char']: e.get('from', e.get('side', 'left')) for e in entering_list}
    exiting_set   = {e['char'] for e in scene_def.get('exit', [])}

    present        = set(initial_chars.keys()) | set(entering_dict.keys())
    sorted_present = sorted(present)
    slots          = slot_positions(len(sorted_present))
    char_targets   = {cid: slots[i] for i,cid in enumerate(sorted_present)}

    # Персонажі ходять з краю екрану (не pop-in)
    char_starts   = {}
    arrival_times = {}
    
    for cid in entering_dict:
        # Нові персонажі — ходять з краю екрану
        side = entering_dict[cid]  # 'left' або 'right'
        char_starts[cid] = -100 if side == 'left' else W + 100  # з-за меж екрану
        dist = abs(char_targets[cid] - char_starts[cid])
        arrival_times[cid] = dist / WALK_SPEED  # час ходьби
    for cid in initial_chars:
        start_x = initial_chars[cid]
        char_starts[cid]   = start_x
        dist = abs(char_targets[cid] - start_x)
        # Якщо треба перейти — ходьба (не більше 1.5с)
        arrival_times[cid] = min(dist / WALK_SPEED, 1.5) if dist > 10 else 0.0

    enter_end = max(arrival_times.values()) if arrival_times else 0.0

    # Аудіо (beat = тиша без TTS)
    dialogs     = scene_def.get('dialogs', [])
    audio_paths = []
    audio_durs  = []
    for i, dlg in enumerate(dialogs):
        if 'beat' in dlg:
            audio_paths.append(None)
            audio_durs.append(float(dlg['beat']))
        elif 'text' in dlg:
            cid   = dlg['char']
            voice = CHAR_CFG[cid % len(CHAR_CFG)]['voice']
            path  = os.path.join(work_dir, f'd_{scene_idx}_{i}.mp3')
            asyncio.run(gen_audio(dlg['text'], voice, path))
            audio_paths.append(path)
            audio_durs.append(get_duration(path))
        else:
            # Діалог без text і без beat — пропускаємо
            audio_paths.append(None)
            audio_durs.append(0.5)

    dialog_times = []
    t = enter_end + 0.3
    for dur in audio_durs:
        dialog_times.append((t, t+dur))
        t += dur + 0.25

    dialogs_end = dialog_times[-1][1] if dialog_times else (enter_end+0.3)
    exit_start  = dialogs_end + 0.2
    # South Park: персонажі зникають миттєво (pop-out)
    exit_data = {cid: (char_targets.get(cid, W//2), char_targets.get(cid, W//2), 0.0)
                 for cid in exiting_set}
    exit_end  = exit_start  # миттєво — не додає часу
    total_dur    = exit_end + 0.4
    total_frames = int(total_dur * FPS)
    font         = load_font(28)

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

            # ── Визначаємо активний діалог / beat ──
            talking_char  = -1
            bubble_text   = ''
            bubble_emot   = 'normal'
            beat_emotions = {}   # char_id -> emotion під час beat
            current_dlg   = None

            for di, dlg in enumerate(dialogs):
                dt_s, dt_e = dialog_times[di]
                if dt_s <= t_cur <= dt_e:
                    if 'beat' in dlg:
                        # Beat: тиша з емоцією, без бульки
                        bc = dlg.get('emotion_char', -1)
                        if bc >= 0:
                            beat_emotions[bc] = dlg.get('emotion', 'normal')
                    else:
                        talking_char = dlg['char']
                        bubble_text  = dlg.get('text', '')
                        bubble_emot  = dlg.get('emotion', 'normal')
                        current_dlg  = dlg
                    break

            img  = Image.new('RGB', (W, H))
            draw = ImageDraw.Draw(img)
            draw_bg(draw, fi)

            for char_id in sorted(present, key=lambda c: char_targets.get(c, W//2)):
                target_x = char_targets[char_id]
                start_x  = char_starts[char_id]
                arr_t    = arrival_times.get(char_id, 0.0)

                gesture       = None
                facing_camera = False

                if char_id in exiting_set and t_cur >= exit_start:
                    # Pop-out: просто не малюємо персонажа
                    continue
                elif arr_t > 0 and t_cur < arr_t:
                    prog         = t_cur/arr_t
                    cx_f         = start_x+(target_x-start_x)*prog
                    walking      = True
                    facing_right = target_x > start_x
                    emo          = 'normal'
                else:
                    cx_f    = float(target_x)
                    walking = False
                    if talking_char>=0 and talking_char!=char_id and talking_char in char_targets:
                        facing_right = char_targets[talking_char] > target_x
                    elif char_id in entering_dict:
                        facing_right = entering_dict[char_id] == 'left'
                    else:
                        facing_right = target_x <= W//2

                    # Beat emotion або звичайна
                    if char_id in beat_emotions:
                        emo = beat_emotions[char_id]
                    elif char_id == talking_char:
                        emo = bubble_emot
                        # Gesture і facing camera тільки для говорячого
                        if current_dlg:
                            gesture       = current_dlg.get('gesture')
                            facing_camera = current_dlg.get('facing') == 'camera'
                    else:
                        emo = 'normal'

                if cx_f < -HEAD_RX*2 or cx_f > W+HEAD_RX*2:
                    continue

                is_talking = (char_id == talking_char)

                # Конвертуємо facing_right в direction (South Park стиль)
                if facing_camera:
                    direction = 0  # фронтально в камеру
                elif walking:
                    # При ходьбі — профіль (боком)
                    direction = 1 if facing_right else 2
                else:
                    # Стоїть — ВСІ персонажі лицем до камери (фронтально)
                    direction = 0
                    facing_camera = True  # два ока симетрично
                
                draw_char(draw, fi, int(cx_f), char_id,
                          walking=walking, direction=direction,
                          talking=is_talking, emotion=emo,
                          gesture=gesture, facing_camera=facing_camera)
                # Субтитри малюємо тільки один раз для активного діалогу
                if is_talking and bubble_text and current_dlg and current_dlg.get('char') == char_id:
                    draw_subtitle(draw, bubble_text, font)

            proc.stdin.write(img.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()

    # Close-up zoom через FFmpeg (crop центр 1.5x замість 2x)
    shot = scene_def.get('shot', 'normal')
    if shot == 'close_up':
        zoomed = os.path.join(work_dir, f'zoom_{scene_idx}.mp4')
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error',
            '-i', silent,
            '-vf', f'crop={int(W*0.67)}:{int(H*0.67)}:{int(W*0.165)}:{int(H*0.165)},scale={W}:{H}',
            '-c:v', 'libx264', '-preset', 'ultrafast',
            '-crf', '26', '-pix_fmt', 'yuv420p', '-threads', '1', zoomed
        ], check=True)
        os.unlink(silent)
        silent = zoomed

    # Мікс аудіо (beat = None, пропускаємо)
    real_audio = [(i, p) for i, p in enumerate(audio_paths) if p is not None]
    scene_out  = os.path.join(work_dir, f'scene_{scene_idx}.mp4')
    if real_audio:
        inputs_cmd   = []
        filter_parts = []
        for j, (i, path) in enumerate(real_audio):
            delay_ms = int(dialog_times[i][0]*1000)
            inputs_cmd += ['-i', path]
            filter_parts.append(f'[{j}:a]adelay={delay_ms}|{delay_ms}[a{j}]')
        mix_str = ''.join(f'[a{j}]' for j in range(len(real_audio)))
        fc = ';'.join(filter_parts) + f';{mix_str}amix=inputs={len(real_audio)}:dropout_transition=0[out]'
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

# ─── Чорний кадр між сценами (cut) ───────────────────────────────────────────

def make_black_clip(work_dir, idx, frames=8):
    """Короткий чорний кліп між сценами — South Park різкий cut."""
    path = os.path.join(work_dir, f'black_{idx}.mp4')
    dur  = frames / FPS
    subprocess.run([
        'ffmpeg', '-y', '-loglevel', 'error',
        '-f', 'lavfi', '-i', f'color=c=black:size={W}x{H}:rate={FPS}',
        '-f', 'lavfi', '-i', 'aevalsrc=0:sample_rate=44100:channel_layout=stereo',
        '-t', str(dur),
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '26', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', path
    ], check=True)
    return path

# ─── Головна ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',  required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    print('🎬 Cartoon v2026-03-26-profile-fix2', flush=True)

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
        # Cut-перехід між сценами (не після останньої)
        if idx < len(scenes) - 1:
            clips.append(make_black_clip(work_dir, idx))
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
    
    # 📸 Автоскріншоти для тестування (8 кадрів рівномірно)
    print('📸 Роблю скріншоти...', flush=True)
    screenshots_dir = os.path.join(work_dir, 'screenshots')
    os.makedirs(screenshots_dir, exist_ok=True)
    
    # Отримуємо тривалість відео
    dur_result = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', args.output],
        capture_output=True, text=True, check=True)
    dur_data = json.loads(dur_result.stdout)
    duration = float(dur_data['streams'][0].get('duration', 10))
    
    # Робимо 8 скріншотів рівномірно
    n_frames = 8
    for i in range(n_frames):
        t = (i + 0.5) * duration / n_frames  # центр кожного сегменту
        out_path = os.path.join(screenshots_dir, f'frame_{i+1:02d}.png')
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error',
            '-ss', str(t), '-i', args.output,
            '-vframes', '1', '-q:v', '2',
            out_path
        ], check=True)
    
    print(f'✅ Готово: {args.output}', flush=True)
    print(f'📸 Скріншоти: {screenshots_dir}/frame_*.png ({n_frames} кадрів)', flush=True)

if __name__ == '__main__':
    main()
