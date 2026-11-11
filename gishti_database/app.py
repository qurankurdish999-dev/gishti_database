from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from database import get_connection, init_db, generate_invoice_number
from functools import wraps
import sqlite3
import os
import sys


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
    conn.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
    conn.commit()
    conn.close()
    flash("جۆرەکە سڕایەوە", "info")
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
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    flash("کاڵاکە سڕایەوە", "info")
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
    return render_template("pos.html")


@app.route("/api/checkout", methods=["POST"])
@login_required
def checkout():
    data = request.get_json()
    items = data.get("items", [])
    discount = float(data.get("discount") or 0)
    paid = float(data.get("paid") or 0)
    customer_name = data.get("customer_name", "").strip()

    if not items:
        return jsonify({"success": False, "message": "هیچ کاڵایەک زیاد نەکراوە"}), 400

    conn = get_connection()
    total = sum(float(it["price"]) * float(it["quantity"]) for it in items) - discount
    invoice_number = generate_invoice_number()

    cur = conn.execute(
        """INSERT INTO sales (invoice_number, total, discount, paid, customer_name, user_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (invoice_number, total, discount, paid, customer_name, session["user_id"]),
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
