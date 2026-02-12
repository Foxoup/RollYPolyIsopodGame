from PIL import Image, ImageOps, ImageDraw
import os
import math
import random

# ---------------------------------------------------------------------------
# rainbow_gen.py
# Generates a glorious rainbow background version of the isopod. This script
# creates `rainbowpillbug.png` for the special rainbow roll. Not used at
# runtime except to provide the static asset the bot may send when a rainbow
# occurs. Enjoy the colors.
# ---------------------------------------------------------------------------

def hsv_to_rgb(h: float, s: float = 1.0, v: float = 1.0) -> tuple[int, int, int]:
    if s == 0:
        r = g = b = int(v * 255)
        return r, g, b
    h *= 6.0
    i = int(h)
    f = h - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i %= 6
    if i == 0:
        return int(v * 255), int(t * 255), int(p * 255)
    if i == 1:
        return int(q * 255), int(v * 255), int(p * 255)
    if i == 2:
        return int(p * 255), int(v * 255), int(t * 255)
    if i == 3:
        return int(p * 255), int(q * 255), int(v * 255)
    if i == 4:
        return int(t * 255), int(p * 255), int(q * 255)
    return int(v * 255), int(p * 255), int(t * 255)

base_img = 'isopod.png'
if not os.path.exists(base_img):
    raise FileNotFoundError("isopod.png missing!")

img = Image.open(base_img).convert('RGBA')
rgb_img = img.convert('RGB')
gray = rgb_img.convert('L')
alpha = img.split()[-1]
tinted_rgb = ImageOps.colorize(gray, '#FFFFFF', '#FFFFFF')  # white isopod
tinted = Image.merge('RGBA', tinted_rgb.split()[:3] + (alpha,))

w, h = img.size
canvas_side = max(w, h) * 2
canvas_size = (canvas_side, canvas_side)

# Rainbow gradient
gradient = Image.new('RGBA', canvas_size)
draw = ImageDraw.Draw(gradient)
for y in range(canvas_size[1]):
    hue = (y / canvas_size[1])
    rgb = hsv_to_rgb(hue)
    draw.line((0, y, canvas_side, y), fill=(*rgb, 255))

# Streaks brighter white/gold
streak_rgb = (255, 240, 100)
streak_color = streak_rgb + (220,)
max_radius = canvas_side * 0.45
for _ in range(35):
    angle = math.pi * 2 * random.random()
    start_radius = max_radius * random.uniform(0.7, 1.0)
    end_radius = max_radius * random.uniform(0.0, 0.2)
    sx = canvas_side // 2 + int(start_radius * math.cos(angle))
    sy = canvas_side // 2 + int(start_radius * math.sin(angle))
    ex = canvas_side // 2 + int(end_radius * math.cos(angle))
    ey = canvas_side // 2 + int(end_radius * math.sin(angle))
    lw = random.randint(2, 5)
    draw.line((sx, sy, ex, ey), fill=streak_color, width=lw)

canvas = gradient
paste_x = (canvas_side - w) // 2
paste_y = (canvas_side - h) // 2
canvas.paste(tinted, (paste_x, paste_y), tinted)

output = 'rainbowpillbug.png'
canvas.save(output, 'PNG')
print(f"Generated {output}")
