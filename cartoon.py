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
#   Персонажі ~30% висоти кадру — пропорційні фону
#
W, H       = 1280, 720
FPS        = 25
S          = 0.48          # масштаб персонажів
WALK_SPEED = 220           # px/s (ширший кадр — швидше)

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
#   Персонаж зростом ~220px з 720 = 30.5% кадру (як South Park)
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
LEG_W    = max(7,  int(18 * S))   # = 8
LW       = max(4,  int(9  * S))   # = 4

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
    r = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', path],
        capture_output=True, text=True)
    for s in json.loads(r.stdout).get('streams', []):
        if 'duration' in s:
            return float(s['duration'])
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

    # 4. Будівлі South Park стиль (7 штук, теплі кольори)
    # (bx, bw, bh, color, style)
    buildings = [
        (   0, 192, 295, (192, 162, 128), 'peaked'),   # беж
        ( 186, 170, 225, (168,  68,  62), 'peaked'),   # червоний
        ( 350, 192, 328, ( 68,  98, 142), 'flat'),     # синій
        ( 536, 215, 258, (128, 152,  96), 'peaked'),   # оливковий
        ( 745, 180, 290, (152, 118,  80), 'flat'),     # коричневий
        ( 918, 194, 265, (178,  98,  75), 'flat'),     # теракотовий
        (1105, 175, 245, (208, 198, 175), 'peaked'),   # кремовий
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

    # 8. Машини (великі, South Park пропорції)
    c1x = W + 200 - int(fi * 3.2) % (W + 400)
    c2x = int(fi * 2.5) % (W + 400) - 200
    c3x = W // 3 + 260 - int(fi * 1.8) % (W + 400)
    draw_car(draw, c1x, GROUND_Y + 52,  (198, 52, 52),  facing_right=False, cw=158, ch=54)
    draw_car(draw, c2x, GROUND_Y + 120, (52, 102, 202), facing_right=True,  cw=158, ch=54)
    draw_car(draw, c3x, GROUND_Y + 52,  (52, 175, 75),  facing_right=False, cw=148, ch=50)

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
    Чисте обличчя без тіні — Loading Artist стиль.
    Емоції: normal, talking, surprised, angry, sad
    facing_camera=True — симетричне обличчя прямо в камеру
    """
    if facing_camera:
        fs    = 0
        ey    = HEAD_CY - int(10*S)
        el_cx = cx - int(28*S)
        er_cx = cx + int(28*S)
        er_l  = int(25*S)
        pr_l  = int(14*S)
        er_r  = int(25*S)
        pr_r  = int(14*S)
    else:
        fs  = int(6*S) if facing_right else -int(6*S)
        ey  = HEAD_CY - int(10*S)

        # ── Розміри очей ──
        if facing_right:
            el_cx = cx - int(24*S) + fs
            er_cx = cx + int(38*S) + fs//2
        else:
            el_cx = cx - int(38*S) + fs//2
            er_cx = cx + int(24*S) + fs

        # Базові радіуси (без EYE_SCALE)
        er_l  = int(22*S)
        pr_l  = int(12*S)
        er_r  = int(28*S)
        pr_r  = int(16*S)

        # Зробити ліве/праве правильно при повороті
        if not facing_right:
            er_l, er_r = er_r, er_l
            pr_l, pr_r = pr_r, pr_l

    # Surprised — злегка більші очі
    if emotion == 'surprised':
        er_l = int(er_l * 1.2)
        er_r = int(er_r * 1.2)

    # Малюємо очі
    for ecx, er, pr in [(el_cx, er_l, pr_l), (er_cx, er_r, pr_r)]:
        draw.ellipse([ecx-er, ey-er, ecx+er, ey+er],
                     fill=WHITE, outline=STICK_LINE, width=3)
        draw.ellipse([ecx-pr//2+1, ey-pr//2, ecx+pr//2+1, ey+pr//2+1],
                     fill=STICK_LINE)
        # Відблиск
        draw.ellipse([ecx-6, ey-int(er*0.55), ecx, ey-int(er*0.18)], fill=WHITE)

    # ── Брови ──
    # Нейтральна позиція: трохи вище очей
    brow_y_norm = ey - max(er_l, er_r) - 7

    if facing_camera and emotion not in ('angry', 'sad', 'surprised'):
        # Рівні симетричні брови для "в камеру"
        by = brow_y_norm
        draw.line([(el_cx-er_l+2, by+3), (el_cx+er_l-2, by+3)], fill=STICK_LINE, width=5)
        draw.line([(er_cx-er_r+2, by+3), (er_cx+er_r-2, by+3)], fill=STICK_LINE, width=5)
    elif emotion == 'angry':
        # Злі: V-форма, притиснуті до очей
        by = ey - max(er_l, er_r) - 4
        draw.line([(el_cx-er_l+2, by+2), (el_cx+er_l-2, by+10)],
                  fill=STICK_LINE, width=6)
        draw.line([(er_cx-er_r+2, by+10), (er_cx+er_r-2, by+2)],
                  fill=STICK_LINE, width=6)

    elif emotion == 'sad':
        # Сумні: зовнішні кути опускаються
        by = brow_y_norm
        draw.line([(el_cx-er_l+2, by+10), (el_cx+er_l-2, by+2)],
                  fill=STICK_LINE, width=6)
        draw.line([(er_cx-er_r+2, by+2), (er_cx+er_r-2, by+10)],
                  fill=STICK_LINE, width=6)

    elif emotion == 'surprised':
        # Здивовані: РІЗКО вгору, великий відступ від очей
        by = ey - max(er_l, er_r) - 20  # <-- летять вгору!
        draw.arc([el_cx-er_l+2, by-8, el_cx+er_l-2, by+10],
                 195, 345, fill=STICK_LINE, width=6)
        draw.arc([er_cx-er_r+2, by-8, er_cx+er_r-2, by+10],
                 195, 345, fill=STICK_LINE, width=6)

    else:  # normal / talking
        by = brow_y_norm
        draw.line([(el_cx-er_l+2, by+5), (el_cx+er_l-2, by)],
                  fill=STICK_LINE, width=5)
        draw.line([(er_cx-er_r+2, by), (er_cx+er_r-2, by+5)],
                  fill=STICK_LINE, width=5)

    # ── Ніс ──
    nx = cx + fs//2
    draw.ellipse([nx-3, HEAD_CY+int(12*S), nx+3, HEAD_CY+int(20*S)],
                 fill=(188,148,128))

    # ── Рот ──
    my = HEAD_CY + int(44*S)
    mx_off = fs//2

    if emotion == 'surprised':
        # О-рот
        draw.ellipse([cx-int(9*S)+mx_off, my-int(12*S),
                      cx+int(13*S)+mx_off, my+int(13*S)],
                     fill=(178,28,28), outline=STICK_LINE, width=2)

    elif emotion == 'angry':
        # Зціплені зуби
        mx1 = cx - int(20*S) + mx_off
        mx2 = cx + int(24*S) + mx_off
        my1, my2 = my-int(5*S), my+int(10*S)
        draw.rectangle([mx1, my1, mx2, my2], fill=(178,28,28))
        draw.line([(mx1, my1+5), (mx2, my1+5)], fill=WHITE, width=3)
        draw.rectangle([mx1, my1, mx2, my2], outline=STICK_LINE, width=3)

    elif emotion == 'sad':
        # Перевернута дуга — без сліз
        draw.arc([cx-int(20*S)+mx_off, my-int(4*S),
                  cx+int(28*S)+mx_off, my+int(18*S)],
                 180, 360, fill=STICK_LINE, width=5)

    elif emotion in ('talking', 'normal') and talking and (fi//4) % 2 == 0:
        # Анімований рот
        draw.ellipse([cx-int(24*S)+mx_off, my-int(14*S),
                      cx+int(28*S)+mx_off, my+int(18*S)], fill=(178,28,28))
        draw.rectangle([cx-int(16*S)+mx_off, my-int(12*S),
                        cx+int(20*S)+mx_off, my-2], fill=WHITE)

    else:
        # Звичайна усмішка
        draw.arc([cx-int(20*S)+mx_off, my-int(10*S),
                  cx+int(28*S)+mx_off, my+int(18*S)],
                 0, 180, fill=STICK_LINE, width=5)

# ─── Хвіст Поліни ─────────────────────────────────────────────────────────────

def draw_ponytail(draw, cx, facing_right):
    HAIR_COL  = (198, 88, 28)
    HAIR_DARK = (150, 55, 10)
    side      = -1 if facing_right else 1
    tx        = cx + side * (HEAD_RX - 5)
    ty        = HEAD_CY - HEAD_RY + int(14*S)
    thick     = int(15*S)
    n         = 14
    pts       = []
    for i in range(n+1):
        f  = i / n
        px = tx + side * int(f * 22*S)
        py = ty + int((f**0.75) * 140*S)
        pts.append((px, py))
    for i in range(len(pts)-1):
        w = max(4, int(thick * (1 - i/n*0.5)))
        _seg(draw, *pts[i], *pts[i+1], HAIR_COL, w)
    # Темна обводка
    for i in range(len(pts)-1):
        w = max(2, int(thick*(1-i/n*0.5))-5)
        if w > 1:
            _seg(draw, *pts[i], *pts[i+1], HAIR_DARK, w)
    gx, gy = pts[n//2]
    draw.ellipse([gx-6, gy-6, gx+6, gy+6], fill=(215,45,45))

# ─── Персонаж ─────────────────────────────────────────────────────────────────

def draw_char(draw, fi, cx, char_id, walking=False, facing_right=True, talking=False, emotion='normal', gesture=None, facing_camera=False):
    cfg   = CHAR_CFG[char_id % len(CHAR_CFG)]
    jcol  = cfg['jacket']
    tcol  = cfg['tie']
    hair  = cfg['hair']

    sway  = int(math.sin(fi*0.04)*2)
    cx    = cx + sway
    swing = math.sin(fi*0.12)*20
    fs    = int(6*S) if facing_right else -int(6*S)
    hip_w = SHIRT_W + int(14*S)
    arm_y = NECK_Y  + int(28*S)

    # Хвіст (перед головою — голова перекриє)
    if hair == 'ponytail':
        draw_ponytail(draw, cx, facing_right)

    # ── Руки ──
    front_sw = 1 if facing_right else -1  # сторона "вперед" відносно напрямку
    for side in (-1, 1):
        sw   = side if facing_right else -side
        x_sh = cx + SHIRT_W * sw

        if emotion == 'surprised':
            # Обидві руки вгору — здивування
            x_el = int(cx + SHIRT_W*sw + ARM_LEN*sw*0.2)
            x_h  = int(cx + SHIRT_W*sw*0.3)
            y_el = int(arm_y - ARM_LEN*0.25)
            y_h  = int(arm_y - ARM_LEN*0.85)
        elif emotion == 'angry':
            # Руки розкидані в сторони — злість
            x_el = int(cx + SHIRT_W*sw + ARM_LEN*sw*0.65)
            x_h  = int(cx + SHIRT_W*sw + ARM_LEN*sw*1.1)
            y_el = int(arm_y + ARM_LEN*0.15)
            y_h  = int(arm_y - ARM_LEN*0.15)
        elif gesture == 'explain' and sw == front_sw:
            # Передня рука вгору — жест пояснення/аргумент
            x_el = int(cx + SHIRT_W*sw + ARM_LEN*sw*0.25)
            x_h  = int(cx + SHIRT_W*sw*0.6)
            y_el = int(arm_y - ARM_LEN*0.15)
            y_h  = int(arm_y - ARM_LEN*0.80)
        else:
            # Звичайне положення — руки звисають + гойдання
            x_el = int(cx + SHIRT_W*sw + ARM_LEN*sw*0.45) + 4*sw
            x_h  = int(cx + SHIRT_W*sw + ARM_LEN*sw)
            y_el = int(arm_y + ARM_LEN*0.35 + swing*0.5*sw)
            y_h  = int(arm_y + 58 + swing*sw)

        _limb(draw, [(x_sh,arm_y),(x_el,y_el),(x_h,y_h)], STICK_LINE, SLEEVE_W)

    # ── Куртка ──
    v_d  = NECK_Y + int(70*S)
    lw_s = int(34*S)
    draw.rounded_rectangle([cx-hip_w, NECK_Y+4, cx+hip_w, HIP_Y+8],
                            radius=int(18*S), fill=jcol, outline=STICK_LINE, width=3)
    draw.polygon([(cx-int(18*S),NECK_Y+4),(cx+int(18*S),NECK_Y+4),(cx+fs//2,v_d)], fill=WHITE)
    draw.polygon([(cx-int(18*S),NECK_Y+4),(cx-lw_s,NECK_Y+int(26*S)),
                  (cx-int(16*S),v_d-7),(cx+fs//2,v_d)],
                 fill=jcol, outline=STICK_LINE, width=2)
    draw.polygon([(cx+int(18*S),NECK_Y+4),(cx+lw_s,NECK_Y+int(26*S)),
                  (cx+int(16*S),v_d-7),(cx+fs//2,v_d)],
                 fill=jcol, outline=STICK_LINE, width=2)
    draw.line([(cx-int(18*S),NECK_Y+4),(cx+fs//2,v_d)], fill=STICK_LINE, width=2)
    draw.line([(cx+int(18*S),NECK_Y+4),(cx+fs//2,v_d)], fill=STICK_LINE, width=2)
    tx_t = cx + fs//3
    draw.polygon([
        (tx_t-4,v_d-2),(tx_t+4,v_d-2),
        (tx_t+6,v_d+int(36*S)),(tx_t,v_d+int(52*S)),(tx_t-6,v_d+int(36*S))
    ], fill=tcol, outline=STICK_LINE, width=2)

    # ── Ноги ──
    if walking:
        phase  = fi * 0.22
        dir_m  = 1 if facing_right else -1
        stride = int(40*S)
        lift   = int(16*S)
        l_sw   = math.sin(phase) * stride * dir_m
        l_li   = max(0, math.sin(phase)) * lift
        r_sw   = math.sin(phase+math.pi) * stride * dir_m
        r_li   = max(0, math.sin(phase+math.pi)) * lift
        lknee  = (cx-int(48*S)+int(l_sw*0.5), HIP_Y+int(85*S)-int(l_li*0.5))
        lfoot  = (cx-int(48*S)+int(l_sw),      GROUND_Y-int(l_li))
        rknee  = (cx+int(48*S)+int(r_sw*0.5),  HIP_Y+int(85*S)-int(r_li*0.5))
        rfoot  = (cx+int(48*S)+int(r_sw),       GROUND_Y-int(r_li))
    else:
        lknee = (cx-int(48*S), HIP_Y+int(85*S))
        lfoot = (cx-int(48*S), GROUND_Y)
        rknee = (cx+int(48*S), HIP_Y+int(85*S))
        rfoot = (cx+int(48*S), GROUND_Y)

    lhip = (cx-hip_w//2, HIP_Y+6)
    rhip = (cx+hip_w//2, HIP_Y+6)
    _limb(draw, [lhip,lknee], STICK_LINE, LEG_W)
    _limb(draw, [lknee,lfoot], STICK_LINE, LEG_W)
    _limb(draw, [rhip,rknee], STICK_LINE, LEG_W)
    _limb(draw, [rknee,rfoot], STICK_LINE, LEG_W)
    shoe  = int(34*S)
    r_sh  = max(3, int(4*S))
    draw.rounded_rectangle([lfoot[0]-shoe, lfoot[1]-5, lfoot[0]+shoe//3, lfoot[1]+10],
                            radius=r_sh, fill=STICK_LINE)
    draw.rounded_rectangle([rfoot[0]-shoe//3, rfoot[1]-5, rfoot[0]+shoe, rfoot[1]+10],
                            radius=r_sh, fill=STICK_LINE)

    # ── Голова — чиста, без тіні ──
    draw.ellipse([cx-HEAD_RX, HEAD_CY-HEAD_RY, cx+HEAD_RX, HEAD_CY+HEAD_RY],
                 fill=WHITE, outline=STICK_LINE, width=LW)

    # ── Обличчя ──
    draw_face(draw, fi, cx, facing_right, emotion, talking, facing_camera=facing_camera)

# ─── Хмаринка діалогу ─────────────────────────────────────────────────────────

def wrap_text(text, max_chars=18):
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
    line_h = 38
    pad    = 14

    bub_w = min(340, W // max(n_slots, 1) + 100)
    bx1   = max(8, cx - bub_w//2)
    bx2   = min(W-8, bx1 + bub_w)
    if bx2-bx1 < 100: bx1 = max(8, bx2-100)
    by1   = 18
    by2   = by1 + len(lines)*line_h + pad*2

    draw.rounded_rectangle([bx1+4, by1+4, bx2+4, by2+4], radius=15, fill=(148,148,148))
    draw.rounded_rectangle([bx1, by1, bx2, by2], radius=15,
                            fill=BUBBLE_BG, outline=BUBBLE_BD, width=3)
    tail_y  = HEAD_CY - HEAD_RY - 5
    mid_bub = (bx1+bx2)//2
    draw.polygon([(mid_bub-10,by2),(mid_bub+10,by2),(cx,tail_y)], fill=BUBBLE_BG)
    draw.line([(mid_bub-10,by2),(cx,tail_y)], fill=BUBBLE_BD, width=2)
    draw.line([(mid_bub+10,by2),(cx,tail_y)], fill=BUBBLE_BD, width=2)
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
    entering_dict = {e['char']: e.get('from', e.get('side', 'left')) for e in entering_list}
    exiting_set   = {e['char'] for e in scene_def.get('exit', [])}

    present        = set(initial_chars.keys()) | set(entering_dict.keys())
    sorted_present = sorted(present)
    slots          = slot_positions(len(sorted_present))
    char_targets   = {cid: slots[i] for i,cid in enumerate(sorted_present)}

    # South Park стиль: персонажі з'являються миттєво (pop-in)
    # Ті що вже були — можуть перейти на нову позицію якщо слот змінився
    char_starts   = {}
    arrival_times = {}
    for cid in entering_dict:
        # Нові персонажі — pop-in одразу на слот
        char_starts[cid]   = char_targets[cid]
        arrival_times[cid] = 0.0
    for cid in initial_chars:
        start_x = initial_chars[cid]
        char_starts[cid]   = start_x
        dist = abs(char_targets[cid] - start_x)
        # Якщо треба перейти — коротка пробіжка (не більше 0.6с)
        arrival_times[cid] = min(dist / WALK_SPEED, 0.6) if dist > 10 else 0.0

    enter_end = max(arrival_times.values()) if arrival_times else 0.0

    # Аудіо (beat = тиша без TTS)
    dialogs     = scene_def.get('dialogs', [])
    audio_paths = []
    audio_durs  = []
    for i, dlg in enumerate(dialogs):
        if 'beat' in dlg:
            audio_paths.append(None)
            audio_durs.append(float(dlg['beat']))
        else:
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
                        bubble_text  = dlg['text']
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
                draw_char(draw, fi, int(cx_f), char_id,
                          walking=walking, facing_right=facing_right,
                          talking=is_talking, emotion=emo,
                          gesture=gesture, facing_camera=facing_camera)
                if is_talking and bubble_text:
                    slot_i = sorted_present.index(char_id)
                    draw_bubble(draw, bubble_text, font, int(cx_f), slot_i, len(sorted_present))

            proc.stdin.write(img.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()

    # Close-up zoom через FFmpeg (crop центр 2x)
    shot = scene_def.get('shot', 'normal')
    if shot == 'close_up':
        zoomed = os.path.join(work_dir, f'zoom_{scene_idx}.mp4')
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error',
            '-i', silent,
            '-vf', f'crop={W//2}:{H}:{W//4}:0,scale={W}:{H}',
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
    print(f'✅ Готово: {args.output}', flush=True)

if __name__ == '__main__':
    main()
