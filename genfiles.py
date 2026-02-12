from PIL import Image, ImageOps, ImageDraw
import os
import math
import random

# ---------------------------------------------------------------------------
# genfiles.py
# Tiny script to batch-generate colored isopod images from a base image.
# Run this when you want a folder of nicely tinted isopod PNGs. may at times
# end up making witchcraft. It is not
# used at runtime by the bot, but helpful for preparing assets. Keep it
# separate and feel free to run manually.
# ---------------------------------------------------------------------------

hex_colors = {
    'red': '#FF0000',
    'orange': '#FF8C00',
    'yellow': '#FFFF00',
    'green': '#00A000',
    'blue': '#0000FF',
    'purple': '#800080',
    'pink': '#FF69B4',
    'cyan': '#00FFFF',
    'lime': '#00FF00',
    'magenta': '#FF00FF',
    'teal': '#008080',
    'indigo': '#4B0082'
}

def hex_to_rgb(hex_str):
    hex_str = hex_str.lstrip('#')
    return tuple(int(hex_str[i:i+2], 16) for i in range(0, 6, 2))

def create_vertical_gradient(size, start_rgb, end_rgb):
    width, height = size
    gradient = Image.new('RGBA', size)
    draw = ImageDraw.Draw(gradient)
    for y in range(height):
        ratio = y / height
        r = int(start_rgb[0] * (1 - ratio) + end_rgb[0] * ratio)
        g = int(start_rgb[1] * (1 - ratio) + end_rgb[1] * ratio)
        b = int(start_rgb[2] * (1 - ratio) + end_rgb[2] * ratio)
        draw.line((0, y, width, y), fill=(r, g, b, 255))
    return gradient

def add_streaks(canvas, base_rgb, num_streaks=25):
    draw = ImageDraw.Draw(canvas)
    width, height = canvas.size
    cx, cy = width // 2, height // 2
    streak_rgb = tuple(min(255, int(base_rgb[i] * 1.4 + 60)) for i in range(3))
    streak_color = streak_rgb + (200,)
    max_radius = max(width, height) * 0.45
    for _ in range(num_streaks):
        angle = math.pi * 2 * random.random()
        start_radius = max_radius * random.uniform(0.6, 1.0)
        end_radius = max_radius * random.uniform(0.0, 0.3)
        sx = cx + int(start_radius * math.cos(angle))
        sy = cy + int(start_radius * math.sin(angle))
        ex = cx + int(end_radius * math.cos(angle))
        ey = cy + int(end_radius * math.sin(angle))
        line_width = random.randint(1, 4)
        draw.line((sx, sy, ex, ey), fill=streak_color, width=line_width)

with open('colors.txt', 'r') as f:
    colors = [line.strip() for line in f if line.strip()]

base_img = 'isopod.png'

if not os.path.exists(base_img):
    raise FileNotFoundError(f"Base image {base_img} not found!")

img = Image.open(base_img).convert('RGBA')
rgb_img = img.convert('RGB')
gray = rgb_img.convert('L')
alpha = img.split()[-1]

for color_name in colors:
    if color_name not in hex_colors:
        print(f"Unknown color '{color_name}', skipping.")
        continue
    
    tinted_rgb = ImageOps.colorize(gray, '#000000', hex_colors[color_name])
    tinted = Image.merge('RGBA', tinted_rgb.split()[:3] + (alpha,))
    
    color_hex = hex_colors[color_name]
    rgb = hex_to_rgb(color_hex)
    dark_rgb = tuple(int(c * 0.25) for c in rgb)
    light_rgb = rgb
    
    w, h = img.size
    canvas_side = max(w, h) * 2
    canvas_size = (canvas_side, canvas_side)
    
    canvas = create_vertical_gradient(canvas_size, dark_rgb, light_rgb)
    add_streaks(canvas, light_rgb)
    
    paste_x = (canvas_side - w) // 2
    paste_y = (canvas_side - h) // 2
    canvas.paste(tinted, (paste_x, paste_y), tinted)
    
    output = f"{color_name}isopod.png"
    canvas.save(output, 'PNG')
    print(f"Generated {output}")

print("All epic streaky gradient transparent isopod images generated!")
