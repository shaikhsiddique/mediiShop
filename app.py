from flask import Flask, render_template, request, jsonify, redirect, url_for
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
DB = "medishop.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            brand TEXT,
            category TEXT,
            batch_no TEXT,
            expiry_date TEXT,
            mrp REAL NOT NULL,
            purchase_price REAL,
            stock INTEGER NOT NULL DEFAULT 0,
            unit TEXT DEFAULT 'Strips',
            hsn_code TEXT,
            gst_percent REAL DEFAULT 12.0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_no TEXT UNIQUE NOT NULL,
            customer_name TEXT,
            customer_phone TEXT,
            customer_address TEXT,
            subtotal REAL,
            discount REAL DEFAULT 0,
            gst_amount REAL,
            total REAL,
            payment_mode TEXT DEFAULT 'Cash',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS bill_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id INTEGER,
            product_id INTEGER,
            product_name TEXT,
            batch_no TEXT,
            expiry_date TEXT,
            mrp REAL,
            quantity INTEGER,
            discount REAL DEFAULT 0,
            gst_percent REAL,
            total REAL,
            FOREIGN KEY(bill_id) REFERENCES bills(id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        );
    """)
    conn.commit()
    conn.close()

def generate_bill_no():
    now = datetime.now()
    return f"MED-{now.strftime('%Y%m%d%H%M%S')}"

# ── Routes ──────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

# Products
@app.route("/api/products", methods=["GET"])
def get_products():
    conn = get_db()
    q = request.args.get("q", "")
    if q:
        rows = conn.execute(
            "SELECT * FROM products WHERE name LIKE ? OR brand LIKE ? OR category LIKE ? ORDER BY name",
            (f"%{q}%", f"%{q}%", f"%{q}%")
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/products/<int:pid>", methods=["GET"])
def get_product(pid):
    conn = get_db()
    row = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    conn.close()
    if row:
        return jsonify(dict(row))
    return jsonify({"error": "Not found"}), 404

@app.route("/api/products", methods=["POST"])
def add_product():
    d = request.json
    conn = get_db()
    conn.execute("""
        INSERT INTO products (name, brand, category, batch_no, expiry_date, mrp, purchase_price, stock, unit, hsn_code, gst_percent)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (d["name"], d.get("brand",""), d.get("category",""), d.get("batch_no",""),
          d.get("expiry_date",""), d["mrp"], d.get("purchase_price",0),
          d.get("stock",0), d.get("unit","Strips"), d.get("hsn_code",""), d.get("gst_percent",12)))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/products/<int:pid>", methods=["PUT"])
def update_product(pid):
    d = request.json
    conn = get_db()
    conn.execute("""
        UPDATE products SET name=?, brand=?, category=?, batch_no=?, expiry_date=?,
        mrp=?, purchase_price=?, stock=?, unit=?, hsn_code=?, gst_percent=?
        WHERE id=?
    """, (d["name"], d.get("brand",""), d.get("category",""), d.get("batch_no",""),
          d.get("expiry_date",""), d["mrp"], d.get("purchase_price",0),
          d.get("stock",0), d.get("unit","Strips"), d.get("hsn_code",""),
          d.get("gst_percent",12), pid))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/products/<int:pid>", methods=["DELETE"])
def delete_product(pid):
    conn = get_db()
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# Bills
@app.route("/api/bills", methods=["GET"])
def get_bills():
    conn = get_db()
    rows = conn.execute("SELECT * FROM bills ORDER BY created_at DESC LIMIT 100").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/bills/<int:bid>", methods=["GET"])
def get_bill(bid):
    conn = get_db()
    bill = conn.execute("SELECT * FROM bills WHERE id=?", (bid,)).fetchone()
    items = conn.execute("SELECT * FROM bill_items WHERE bill_id=?", (bid,)).fetchall()
    conn.close()
    if bill:
        return jsonify({"bill": dict(bill), "items": [dict(i) for i in items]})
    return jsonify({"error": "Not found"}), 404

@app.route("/api/bills", methods=["POST"])
def create_bill():
    d = request.json
    conn = get_db()
    try:
        bill_no = generate_bill_no()
        items = d.get("items", [])
        
        # Validate stock
        for item in items:
            row = conn.execute("SELECT stock FROM products WHERE id=?", (item["product_id"],)).fetchone()
            if not row or row["stock"] < item["quantity"]:
                return jsonify({"error": f"Insufficient stock for product ID {item['product_id']}"}), 400

        cur = conn.execute("""
            INSERT INTO bills (bill_no, customer_name, customer_phone, customer_address,
            subtotal, discount, gst_amount, total, payment_mode)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (bill_no, d.get("customer_name","Walk-in"), d.get("customer_phone",""),
              d.get("customer_address",""), d["subtotal"], d.get("discount",0),
              d["gst_amount"], d["total"], d.get("payment_mode","Cash")))
        bill_id = cur.lastrowid

        for item in items:
            conn.execute("""
                INSERT INTO bill_items (bill_id, product_id, product_name, batch_no, expiry_date,
                mrp, quantity, discount, gst_percent, total)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (bill_id, item["product_id"], item["product_name"], item.get("batch_no",""),
                  item.get("expiry_date",""), item["mrp"], item["quantity"],
                  item.get("discount",0), item.get("gst_percent",12), item["total"]))
            # Reduce stock
            conn.execute("UPDATE products SET stock = stock - ? WHERE id=?",
                         (item["quantity"], item["product_id"]))

        conn.commit()
        return jsonify({"success": True, "bill_id": bill_id, "bill_no": bill_no})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# Dashboard stats
@app.route("/api/stats", methods=["GET"])
def stats():
    conn = get_db()
    total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    low_stock = conn.execute("SELECT COUNT(*) FROM products WHERE stock <= 10").fetchone()[0]
    total_bills = conn.execute("SELECT COUNT(*) FROM bills").fetchone()[0]
    today_revenue = conn.execute(
        "SELECT COALESCE(SUM(total),0) FROM bills WHERE DATE(created_at)=DATE('now')"
    ).fetchone()[0]
    conn.close()
    return jsonify({
        "total_products": total_products,
        "low_stock": low_stock,
        "total_bills": total_bills,
        "today_revenue": round(today_revenue, 2)
    })

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)