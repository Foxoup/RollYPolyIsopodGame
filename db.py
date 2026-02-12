import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

DB_PATH = 'isopods.db'

# ---------------------------------------------------------------------------
# Database schema & helpers
# This module owns the SQLite schema and tiny helper functions used across
# the bot. The SQL below creates tables and indexes. it's the single source
# of truth for the data layout.
#
# WARNING: The SQL here is magical and ancient. Actually I have
# no idea what this one does, it was suggested by AI, and apparently changing
# this breaks the bot. 
# If you tinker, back up the DB first.
# ---------------------------------------------------------------------------

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    # OK database time. The following block creates all tables if missing.
    # If you squint, it's just a bunch of CREATE TABLE statements. If you
    # touch them, expect surprises. Migrations are not sophisticated here.
    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            money INTEGER DEFAULT 0,
            legendary INTEGER DEFAULT 0,
            last_roll REAL DEFAULT 0,
            roll_charges INTEGER DEFAULT 1,
            last_charge_at REAL DEFAULT 0
        )
    ''')
    # Inventory
    c.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            market_id INTEGER,
            acquired_at REAL DEFAULT (strftime('%s','now')),
            name TEXT,
            status TEXT,
            price INTEGER,
            color TEXT,
            hp INTEGER,
            attack INTEGER,
            moves_json TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(market_id) REFERENCES marketplace(id)
        )
    ''')
    # Marketplace
    c.execute('''
        CREATE TABLE IF NOT EXISTS marketplace (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            color TEXT,
            word TEXT,
            full_name TEXT UNIQUE,
            status TEXT,
            price INTEGER
        )
    ''')
    # Items
    c.execute('''
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_type TEXT,
            quantity INTEGER DEFAULT 1,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_items (
            user_id INTEGER,
            item_id TEXT,
            qty INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, item_id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS shop_items (
            item_id TEXT PRIMARY KEY,
            name TEXT,
            price INTEGER,
            effect_type TEXT,
            effect_value TEXT,
            description TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS shop_rotation (
            slot INTEGER PRIMARY KEY,
            item_id TEXT,
            refresh_at REAL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_effects (
            user_id INTEGER,
            effect_type TEXT,
            effect_value TEXT,
            expires_at REAL,
            PRIMARY KEY(user_id, effect_type)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS isopod_stats (
            market_id INTEGER PRIMARY KEY,
            hp INTEGER,
            attack INTEGER,
            moves_json TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS pending_battles (
            battle_id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenger_id INTEGER,
            target_id INTEGER,
            challenger_inv_id INTEGER,
            target_inv_id INTEGER,
            chat_id INTEGER,
            status TEXT,
            created_at REAL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS fish_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            color TEXT,
            word TEXT,
            name TEXT,
            tier TEXT,
            price INTEGER
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS fishing_rods (
            rod_id TEXT PRIMARY KEY,
            name TEXT,
            price INTEGER,
            tier INTEGER,
            bite_chance REAL,
            save_bait_chance REAL,
            multi_catch_max INTEGER,
            speed_sec REAL,
            bonus_item_chance REAL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_rods (
            user_id INTEGER,
            rod_id TEXT,
            qty INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, rod_id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_fish (
            user_id INTEGER,
            fish_id INTEGER,
            qty INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, fish_id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS auctions (
            auction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER,
            buyer_id INTEGER,
            name TEXT,
            status TEXT,
            price INTEGER,
            color TEXT,
            hp INTEGER,
            attack INTEGER,
            moves_json TEXT,
            level INTEGER,
            xp INTEGER,
            created_at REAL,
            state TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS pending_races (
            race_id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenger_id INTEGER,
            target_id INTEGER,
            challenger_inv_id INTEGER,
            target_inv_id INTEGER,
            bet INTEGER,
            chat_id INTEGER,
            status TEXT,
            created_at REAL
        )
    ''')
    # Global state
    c.execute('''
        CREATE TABLE IF NOT EXISTS global_state (
            key TEXT PRIMARY KEY,
            value REAL
        )
    ''')
    # Indexes
    c.execute('CREATE INDEX IF NOT EXISTS idx_inv_user ON inventory(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_market_price ON marketplace(price)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_users_money ON users(money DESC)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_items_user ON items(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_user_items_user ON user_items(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_effects_user ON user_effects(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_stats_market ON isopod_stats(market_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_battles_target ON pending_battles(target_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_fish_tier ON fish_catalog(tier)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_user_rods ON user_rods(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_user_fish ON user_fish(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_auctions_state ON auctions(state)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_races_target ON pending_races(target_id)')
    conn.commit()
    ensure_columns(conn)
    conn.close()

# --------------------------------------------------------------------------------
# ensure_columns: tiny migration helper that adds columns if older DB lacks
# them. This is intentionally simplistic: it runs PRAGMA table_info then
# issues ALTER TABLE ADD COLUMN when necessary. It is safe-ish but slow.
# --------------------------------------------------------------------------------

def ensure_columns(conn):
    c = conn.cursor()
    def has_column(table, column):
        c.execute(f'PRAGMA table_info({table})')
        return any(row[1] == column for row in c.fetchall())
    user_columns = [
        ('roll_charges', 'INTEGER DEFAULT 1'),
        ('last_charge_at', 'REAL DEFAULT 0')
    ]
    for col, col_def in user_columns:
        if not has_column('users', col):
            c.execute(f'ALTER TABLE users ADD COLUMN {col} {col_def}')
    inv_columns = [
        ('name', 'TEXT'),
        ('status', 'TEXT'),
        ('price', 'INTEGER'),
        ('color', 'TEXT'),
        ('hp', 'INTEGER'),
        ('attack', 'INTEGER'),
        ('moves_json', 'TEXT'),
        ('locked', 'INTEGER DEFAULT 0'),
        ('level', 'INTEGER DEFAULT 1'),
        ('xp', 'INTEGER DEFAULT 0')
    ]
    for col, col_def in inv_columns:
        if not has_column('inventory', col):
            c.execute(f'ALTER TABLE inventory ADD COLUMN {col} {col_def}')
    if not has_column('pending_battles', 'chat_id'):
        c.execute('ALTER TABLE pending_battles ADD COLUMN chat_id INTEGER')
    conn.commit()

def get_or_create_user(user_id: int, username: str) -> Dict[str, Any]:
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = c.fetchone()
    if user:
        conn.close()
        return {
            'user_id': user[0],
            'username': user[1],
            'money': user[2],
            'legendary': bool(user[3]),
            'last_roll': user[4],
            'roll_charges': user[5],
            'last_charge_at': user[6]
        }
    c.execute('INSERT INTO users (user_id, username, roll_charges, last_charge_at) VALUES (?, ?, ?, ?)',
              (user_id, username, 1, datetime.utcnow().timestamp()))
    conn.commit()
    conn.close()
    return {'user_id': user_id, 'username': username, 'money': 0, 'legendary': False, 'last_roll': 0, 'roll_charges': 1, 'last_charge_at': datetime.utcnow().timestamp()}

def update_user_last_roll(user_id: int, timestamp: float):
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE users SET last_roll = ? WHERE user_id = ?', (timestamp, user_id))
    conn.commit()
    conn.close()

def update_user_money(user_id: int, delta: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE users SET money = money + ? WHERE user_id = ?', (delta, user_id))
    conn.commit()
    conn.close()

def set_legendary(user_id: int, is_legendary: bool):
    conn = get_conn()
    c = conn.cursor()
    c.execute('UPDATE users SET legendary = ? WHERE user_id = ?', (int(is_legendary), user_id))
    conn.commit()
    conn.close()

# More funcs later
