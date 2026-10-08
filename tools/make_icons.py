"""Рисует значки ярлыков (tools/icons/*.png и *.ico). Нужен Pillow; готовые файлы лежат в git, при сборке архива рисовать не нужно.

    python tools/make_icons.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / 'icons'
S = 1024  # рисуем крупно и уменьшаем: гладкие края
WHITE = (255, 255, 255, 255)
SOFT = (255, 255, 255, 140)


def background(top, bottom):
    """Скруглённый квадрат с вертикальным градиентом и мягким бликом сверху."""
    grad = Image.new('RGBA', (S, S))
    px = grad.load()
    for y in range(S):
        t = y / (S - 1)
        colour = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
        for x in range(S):
            px[x, y] = colour
    mask = Image.new('L', (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((24, 24, S - 24, S - 24), radius=220, fill=255)
    base = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    base.paste(grad, (0, 0), mask)
    gloss = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).ellipse((-200, -620, S + 200, 420), fill=(255, 255, 255, 38))
    base.alpha_composite(Image.composite(gloss, Image.new('RGBA', (S, S), (0, 0, 0, 0)), mask))
    return base


def database(d):
    """База ПХГ: стопка дисков."""
    for i, y in enumerate((250, 430, 610)):
        d.rounded_rectangle((220, y, 804, y + 150), radius=75, fill=WHITE if i == 0 else SOFT if i == 1 else WHITE)
        d.ellipse((290, y + 52, 346, y + 108), fill=(40, 90, 170, 255))
        d.rounded_rectangle((400, y + 60, 740, y + 90), radius=15, fill=(40, 90, 170, 200))
    d.rounded_rectangle((220, 790, 804, 840), radius=25, fill=SOFT)


def maps(d):
    """Карты ГСП: булавка на карте с секторной диаграммой."""
    d.polygon([(190, 300), (400, 240), (624, 320), (834, 250), (834, 760), (624, 830), (400, 750), (190, 810)], fill=SOFT)
    d.line([(400, 240), (400, 750)], fill=(255, 255, 255, 90), width=8)
    d.line([(624, 320), (624, 830)], fill=(255, 255, 255, 90), width=8)
    cx, cy, r = 512, 470, 190
    d.pieslice((cx - r, cy - r, cx + r, cy + r), -90, 150, fill=WHITE)
    d.pieslice((cx - r, cy - r, cx + r, cy + r), 150, 270, fill=(255, 214, 102, 255))
    d.ellipse((cx - 56, cy - 56, cx + 56, cy + 56), fill=(18, 110, 112, 255))


def schedule(d):
    """Скедул ПХГ: календарь с диаграммой Ганта."""
    d.rounded_rectangle((170, 220, 854, 830), radius=70, fill=WHITE)
    d.rounded_rectangle((170, 220, 854, 380), radius=70, fill=(255, 255, 255, 200))
    d.rectangle((170, 330, 854, 380), fill=(255, 255, 255, 200))
    for x in (310, 714):
        d.rounded_rectangle((x - 28, 150, x + 28, 290), radius=28, fill=(255, 255, 255, 255))
    d.rectangle((170, 330, 854, 346), fill=(214, 110, 20, 255))
    for row, (a, b, colour) in enumerate(((250, 560, (230, 126, 34, 255)), (380, 700, (74, 144, 217, 255)), (300, 480, (70, 170, 120, 255)), (520, 760, (200, 70, 90, 255)))):
        y = 410 + row * 98
        d.rounded_rectangle((a, y, b, y + 60), radius=30, fill=colour)


def restart(d):
    """Перечислитель UNRST: список слов с часами."""
    for i, w in enumerate((520, 420, 470, 340)):
        y = 250 + i * 130
        d.ellipse((190, y, 250, y + 60), fill=WHITE)
        d.rounded_rectangle((290, y + 8, 290 + w, y + 52), radius=22, fill=WHITE if i % 2 == 0 else SOFT)
    cx, cy, r = 700, 700, 190
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 214, 102, 255), outline=WHITE, width=24)
    d.line([(cx, cy), (cx, cy - 115)], fill=(86, 52, 150, 255), width=26)
    d.line([(cx, cy), (cx + 85, cy + 40)], fill=(86, 52, 150, 255), width=26)


def model(d):
    """Описание расчёта: сетка ячеек с выделенным слоем."""
    cell, gap, x0, y0 = 170, 26, 170, 190
    for i in range(4):
        for j in range(4):
            x, y = x0 + j * (cell + gap), y0 + i * (cell + gap)
            hot = (i, j) in ((1, 1), (1, 2), (2, 1), (2, 2))
            d.rounded_rectangle((x, y, x + cell, y + cell), radius=34, fill=(255, 196, 66, 255) if hot else (255, 255, 255, 235 if (i + j) % 2 == 0 else 170))
    d.rounded_rectangle((170, 100, 854, 140), radius=20, fill=SOFT)


def console(d):
    """Консольное меню: приглашение >_ ."""
    d.rounded_rectangle((150, 220, 874, 800), radius=60, fill=(10, 16, 24, 255))
    d.rounded_rectangle((150, 220, 874, 320), radius=60, fill=(40, 52, 68, 255))
    d.rectangle((150, 270, 874, 320), fill=(40, 52, 68, 255))
    for k, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse((205 + k * 70, 252, 245 + k * 70, 292), fill=c + (255,))
    d.line([(260, 450), (390, 540), (260, 630)], fill=(110, 231, 160, 255), width=44, joint='curve')
    d.rounded_rectangle((440, 610, 640, 650), radius=18, fill=(110, 231, 160, 255))


ICONS = {
    'pxg_base': ((46, 110, 214), (22, 52, 130), database),
    'karty_gsp': ((30, 170, 160), (14, 94, 104), maps),
    'skedul_pxg': ((246, 160, 60), (206, 84, 28), schedule),
    'perechislit_unrst': ((140, 98, 214), (70, 42, 140), restart),
    'opisat_model': ((86, 110, 138), (36, 52, 74), model),
    'pxg_base_console': ((70, 78, 90), (22, 26, 34), console),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (top, bottom, glyph) in ICONS.items():
        image = background(top, bottom)
        layer = Image.new('RGBA', (S, S), (0, 0, 0, 0))
        glyph(ImageDraw.Draw(layer))
        shadow = Image.new('RGBA', (S, S), (0, 0, 0, 0))
        shadow.paste((0, 0, 0, 70), (0, 14), layer.getchannel('A'))
        image.alpha_composite(shadow)
        image.alpha_composite(layer)
        image.resize((256, 256), Image.LANCZOS).save(str(OUT / (name + '.png')))
        image.save(str(OUT / (name + '.ico')), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        print(name)


if __name__ == '__main__':
    main()
