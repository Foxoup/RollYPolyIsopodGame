import os
import time
import random
import math
import json
from PIL import Image, ImageOps, ImageDraw
from db import get_conn

BASE_DIR = os.path.dirname(__file__)
ASSETS_DIR = os.path.join(BASE_DIR, 'Assets')
TXTS_DIR = os.path.join(ASSETS_DIR, 'TXTS')
GRAPHICS_DIR = os.path.join(ASSETS_DIR, 'Graphics')

# ---------------------------------------------------------------------------
# Utils: graphics, market generation, and file helpers
#
# Small, focused helpers to centralize file paths and image generation. The
# market generation functions below write directly to the DB (see
# `generate_marketplace`) altering those SQL writes or the pricing logic
# will change game balance. The usual advice applies: backup your DB first. and for the
# love of god, if you ask me to put your changes on production, test them first.
# ---------------------------------------------------------------------------

def get_txt_path(filename: str) -> str:
    return os.path.join(TXTS_DIR, filename)

def get_graphics_path(filename: str) -> str:
    return os.path.join(GRAPHICS_DIR, filename)

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

status_ranges = {
    'common': (5, 30),
    'rare': (40, 90),
    'epic': (120, 240),
    'legendary': (300, 700)
}

status_weights = [92, 6, 1.5, 0.5]  # %

def load_lists():
    with open(get_txt_path('colors.txt'), 'r') as f:
        colors = [l.strip() for l in f if l.strip()]
    with open(get_txt_path('wordslist.txt'), 'r') as f:
        words = [l.strip() for l in f if l.strip()]
    return colors, words

def needs_regen():
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT value FROM global_state WHERE key = ?', ('last_regen',))
    res = c.fetchone()
    conn.close()
    if not res:
        return True
    return time.time() - res[0] > 3 * 3600

def generate_marketplace():
    print("Generating marketplace...")
    conn = get_conn()
    c = conn.cursor()
    c.execute('DELETE FROM marketplace')
    c.execute('DELETE FROM isopod_stats')
    colors, words = load_lists()
    statuses = list(status_ranges.keys())
    move_pool = [
        'Shell Bash', 'Dust Kick', 'Claw Snap', 'Roll Tackle',
        'Antenna Jab', 'Mud Splash', 'Spore Puff', 'Stink Spray'
    ]
    for color in colors:
        for word in words:
            status = random.choices(statuses, weights=status_weights)[0]
            min_p, max_p = status_ranges[status]
            price = random.randint(min_p, max_p)
            full_name = f"{status.capitalize()} {color.capitalize()} {word} isopod"
            c.execute('INSERT INTO marketplace (color, word, full_name, status, price) VALUES (?, ?, ?, ?, ?)',
                      (color, word, full_name, status, price))
            market_id = c.lastrowid
            if status == 'common':
                hp = random.randint(20, 35)
                attack = random.randint(5, 10)
                moves_count = 2
            elif status == 'rare':
                hp = random.randint(30, 50)
                attack = random.randint(8, 14)
                moves_count = 3
            elif status == 'epic':
                hp = random.randint(45, 70)
                attack = random.randint(12, 20)
                moves_count = 3
            else:
                hp = random.randint(70, 100)
                attack = random.randint(18, 28)
                moves_count = 4
            moves = random.sample(move_pool, k=moves_count)
            move_defs = []
            for mv in moves:
                power = attack + random.randint(-2, 4)
                move_defs.append({'name': mv, 'power': max(1, power)})
            c.execute('INSERT INTO isopod_stats (market_id, hp, attack, moves_json) VALUES (?, ?, ?, ?)',
                      (market_id, hp, attack, json.dumps(move_defs)))
    conn.commit()
    c.execute('INSERT OR REPLACE INTO global_state (key, value) VALUES (?, ?)', ('last_regen', time.time()))
    conn.commit()
    conn.close()
    print(f"Generated {len(colors)*len(words)} isopods")

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

def generate_isopod_image(color_name: str, output_path: str = 'tempbug.png'):
    if color_name not in hex_colors:
        raise ValueError(f"Unknown color: {color_name}")
    base_img = get_graphics_path('isopod.png')
    if not os.path.exists(base_img):
        raise FileNotFoundError("isopod.png not found!")
    img = Image.open(base_img).convert('RGBA')
    rgb_img = img.convert('RGB')
    gray = rgb_img.convert('L')
    alpha = img.split()[-1]
    color_hex = hex_colors[color_name]
    tinted_rgb = ImageOps.colorize(gray, '#000000', color_hex)
    tinted = Image.merge('RGBA', tinted_rgb.split()[:3] + (alpha,))
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
    canvas.save(output_path, 'PNG')
    return output_path

def generate_isofish_image(color_name: str, output_path: str = 'tempfish.png'):
    if color_name not in hex_colors:
        raise ValueError(f"Unknown color: {color_name}")
    base_img = get_graphics_path('isofish.png')
    if not os.path.exists(base_img):
        raise FileNotFoundError("isofish.png not found!")
    img = Image.open(base_img).convert('RGBA')
    rgb_img = img.convert('RGB')
    gray = rgb_img.convert('L')
    alpha = img.split()[-1]
    color_hex = hex_colors[color_name]
    tinted_rgb = ImageOps.colorize(gray, '#000000', color_hex)
    tinted = Image.merge('RGBA', tinted_rgb.split()[:3] + (alpha,))
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
    canvas.save(output_path, 'PNG')
    return output_path

def cleanup_temp():
    temp = 'tempbug.png'
    if os.path.exists(temp):
        os.remove(temp)
    temp_fish = 'tempfish.png'
    if os.path.exists(temp_fish):
        os.remove(temp_fish)
