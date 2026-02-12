import telebot
import os
import time
import random
import json
from db import init_db, get_or_create_user, update_user_last_roll, update_user_money, set_legendary, get_conn
from utils import needs_regen, generate_marketplace, generate_isopod_image, generate_isofish_image, cleanup_temp, get_txt_path, get_graphics_path, load_lists

import logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__file__)

TOKEN = open(get_txt_path('telegramapikey.txt')).read().strip()

COOLDOWN = 300
MAX_CHARGES = 5
SHOP_REFRESH = 3600
MARKET_REFRESH = 3 * 3600
INSTANTROLL_PRICE = 250
OVERCHARGE_MAX = 10
XP_PER_LEVEL = 100
LEVEL_HP_BONUS = 2
LEVEL_ATK_BONUS = 1
RAINBOW_CHANCE = 0.005
HEAL_CHANCE = 0.1
NERF_CHANCE = 0.05
ITEM_DROP_CHANCE = 0.05
BROADCAST_PASSWORD_FILE = get_txt_path('broadcast_password.txt')

ITEM_DEFS = {
    'energy_drink': {
        'name': 'Energy Drink',
        'price': 50,
        'effect_type': 'add_charge',
        'effect_value': '1',
        'description': 'Add 1 roll charge (can overcharge)'
    },
    'energy_drink_pack': {
        'name': 'Energy Drink Pack',
        'price': 220,
        'effect_type': 'add_charge',
        'effect_value': '5',
        'description': 'Add 5 roll charges (can overcharge)'
    },
    'lucky_token': {
        'name': 'Lucky Token',
        'price': 220,
        'effect_type': 'guarantee_rare',
        'effect_value': '1',
        'description': 'Next roll is Rare or better'
    },
    'golden_ticket': {
        'name': 'Golden Ticket',
        'price': 900,
        'effect_type': 'guarantee_legendary',
        'effect_value': '1',
        'description': 'Next roll is Legendary'
    },
    'double_roll': {
        'name': 'Double Roll',
        'price': 180,
        'effect_type': 'double_roll',
        'effect_value': '1',
        'description': 'Double your current charges (up to max)'
    },
    'market_refresh': {
        'name': 'Market Refresh',
        'price': 260,
        'effect_type': 'regen_market',
        'effect_value': '1',
        'description': 'Force global market regen now'
    },
    'iso_magnet': {
        'name': 'Iso Magnet',
        'price': 200,
        'effect_type': 'item_drop_boost',
        'effect_value': '2',
        'description': 'Double item drop chance for 30 minutes'
    },
    'sale_voucher': {
        'name': 'Sale Voucher',
        'price': 150,
        'effect_type': 'shop_discount',
        'effect_value': '10',
        'description': '10% off next 3 shop buys'
    },
    'safety_net': {
        'name': 'Safety Net',
        'price': 300,
        'effect_type': 'safety_net',
        'effect_value': '1',
        'description': 'Prevents losing an isopod in next battle loss'
    },
    'bite_bug': {
        'name': 'Bite Bug',
        'price': 160,
        'effect_type': 'bite_bug',
        'effect_value': '1',
        'description': 'Steal 5-15% iso$ from a target'
    },
    'sticky_goo': {
        'name': 'Sticky Goo',
        'price': 130,
        'effect_type': 'sticky_goo',
        'effect_value': '1',
        'description': 'Remove 1 charge and delay next charge'
    },
    'fake_coupon': {
        'name': 'Fake Coupon',
        'price': 140,
        'effect_type': 'fake_coupon',
        'effect_value': '1',
        'description': 'Target loses 1 charge with no roll'
    },
    'market_sabotage': {
        'name': 'Market Sabotage',
        'price': 280,
        'effect_type': 'market_sabotage',
        'effect_value': '1',
        'description': 'Regenerate market with lower prices'
    },
    'spy_drone': {
        'name': 'Spy Drone',
        'price': 190,
        'effect_type': 'spy_drone',
        'effect_value': '1',
        'description': '20% defense in your next battle'
    },
    'swap_token': {
        'name': 'Swap Token',
        'price': 240,
        'effect_type': 'swap_token',
        'effect_value': '1',
        'description': 'Swap a random isopod with a target'
    },
    'iso_candy': {
        'name': 'Iso Candy',
        'price': 120,
        'effect_type': 'add_xp',
        'effect_value': '25',
        'description': 'Add 25 XP to an isopod'
    },
    'fusion_pod': {
        'name': 'Fusion Pod',
        'price': 320,
        'effect_type': 'fusion_pod',
        'effect_value': '1',
        'description': 'Required to breed two isopods'
    },
    'breeding_food': {
        'name': 'Breeding Food',
        'price': 160,
        'effect_type': 'breeding_food',
        'effect_value': '1',
        'description': 'Required to breed two isopods'
    },
    'race_fuel': {
        'name': 'Race Fuel',
        'price': 180,
        'effect_type': 'race_boost',
        'effect_value': '0.2',
        'description': '20% speed boost in next race'
    }
}

def ensure_broadcast_password_file():
    if not os.path.exists(BROADCAST_PASSWORD_FILE):
        with open(BROADCAST_PASSWORD_FILE, 'w') as f:
            f.write('changeme')

# --------------------------------------------------------------------------------
# Shop / item seeding helpers
# These touch the DB to ensure expected shop rows exist. SQL here is pretty
# straightforward: check, insert if missing. Commenting because changing this
# can silently alter shop behavior, don't be surprised if an edit breaks buys.
# --------------------------------------------------------------------------------

def seed_shop_items(conn):
    c = conn.cursor()
    for item_id, data in ITEM_DEFS.items():
        c.execute('SELECT 1 FROM shop_items WHERE item_id = ?', (item_id,))
        if c.fetchone():
            continue
        c.execute(
            'INSERT INTO shop_items (item_id, name, price, effect_type, effect_value, description) VALUES (?, ?, ?, ?, ?, ?)',
            (item_id, data['name'], data['price'], data['effect_type'], data['effect_value'], data['description'])
        )
    conn.commit()

def get_item_short_map(conn):
    seed_shop_items(conn)
    c = conn.cursor()
    c.execute('SELECT item_id FROM shop_items ORDER BY item_id')
    item_ids = [r[0] for r in c.fetchall()]
    return {str(i + 1): item_id for i, item_id in enumerate(item_ids)}

# --------------------------------------------------------------------------------
# Item resolving: accepts long ids, short numeric picks,
# or the internal key from ITEM_DEFS. Mostly a convenience layer on top of SQL.
# --------------------------------------------------------------------------------

def resolve_item_id(conn, token):
    seed_shop_items(conn)
    if not token:
        return None
    c = conn.cursor()
    c.execute('SELECT 1 FROM shop_items WHERE item_id = ?', (token,))
    if c.fetchone():
        return token
    if token in ITEM_DEFS:
        return token
    if token.isdigit():
        short_map = get_item_short_map(conn)
        return short_map.get(token)
    return None

# --------------------------------------------------------------------------------
# Fishing & Fish catalog seeding
# This creates catalog rows based on text files. I don't fully remember the
# heuristics used here either, so changing price/tier weights might feel like
# witchcraft. Tread carefully unless you want surprising fish economics.
# --------------------------------------------------------------------------------

