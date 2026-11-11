from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from database import get_connection, init_db, generate_invoice_number, generate_purchase_number
from functools import wraps
import sqlite3
import os
import sys
import json


def _resource_dir():
    """کاتێک بەرنامەکە بە PyInstaller بکرێتە .exe، فایلە جێگیرەکان
    (templates/static) لەناو فۆڵدەرێکی کاتیی دەبن، نەک لەتەنیشت exe."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


_base = _resource_dir()
app = Flask(
    __name__,
    template_folder=os.path.join(_base, "templates"),
    static_folder=os.path.join(_base, "static"),
)
app.secret_key = "change-this-secret-key-please"  # دەتوانیت بیگۆڕیت

# دروستکردنی داتابەیس لە کاتی دەستپێکردن
init_db()


# ---------------------------------------------------------------------------
# یارمەتیدەر (helpers)
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_user():
    return dict(current_user=session.get("fullname"), current_role=session.get("role"))


def log_activity(conn, action, entity_type, description):
    """تۆمارکردنی چالاکییەک لە تۆماری سیستەم"""
    conn.execute(
        "INSERT INTO activity_log (user_name, action, entity_type, description) VALUES (?, ?, ?, ?)",
        (session.get("fullname", "-"), action, entity_type, description),
    )


TABLE_BY_ENTITY = {"product": "products", "category": "categories", "party": "parties"}


def soft_delete(conn, entity_type, row):
    """لەبری سڕینەوەی هەمیشەیی، تۆمارەکە دەگوازرێتەوە بۆ سەبەتەی سڕاوەکان"""
    table = TABLE_BY_ENTITY[entity_type]
    conn.execute(
        "INSERT INTO recycle_bin (entity_type, original_id, data_json, deleted_by) VALUES (?, ?, ?, ?)",
        (entity_type, row["id"], json.dumps(dict(row), ensure_ascii=False), session.get("fullname")),
    )
    conn.execute(f"DELETE FROM {table} WHERE id = ?", (row["id"],))


def restore_from_recycle(conn, bin_id):
    rec = conn.execute("SELECT * FROM recycle_bin WHERE id = ?", (bin_id,)).fetchone()
    if not rec:
        return False
    data = json.loads(rec["data_json"])
    table = TABLE_BY_ENTITY[rec["entity_type"]]
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    conn.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})", tuple(data.values()))
    conn.execute("DELETE FROM recycle_bin WHERE id = ?", (bin_id,))
    return True


# ---------------------------------------------------------------------------
# چوونەژوورەوە / دەرچوون
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        conn = get_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? AND password = ?",
            (username, password),
        ).fetchone()
        conn.close()
        if user:
            session["user_id"] = user["id"]
            session["fullname"] = user["fullname"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        flash("ناوی بەکارهێنەر یان وشەی نهێنی هەڵەیە", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# داشبۆرد
# ---------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


# ---------------------------------------------------------------------------
# جۆرەکان (Categories)
# ---------------------------------------------------------------------------
@app.route("/categories", methods=["GET", "POST"])
@login_required
def categories():
    conn = get_connection()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            try:
                conn.execute("INSERT INTO categories (name) VALUES (?)", (name,))
                log_activity(conn, "زیادکرا", "جۆر", f"جۆری '{name}' زیادکرا")
                conn.commit()
                flash("جۆرەکە زیاد کرا", "success")
            except sqlite3.IntegrityError:
                flash("ئەم جۆرە پێشتر هەیە", "warning")
        return redirect(url_for("categories"))
    cats = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    conn.close()
    return render_template("categories.html", categories=cats)


@app.route("/categories/delete/<int:cat_id>")
@login_required
def delete_category(cat_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM categories WHERE id = ?", (cat_id,)).fetchone()
    if row:
        soft_delete(conn, "category", row)
        log_activity(conn, "سڕایەوە", "جۆر", f"جۆری '{row['name']}' نێردرا بۆ سەبەتەی سڕاوەکان")
        conn.commit()
    conn.close()
    flash("جۆرەکە نێردرا بۆ سەبەتەی سڕاوەکان", "info")
    return redirect(url_for("categories"))


# ---------------------------------------------------------------------------
# کاڵاکان (Products)
# ---------------------------------------------------------------------------
@app.route("/products")
@login_required
def products():
    q = request.args.get("q", "").strip()
    conn = get_connection()
    if q:
        rows = conn.execute(
            """SELECT p.*, c.name as category_name FROM products p
               LEFT JOIN categories c ON p.category_id = c.id
               WHERE p.name LIKE ? OR p.barcode LIKE ?
               ORDER BY p.name""",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT p.*, c.name as category_name FROM products p
               LEFT JOIN categories c ON p.category_id = c.id
               ORDER BY p.name"""
        ).fetchall()
    conn.close()
    return render_template("products.html", products=rows, q=q)


