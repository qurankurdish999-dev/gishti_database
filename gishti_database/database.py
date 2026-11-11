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
