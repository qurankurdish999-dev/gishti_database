import sqlite3
import os
import sys
from datetime import datetime


def _base_dir():
    """شوێنی فۆڵدەری بنەڕەتی: کاتێک بەرنامەکە بکرێتە .exe (PyInstaller)،
    داتابەیس دەبێت لەتەنیشت فایلی exe هەڵبگیرێت، نەک لە فۆڵدەری کاتیی
    ناوخۆیی کە دوای داخستن دەسڕدرێتەوە."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


DB_PATH = os.path.join(_base_dir(), "database.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """دروستکردنی خشتەکانی داتابەیس ئەگەر بوونیان نەبێت"""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            fullname TEXT,
            role TEXT DEFAULT 'staff'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            barcode TEXT,
            category_id INTEGER,
            purchase_price REAL DEFAULT 0,
            sale_price REAL NOT NULL DEFAULT 0,
            quantity REAL NOT NULL DEFAULT 0,
            unit TEXT DEFAULT 'دانە',
            min_quantity REAL DEFAULT 5,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT UNIQUE,
            sale_date TEXT DEFAULT (datetime('now')),
            total REAL NOT NULL DEFAULT 0,
            discount REAL DEFAULT 0,
            paid REAL DEFAULT 0,
            customer_name TEXT,
            user_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            product_id INTEGER,
            product_name TEXT,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
        )
    """)

    # -------------------- لایەنەکان (کڕیار / دابینکەر) --------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS parties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            party_type TEXT NOT NULL DEFAULT 'customer',  -- customer / supplier / both
            opening_balance REAL DEFAULT 0,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # -------------------- کڕین --------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT UNIQUE,
            purchase_date TEXT DEFAULT (datetime('now')),
            total REAL NOT NULL DEFAULT 0,
            discount REAL DEFAULT 0,
            paid REAL DEFAULT 0,
            party_id INTEGER,
            user_id INTEGER,
            FOREIGN KEY (party_id) REFERENCES parties(id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS purchase_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_id INTEGER NOT NULL,
            product_id INTEGER,
            product_name TEXT,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (purchase_id) REFERENCES purchases(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
        )
    """)

    # -------------------- بەڵگەکان: وەرگرتن/دان/خەرجی/داشکاندن/گواستنەوە --------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trans_type TEXT NOT NULL,   -- receipt / payment / expense_general / expense_purchase / discount / transfer
            trans_date TEXT DEFAULT (datetime('now')),
            amount REAL NOT NULL,
            party_id INTEGER,
            to_party_id INTEGER,
            note TEXT,
            user_id INTEGER,
            FOREIGN KEY (party_id) REFERENCES parties(id) ON DELETE SET NULL,
            FOREIGN KEY (to_party_id) REFERENCES parties(id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    # -------------------- تۆماری چالاکی --------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_time TEXT DEFAULT (datetime('now')),
            user_name TEXT,
            action TEXT,
            entity_type TEXT,
            description TEXT
        )
    """)

    # -------------------- سەبەتەی سڕاوەکان (Recycle bin) --------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS recycle_bin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deleted_at TEXT DEFAULT (datetime('now')),
            entity_type TEXT NOT NULL,
            original_id INTEGER,
            data_json TEXT NOT NULL,
            deleted_by TEXT
        )
    """)

    conn.commit()

    # --------- migrasyon: زیادکردنی party_id بۆ sales ئەگەر بوونی نەبێت ---------
    cols = [r["name"] for r in c.execute("PRAGMA table_info(sales)").fetchall()]
    if "party_id" not in cols:
        c.execute("ALTER TABLE sales ADD COLUMN party_id INTEGER")
        conn.commit()

    # دروستکردنی بەکارهێنەری سەرەکی (admin) ئەگەر هیچ بەکارهێنەرێک نەبوو
    c.execute("SELECT COUNT(*) as cnt FROM users")
    if c.fetchone()["cnt"] == 0:
        c.execute(
            "INSERT INTO users (username, password, fullname, role) VALUES (?, ?, ?, ?)",
            ("admin", "admin123", "بەڕێوەبەری سیستەم", "admin"),
        )
        conn.commit()

    # دروستکردنی چەند جۆرێکی نموونەیی
    c.execute("SELECT COUNT(*) as cnt FROM categories")
    if c.fetchone()["cnt"] == 0:
        for cat in ["گشتی", "خۆراک", "خواردنەوە", "دەرمان", "کەلوپەلی ماڵ"]:
            try:
                c.execute("INSERT INTO categories (name) VALUES (?)", (cat,))
            except sqlite3.IntegrityError:
                pass
        conn.commit()

    conn.close()


def generate_invoice_number():
    """دروستکردنی ژمارەی وەسڵ بەپێی کات"""
    return datetime.now().strftime("INV-%Y%m%d-%H%M%S")


def generate_purchase_number():
    """دروستکردنی ژمارەی پسووڵەی کڕین بەپێی کات"""
    return datetime.now().strftime("PUR-%Y%m%d-%H%M%S")
