#!/usr/bin/env python3
"""
Тест ходьби — рендерить всі 8 фаз walk cycle для обох напрямків.
Зберігає PNG файли в test_walk_frames/
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from PIL import Image, ImageDraw
from cartoon import draw_char, W, H, GROUND_Y, FPS

OUT_DIR = os.path.join(os.path.dirname(__file__), 'test_walk_frames')
os.makedirs(OUT_DIR, exist_ok=True)

def make_frame(fi, direction, char_id=0):
    img  = Image.new('RGB', (W, H), (200, 220, 240))
    draw = ImageDraw.Draw(img)
    # Фон
    draw.rectangle([(0, GROUND_Y), (W, H)], fill=(80, 160, 80))
    draw.line([(0, GROUND_Y), (W, GROUND_Y)], fill=(40, 120, 40), width=3)
    # Сітка
    for x in range(0, W, 100):
        draw.line([(x, 0), (x, H)], fill=(180, 200, 220), width=1)
    for y in range(0, H, 100):
        draw.line([(0, y), (W, y)], fill=(180, 200, 220), width=1)
    # Персонаж (центр екрану)
    draw_char(draw, fi, W//2, char_id, walking=True, direction=direction,
              talking=False, emotion='normal')
    # Мітка
    dir_name = 'RIGHT' if direction == 1 else 'LEFT'
    cycle = (fi // 4) % 8
    draw.text((20, 20), f'dir={dir_name}  fi={fi}  cycle={cycle}', fill=(0,0,0))
    return img

# Рендеримо всі 8 фаз для RIGHT (direction=1)
print("Рендеримо RIGHT...")
for cycle in range(8):
    fi = cycle * 4  # fi такий, щоб (fi//4)%8 == cycle
    img = make_frame(fi, direction=1)
    path = os.path.join(OUT_DIR, f'right_cycle{cycle:02d}_fi{fi:03d}.png')
    img.save(path)
    print(f"  {path}")

# Рендеримо всі 8 фаз для LEFT (direction=2)
print("Рендеримо LEFT...")
for cycle in range(8):
    fi = cycle * 4
    img = make_frame(fi, direction=2)
    path = os.path.join(OUT_DIR, f'left_cycle{cycle:02d}_fi{fi:03d}.png')
    img.save(path)
    print(f"  {path}")

print(f"\n✅ Збережено {16} кадрів у: {OUT_DIR}")
print("Перевір колін: чи вони завжди гнуться ВПЕРЕД у напрямку ходьби.")
