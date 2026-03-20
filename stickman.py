#!/usr/bin/env python3
"""
Stickman video generator for MoltBot
Usage: python3 stickman.py --input /tmp/input.json --output /tmp/output.mp4
Input JSON: {"text": "Ukrainian text here"}
"""

import sys
import json
import math
import subprocess
import argparse
import asyncio
import os

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

# ─── Налаштування кадру ───────────────────────────────────────────────────────

W, H   = 480, 854
FPS    = 25
VOICE  = "uk-UA-OstapNeural"

# Кольори
BG_SKY    = (15, 25, 50)
BG_GROUND = (30, 50, 30)
STICK_COL = (255, 220, 100)
WHITE     = (255, 255, 255)
BLACK     = (0, 0, 0)

# Позиції стікмена
CX         = W // 2
GROUND_Y   = H - 110
HEAD_R     = 40
HEAD_CY    = GROUND_Y - 290
NECK_Y     = HEAD_CY + HEAD_R + 4
BODY_LEN   = 125
HIP_Y      = NECK_Y + BODY_LEN
SHOULDER_Y = NECK_Y + 18
ARM_LEN    = 78
LW         = 5   # товщина ліній

# ─── Малювання ────────────────────────────────────────────────────────────────

def draw_background(draw):
    draw.rectangle([(0, 0),        (W, GROUND_Y)], fill=BG_SKY)
    draw.rectangle([(0, GROUND_Y), (W, H)],        fill=BG_GROUND)
    draw.line([(0, GROUND_Y), (W, GROUND_Y)], fill=(60, 100, 60), width=3)


def draw_stickman(draw, frame_idx, talking=True):
    sway = int(math.sin(frame_idx * 0.04) * 2)
    cx = CX + sway

    # Тіло
    draw.line([(cx, NECK_Y), (cx, HIP_Y)], fill=STICK_COL, width=LW)

    # Руки — хитаються
    swing = math.sin(frame_idx * 0.12) * 18
    draw.line([(cx, SHOULDER_Y), (cx - ARM_LEN, SHOULDER_Y + 55 + int(swing))],  fill=STICK_COL, width=LW)
    draw.line([(cx, SHOULDER_Y), (cx + ARM_LEN, SHOULDER_Y + 55 - int(swing))],  fill=STICK_COL, width=LW)

    # Ноги
    draw.line([(cx, HIP_Y), (cx - 48, GROUND_Y)], fill=STICK_COL, width=LW)
    draw.line([(cx, HIP_Y), (cx + 48, GROUND_Y)], fill=STICK_COL, width=LW)

    # Голова
    draw.ellipse(
        [cx - HEAD_R, HEAD_CY - HEAD_R, cx + HEAD_R, HEAD_CY + HEAD_R],
        outline=STICK_COL, width=LW
    )

    # Очі
    ey = HEAD_CY - 10
    draw.ellipse([cx - 17, ey - 6, cx - 5,  ey + 6], fill=STICK_COL)
    draw.ellipse([cx +  5, ey - 6, cx + 17, ey + 6], fill=STICK_COL)

    # Рот — відкритий/закритий (мова)
    my = HEAD_CY + 14
    if talking and (frame_idx // 4) % 2 == 0:
        draw.ellipse([cx - 13, my - 7, cx + 13, my + 9], fill=(180, 40, 40))
    else:
        draw.arc([cx - 13, my - 4, cx + 13, my + 10], 0, 180, fill=STICK_COL, width=3)


def draw_subtitle(draw, text, font):
    # Розбити текст на рядки (~22 символи)
    words = text.split()
    lines, line = [], ''
    for w in words:
        test = (line + ' ' + w).strip()
        if len(test) > 22:
            if line:
                lines.append(line.strip())
            line = w
        else:
            line = test
    if line:
        lines.append(line.strip())
    lines = lines[:3]

    start_y = H - 75 - len(lines) * 45
    for l in lines:
        bbox = draw.textbbox((CX, start_y), l, font=font, anchor='mt')
        pad = 10
        # Чорний фон під текстом
        draw.rectangle([bbox[0]-pad, bbox[1]-4, bbox[2]+pad, bbox[3]+4], fill=BLACK)
        # Тінь + текст
        draw.text((CX+2, start_y+2), l, font=font, fill=(60, 60, 60), anchor='mt')
        draw.text((CX,   start_y),   l, font=font, fill=WHITE,        anchor='mt')
        start_y += 45


# ─── Генерація аудіо ──────────────────────────────────────────────────────────

async def generate_audio(text, audio_path):
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(audio_path)


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


# ─── Генерація кадрів → FFmpeg ────────────────────────────────────────────────

def generate_silent_video(text, duration, silent_path):
    total_frames = int(duration * FPS)

    font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    try:
        font = ImageFont.truetype(font_path, 34)
    except Exception:
        font = ImageFont.load_default()

    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{W}x{H}',
        '-pix_fmt', 'rgb24',
        '-r', str(FPS),
        '-i', 'pipe:0',
        '-c:v', 'libx264', '-preset', 'ultrafast',
        '-crf', '28', '-pix_fmt', 'yuv420p',
        '-threads', '1',
        silent_path
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(total_frames):
            img  = Image.new('RGB', (W, H), BG_SKY)
            draw = ImageDraw.Draw(img)
            draw_background(draw)
            draw_stickman(draw, i, talking=True)
            draw_subtitle(draw, text, font)
            proc.stdin.write(img.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()


# ─── Головна функція ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',  required=True, help='JSON file with {"text": "..."}')
    parser.add_argument('--output', required=True, help='Output MP4 path')
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)
    text = data['text']

    work_dir    = os.path.dirname(os.path.abspath(args.output))
    audio_path  = os.path.join(work_dir, 'audio.mp3')
    silent_path = os.path.join(work_dir, 'silent.mp4')

    print(f'🎙 Озвучка: "{text[:60]}..."', flush=True)
    asyncio.run(generate_audio(text, audio_path))

    duration = get_audio_duration(audio_path) + 0.8
    print(f'⏱ Тривалість: {duration:.1f}с ({int(duration * FPS)} кадрів)', flush=True)

    print('🎨 Малюю стікмена...', flush=True)
    generate_silent_video(text, duration, silent_path)

    print('🎞 Склеюю відео + аудіо...', flush=True)
    subprocess.run([
        'ffmpeg', '-y', '-loglevel', 'error',
        '-i', silent_path,
        '-i', audio_path,
        '-c:v', 'copy', '-c:a', 'aac',
        '-shortest',
        args.output
    ], check=True)

    print(f'✅ Готово: {args.output}', flush=True)


if __name__ == '__main__':
    main()