def seed_fishing_rods(conn):
    c = conn.cursor()
    rods = [
        ('basic_rod', 'Basic Rod', 150, 1, 0.55, 0.10, 1, 2.0, 0.03),
        ('sturdy_rod', 'Sturdy Rod', 350, 2, 0.70, 0.20, 2, 1.5, 0.05),
        ('elite_rod', 'Elite Rod', 700, 3, 0.82, 0.35, 5, 1.0, 0.08)
    ]
    for rod in rods:
        c.execute('SELECT 1 FROM fishing_rods WHERE rod_id = ?', (rod[0],))
        if c.fetchone():
            continue
        c.execute('''
            INSERT INTO fishing_rods (rod_id, name, price, tier, bite_chance, save_bait_chance, multi_catch_max, speed_sec, bonus_item_chance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', rod)
    conn.commit()

def ensure_fish_catalog(conn):
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM fish_catalog')
    if c.fetchone()[0] > 0:
        return
    colors, words = load_lists()
    tiers = ['common', 'rare', 'epic', 'legendary']
    weights = [70, 20, 8, 2]
    tier_ranges = {
        'common': (20, 60),
        'rare': (80, 160),
        'epic': (200, 400),
        'legendary': (600, 1200)
    }
    for color in colors:
        for word in words:
            tier = random.choices(tiers, weights=weights)[0]
            min_p, max_p = tier_ranges[tier]
            price = random.randint(min_p, max_p)
            name = f"{tier.capitalize()} {color.capitalize()} {word} isofish"
            c.execute('INSERT INTO fish_catalog (color, word, name, tier, price) VALUES (?, ?, ?, ?, ?)',
                      (color, word, name, tier, price))
    conn.commit()

def add_user_rod(conn, user_id, rod_id, qty=1):
    c = conn.cursor()
    c.execute('SELECT qty FROM user_rods WHERE user_id = ? AND rod_id = ?', (user_id, rod_id))
    row = c.fetchone()
    if row:
        c.execute('UPDATE user_rods SET qty = qty + ? WHERE user_id = ? AND rod_id = ?', (qty, user_id, rod_id))
    else:
        c.execute('INSERT INTO user_rods (user_id, rod_id, qty) VALUES (?, ?, ?)', (user_id, rod_id, qty))
    conn.commit()

def add_user_fish(conn, user_id, fish_id, qty=1):
    c = conn.cursor()
    c.execute('SELECT qty FROM user_fish WHERE user_id = ? AND fish_id = ?', (user_id, fish_id))
    row = c.fetchone()
    if row:
        c.execute('UPDATE user_fish SET qty = qty + ? WHERE user_id = ? AND fish_id = ?', (qty, user_id, fish_id))
    else:
        c.execute('INSERT INTO user_fish (user_id, fish_id, qty) VALUES (?, ?, ?)', (user_id, fish_id, qty))
    conn.commit()

# --------------------------------------------------------------------------------
# Shop rotation and effects
# Lots of SQL selects/inserts here; the logic picks shop items, refreshes
# rotation, and persists user effects. If you think "I can optimize this",
# remember the database layout is flat and tiny. Premature optimization may
# cause more bugs than wins.
# --------------------------------------------------------------------------------

def get_shop_rotation(conn, now):
    seed_shop_items(conn)
    c = conn.cursor()
    c.execute('SELECT slot, item_id, refresh_at FROM shop_rotation ORDER BY slot')
    rows = c.fetchall()
    refreshed = False
    if not rows or any(r[2] is None for r in rows) or now - rows[0][2] >= SHOP_REFRESH:
        c.execute('SELECT item_id FROM shop_items')
        item_ids = [r[0] for r in c.fetchall()]
        picks = random.sample(item_ids, k=min(3, len(item_ids)))
        c.execute('DELETE FROM shop_rotation')
        for idx, item_id in enumerate(picks, 1):
            c.execute('INSERT INTO shop_rotation (slot, item_id, refresh_at) VALUES (?, ?, ?)', (idx, item_id, now))
        conn.commit()
        c.execute('SELECT slot, item_id, refresh_at FROM shop_rotation ORDER BY slot')
        rows = c.fetchall()
        refreshed = True
    return rows, refreshed

def get_effect(conn, user_id, effect_type, now):
    c = conn.cursor()
    c.execute('SELECT effect_value, expires_at FROM user_effects WHERE user_id = ? AND effect_type = ?', (user_id, effect_type))
    row = c.fetchone()
    if not row:
        return None
    value, expires_at = row
    if expires_at and now > expires_at:
        c.execute('DELETE FROM user_effects WHERE user_id = ? AND effect_type = ?', (user_id, effect_type))
        conn.commit()
        return None
    try:
        return json.loads(value)
    except Exception:
        return value

def set_effect(conn, user_id, effect_type, value, duration=None):
    now = time.time()
    expires_at = now + duration if duration else None
    if not isinstance(value, str):
        value = json.dumps(value)
    c = conn.cursor()
    c.execute(
        'INSERT OR REPLACE INTO user_effects (user_id, effect_type, effect_value, expires_at) VALUES (?, ?, ?, ?)',
        (user_id, effect_type, value, expires_at)
    )
    conn.commit()

def consume_effect(conn, user_id, effect_type):
    c = conn.cursor()
    c.execute('DELETE FROM user_effects WHERE user_id = ? AND effect_type = ?', (user_id, effect_type))
    conn.commit()

def add_user_item(conn, user_id, item_id, qty=1):
    c = conn.cursor()
    c.execute('SELECT qty FROM user_items WHERE user_id = ? AND item_id = ?', (user_id, item_id))
    row = c.fetchone()
    if row:
        c.execute('UPDATE user_items SET qty = qty + ? WHERE user_id = ? AND item_id = ?', (qty, user_id, item_id))
    else:
        c.execute('INSERT INTO user_items (user_id, item_id, qty) VALUES (?, ?, ?)', (user_id, item_id, qty))
    conn.commit()

def consume_user_item(conn, user_id, item_id, qty=1):
    c = conn.cursor()
    c.execute('SELECT qty FROM user_items WHERE user_id = ? AND item_id = ?', (user_id, item_id))
    row = c.fetchone()
    if not row or row[0] < qty:
        return False
    c.execute('UPDATE user_items SET qty = qty - ? WHERE user_id = ? AND item_id = ?', (qty, user_id, item_id))
    c.execute('DELETE FROM user_items WHERE user_id = ? AND item_id = ? AND qty <= 0', (user_id, item_id))
    conn.commit()
    return True

def get_user_item_qty(conn, user_id, item_id):
    c = conn.cursor()
    c.execute('SELECT qty FROM user_items WHERE user_id = ? AND item_id = ?', (user_id, item_id))
    row = c.fetchone()
    return row[0] if row else 0

# --------------------------------------------------------------------------------
# Charge syncing + helper text
# Handles the timed charge regen mechanic. This is pure game logic with a
# couple of DB writes. Messing with timing constants will change pacing.
# --------------------------------------------------------------------------------

def update_user_charges(conn, user_id, charges, last_charge_at=None):
    if charges is None:
        charges = 0
    if charges < 0:
        charges = 0
    if charges > OVERCHARGE_MAX:
        charges = OVERCHARGE_MAX
    c = conn.cursor()
    if last_charge_at is None:
        c.execute('UPDATE users SET roll_charges = ? WHERE user_id = ?', (charges, user_id))
    else:
        c.execute('UPDATE users SET roll_charges = ?, last_charge_at = ? WHERE user_id = ?', (charges, last_charge_at, user_id))
    conn.commit()

def sync_charges(conn, user_id, now):
    c = conn.cursor()
    c.execute('SELECT roll_charges, last_charge_at FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    if not row:
        return 1, now
    charges, last_charge_at = row
    if charges is None:
        charges = 0
    if charges < 0:
        charges = 0
    if not last_charge_at:
        last_charge_at = now
    if last_charge_at > now:
        return charges, last_charge_at
    gained = int((now - last_charge_at) // COOLDOWN)
    if gained > 0:
        if charges < MAX_CHARGES:
            charges = min(MAX_CHARGES, charges + gained)
        last_charge_at = last_charge_at + gained * COOLDOWN
        update_user_charges(conn, user_id, charges, last_charge_at)
    else:
        update_user_charges(conn, user_id, charges, last_charge_at)
    return charges, last_charge_at

def charge_status_text(charges, last_charge_at, now):
    if charges is None:
        charges = 0
    if charges < 0:
        charges = 0
    if charges >= MAX_CHARGES:
        status = "full" if charges == MAX_CHARGES else "overcharged"
        return f"Charges: {charges}/{MAX_CHARGES} ({status})"
    if last_charge_at > now:
        remain = int(last_charge_at - now)
    else:
        remain = int(COOLDOWN - (now - last_charge_at))
    if remain < 0:
        remain = 0
    m, s = divmod(remain, 60)
    return f"Charges: {charges}/{MAX_CHARGES} | Next in {m}m {s:02d}s"

# --------------------------------------------------------------------------------
# Lookup helpers
# Small utilities that wrap SQL to return single values. Useful to centralize
# queries that otherwise appear in multiple command handlers.
# --------------------------------------------------------------------------------

def get_user_id_by_username(conn, username):
    c = conn.cursor()
    c.execute('SELECT user_id FROM users WHERE username = ?', (username,))
    row = c.fetchone()
    return row[0] if row else None

def get_isopod_record(conn, inv_id, user_id):
    c = conn.cursor()
    # SQL grab: inventory joined to marketplace and stats. This merges user
    # overrides with marketplace defaults so the inventory row has a full
    # usable record. If you're tempted to refactor this, remember the code
    # later assumes certain defaults exist.
    c.execute('''
        SELECT i.id, i.name, i.status, i.price, i.color, i.hp, i.attack, i.moves_json,
               m.full_name, m.status, m.price, m.color, s.hp, s.attack, s.moves_json
        FROM inventory i
        LEFT JOIN marketplace m ON i.market_id = m.id
        LEFT JOIN isopod_stats s ON i.market_id = s.market_id
        WHERE i.id = ? AND i.user_id = ?
    ''', (inv_id, user_id))
    row = c.fetchone()
    if not row:
        return None
    (iid, name, status, price, color, hp, attack, moves_json,
     m_name, m_status, m_price, m_color, s_hp, s_attack, s_moves) = row
    if not name:
        name = m_name
    if not status:
        status = m_status
    if not price:
        price = m_price
    if not color:
        color = m_color
    if not hp:
        hp = s_hp
    if not attack:
        attack = s_attack
    if not moves_json:
        moves_json = s_moves
    if name and hp and attack and moves_json:
        c.execute('UPDATE inventory SET name = ?, status = ?, price = ?, color = ?, hp = ?, attack = ?, moves_json = ? WHERE id = ?',
                  (name, status, price, color, hp, attack, moves_json, inv_id))
        conn.commit()
    return {
        'id': iid,
        'name': name or 'Unknown isopod',
        'status': status or 'common',
        'price': price or 0,
        'color': color or 'unknown',
        'hp': hp or 10,
        'attack': attack or 5,
        'moves': json.loads(moves_json) if moves_json else []
    }

# --------------------------------------------------------------------------------
# Roll logic
# This is where the bot pulls a random isopod from the marketplace and
# inserts it into a player's inventory. It includes image generation calls,
# special-case rainbow handling, charge adjustments, and potential item drops.
# It's one of the more complex command flows. Read it slowly if you change it.
# --------------------------------------------------------------------------------

def roll_isopod(conn, uid, msg, now, guarantee=None):
    if needs_regen():
        generate_marketplace()
    cid = msg.chat.id
    if guarantee is None and random.random() < RAINBOW_CHANCE:
        logger.info(f"Rainbow rolled by {uid}")
        set_legendary(uid, True)
        caption = "🌈 RAINBOW PILLBUG! Legendary status!"
        rainbow_path = get_graphics_path('rainbowpillbug.png')
        if os.path.exists(rainbow_path):
            with open(rainbow_path, 'rb') as f:
                bot.send_photo(cid, f, caption=caption)
        else:
            bot.reply_to(msg, caption)
        update_user_last_roll(uid, now)
        return
    c = conn.cursor()
    if guarantee == 'legendary':
        c.execute("SELECT id, full_name, status, price, color FROM marketplace WHERE status = 'legendary' ORDER BY RANDOM() LIMIT 1")
    elif guarantee == 'rare':
        c.execute("SELECT id, full_name, status, price, color FROM marketplace WHERE status IN ('rare','epic','legendary') ORDER BY RANDOM() LIMIT 1")
    else:
        c.execute('SELECT id, full_name, status, price, color FROM marketplace ORDER BY RANDOM() LIMIT 1')
    row = c.fetchone()
    if not row:
        bot.reply_to(msg, "No market entries found.")
        return
    market_id, full_name, status, price, color = row
    c.execute('SELECT hp, attack, moves_json FROM isopod_stats WHERE market_id = ?', (market_id,))
    stats = c.fetchone()
    hp, attack, moves_json = stats if stats else (20, 5, '[]')
    img_path = generate_isopod_image(color)
    caption = f"{full_name}\n💰 {price} iso$\n❤️ {hp} | ⚔️ {attack}"
    with open(img_path, 'rb') as f:
        bot.send_photo(cid, f, caption=caption)
    cleanup_temp()
    c.execute('''
        INSERT INTO inventory (user_id, market_id, name, status, price, color, hp, attack, moves_json, level, xp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (uid, market_id, full_name, status, price, color, hp, attack, moves_json, 1, 0))
    conn.commit()
    logger.info(f"Rolled '{full_name}' (price {price}, market_id {market_id}) for {uid}")
    if random.random() < HEAL_CHANCE:
        c.execute('SELECT roll_charges FROM users WHERE user_id = ?', (uid,))
        charges = c.fetchone()[0]
        charges = min(MAX_CHARGES, charges + 1)
        update_user_charges(conn, uid, charges)
        bot.reply_to(msg, "💚 Healing pill bug! +1 charge")
    elif random.random() < NERF_CHANCE:
        extra = 600
        c.execute('SELECT roll_charges FROM users WHERE user_id = ?', (uid,))
        charges = c.fetchone()[0]
        update_user_charges(conn, uid, charges, now + extra)
        bot.reply_to(msg, "😵 Bit you! Next charge delayed by 10 minutes!")
    update_user_last_roll(uid, now)
    drop_chance = ITEM_DROP_CHANCE
    boost = get_effect(conn, uid, 'item_drop_boost', now)
    if boost:
        try:
            drop_chance *= float(boost)
        except Exception:
            pass
    if random.random() < drop_chance:
        item_id = random.choice(list(ITEM_DEFS.keys()))
        add_user_item(conn, uid, item_id, 1)
        bot.reply_to(msg, f"🎁 {ITEM_DEFS[item_id]['name']}!")

# --------------------------------------------------------------------------------
# Short utility view / formatting helpers
# --------------------------------------------------------------------------------

def format_inventory_list(conn, user_id, limit=10):
    c = conn.cursor()
    c.execute('''
        SELECT i.id, COALESCE(i.name, m.full_name), COALESCE(i.status, m.status), COALESCE(i.price, m.price), i.hp, i.attack, i.locked, i.level
        FROM inventory i LEFT JOIN marketplace m ON i.market_id = m.id
        WHERE i.user_id = ? ORDER BY i.acquired_at DESC LIMIT ?
    ''', (user_id, limit))
    rows = c.fetchall()
    if not rows:
        return "(empty)"
    lines = []
    for inv_id, name, status, price, hp, atk, locked, level in rows:
        lock_text = " 🔒" if locked else ""
        level_text = f" Lv{level}" if level else ""
        lines.append(f"{inv_id}: {name} ({status}){level_text} ❤️ {hp or '?'} ⚔️ {atk or '?'}{lock_text}")
    return "\n".join(lines)

def send_to_users(user_ids, text):
    sent = 0
    for uid in set(user_ids):
        try:
            bot.send_message(uid, text)
            sent += 1
        except Exception:
            continue
    return sent

def send_to_chat(chat_id, text):
    try:
        bot.send_message(chat_id, text)
        return True
    except Exception:
        return False

def send_silent_to_chat(chat_id, text):
    try:
        bot.send_message(chat_id, text, disable_notification=True)
        return True
    except Exception:
        return False

def notify_expired_effects(conn, user_id, chat_id, now):
    c = conn.cursor()
    c.execute('SELECT effect_type FROM user_effects WHERE user_id = ? AND expires_at IS NOT NULL AND expires_at <= ?', (user_id, now))
    rows = c.fetchall()
    if not rows:
        return
    expired = [r[0] for r in rows]
    c.execute('DELETE FROM user_effects WHERE user_id = ? AND expires_at IS NOT NULL AND expires_at <= ?', (user_id, now))
    conn.commit()
    names = {
        'item_drop_boost': 'Item drop boost'
    }
    labels = [names.get(e) or e for e in expired]
    send_silent_to_chat(chat_id, f"⏱️ Expired: {', '.join(labels)}")

def run_battle(conn, challenger_id, target_id, challenger_inv_id, target_inv_id, chat_id):
    c = conn.cursor()
    challenger = get_isopod_record(conn, challenger_inv_id, challenger_id)
    target = get_isopod_record(conn, target_inv_id, target_id)
    if not challenger or not target:
        return False, "Isopod not found"
    now = time.time()
    challenger_boost = get_effect(conn, challenger_id, 'battle_defense_boost', now)
    target_boost = get_effect(conn, target_id, 'battle_defense_boost', now)
    if challenger_boost:
        consume_effect(conn, challenger_id, 'battle_defense_boost')
    if target_boost:
        consume_effect(conn, target_id, 'battle_defense_boost')
    try:
        challenger_boost = float(challenger_boost) if challenger_boost else 0.0
    except Exception:
        challenger_boost = 0.2
    try:
        target_boost = float(target_boost) if target_boost else 0.0
    except Exception:
        target_boost = 0.2
    c.execute('SELECT username FROM users WHERE user_id = ?', (challenger_id,))
    challenger_name = c.fetchone()[0] or 'challenger'
    c.execute('SELECT username FROM users WHERE user_id = ?', (target_id,))
    target_name = c.fetchone()[0] or 'target'
    hp1 = challenger['hp']
    hp2 = target['hp']
    moves1 = challenger['moves'] or [{'name': 'Tackle', 'power': challenger['attack']}]
    moves2 = target['moves'] or [{'name': 'Tackle', 'power': target['attack']}]
    rounds = 0
    while hp1 > 0 and hp2 > 0 and rounds < 20:
        rounds += 1
        move1 = random.choice(moves1)
        move2 = random.choice(moves2)
        dmg1 = max(1, int(move1['power']) + random.randint(-2, 2))
        dmg2 = max(1, int(move2['power']) + random.randint(-2, 2))
        if target_boost:
            dmg1 = max(1, int(dmg1 * (1 - target_boost)))
        if challenger_boost:
            dmg2 = max(1, int(dmg2 * (1 - challenger_boost)))
        hp2 -= dmg1
        hp1 -= dmg2
        text = (
            f"Round {rounds}: @{challenger_name}'s {challenger['name']} used {move1['name']} for {dmg1} dmg (HP {max(hp1,0)})\n"
            f"@{target_name}'s {target['name']} used {move2['name']} for {dmg2} dmg (HP {max(hp2,0)})"
        )
        send_to_chat(chat_id, text)
    if hp1 <= 0 and hp2 <= 0:
        winner_id = challenger_id if random.random() < 0.5 else target_id
    elif hp1 > hp2:
        winner_id = challenger_id
    else:
        winner_id = target_id
    loser_id = target_id if winner_id == challenger_id else challenger_id
    reward = random.randint(50, 120) + int((challenger['price'] + target['price']) / 15)
    update_user_money(winner_id, reward)
    safety = get_effect(conn, loser_id, 'safety_net', time.time())
    if safety:
        consume_effect(conn, loser_id, 'safety_net')
        lost_text = "Safety Net saved your isopod!"
    else:
        lose_inv_id = target_inv_id if loser_id == target_id else challenger_inv_id
        c.execute('DELETE FROM inventory WHERE id = ?', (lose_inv_id,))
        conn.commit()
        lost_text = "Your isopod was lost in battle."
    winner_name = challenger_name if winner_id == challenger_id else target_name
    loser_name = target_name if winner_id == challenger_id else challenger_name
    final_text = f"🏁 Winner: @{winner_name}! +{reward} iso$\nLoser: @{loser_name}. {lost_text}"
    send_to_chat(chat_id, final_text)
    return True, "Battle completed"

def run_race(conn, challenger_id, target_id, challenger_inv_id, target_inv_id, chat_id, bet):
    c = conn.cursor()
    challenger = get_isopod_record(conn, challenger_inv_id, challenger_id)
    target = get_isopod_record(conn, target_inv_id, target_id)
    if not challenger or not target:
        return False, "Isopod not found"
    now = time.time()
    challenger_boost = get_effect(conn, challenger_id, 'race_speed_boost', now)
    target_boost = get_effect(conn, target_id, 'race_speed_boost', now)
    if challenger_boost:
        consume_effect(conn, challenger_id, 'race_speed_boost')
    if target_boost:
        consume_effect(conn, target_id, 'race_speed_boost')
    try:
        challenger_boost = float(challenger_boost) if challenger_boost else 0.0
    except Exception:
        challenger_boost = 0.2
    try:
        target_boost = float(target_boost) if target_boost else 0.0
    except Exception:
        target_boost = 0.2
    speed1 = random.uniform(1.0, 10.0) * (1 + challenger_boost)
    speed2 = random.uniform(1.0, 10.0) * (1 + target_boost)
    if speed1 == speed2:
        winner_id = challenger_id if random.random() < 0.5 else target_id
    elif speed1 > speed2:
        winner_id = challenger_id
    else:
        winner_id = target_id
    loser_id = target_id if winner_id == challenger_id else challenger_id
    update_user_money(winner_id, bet)
    update_user_money(loser_id, -bet)
    c.execute('SELECT username FROM users WHERE user_id = ?', (challenger_id,))
    challenger_name = c.fetchone()[0] or 'challenger'
    c.execute('SELECT username FROM users WHERE user_id = ?', (target_id,))
    target_name = c.fetchone()[0] or 'target'
    winner_name = challenger_name if winner_id == challenger_id else target_name
    loser_name = target_name if winner_id == challenger_id else challenger_name
    text = (
        f"🏁 Race result: @{winner_name} wins {bet} iso$!\n"
        f"Speeds: @{challenger_name} {speed1:.2f} | @{target_name} {speed2:.2f}\n"
        f"Loser: @{loser_name}"
    )
    send_to_chat(chat_id, text)
    return True, "Race completed"

init_db()
ensure_broadcast_password_file()
conn = get_conn()
seed_fishing_rods(conn)
ensure_fish_catalog(conn)
conn.close()
if needs_regen():
    generate_marketplace()

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start(msg):
    logger.info(f"Start/help by user {msg.from_user.id}")
    uid = msg.from_user.id
    user = get_or_create_user(uid, msg.from_user.username or 'unknown')
    text = f"""🦠 Roll-y Poly Isopod Bot, {user['username']}!

Use /help to see all commands."""
    bot.reply_to(msg, text)

@bot.message_handler(commands=['help'])
def help_command(msg):
    text = """📜 Commands

/roll | /r - Roll using 1 charge
/roll all - Roll all charges
/charges - View charge status
/instantroll | /instaroll - Instant roll (costs iso$)
/inventory - List isopods (IDs for sell)
/items | /item - List items and effects
/item delete <item_id> [qty]
/item sell <item_id> [qty]
/buy, /use, /item delete/sell accept short item IDs from /items
/shop - Shop rotation
/buy <item_id> - Buy shop item
/use <item_id> [@user] - Use item
/sell <ID> | /sell all [rarity]
/sellall | /sall - Shortcut for /sell all
/lock <ID> | /unlock <ID>
/breed <id1> <id2>
/rainbowfusion <ids...>
/fishing shop | /fishing buy <rod_id> | /fishing start <rod_id> <isopod_id> | /fishing inventory
/auction list | /auction sell <isopod_id> <price> | /auction buy <auction_id> | /auction cancel <id|all>
/market - Top high/low
/top - Richest
/legendary - Legendaries
/battle @user <isopod_id>
/accept <isopod_id> | /decline
/race @user <isopod_id> <bet>
/raceaccept <isopod_id> | /racedecline
/broadcast <password> <message>"""
    bot.reply_to(msg, text)

@bot.message_handler(commands=['roll', 'r'])
def roll(msg):
    uid = msg.from_user.id
    logger.info(f"Roll attempt by {uid}")
    get_or_create_user(uid, msg.from_user.username or 'unknown')
    now = time.time()
    use_all = len(msg.text.split()) > 1 and msg.text.split()[1].lower() == 'all'
    conn = get_conn()
    notify_expired_effects(conn, uid, msg.chat.id, now)
    charges, last_charge_at = sync_charges(conn, uid, now)
    if use_all:
        count = charges
    else:
        count = 1
    if count > charges:
        count = charges
    if count <= 0:
        status = charge_status_text(charges, last_charge_at, now)
        bot.reply_to(msg, f"⏳ No charges. {status}")
        conn.close()
        return
    charges -= count
    update_user_charges(conn, uid, charges)
    guarantee = get_effect(conn, uid, 'guarantee_legendary', now)
    if guarantee:
        consume_effect(conn, uid, 'guarantee_legendary')
        guarantee = 'legendary'
    else:
        guarantee = get_effect(conn, uid, 'guarantee_rare', now)
        if guarantee:
            consume_effect(conn, uid, 'guarantee_rare')
            guarantee = 'rare'
    for _ in range(count):
        roll_isopod(conn, uid, msg, now, guarantee)
        guarantee = None
    charges, last_charge_at = sync_charges(conn, uid, time.time())
    bot.reply_to(msg, charge_status_text(charges, last_charge_at, time.time()))
    conn.close()

@bot.message_handler(commands=['instantroll', 'instaroll'])
def instantroll(msg):
    uid = msg.from_user.id
    user = get_or_create_user(uid, msg.from_user.username or 'unknown')
    if user['money'] < INSTANTROLL_PRICE:
        bot.reply_to(msg, f"💸 Need {INSTANTROLL_PRICE} iso$")
        return
    update_user_money(uid, -INSTANTROLL_PRICE)
    conn = get_conn()
    now = time.time()
    charges, last_charge_at = sync_charges(conn, uid, now)
    if charges < 1:
        update_user_charges(conn, uid, 1)
    conn.close()
    roll(msg)

@bot.message_handler(commands=['inventory'])
def inventory(msg):
    uid = msg.from_user.id
    logger.info(f"Inventory request by {uid}")
    conn = get_conn()
    notify_expired_effects(conn, uid, msg.chat.id, time.time())
    c = conn.cursor()
    # Recent 10
    c.execute('''
        SELECT i.id, COALESCE(i.name, m.full_name), COALESCE(i.price, m.price), COALESCE(i.status, m.status), i.hp, i.attack, i.locked, i.level
        FROM inventory i LEFT JOIN marketplace m ON i.market_id = m.id
        WHERE i.user_id = ? ORDER BY i.acquired_at DESC LIMIT 10
    ''', (uid,))
    rows = c.fetchall()
    if not rows:
        bot.reply_to(msg, "📦 Empty inventory")
        conn.close()
        return
    lines = ["📦 Recent (/sell <ID>):"]
    recent_total = 0
    for inv_id, name, p, s, hp, atk, locked, level in rows:
        p = p or 0
        lock_text = " 🔒" if locked else ""
        level_text = f" Lv{level}" if level else ""
        lines.append(f"{inv_id}: {name} ({s}){level_text} 💰{p} | ❤️ {hp or '?'} ⚔️ {atk or '?'}{lock_text}")
        recent_total += p
    c.execute('''
        SELECT SUM(COALESCE(i.price, m.price))
        FROM inventory i LEFT JOIN marketplace m ON i.market_id = m.id
        WHERE i.user_id = ?
    ''', (uid,))
    full_total = c.fetchone()[0] or 0
    lines.append(f"Recent total: {recent_total} | Full inv: {full_total} iso$")
    bot.reply_to(msg, "\n".join(lines))
    conn.close()

@bot.message_handler(commands=['charges'])
def charges(msg):
    uid = msg.from_user.id
    get_or_create_user(uid, msg.from_user.username or 'unknown')
    conn = get_conn()
    now = time.time()
    notify_expired_effects(conn, uid, msg.chat.id, now)
    charges, last_charge_at = sync_charges(conn, uid, now)
    bot.reply_to(msg, charge_status_text(charges, last_charge_at, now))
    conn.close()

@bot.message_handler(commands=['items', 'item'])
def items(msg):
    uid = msg.from_user.id
    conn = get_conn()
    notify_expired_effects(conn, uid, msg.chat.id, time.time())
    c = conn.cursor()
    parts = msg.text.split()
    if len(parts) >= 2 and parts[1].lower() in ['delete', 'sell']:
        action = parts[1].lower()
        if len(parts) < 3:
            bot.reply_to(msg, f" /{parts[0].lstrip('/')} {action} <item_id> [qty]")
            conn.close()
            return
        item_id = resolve_item_id(conn, parts[2])
        if not item_id:
            bot.reply_to(msg, "Unknown item")
            conn.close()
            return
        qty = 1
        if len(parts) >= 4:
            try:
                qty = int(parts[3])
            except ValueError:
                bot.reply_to(msg, "Invalid qty")
                conn.close()
                return
        if qty <= 0:
            bot.reply_to(msg, "Qty must be positive")
            conn.close()
            return
        available = get_user_item_qty(conn, uid, item_id)
        if available < qty:
            bot.reply_to(msg, "Not enough items")
            conn.close()
            return
        if action == 'delete':
            consume_user_item(conn, uid, item_id, qty)
            bot.reply_to(msg, f"🗑️ Deleted {qty}x {item_id}")
            conn.close()
            return
        c.execute('SELECT price FROM shop_items WHERE item_id = ?', (item_id,))
        row = c.fetchone()
        if not row:
            bot.reply_to(msg, "Item cannot be sold")
            conn.close()
            return
        sell_price = max(1, int(row[0] * 0.5))
        consume_user_item(conn, uid, item_id, qty)
        update_user_money(uid, sell_price * qty)
        bot.reply_to(msg, f"✅ Sold {qty}x {item_id} for {sell_price * qty} iso$")
        conn.close()
        return
    c.execute('''
        SELECT ui.item_id, ui.qty, si.name, si.description
        FROM user_items ui LEFT JOIN shop_items si ON ui.item_id = si.item_id
        WHERE ui.user_id = ? AND ui.qty > 0
        ORDER BY ui.qty DESC
    ''', (uid,))
    rows = c.fetchall()
    if not rows:
        bot.reply_to(msg, "🧰 No items")
        conn.close()
        return
    short_map = get_item_short_map(conn)
    item_id_to_short = {v: k for k, v in short_map.items()}
    lines = ["🧰 Items:"]
    for item_id, qty, name, desc in rows:
        label = name or item_id
        short_id = item_id_to_short.get(item_id)
        short_text = f"[{short_id}] " if short_id else ""
        if desc:
            lines.append(f"{short_text}{item_id} x{qty} - {label} | {desc}")
        else:
            lines.append(f"{short_text}{item_id} x{qty} - {label}")
    lines.append("Use: /use <item_id> [@user]")
    bot.reply_to(msg, "\n".join(lines))
    conn.close()

@bot.message_handler(commands=['shop'])
def shop(msg):
    conn = get_conn()
    now = time.time()
    notify_expired_effects(conn, msg.from_user.id, msg.chat.id, now)
    rows, refreshed = get_shop_rotation(conn, now)
    if refreshed:
        send_silent_to_chat(msg.chat.id, "🛒 Shop refreshed")
    c = conn.cursor()
    short_map = get_item_short_map(conn)
    item_id_to_short = {v: k for k, v in short_map.items()}
    lines = ["🛒 Shop (rotates hourly):"]
    if rows and rows[0][2]:
        next_refresh = int(rows[0][2] + SHOP_REFRESH - now)
        if next_refresh < 0:
            next_refresh = 0
        m, s = divmod(next_refresh, 60)
        lines.append(f"Next refresh in {m}m {s:02d}s")
    for slot, item_id, refresh_at in rows:
        c.execute('SELECT name, price, description FROM shop_items WHERE item_id = ?', (item_id,))
        row = c.fetchone()
        if not row:
            continue
        name, price, desc = row
        short_id = item_id_to_short.get(item_id)
        short_text = f"[{short_id}] " if short_id else ""
        lines.append(f"{short_text}{item_id} - {name} 💰{price} | {desc}")
    bot.reply_to(msg, "\n".join(lines) if len(lines) > 1 else "Shop is empty")
    conn.close()

@bot.message_handler(commands=['fishing'])
def fishing(msg):
    parts = msg.text.split()
    if len(parts) < 2:
        bot.reply_to(msg, "Use: /fishing shop | /fishing buy <rod_id> | /fishing start <rod_id> <isopod_id> | /fishing inventory")
        return
    action = parts[1].lower()
    uid = msg.from_user.id
    conn = get_conn()
    now = time.time()
    notify_expired_effects(conn, uid, msg.chat.id, now)
    seed_fishing_rods(conn)
    ensure_fish_catalog(conn)
    c = conn.cursor()
    if action == 'shop':
        c.execute('SELECT rod_id, name, price, tier, bite_chance, save_bait_chance, multi_catch_max FROM fishing_rods ORDER BY tier')
        rows = c.fetchall()
        lines = ["🎣 Fishing Shop:"]
        for rod_id, name, price, tier, bite, save_bait, multi_max in rows:
            lines.append(f"{rod_id} - {name} 💰{price} | Tier {tier} | Bite {int(bite*100)}% | Save bait {int(save_bait*100)}% | Max catch {multi_max}")
        bot.reply_to(msg, "\n".join(lines))
        conn.close()
        return
    if action == 'buy':
        if len(parts) < 3:
            bot.reply_to(msg, " /fishing buy <rod_id>")
            conn.close()
            return
        rod_id = parts[2]
        c.execute('SELECT name, price FROM fishing_rods WHERE rod_id = ?', (rod_id,))
        row = c.fetchone()
        if not row:
            bot.reply_to(msg, "Unknown rod")
            conn.close()
            return
        name, price = row
        c.execute('SELECT money FROM users WHERE user_id = ?', (uid,))
        money = c.fetchone()[0]
        if money < price:
            bot.reply_to(msg, f"💸 Need {price} iso$")
            conn.close()
            return
        update_user_money(uid, -price)
        add_user_rod(conn, uid, rod_id, 1)
        bot.reply_to(msg, f"✅ Bought {name} for {price} iso$")
        conn.close()
        return
    if action == 'inventory':
        c.execute('''
            SELECT uf.fish_id, uf.qty, fc.name, fc.tier, fc.price
            FROM user_fish uf LEFT JOIN fish_catalog fc ON uf.fish_id = fc.id
            WHERE uf.user_id = ? AND uf.qty > 0
            ORDER BY uf.qty DESC
        ''', (uid,))
        rows = c.fetchall()
        if not rows:
            bot.reply_to(msg, "🐟 No fish")
            conn.close()
            return
        lines = ["🐟 Your Fish:"]
        for fish_id, qty, name, tier, price in rows:
            label = name or f"Fish {fish_id}"
            lines.append(f"{fish_id} x{qty} - {label} ({tier}) 💰{price}")
        bot.reply_to(msg, "\n".join(lines))
        conn.close()
        return
    if action == 'start':
        if len(parts) < 4:
            bot.reply_to(msg, " /fishing start <rod_id> <isopod_id>")
            conn.close()
            return
        rod_id = parts[2]
        try:
            bait_id = int(parts[3])
        except ValueError:
            bot.reply_to(msg, "Invalid isopod ID")
            conn.close()
            return
        c.execute('SELECT qty FROM user_rods WHERE user_id = ? AND rod_id = ?', (uid, rod_id))
        row = c.fetchone()
        if not row or row[0] <= 0:
            bot.reply_to(msg, "You do not own that rod")
            conn.close()
            return
        c.execute('SELECT name, price, tier, bite_chance, save_bait_chance, multi_catch_max, speed_sec, bonus_item_chance FROM fishing_rods WHERE rod_id = ?', (rod_id,))
        rod = c.fetchone()
        if not rod:
            bot.reply_to(msg, "Unknown rod")
            conn.close()
            return
        c.execute('SELECT id, locked FROM inventory WHERE id = ? AND user_id = ?', (bait_id, uid))
        bait = c.fetchone()
        if not bait:
            bot.reply_to(msg, "Bait isopod not found")
            conn.close()
            return
        if bait[1]:
            bot.reply_to(msg, "Unlock that isopod before using it as bait")
            conn.close()
            return
        name, price, tier, bite_chance, save_bait_chance, multi_catch_max, speed_sec, bonus_item_chance = rod
        bot.reply_to(msg, "🎣 Casting...")
        time.sleep(float(speed_sec))
        bait_saved = random.random() < float(save_bait_chance)
        bite = random.random() < float(bite_chance)
        if not bite:
            if not bait_saved:
                c.execute('DELETE FROM inventory WHERE id = ? AND user_id = ?', (bait_id, uid))
                conn.commit()
                bot.reply_to(msg, "No bites. Bait consumed.")
            else:
                bot.reply_to(msg, "No bites. Bait saved.")
            conn.close()
            return
        weights = [70, 20, 8, 2]
        if tier >= 2:
            weights = [60, 25, 12, 3]
        if tier >= 3:
            weights = [50, 28, 16, 6]
        tiers = ['common', 'rare', 'epic', 'legendary']
        fish_tier = random.choices(tiers, weights=weights)[0]
        c.execute('SELECT id, name, price, color FROM fish_catalog WHERE tier = ? ORDER BY RANDOM() LIMIT 1', (fish_tier,))
        fish = c.fetchone()
        if not fish:
            bot.reply_to(msg, "No fish available. Try again.")
            conn.close()
            return
        fish_id, fish_name, fish_price, fish_color = fish
        count = 1
        if multi_catch_max and multi_catch_max > 1:
            count = random.randint(1, int(multi_catch_max))
        add_user_fish(conn, uid, fish_id, count)
        if not bait_saved:
            c.execute('DELETE FROM inventory WHERE id = ? AND user_id = ?', (bait_id, uid))
        conn.commit()
        bonus_text = ""
        if random.random() < float(bonus_item_chance):
            item_id = random.choice(list(ITEM_DEFS.keys()))
            add_user_item(conn, uid, item_id, 1)
            bonus_text = f" + Bonus item: {ITEM_DEFS[item_id]['name']}"
        caption = f"🐟 Caught {count}x {fish_name} ({fish_tier}) 💰{fish_price} each.{bonus_text}"
        try:
            img_path = generate_isofish_image(fish_color or 'blue')
            with open(img_path, 'rb') as f:
                bot.send_photo(msg.chat.id, f, caption=caption)
            cleanup_temp()
        except Exception:
            bot.reply_to(msg, caption)
        conn.close()
        return
    bot.reply_to(msg, "Unknown fishing command")
    conn.close()

@bot.message_handler(commands=['buy'])
def buy(msg):
    parts = msg.text.split()
    if len(parts) < 2:
        bot.reply_to(msg, " /buy <item_id>")
        return
    conn = get_conn()
    item_id = resolve_item_id(conn, parts[1])
    if not item_id:
        bot.reply_to(msg, "Unknown item")
        conn.close()
        return
    uid = msg.from_user.id
    now = time.time()
    notify_expired_effects(conn, uid, msg.chat.id, now)
    rows, refreshed = get_shop_rotation(conn, now)
    if refreshed:
        send_silent_to_chat(msg.chat.id, "🛒 Shop refreshed")
    shop_ids = [r[1] for r in rows]
    if item_id not in shop_ids:
        bot.reply_to(msg, "Item not in current shop")
        conn.close()
        return
    c = conn.cursor()
    c.execute('SELECT name, price FROM shop_items WHERE item_id = ?', (item_id,))
    row = c.fetchone()
    if not row:
        bot.reply_to(msg, "Unknown item")
        conn.close()
        return
    name, price = row
    discount = get_effect(conn, uid, 'shop_discount', now)
    if isinstance(discount, dict):
        percent = int(discount.get('percent', 0))
        uses = int(discount.get('uses', 0))
        if percent > 0 and uses > 0:
            price = max(1, int(price * (100 - percent) / 100))
            uses -= 1
            if uses <= 0:
                consume_effect(conn, uid, 'shop_discount')
            else:
                set_effect(conn, uid, 'shop_discount', {'percent': percent, 'uses': uses})
    c.execute('SELECT money FROM users WHERE user_id = ?', (uid,))
    money = c.fetchone()[0]
    if money < price:
        bot.reply_to(msg, f"💸 Need {price} iso$")
        conn.close()
        return
    update_user_money(uid, -price)
    add_user_item(conn, uid, item_id, 1)
    bot.reply_to(msg, f"✅ Bought {name} for {price} iso$")
    conn.close()

@bot.message_handler(commands=['sell', 's', 'sellall', 'sall'])
def sell(msg):
    text = msg.text.split()
    if text and text[0] in ['/sellall', '/sall']:
        text = ['sell', 'all'] + text[1:]
    if len(text) < 2:
        bot.reply_to(msg, " /sell <ID>")
        return
    if text[1].lower() == 'all':
        rarity = text[2].lower() if len(text) > 2 else None
        valid = ['common', 'rare', 'epic', 'legendary']
        if rarity and rarity not in valid:
            bot.reply_to(msg, "Invalid rarity. Use common/rare/epic/legendary")
            return
        uid = msg.from_user.id
        conn = get_conn()
        c = conn.cursor()
        if rarity:
            c.execute('''
                SELECT i.id, COALESCE(i.price, m.price), LOWER(COALESCE(i.status, m.status))
                FROM inventory i LEFT JOIN marketplace m ON i.market_id = m.id
                WHERE i.user_id = ? AND LOWER(COALESCE(i.status, m.status)) = ? AND COALESCE(i.locked, 0) = 0
                  AND LOWER(COALESCE(i.color, '')) != 'rainbow'
            ''', (uid, rarity))
        else:
            c.execute('''
                SELECT i.id, COALESCE(i.price, m.price), LOWER(COALESCE(i.status, m.status))
                FROM inventory i LEFT JOIN marketplace m ON i.market_id = m.id
                WHERE i.user_id = ? AND COALESCE(i.locked, 0) = 0
                  AND LOWER(COALESCE(i.color, '')) != 'rainbow'
            ''', (uid,))
        rows = c.fetchall()
        if not rows:
            bot.reply_to(msg, "Nothing to sell")
            conn.close()
            return
        ids = [r[0] for r in rows]
        total = sum(r[1] or 0 for r in rows)
        c.execute(f"DELETE FROM inventory WHERE id IN ({','.join(['?']*len(ids))})", ids)
        conn.commit()
        update_user_money(uid, total)
        conn.close()
        bot.reply_to(msg, f"✅ Sold {len(ids)} isopods for {total} iso$")
        return
    try:
        inv_id = int(text[1])
    except ValueError:
        bot.reply_to(msg, "Invalid ID")
        return
    uid = msg.from_user.id
    conn = get_conn()
    c = conn.cursor()
    c.execute('''
        SELECT COALESCE(i.price, m.price), COALESCE(i.locked, 0), COALESCE(i.color, '')
        FROM inventory i LEFT JOIN marketplace m ON i.market_id = m.id
        WHERE i.id = ? AND i.user_id = ?
    ''', (inv_id, uid))
    row = c.fetchone()
    if row:
        price, locked, color = row
        if locked:
            bot.reply_to(msg, "🔒 That isopod is locked. Use /unlock <ID> first.")
            conn.close()
            return
        if str(color).lower() == 'rainbow':
            bot.reply_to(msg, "🌈 Legendary rainbow isopods cannot be sold.")
            conn.close()
            return
        price = price or 0
        c.execute('DELETE FROM inventory WHERE id = ?', (inv_id,))
        conn.commit()
        update_user_money(uid, price)
        bot.reply_to(msg, f"✅ Sold {price} iso$!")
    else:
        bot.reply_to(msg, "❌ Invalid/not yours")
    conn.close()

@bot.message_handler(commands=['lock', 'unlock'])
def lock_isopod(msg):
    parts = msg.text.split()
    if len(parts) < 2:
        bot.reply_to(msg, f" /{parts[0].lstrip('/')} <ID>")
        return
    try:
        inv_id = int(parts[1])
    except ValueError:
        bot.reply_to(msg, "Invalid ID")
        return
    uid = msg.from_user.id
    lock_value = 1 if parts[0].lower() == '/lock' else 0
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT id FROM inventory WHERE id = ? AND user_id = ?', (inv_id, uid))
    row = c.fetchone()
    if not row:
        bot.reply_to(msg, "❌ Invalid/not yours")
        conn.close()
        return
    c.execute('UPDATE inventory SET locked = ? WHERE id = ? AND user_id = ?', (lock_value, inv_id, uid))
    conn.commit()
    conn.close()
    if lock_value:
        bot.reply_to(msg, f"🔒 Locked isopod {inv_id}")
    else:
        bot.reply_to(msg, f"🔓 Unlocked isopod {inv_id}")

@bot.message_handler(commands=['breed'])
def breed_isopods(msg):
    parts = msg.text.split()
    if len(parts) < 3:
        bot.reply_to(msg, " /breed <id1> <id2>")
        return
    try:
        id1 = int(parts[1])
        id2 = int(parts[2])
    except ValueError:
        bot.reply_to(msg, "Invalid IDs")
        return
    if id1 == id2:
        bot.reply_to(msg, "Choose two different isopods")
        return
    uid = msg.from_user.id
    conn = get_conn()
    notify_expired_effects(conn, uid, msg.chat.id, time.time())
    if get_user_item_qty(conn, uid, 'fusion_pod') < 1 or get_user_item_qty(conn, uid, 'breeding_food') < 1:
        bot.reply_to(msg, "Need Fusion Pod + Breeding Food")
        conn.close()
        return
    c = conn.cursor()
    c.execute('''
        SELECT id, name, status, price, color, hp, attack, moves_json, locked
        FROM inventory WHERE user_id = ? AND id IN (?, ?)
    ''', (uid, id1, id2))
    rows = c.fetchall()
    if len(rows) != 2:
        bot.reply_to(msg, "Isopod not found")
        conn.close()
        return
    data = {r[0]: r for r in rows}
    r1 = data[id1]
    r2 = data[id2]
    if r1[8] or r2[8]:
        bot.reply_to(msg, "Unlock isopods before breeding")
        conn.close()
        return
    status1 = (r1[2] or 'common').lower()
    status2 = (r2[2] or 'common').lower()
    tier_map = {'common': 'rare', 'rare': 'epic', 'epic': 'legendary'}
    if status1 != status2 or status1 not in tier_map:
        bot.reply_to(msg, "Breeding requires two of the same tier (common/rare/epic)")
        conn.close()
        return
    if not consume_user_item(conn, uid, 'fusion_pod', 1) or not consume_user_item(conn, uid, 'breeding_food', 1):
        bot.reply_to(msg, "Need Fusion Pod + Breeding Food")
        conn.close()
        return
    new_status = tier_map[status1]
    name1 = r1[1] or 'Isopod'
    name2 = r2[1] or 'Isopod'
    price1 = r1[3] or 0
    price2 = r2[3] or 0
    hp1 = r1[5] or 10
    hp2 = r2[5] or 10
    atk1 = r1[6] or 5
    atk2 = r2[6] or 5
    color = r1[4] or r2[4] or 'unknown'
    new_price = int((price1 + price2) / 2)
    new_hp = int((hp1 + hp2) / 2) + 5
    new_atk = int((atk1 + atk2) / 2) + 2
    moves = []
    for mv_json in [r1[7], r2[7]]:
        try:
            moves.extend(json.loads(mv_json) if mv_json else [])
        except Exception:
            continue
    unique = []
    seen = set()
    for mv in moves:
        name = mv.get('name')
        if not name or name in seen:
            continue
        seen.add(name)
        unique.append(mv)
    if not unique:
        unique = [{'name': 'Tackle', 'power': new_atk}]
    if len(unique) > 4:
        unique = random.sample(unique, k=4)
    new_name = f"Fusion {name1} + {name2}"
    c.execute('DELETE FROM inventory WHERE user_id = ? AND id IN (?, ?)', (uid, id1, id2))
    c.execute('''
        INSERT INTO inventory (user_id, market_id, name, status, price, color, hp, attack, moves_json, level, xp, locked)
        VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (uid, new_name, new_status, new_price, color, new_hp, new_atk, json.dumps(unique), 1, 0, 0))
    conn.commit()
    conn.close()
    bot.reply_to(msg, f"🧬 Bred {new_name} ({new_status})")

@bot.message_handler(commands=['rainbowfusion'])
def rainbow_fusion(msg):
    parts = msg.text.split()
    if len(parts) < 2:
        bot.reply_to(msg, " /rainbowfusion <id1> <id2> ...")
        return
    try:
        ids = [int(p) for p in parts[1:]]
    except ValueError:
        bot.reply_to(msg, "Invalid IDs")
        return
    uid = msg.from_user.id
    conn = get_conn()
    notify_expired_effects(conn, uid, msg.chat.id, time.time())
    colors, _ = load_lists()
    if len(ids) != len(colors):
        bot.reply_to(msg, f"Need {len(colors)} legendary isopods (one of each color)")
        conn.close()
        return
    if get_user_item_qty(conn, uid, 'fusion_pod') < 1 or get_user_item_qty(conn, uid, 'breeding_food') < 1:
        bot.reply_to(msg, "Need Fusion Pod + Breeding Food")
        conn.close()
        return
    c = conn.cursor()
    q = f"SELECT id, name, status, price, color, hp, attack, moves_json, locked FROM inventory WHERE user_id = ? AND id IN ({','.join(['?']*len(ids))})"
    c.execute(q, [uid] + ids)
    rows = c.fetchall()
    if len(rows) != len(ids):
        bot.reply_to(msg, "Isopod not found")
        conn.close()
        return
    if any(r[8] for r in rows):
        bot.reply_to(msg, "Unlock isopods before fusing")
        conn.close()
        return
    inv_colors = [str(r[4]).lower() for r in rows]
    if any((r[2] or '').lower() != 'legendary' for r in rows):
        bot.reply_to(msg, "All entries must be legendary")
        conn.close()
        return
    if set(inv_colors) != set(colors):
        bot.reply_to(msg, "Need one of each legendary color")
        conn.close()
        return
    if not consume_user_item(conn, uid, 'fusion_pod', 1) or not consume_user_item(conn, uid, 'breeding_food', 1):
        bot.reply_to(msg, "Need Fusion Pod + Breeding Food")
        conn.close()
        return
    prices = [r[3] or 0 for r in rows]
    hps = [r[5] or 10 for r in rows]
    atks = [r[6] or 5 for r in rows]
    new_price = int(sum(prices) / len(prices)) + 500
    new_hp = int(sum(hps) / len(hps)) + 20
    new_atk = int(sum(atks) / len(atks)) + 5
    moves = []
    for mv_json in [r[7] for r in rows]:
        try:
            moves.extend(json.loads(mv_json) if mv_json else [])
        except Exception:
            continue
    unique = []
    seen = set()
    for mv in moves:
        name = mv.get('name')
        if not name or name in seen:
            continue
        seen.add(name)
        unique.append(mv)
    if not unique:
        unique = [{'name': 'Tackle', 'power': new_atk}]
    if len(unique) > 4:
        unique = random.sample(unique, k=4)
    c.execute(f"DELETE FROM inventory WHERE user_id = ? AND id IN ({','.join(['?']*len(ids))})", [uid] + ids)
    c.execute('''
        INSERT INTO inventory (user_id, market_id, name, status, price, color, hp, attack, moves_json, level, xp, locked)
        VALUES (?, NULL, ?, 'legendary', ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (uid, 'Legendary Rainbow Isopod', new_price, 'rainbow', new_hp, new_atk, json.dumps(unique), 1, 0, 0))
    conn.commit()
    conn.close()
    bot.reply_to(msg, "🌈 Rainbow fusion complete!")

@bot.message_handler(commands=['market'])
def market(msg):
    logger.info(f"Market request by {msg.from_user.id}")
    conn = get_conn()
    now = time.time()
    notify_expired_effects(conn, msg.from_user.id, msg.chat.id, now)
    if needs_regen():
        generate_marketplace()
        send_silent_to_chat(msg.chat.id, "📈 Market refreshed")
    c = conn.cursor()
    c.execute('SELECT full_name, price, status FROM marketplace ORDER BY price DESC LIMIT 10')
    high = c.fetchall()
    c.execute('SELECT full_name, price, status FROM marketplace ORDER BY price ASC LIMIT 10')
    low = c.fetchall()
    c.execute('SELECT value FROM global_state WHERE key = ?', ('last_regen',))
    last_regen_row = c.fetchone()
    conn.close()
    high_lines = [f"{name} {p}$" for name, p, s in high]
    low_lines = [f"{name} {p}$" for name, p, s in low]
    refresh_text = ""
    if last_regen_row and last_regen_row[0]:
        next_refresh = int(last_regen_row[0] + MARKET_REFRESH - now)
        if next_refresh < 0:
            next_refresh = 0
        m, s = divmod(next_refresh, 60)
        refresh_text = f"\n\nNext refresh in {m}m {s:02d}s"
    text = "📈 High:\n" + "\n".join(high_lines) + "\n\n📉 Low:\n" + "\n".join(low_lines) + refresh_text
    bot.reply_to(msg, text)

@bot.message_handler(commands=['auction'])
def auction(msg):
    parts = msg.text.split()
    if len(parts) < 2:
        bot.reply_to(msg, "Use: /auction list | /auction sell <isopod_id> <price> | /auction buy <auction_id> | /auction cancel <id|all>")
        return
    action = parts[1].lower()
    uid = msg.from_user.id
    conn = get_conn()
    notify_expired_effects(conn, uid, msg.chat.id, time.time())
    c = conn.cursor()
    if action == 'list':
        c.execute('''
            SELECT a.auction_id, a.name, a.status, a.price, u.username
            FROM auctions a LEFT JOIN users u ON a.seller_id = u.user_id
            WHERE a.state = 'active'
            ORDER BY a.created_at DESC LIMIT 20
        ''')
        rows = c.fetchall()
        if not rows:
            bot.reply_to(msg, "No active auctions")
            conn.close()
            return
        lines = ["🏷️ Auctions:"]
        for auction_id, name, status, price, username in rows:
            seller = username or 'unknown'
            lines.append(f"{auction_id}: {name} ({status}) 💰{price} | @{seller}")
        bot.reply_to(msg, "\n".join(lines))
        conn.close()
        return
    if action == 'sell':
        if len(parts) < 4:
            bot.reply_to(msg, " /auction sell <isopod_id> <price>")
            conn.close()
            return
        try:
            inv_id = int(parts[2])
            price = int(parts[3])
        except ValueError:
            bot.reply_to(msg, "Invalid ID or price")
            conn.close()
            return
        if price <= 0:
            bot.reply_to(msg, "Price must be positive")
            conn.close()
            return
        c.execute('''
            SELECT name, status, color, hp, attack, moves_json, level, xp, locked
            FROM inventory WHERE id = ? AND user_id = ?
        ''', (inv_id, uid))
        row = c.fetchone()
        if not row:
            bot.reply_to(msg, "Isopod not found")
            conn.close()
            return
        name, status, color, hp, attack, moves_json, level, xp, locked = row
        if locked:
            bot.reply_to(msg, "Unlock that isopod before auctioning")
            conn.close()
            return
        if str(color).lower() == 'rainbow':
            bot.reply_to(msg, "🌈 Legendary rainbow isopods cannot be auctioned")
            conn.close()
            return
        c.execute('DELETE FROM inventory WHERE id = ? AND user_id = ?', (inv_id, uid))
        c.execute('''
            INSERT INTO auctions (seller_id, buyer_id, name, status, price, color, hp, attack, moves_json, level, xp, created_at, state)
            VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        ''', (uid, name, status, price, color, hp, attack, moves_json, level or 1, xp or 0, time.time()))
        conn.commit()
        bot.reply_to(msg, "✅ Auction listed")
        conn.close()
        return
    if action == 'buy':
        if len(parts) < 3:
            bot.reply_to(msg, " /auction buy <auction_id>")
            conn.close()
            return
        try:
            auction_id = int(parts[2])
        except ValueError:
            bot.reply_to(msg, "Invalid auction ID")
            conn.close()
            return
        c.execute('''
            SELECT auction_id, seller_id, name, status, price, color, hp, attack, moves_json, level, xp
            FROM auctions WHERE auction_id = ? AND state = 'active'
        ''', (auction_id,))
        row = c.fetchone()
        if not row:
            bot.reply_to(msg, "Auction not found")
            conn.close()
            return
        _, seller_id, name, status, price, color, hp, attack, moves_json, level, xp = row
        if seller_id == uid:
            bot.reply_to(msg, "You cannot buy your own auction")
            conn.close()
            return
        c.execute('SELECT money FROM users WHERE user_id = ?', (uid,))
        money = c.fetchone()[0]
        if money < price:
            bot.reply_to(msg, f"💸 Need {price} iso$")
            conn.close()
            return
        update_user_money(uid, -price)
        update_user_money(seller_id, price)
        c.execute('''
            INSERT INTO inventory (user_id, market_id, name, status, price, color, hp, attack, moves_json, level, xp, locked)
            VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (uid, name, status, price, color, hp, attack, moves_json, level or 1, xp or 0, 0))
        c.execute('UPDATE auctions SET buyer_id = ?, state = ? WHERE auction_id = ?', (uid, 'sold', auction_id))
        conn.commit()
        bot.reply_to(msg, "✅ Auction purchased")
        conn.close()
        return
    if action == 'cancel':
        if len(parts) < 3:
            bot.reply_to(msg, " /auction cancel <id|all>")
            conn.close()
            return
        if parts[2].lower() == 'all':
            c.execute('''
                SELECT auction_id, name, status, price, color, hp, attack, moves_json, level, xp
                FROM auctions WHERE seller_id = ? AND state = 'active'
            ''', (uid,))
            rows = c.fetchall()
            if not rows:
                bot.reply_to(msg, "No active auctions")
                conn.close()
                return
            for auction_id, name, status, price, color, hp, attack, moves_json, level, xp in rows:
                c.execute('''
                    INSERT INTO inventory (user_id, market_id, name, status, price, color, hp, attack, moves_json, level, xp, locked)
                    VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (uid, name, status, price, color, hp, attack, moves_json, level or 1, xp or 0, 0))
                c.execute('UPDATE auctions SET state = ? WHERE auction_id = ?', ('cancelled', auction_id))
            conn.commit()
            bot.reply_to(msg, "✅ Cancelled all your auctions")
            conn.close()
            return
        try:
            auction_id = int(parts[2])
        except ValueError:
            bot.reply_to(msg, "Invalid auction ID")
            conn.close()
            return
        c.execute('''
            SELECT name, status, price, color, hp, attack, moves_json, level, xp
            FROM auctions WHERE auction_id = ? AND seller_id = ? AND state = 'active'
        ''', (auction_id, uid))
        row = c.fetchone()
        if not row:
            bot.reply_to(msg, "Auction not found")
            conn.close()
            return
        name, status, price, color, hp, attack, moves_json, level, xp = row
        c.execute('''
            INSERT INTO inventory (user_id, market_id, name, status, price, color, hp, attack, moves_json, level, xp, locked)
            VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (uid, name, status, price, color, hp, attack, moves_json, level or 1, xp or 0, 0))
        c.execute('UPDATE auctions SET state = ? WHERE auction_id = ?', ('cancelled', auction_id))
        conn.commit()
        bot.reply_to(msg, "✅ Auction cancelled")
        conn.close()
        return
    bot.reply_to(msg, "Unknown auction command")
    conn.close()

@bot.message_handler(commands=['top'])
def top(msg):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT username, money FROM users ORDER BY money DESC LIMIT 10')
    rows = c.fetchall()
    conn.close()
    lines = [f"{i}. {u}: {m}$" for i, (u, m) in enumerate(rows, 1)]
    text = "💰 Richest:\n" + "\n".join(lines) if lines else "None"
    bot.reply_to(msg, text)

@bot.message_handler(commands=['legendary'])
def legendary(msg):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT username FROM users WHERE legendary = 1')
    rows = c.fetchall()
    conn.close()
    lines = [f"• {r[0]}" for r in rows]
    text = "🏆 Legendaries:\n" + "\n".join(lines) if lines else "None"
    bot.reply_to(msg, text)

@bot.message_handler(commands=['use'])
def use_item(msg):
    parts = msg.text.split()
    if len(parts) < 2:
        bot.reply_to(msg, " /use <item_id> [@user]")
        return
    target_username = None
    target_isopod_id = None
    for p in parts[2:]:
        if p.startswith('@'):
            target_username = p[1:]
            break
        if p.isdigit():
            target_isopod_id = int(p)
            break
    uid = msg.from_user.id
    now = time.time()
    conn = get_conn()
    notify_expired_effects(conn, uid, msg.chat.id, now)
    item_id = resolve_item_id(conn, parts[1])
    if not item_id:
        bot.reply_to(msg, "Unknown item")
        conn.close()
        return
    c = conn.cursor()
    c.execute('SELECT qty FROM user_items WHERE user_id = ? AND item_id = ?', (uid, item_id))
    row = c.fetchone()
    if not row or row[0] <= 0:
        bot.reply_to(msg, "No item")
        conn.close()
        return
    if item_id in ITEM_DEFS:
        effect_type = ITEM_DEFS[item_id]['effect_type']
        effect_value = ITEM_DEFS[item_id]['effect_value']
    else:
        c.execute('SELECT effect_type, effect_value FROM shop_items WHERE item_id = ?', (item_id,))
        row = c.fetchone()
        if not row:
            bot.reply_to(msg, "Unknown item")
            conn.close()
            return
        effect_type, effect_value = row
    res = None
    if effect_type == 'add_charge':
        charges, last_charge_at = sync_charges(conn, uid, now)
        charges = min(OVERCHARGE_MAX, charges + int(effect_value))
        update_user_charges(conn, uid, charges)
        res = f"⚡ +{effect_value} charge(s)"
    elif effect_type == 'guarantee_rare':
        set_effect(conn, uid, 'guarantee_rare', '1')
        res = "🍀 Next roll guaranteed Rare+"
    elif effect_type == 'guarantee_legendary':
        set_effect(conn, uid, 'guarantee_legendary', '1')
        res = "🏆 Next roll guaranteed Legendary"
    elif effect_type == 'double_roll':
        charges, last_charge_at = sync_charges(conn, uid, now)
        new_charges = min(OVERCHARGE_MAX, charges * 2)
        update_user_charges(conn, uid, new_charges)
        res = f"🎲 Charges doubled to {new_charges}/{MAX_CHARGES}"
    elif effect_type == 'regen_market':
        generate_marketplace()
        res = "🔄 Market regenerated"
        send_silent_to_chat(msg.chat.id, "📈 Market refreshed")
    elif effect_type == 'item_drop_boost':
        set_effect(conn, uid, 'item_drop_boost', effect_value, duration=1800)
        res = "🧲 Item drops boosted for 30 minutes"
    elif effect_type == 'shop_discount':
        set_effect(conn, uid, 'shop_discount', {'percent': int(effect_value), 'uses': 3})
        res = "🏷️ 10% discount for next 3 shop buys"
    elif effect_type == 'safety_net':
        set_effect(conn, uid, 'safety_net', '1')
        res = "🛡️ Safety Net armed"
    elif effect_type == 'add_xp':
        if not target_isopod_id:
            bot.reply_to(msg, "Use: /use iso_candy <isopod_id>")
            conn.close()
            return
        c.execute('SELECT level, xp, hp, attack FROM inventory WHERE id = ? AND user_id = ?', (target_isopod_id, uid))
        row = c.fetchone()
        if not row:
            bot.reply_to(msg, "Isopod not found")
            conn.close()
            return
        level, xp, hp, attack = row
        level = level or 1
        xp = xp or 0
        hp = hp or 10
        attack = attack or 5
        xp += int(effect_value)
        levels_gained = 0
        while xp >= XP_PER_LEVEL:
            xp -= XP_PER_LEVEL
            level += 1
            hp += LEVEL_HP_BONUS
            attack += LEVEL_ATK_BONUS
            levels_gained += 1
        c.execute('UPDATE inventory SET level = ?, xp = ?, hp = ?, attack = ? WHERE id = ? AND user_id = ?',
                  (level, xp, hp, attack, target_isopod_id, uid))
        conn.commit()
        if levels_gained:
            res = f"🍬 {levels_gained} level(s) gained! Lv{level} ❤️ {hp} ⚔️ {attack}"
        else:
            res = f"🍬 XP +{effect_value}. Lv{level} ({xp}/{XP_PER_LEVEL})"
    elif effect_type == 'spy_drone':
        set_effect(conn, uid, 'battle_defense_boost', '0.2')
        res = "🛰️ Defense boost applied to your next battle"
    elif effect_type == 'race_boost':
        set_effect(conn, uid, 'race_speed_boost', effect_value)
        res = "🏁 Race speed boost applied"
    elif effect_type in ['bite_bug', 'sticky_goo', 'fake_coupon', 'swap_token']:
        if not target_username:
            bot.reply_to(msg, "Target required: /use <item_id> @user")
            conn.close()
            return
        target_id = get_user_id_by_username(conn, target_username)
        if not target_id:
            bot.reply_to(msg, "Target not found")
            conn.close()
            return
        if effect_type == 'bite_bug':
            c.execute('SELECT money FROM users WHERE user_id = ?', (target_id,))
            target_money = c.fetchone()[0]
            percent = random.randint(5, 15)
            steal = max(5, int(target_money * percent / 100))
            steal = min(100, steal)
            steal = min(steal, target_money)
            update_user_money(target_id, -steal)
            update_user_money(uid, steal)
            res = f"🪲 Stole {steal} iso$ from @{target_username}"
        elif effect_type == 'sticky_goo':
            t_charges, t_last = sync_charges(conn, target_id, now)
            if t_charges <= 0:
                res = f"🧪 @{target_username} has no charges"
            else:
                penalty = COOLDOWN
                new_last = max(t_last, now) + penalty
                update_user_charges(conn, target_id, t_charges - 1, new_last)
                res = f"🧪 Removed 1 charge and delayed @{target_username}'s next charge"
        elif effect_type == 'fake_coupon':
            t_charges, t_last = sync_charges(conn, target_id, now)
            if t_charges <= 0:
                res = f"🎟️ @{target_username} has no charges"
            else:
                update_user_charges(conn, target_id, t_charges - 1)
                res = f"🎟️ @{target_username} lost 1 charge (no roll)"
        elif effect_type == 'swap_token':
            c.execute('SELECT id FROM inventory WHERE user_id = ? ORDER BY RANDOM() LIMIT 1', (uid,))
            user_inv = c.fetchone()
            c.execute('SELECT id FROM inventory WHERE user_id = ? ORDER BY RANDOM() LIMIT 1', (target_id,))
            target_inv = c.fetchone()
            if not user_inv or not target_inv:
                res = "Swap failed (one side has no isopods)"
            else:
                c.execute('UPDATE inventory SET user_id = ? WHERE id = ?', (target_id, user_inv[0]))
                c.execute('UPDATE inventory SET user_id = ? WHERE id = ?', (uid, target_inv[0]))
                conn.commit()
                res = f"🔁 Swapped a random isopod with @{target_username}"
    elif effect_type == 'market_sabotage':
        generate_marketplace()
        c.execute('UPDATE marketplace SET price = MAX(1, CAST(price * 0.8 AS INT))')
        conn.commit()
        res = "💥 Market sabotaged (prices lowered)"
        send_silent_to_chat(msg.chat.id, "📈 Market refreshed")
    else:
        res = "Unknown item"
    if not res:
        res = "Done"
    c.execute('UPDATE user_items SET qty = qty - 1 WHERE user_id = ? AND item_id = ?', (uid, item_id))
    c.execute('DELETE FROM user_items WHERE user_id = ? AND item_id = ? AND qty <= 0', (uid, item_id))
    conn.commit()
    conn.close()
    bot.reply_to(msg, res)

@bot.message_handler(commands=['broadcast'])
def broadcast(msg):
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(msg, " /broadcast <password> <message>")
        return
    password = parts[1]
    message = parts[2]
    try:
        stored = open(BROADCAST_PASSWORD_FILE).read().strip()
    except Exception:
        bot.reply_to(msg, "Broadcast password file missing")
        return
    if password != stored:
        bot.reply_to(msg, "Wrong password")
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT user_id FROM users')
    user_ids = [r[0] for r in c.fetchall()]
    conn.close()
    sent = send_to_users(user_ids, f"📣 Broadcast: {message}")
    bot.reply_to(msg, f"Broadcast sent to {sent} users")

@bot.message_handler(commands=['battle'])
def battle(msg):
    if msg.chat.type == 'private':
        bot.reply_to(msg, "Battles only work in group chats")
        return
    parts = msg.text.split()
    if len(parts) < 3:
        bot.reply_to(msg, " /battle @user <isopod_id>")
        return
    target_username = parts[1].lstrip('@')
    try:
        inv_id = int(parts[2])
    except ValueError:
        bot.reply_to(msg, "Invalid isopod ID")
        return
    challenger_id = msg.from_user.id
    conn = get_conn()
    target_id = get_user_id_by_username(conn, target_username)
    if not target_id:
        bot.reply_to(msg, "Target not found")
        conn.close()
        return
    isopod = get_isopod_record(conn, inv_id, challenger_id)
    if not isopod:
        bot.reply_to(msg, "Isopod not found")
        conn.close()
        return
    c = conn.cursor()
    c.execute('''
        INSERT INTO pending_battles (challenger_id, target_id, challenger_inv_id, chat_id, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
    ''', (challenger_id, target_id, inv_id, msg.chat.id, time.time()))
    conn.commit()
    inv_list = format_inventory_list(conn, target_id, limit=10)
    conn.close()
    bot.reply_to(msg, f"⚔️ Challenge sent to @{target_username}")
    send_to_chat(msg.chat.id, f"⚔️ @{target_username}, you were challenged by @{msg.from_user.username or 'unknown'}\nYour inventory:\n{inv_list}\nUse /accept <isopod_id> or /decline")

@bot.message_handler(commands=['race'])
def race(msg):
    if msg.chat.type == 'private':
        bot.reply_to(msg, "Races only work in group chats")
        return
    parts = msg.text.split()
    if len(parts) < 4:
        bot.reply_to(msg, " /race @user <isopod_id> <bet>")
        return
    target_username = parts[1].lstrip('@')
    try:
        inv_id = int(parts[2])
        bet = int(parts[3])
    except ValueError:
        bot.reply_to(msg, "Invalid isopod ID or bet")
        return
    if bet <= 0:
        bot.reply_to(msg, "Bet must be positive")
        return
    challenger_id = msg.from_user.id
    conn = get_conn()
    target_id = get_user_id_by_username(conn, target_username)
    if not target_id:
        bot.reply_to(msg, "Target not found")
        conn.close()
        return
    c = conn.cursor()
    c.execute('SELECT money FROM users WHERE user_id = ?', (challenger_id,))
    money = c.fetchone()[0]
    if money < bet:
        bot.reply_to(msg, f"💸 Need {bet} iso$ to race")
        conn.close()
        return
    isopod = get_isopod_record(conn, inv_id, challenger_id)
    if not isopod:
        bot.reply_to(msg, "Isopod not found")
        conn.close()
        return
    c.execute('''
        INSERT INTO pending_races (challenger_id, target_id, challenger_inv_id, chat_id, bet, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
    ''', (challenger_id, target_id, inv_id, msg.chat.id, bet, time.time()))
    conn.commit()
    inv_list = format_inventory_list(conn, target_id, limit=10)
    conn.close()
    bot.reply_to(msg, f"🏁 Race challenge sent to @{target_username}")
    send_to_chat(msg.chat.id, f"🏁 @{target_username}, you were challenged by @{msg.from_user.username or 'unknown'} for {bet} iso$\nYour inventory:\n{inv_list}\nUse /raceaccept <isopod_id> or /racedecline")

@bot.message_handler(commands=['accept'])
def accept(msg):
    if msg.chat.type == 'private':
        bot.reply_to(msg, "Accept battles in the original group chat")
        return
    parts = msg.text.split()
    if len(parts) < 2:
        bot.reply_to(msg, " /accept <isopod_id>")
        return
    try:
        target_inv_id = int(parts[1])
    except ValueError:
        bot.reply_to(msg, "Invalid isopod ID")
        return
    target_id = msg.from_user.id
    conn = get_conn()
    c = conn.cursor()
    c.execute('''
        SELECT battle_id, challenger_id, challenger_inv_id, chat_id
        FROM pending_battles
        WHERE target_id = ? AND status = 'pending'
        ORDER BY created_at DESC LIMIT 1
    ''', (target_id,))
    row = c.fetchone()
    if not row:
        bot.reply_to(msg, "No pending battle")
        conn.close()
        return
    battle_id, challenger_id, challenger_inv_id, chat_id = row
    if chat_id and chat_id != msg.chat.id:
        bot.reply_to(msg, "Accept the battle in the original chat")
        conn.close()
        return
    c.execute('UPDATE pending_battles SET target_inv_id = ?, status = ? WHERE battle_id = ?', (target_inv_id, 'accepted', battle_id))
    conn.commit()
    ok, result = run_battle(conn, challenger_id, target_id, challenger_inv_id, target_inv_id, chat_id or msg.chat.id)
    c.execute('UPDATE pending_battles SET status = ? WHERE battle_id = ?', ('completed' if ok else 'failed', battle_id))
    conn.commit()
    conn.close()
    if not ok:
        bot.reply_to(msg, result)

@bot.message_handler(commands=['decline'])
def decline(msg):
    if msg.chat.type == 'private':
        bot.reply_to(msg, "Decline battles in the original group chat")
        return
    target_id = msg.from_user.id
    conn = get_conn()
    c = conn.cursor()
    c.execute('''
        SELECT battle_id, challenger_id, chat_id
        FROM pending_battles
        WHERE target_id = ? AND status = 'pending'
        ORDER BY created_at DESC LIMIT 1
    ''', (target_id,))
    row = c.fetchone()
    if not row:
        bot.reply_to(msg, "No pending battle")
        conn.close()
        return
    battle_id, challenger_id, chat_id = row
    if chat_id and chat_id != msg.chat.id:
        bot.reply_to(msg, "Decline the battle in the original chat")
        conn.close()
        return
    c.execute('UPDATE pending_battles SET status = ? WHERE battle_id = ?', ('declined', battle_id))
    conn.commit()
    conn.close()
    bot.reply_to(msg, "Declined")
    send_to_chat(msg.chat.id, f"@{msg.from_user.username or 'unknown'} declined the battle")

@bot.message_handler(commands=['raceaccept'])
def race_accept(msg):
    if msg.chat.type == 'private':
        bot.reply_to(msg, "Accept races in the original group chat")
        return
    parts = msg.text.split()
    if len(parts) < 2:
        bot.reply_to(msg, " /raceaccept <isopod_id>")
        return
    try:
        target_inv_id = int(parts[1])
    except ValueError:
        bot.reply_to(msg, "Invalid isopod ID")
        return
    target_id = msg.from_user.id
    conn = get_conn()
    c = conn.cursor()
    c.execute('''
        SELECT race_id, challenger_id, challenger_inv_id, chat_id, bet
        FROM pending_races
        WHERE target_id = ? AND status = 'pending'
        ORDER BY created_at DESC LIMIT 1
    ''', (target_id,))
    row = c.fetchone()
    if not row:
        bot.reply_to(msg, "No pending race")
        conn.close()
        return
    race_id, challenger_id, challenger_inv_id, chat_id, bet = row
    if chat_id and chat_id != msg.chat.id:
        bot.reply_to(msg, "Accept the race in the original chat")
        conn.close()
        return
    c.execute('SELECT money FROM users WHERE user_id = ?', (target_id,))
    money = c.fetchone()[0]
    if money < bet:
        bot.reply_to(msg, f"💸 Need {bet} iso$ to accept")
        c.execute('UPDATE pending_races SET status = ? WHERE race_id = ?', ('failed', race_id))
        conn.commit()
        conn.close()
        return
    c.execute('UPDATE pending_races SET target_inv_id = ?, status = ? WHERE race_id = ?', (target_inv_id, 'accepted', race_id))
    conn.commit()
    ok, result = run_race(conn, challenger_id, target_id, challenger_inv_id, target_inv_id, chat_id or msg.chat.id, bet)
    c.execute('UPDATE pending_races SET status = ? WHERE race_id = ?', ('completed' if ok else 'failed', race_id))
    conn.commit()
    conn.close()
    if not ok:
        bot.reply_to(msg, result)

@bot.message_handler(commands=['racedecline'])
def race_decline(msg):
    if msg.chat.type == 'private':
        bot.reply_to(msg, "Decline races in the original group chat")
        return
    target_id = msg.from_user.id
    conn = get_conn()
    c = conn.cursor()
    c.execute('''
        SELECT race_id, challenger_id, chat_id
        FROM pending_races
        WHERE target_id = ? AND status = 'pending'
        ORDER BY created_at DESC LIMIT 1
    ''', (target_id,))
    row = c.fetchone()
    if not row:
        bot.reply_to(msg, "No pending race")
        conn.close()
        return
    race_id, challenger_id, chat_id = row
    if chat_id and chat_id != msg.chat.id:
        bot.reply_to(msg, "Decline the race in the original chat")
        conn.close()
        return
    c.execute('UPDATE pending_races SET status = ? WHERE race_id = ?', ('declined', race_id))
    conn.commit()
    conn.close()
    bot.reply_to(msg, "Declined")
    send_to_chat(msg.chat.id, f"@{msg.from_user.username or 'unknown'} declined the race")

print("Bot running...")
bot.infinity_polling()