@app.route("/products/add", methods=["GET", "POST"])
@login_required
def add_product():
    conn = get_connection()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        barcode = request.form.get("barcode", "").strip()
        category_id = request.form.get("category_id") or None
        purchase_price = float(request.form.get("purchase_price") or 0)
        sale_price = float(request.form.get("sale_price") or 0)
        quantity = float(request.form.get("quantity") or 0)
        unit = request.form.get("unit", "دانە")
        min_quantity = float(request.form.get("min_quantity") or 5)

        conn.execute(
            """INSERT INTO products
               (name, barcode, category_id, purchase_price, sale_price, quantity, unit, min_quantity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, barcode, category_id, purchase_price, sale_price, quantity, unit, min_quantity),
        )
        log_activity(conn, "زیادکرا", "کاڵا", f"کاڵای '{name}' زیادکرا")
        conn.commit()
        conn.close()
        flash("کاڵاکە زیادکرا بە سەرکەوتوویی", "success")
        return redirect(url_for("products"))

    cats = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    conn.close()
    return render_template("product_form.html", categories=cats, product=None)


@app.route("/products/edit/<int:product_id>", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    conn = get_connection()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        barcode = request.form.get("barcode", "").strip()
        category_id = request.form.get("category_id") or None
        purchase_price = float(request.form.get("purchase_price") or 0)
        sale_price = float(request.form.get("sale_price") or 0)
        quantity = float(request.form.get("quantity") or 0)
        unit = request.form.get("unit", "دانە")
        min_quantity = float(request.form.get("min_quantity") or 5)

        conn.execute(
            """UPDATE products SET name=?, barcode=?, category_id=?, purchase_price=?,
               sale_price=?, quantity=?, unit=?, min_quantity=? WHERE id=?""",
            (name, barcode, category_id, purchase_price, sale_price, quantity, unit, min_quantity, product_id),
        )
        conn.commit()
        conn.close()
        flash("کاڵاکە نوێکرایەوە", "success")
        return redirect(url_for("products"))

    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    cats = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    conn.close()
    if not product:
        flash("کاڵاکە نەدۆزرایەوە", "danger")
        return redirect(url_for("products"))
    return render_template("product_form.html", categories=cats, product=product)


@app.route("/products/delete/<int:product_id>")
@login_required
def delete_product(product_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if row:
        soft_delete(conn, "product", row)
        log_activity(conn, "سڕایەوە", "کاڵا", f"کاڵای '{row['name']}' نێردرا بۆ سەبەتەی سڕاوەکان")
        conn.commit()
    conn.close()
    flash("کاڵاکە نێردرا بۆ سەبەتەی سڕاوەکان (دەتوانیت بیگەڕێنیتەوە)", "info")
    return redirect(url_for("products"))


# ---------------------------------------------------------------------------
# API بۆ گەڕان لە کاتی فرۆشتن (POS)
# ---------------------------------------------------------------------------
@app.route("/api/search_products")
@login_required
def api_search_products():
    q = request.args.get("q", "").strip()
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, name, barcode, sale_price, quantity, unit FROM products
           WHERE name LIKE ? OR barcode LIKE ? LIMIT 20""",
        (f"%{q}%", f"%{q}%"),
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# فرۆشتن (Point of Sale)
# ---------------------------------------------------------------------------
@app.route("/sales/new")
@login_required
def new_sale():
    conn = get_connection()
    customers = conn.execute(
        "SELECT * FROM parties WHERE party_type IN ('customer','both') ORDER BY name"
    ).fetchall()
    conn.close()
    return render_template("pos.html", customers=customers)


@app.route("/api/checkout", methods=["POST"])
@login_required
def checkout():
    data = request.get_json()
    items = data.get("items", [])
    discount = float(data.get("discount") or 0)
    paid = float(data.get("paid") or 0)
    customer_name = data.get("customer_name", "").strip()
    party_id = data.get("party_id") or None

    if not items:
        return jsonify({"success": False, "message": "هیچ کاڵایەک زیاد نەکراوە"}), 400

    conn = get_connection()
    total = sum(float(it["price"]) * float(it["quantity"]) for it in items) - discount
    invoice_number = generate_invoice_number()

    cur = conn.execute(
        """INSERT INTO sales (invoice_number, total, discount, paid, customer_name, user_id, party_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (invoice_number, total, discount, paid, customer_name, session["user_id"], party_id),
    )
    sale_id = cur.lastrowid

    for it in items:
        product_id = it.get("id")
        qty = float(it["quantity"])
        price = float(it["price"])
        conn.execute(
            """INSERT INTO sale_items (sale_id, product_id, product_name, quantity, price, subtotal)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sale_id, product_id, it["name"], qty, price, qty * price),
        )
        # کەمکردنەوەی کۆگا
        conn.execute(
            "UPDATE products SET quantity = quantity - ? WHERE id = ?",
            (qty, product_id),
        )

    log_activity(conn, "زیادکرا", "فرۆشتن", f"وەسڵی فرۆشتن '{invoice_number}' بە کۆی {total:.0f} دروستکرا")
    conn.commit()
    conn.close()
    return jsonify({"success": True, "sale_id": sale_id, "invoice_number": invoice_number})


@app.route("/sales")
@login_required
def sales():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM sales ORDER BY sale_date DESC").fetchall()
    conn.close()
    return render_template("sales.html", sales=rows)


@app.route("/sales/<int:sale_id>")
@login_required
def sale_detail(sale_id):
    conn = get_connection()
    sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    items = conn.execute("SELECT * FROM sale_items WHERE sale_id = ?", (sale_id,)).fetchall()
    conn.close()
    if not sale:
        flash("وەسڵەکە نەدۆزرایەوە", "danger")
        return redirect(url_for("sales"))
    return render_template("invoice.html", sale=sale, items=items)


# ---------------------------------------------------------------------------
# لایەنەکان (کڕیار / دابینکەر) — Parties
# ---------------------------------------------------------------------------
@app.route("/parties", methods=["GET", "POST"])
@login_required
def parties():
    conn = get_connection()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        party_type = request.form.get("party_type", "customer")
        opening_balance = float(request.form.get("opening_balance") or 0)
        notes = request.form.get("notes", "").strip()
        if name:
            conn.execute(
                """INSERT INTO parties (name, phone, party_type, opening_balance, notes)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, phone, party_type, opening_balance, notes),
            )
            log_activity(conn, "زیادکرا", "لایەن", f"لایەنی '{name}' زیادکرا")
            conn.commit()
            flash("لایەنەکە زیادکرا", "success")
        return redirect(url_for("parties"))

    q = request.args.get("q", "").strip()
    if q:
        rows = conn.execute(
            "SELECT * FROM parties WHERE name LIKE ? OR phone LIKE ? ORDER BY name",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM parties ORDER BY name").fetchall()

    parties_with_balance = []
    for p in rows:
        bal = compute_party_balance(conn, p)
        parties_with_balance.append({**dict(p), "balance": bal})

    conn.close()
    return render_template("parties.html", parties=parties_with_balance, q=q)


@app.route("/parties/edit/<int:party_id>", methods=["GET", "POST"])
@login_required
def edit_party(party_id):
    conn = get_connection()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        party_type = request.form.get("party_type", "customer")
        opening_balance = float(request.form.get("opening_balance") or 0)
        notes = request.form.get("notes", "").strip()
        conn.execute(
            """UPDATE parties SET name=?, phone=?, party_type=?, opening_balance=?, notes=?
               WHERE id=?""",
            (name, phone, party_type, opening_balance, notes, party_id),
        )
        log_activity(conn, "دەستکاریکرا", "لایەن", f"لایەنی '{name}' نوێکرایەوە")
        conn.commit()
        conn.close()
        flash("لایەنەکە نوێکرایەوە", "success")
        return redirect(url_for("parties"))

    party = conn.execute("SELECT * FROM parties WHERE id = ?", (party_id,)).fetchone()
    conn.close()
    if not party:
        flash("لایەنەکە نەدۆزرایەوە", "danger")
        return redirect(url_for("parties"))
    return render_template("party_form.html", party=party)


@app.route("/parties/delete/<int:party_id>")
@login_required
def delete_party(party_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM parties WHERE id = ?", (party_id,)).fetchone()
    if row:
        soft_delete(conn, "party", row)
        log_activity(conn, "سڕایەوە", "لایەن", f"لایەنی '{row['name']}' نێردرا بۆ سەبەتەی سڕاوەکان")
        conn.commit()
    conn.close()
    flash("لایەنەکە نێردرا بۆ سەبەتەی سڕاوەکان", "info")
    return redirect(url_for("parties"))


def compute_party_balance(conn, party):
    """باڵانسی لایەنێک: بۆ کڕیار ئەرێنی واتە قەرزارمانە، بۆ دابینکەر ئەرێنی واتە قەرزاریێتی.
    بڕی دراو لە کاتی وەسڵ/پسووڵەکە خۆیدا (paid) کەم دەکرێتەوە، هەروەها بەڵگەی وەرگرتن/دان/
    داشکاندن هەموو باڵانس کەم دەکەنەوە، گواستنەوە بۆ دەرەوە باڵانس کەم دەکاتەوە و
    گواستنەوەی وەرگیراو زیادی دەکات."""
    pid = party["id"]
    if party["party_type"] in ("customer", "both"):
        row = conn.execute(
            "SELECT COALESCE(SUM(total),0) t, COALESCE(SUM(paid),0) p FROM sales WHERE party_id = ?", (pid,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COALESCE(SUM(total),0) t, COALESCE(SUM(paid),0) p FROM purchases WHERE party_id = ?", (pid,)
        ).fetchone()
    base_total = row["t"] - row["p"]

    deductions = conn.execute(
        """SELECT COALESCE(SUM(amount),0) v FROM transactions
           WHERE party_id = ? AND trans_type IN ('receipt','payment','discount','transfer')""",
        (pid,),
    ).fetchone()["v"]

    transfers_in = conn.execute(
        "SELECT COALESCE(SUM(amount),0) v FROM transactions WHERE to_party_id = ? AND trans_type = 'transfer'",
        (pid,),
    ).fetchone()["v"]

    return party["opening_balance"] + base_total - deductions + transfers_in


# ---------------------------------------------------------------------------
# کڕین (Purchases)
# ---------------------------------------------------------------------------
@app.route("/purchases/new")
@login_required
def new_purchase():
    conn = get_connection()
    suppliers = conn.execute(
        "SELECT * FROM parties WHERE party_type IN ('supplier','both') ORDER BY name"
    ).fetchall()
    conn.close()
    return render_template("purchase_new.html", suppliers=suppliers)


@app.route("/api/checkout_purchase", methods=["POST"])
@login_required
def checkout_purchase():
    data = request.get_json()
    items = data.get("items", [])
    discount = float(data.get("discount") or 0)
    paid = float(data.get("paid") or 0)
    party_id = data.get("party_id") or None

    if not items:
        return jsonify({"success": False, "message": "هیچ کاڵایەک زیاد نەکراوە"}), 400

    conn = get_connection()
    total = sum(float(it["price"]) * float(it["quantity"]) for it in items) - discount
    invoice_number = generate_purchase_number()

    cur = conn.execute(
        """INSERT INTO purchases (invoice_number, total, discount, paid, party_id, user_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (invoice_number, total, discount, paid, party_id, session["user_id"]),
    )
    purchase_id = cur.lastrowid

    for it in items:
        product_id = it.get("id")
        qty = float(it["quantity"])
        price = float(it["price"])
        conn.execute(
            """INSERT INTO purchase_items (purchase_id, product_id, product_name, quantity, price, subtotal)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (purchase_id, product_id, it["name"], qty, price, qty * price),
        )
        # زیادکردنی کۆگا
        conn.execute(
            "UPDATE products SET quantity = quantity + ? WHERE id = ?",
            (qty, product_id),
        )

    log_activity(conn, "زیادکرا", "کڕین", f"پسووڵەی کڕین '{invoice_number}' بە کۆی {total:.0f} دروستکرا")
    conn.commit()
    conn.close()
    return jsonify({"success": True, "purchase_id": purchase_id, "invoice_number": invoice_number})


@app.route("/purchases")
@login_required
def purchases():
    conn = get_connection()
    rows = conn.execute(
        """SELECT p.*, pt.name as party_name FROM purchases p
           LEFT JOIN parties pt ON p.party_id = pt.id
           ORDER BY p.purchase_date DESC"""
    ).fetchall()
    conn.close()
    return render_template("purchases.html", purchases=rows)


@app.route("/purchases/<int:purchase_id>")
@login_required
def purchase_detail(purchase_id):
    conn = get_connection()
    purchase = conn.execute(
        """SELECT p.*, pt.name as party_name FROM purchases p
           LEFT JOIN parties pt ON p.party_id = pt.id WHERE p.id = ?""",
        (purchase_id,),
    ).fetchone()
    items = conn.execute("SELECT * FROM purchase_items WHERE purchase_id = ?", (purchase_id,)).fetchall()
    conn.close()
    if not purchase:
        flash("پسووڵەکە نەدۆزرایەوە", "danger")
        return redirect(url_for("purchases"))
    return render_template("purchase_invoice.html", purchase=purchase, items=items)


@app.route("/api/search_products_purchase")
@login_required
def api_search_products_purchase():
    """گەڕان بۆ کاڵا لە کاتی کڕین (بەبێ سنووردارکردن بە بڕی کۆگا)"""
    q = request.args.get("q", "").strip()
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, name, barcode, purchase_price as sale_price, quantity, unit FROM products
           WHERE name LIKE ? OR barcode LIKE ? LIMIT 20""",
        (f"%{q}%", f"%{q}%"),
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# بەڵگەکان: وەرگرتن/دان/خەرجی/داشکاندن/گواستنەوە — Transactions/Vouchers
# ---------------------------------------------------------------------------
TRANS_LABELS = {
    "receipt": "بەڵگەی وەرگرتنی پارە",
    "payment": "بەڵگەی دانی پارە",
    "expense_general": "خەرجی گشتی",
    "expense_purchase": "خەرجی کڕین",
    "discount": "بەڵگەی داشکاندن",
    "transfer": "گواستنەوە نێوان لایەنەکان",
}


@app.route("/transactions")
@login_required
def transactions():
    trans_type = request.args.get("type", "")
    conn = get_connection()
    query = """SELECT t.*, p1.name as party_name, p2.name as to_party_name
               FROM transactions t
               LEFT JOIN parties p1 ON t.party_id = p1.id
               LEFT JOIN parties p2 ON t.to_party_id = p2.id"""
    params = []
    if trans_type:
        query += " WHERE t.trans_type = ?"
        params.append(trans_type)
    query += " ORDER BY t.trans_date DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return render_template("transactions.html", transactions=rows, labels=TRANS_LABELS, active_type=trans_type)


@app.route("/transactions/new", methods=["GET", "POST"])
@login_required
def new_transaction():
    conn = get_connection()
    if request.method == "POST":
        trans_type = request.form.get("trans_type")
        amount = float(request.form.get("amount") or 0)
        party_id = request.form.get("party_id") or None
        to_party_id = request.form.get("to_party_id") or None
        note = request.form.get("note", "").strip()

        conn.execute(
            """INSERT INTO transactions (trans_type, amount, party_id, to_party_id, note, user_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (trans_type, amount, party_id, to_party_id, note, session["user_id"]),
        )
        label = TRANS_LABELS.get(trans_type, trans_type)
        log_activity(conn, "زیادکرا", "بەڵگە", f"{label} بە بڕی {amount:.0f} زیادکرا")
        conn.commit()
        conn.close()
        flash("بەڵگەکە زیادکرا", "success")
        return redirect(url_for("transactions"))

    default_type = request.args.get("type", "receipt")
    all_parties = conn.execute("SELECT * FROM parties ORDER BY name").fetchall()
    conn.close()
    return render_template(
        "transaction_form.html", parties=all_parties, labels=TRANS_LABELS, default_type=default_type
    )


# ---------------------------------------------------------------------------
# قەرزەکان و باڵانس — Debts
# ---------------------------------------------------------------------------
@app.route("/debts")
@login_required
def debts():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM parties ORDER BY name").fetchall()
    result = []
    total_customer_debt = 0
    total_supplier_debt = 0
    for p in rows:
        bal = compute_party_balance(conn, p)
        result.append({**dict(p), "balance": bal})
        if p["party_type"] in ("customer", "both"):
            total_customer_debt += bal
        else:
            total_supplier_debt += bal
    conn.close()
    return render_template(
        "debts.html",
        parties=result,
        total_customer_debt=total_customer_debt,
        total_supplier_debt=total_supplier_debt,
    )


# ---------------------------------------------------------------------------
# جووڵەی ئەمڕۆ — Today's movement
# ---------------------------------------------------------------------------
@app.route("/today")
@login_required
def today_movement():
    conn = get_connection()
    sales_today = conn.execute(
        "SELECT * FROM sales WHERE date(sale_date) = date('now') ORDER BY sale_date DESC"
    ).fetchall()
    purchases_today = conn.execute(
        """SELECT p.*, pt.name as party_name FROM purchases p
           LEFT JOIN parties pt ON p.party_id = pt.id
           WHERE date(p.purchase_date) = date('now') ORDER BY p.purchase_date DESC"""
    ).fetchall()
    trans_today = conn.execute(
        """SELECT t.*, p1.name as party_name FROM transactions t
           LEFT JOIN parties p1 ON t.party_id = p1.id
           WHERE date(t.trans_date) = date('now') ORDER BY t.trans_date DESC"""
    ).fetchall()
    conn.close()
    return render_template(
        "today.html",
        sales_today=sales_today,
        purchases_today=purchases_today,
        trans_today=trans_today,
        labels=TRANS_LABELS,
    )


# ---------------------------------------------------------------------------
# تۆماری چالاکی — Activity log
# ---------------------------------------------------------------------------
@app.route("/activity")
@login_required
def activity():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM activity_log ORDER BY log_time DESC LIMIT 200").fetchall()
    conn.close()
    return render_template("activity.html", logs=rows)


# ---------------------------------------------------------------------------
# سەبەتەی سڕاوەکان — Recycle bin
# ---------------------------------------------------------------------------
ENTITY_LABELS = {"product": "کاڵا", "category": "جۆر", "party": "لایەن"}


@app.route("/recycle_bin")
@login_required
def recycle_bin():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM recycle_bin ORDER BY deleted_at DESC").fetchall()
    items = []
    for r in rows:
        data = json.loads(r["data_json"])
        items.append({**dict(r), "name": data.get("name", "-"), "label": ENTITY_LABELS.get(r["entity_type"], r["entity_type"])})
    conn.close()
    return render_template("recycle_bin.html", items=items)


@app.route("/recycle_bin/restore/<int:bin_id>")
@login_required
def restore_item(bin_id):
    conn = get_connection()
    ok = restore_from_recycle(conn, bin_id)
    if ok:
        log_activity(conn, "گەڕێنرایەوە", "سەبەتەی سڕاوەکان", f"تۆمارێک گەڕێنرایەوە")
        conn.commit()
        flash("گەڕێنرایەوە بە سەرکەوتوویی", "success")
    else:
        flash("نەدۆزرایەوە", "danger")
    conn.close()
    return redirect(url_for("recycle_bin"))


@app.route("/recycle_bin/delete_forever/<int:bin_id>")
@login_required
def delete_forever(bin_id):
    conn = get_connection()
    conn.execute("DELETE FROM recycle_bin WHERE id = ?", (bin_id,))
    conn.commit()
    conn.close()
    flash("بۆ هەمیشە سڕایەوە", "info")
    return redirect(url_for("recycle_bin"))


# ---------------------------------------------------------------------------
# ڕاپۆرتەکان
# ---------------------------------------------------------------------------
@app.route("/reports")
@login_required
def reports():
    conn = get_connection()
    total_products = conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
    today_sales = conn.execute(
        "SELECT COALESCE(SUM(total),0) s, COUNT(*) c FROM sales WHERE date(sale_date) = date('now')"
    ).fetchone()
    month_sales = conn.execute(
        "SELECT COALESCE(SUM(total),0) s FROM sales WHERE strftime('%Y-%m', sale_date) = strftime('%Y-%m', 'now')"
    ).fetchone()
    total_stock_value = conn.execute(
        "SELECT COALESCE(SUM(quantity * sale_price),0) v FROM products"
    ).fetchone()["v"]
    recent_sales = conn.execute(
        "SELECT * FROM sales ORDER BY sale_date DESC LIMIT 8"
    ).fetchall()
    daily = conn.execute(
        """SELECT date(sale_date) as d, SUM(total) as total, COUNT(*) as cnt
           FROM sales GROUP BY date(sale_date) ORDER BY d DESC LIMIT 30"""
    ).fetchall()
    best_sellers = conn.execute(
        """SELECT product_name, SUM(quantity) as total_qty, SUM(subtotal) as total_amount
           FROM sale_items GROUP BY product_name ORDER BY total_qty DESC LIMIT 10"""
    ).fetchall()
    low_stock = conn.execute(
        "SELECT * FROM products WHERE quantity <= min_quantity ORDER BY quantity ASC"
    ).fetchall()
    conn.close()
    return render_template(
        "reports.html",
        total_products=total_products,
        today_sales=today_sales,
        month_sales=month_sales,
        total_stock_value=total_stock_value,
        recent_sales=recent_sales,
        daily=daily,
        best_sellers=best_sellers,
        low_stock=low_stock,
    )


# ---------------------------------------------------------------------------
# بەکارهێنەران (تەنها admin)
# ---------------------------------------------------------------------------
@app.route("/users", methods=["GET", "POST"])
@login_required
def users():
    if session.get("role") != "admin":
        flash("مۆڵەتت نییە بۆ ئەم بەشە", "danger")
        return redirect(url_for("dashboard"))

    conn = get_connection()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        fullname = request.form.get("fullname", "").strip()
        role = request.form.get("role", "staff")
        try:
            conn.execute(
                "INSERT INTO users (username, password, fullname, role) VALUES (?, ?, ?, ?)",
                (username, password, fullname, role),
            )
            conn.commit()
            flash("بەکارهێنەر زیادکرا", "success")
        except sqlite3.IntegrityError:
            flash("ئەم ناوی بەکارهێنەرە پێشتر هەیە", "warning")
        return redirect(url_for("users"))

    rows = conn.execute("SELECT id, username, fullname, role FROM users").fetchall()
    conn.close()
    return render_template("users.html", users=rows)


@app.route("/users/delete/<int:user_id>")
@login_required
def delete_user(user_id):
    if session.get("role") != "admin":
        return redirect(url_for("dashboard"))
    conn = get_connection()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash("بەکارهێنەر سڕایەوە", "info")
    return redirect(url_for("users"))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
