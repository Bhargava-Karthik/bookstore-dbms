"""
Bookstore Management System - Backend (Flask REST API + MySQL)

Run:  python app.py   then open http://127.0.0.1:5000
"""
from flask import Flask, jsonify, request, send_from_directory
import mysql.connector

from config import DB_CONFIG

app = Flask(__name__, static_folder="static")


# ------------------------------------------------------------------
# Database helpers
# ------------------------------------------------------------------
def get_conn():
    return mysql.connector.connect(**DB_CONFIG)


def query(sql, params=None, one=False):
    """Run a SELECT and return rows as dicts."""
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = cur.fetchall()
        return (rows[0] if rows else None) if one else rows
    finally:
        conn.close()


def execute(sql, params=None):
    """Run INSERT/UPDATE/DELETE, commit, return (lastrowid, rowcount)."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid, cur.rowcount
    finally:
        conn.close()


@app.errorhandler(mysql.connector.Error)
def handle_db_error(err):
    # e.g. duplicate ISBN/email, FK violation, CHECK constraint
    return jsonify({"error": err.msg}), 400


# ------------------------------------------------------------------
# Generic CRUD for simple tables (authors, books, customers)
# ------------------------------------------------------------------
RESOURCES = {
    "authors": {
        "table": "authors", "pk": "author_id",
        "fields": ["name", "country"],
        "list_sql": "SELECT * FROM authors ORDER BY author_id",
    },
    "books": {
        "table": "books", "pk": "book_id",
        "fields": ["title", "author_id", "isbn", "genre", "price", "stock"],
        "list_sql": """SELECT b.*, a.name AS author_name
                       FROM books b JOIN authors a ON a.author_id = b.author_id
                       ORDER BY b.book_id""",
    },
    "customers": {
        "table": "customers", "pk": "customer_id",
        "fields": ["name", "email", "phone"],
        "list_sql": "SELECT * FROM customers ORDER BY customer_id",
    },
}


def get_resource(name):
    res = RESOURCES.get(name)
    if res is None:
        return None, (jsonify({"error": f"Unknown resource '{name}'"}), 404)
    return res, None


def clean_payload(res, data):
    """Keep only allowed columns; turn empty strings into NULL."""
    return {f: (data[f] if data[f] != "" else None)
            for f in res["fields"] if f in data}


@app.get("/api/<name>")
def list_items(name):
    res, err = get_resource(name)
    if err:
        return err
    return jsonify(query(res["list_sql"]))


@app.get("/api/<name>/<int:item_id>")
def get_item(name, item_id):
    res, err = get_resource(name)
    if err:
        return err
    row = query(f"SELECT * FROM {res['table']} WHERE {res['pk']} = %s", (item_id,), one=True)
    return (jsonify(row), 200) if row else (jsonify({"error": "Not found"}), 404)


@app.post("/api/<name>")
def create_item(name):
    res, err = get_resource(name)
    if err:
        return err
    data = clean_payload(res, request.get_json(force=True))
    if not data:
        return jsonify({"error": "No valid fields"}), 400
    cols = ", ".join(data)
    marks = ", ".join(["%s"] * len(data))
    new_id, _ = execute(f"INSERT INTO {res['table']} ({cols}) VALUES ({marks})",
                        tuple(data.values()))
    return jsonify({"message": "Created", "id": new_id}), 201


@app.put("/api/<name>/<int:item_id>")
def update_item(name, item_id):
    res, err = get_resource(name)
    if err:
        return err
    data = clean_payload(res, request.get_json(force=True))
    if not data:
        return jsonify({"error": "No valid fields"}), 400
    sets = ", ".join(f"{c} = %s" for c in data)
    _, count = execute(f"UPDATE {res['table']} SET {sets} WHERE {res['pk']} = %s",
                       tuple(data.values()) + (item_id,))
    if count == 0 and not query(f"SELECT 1 FROM {res['table']} WHERE {res['pk']}=%s", (item_id,)):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"message": "Updated"})


@app.delete("/api/<name>/<int:item_id>")
def delete_item(name, item_id):
    res, err = get_resource(name)
    if err:
        return err
    _, count = execute(f"DELETE FROM {res['table']} WHERE {res['pk']} = %s", (item_id,))
    if count == 0:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"message": "Deleted"})


# ------------------------------------------------------------------
# Orders (multi-table: orders + order_items, uses a TRANSACTION)
# ------------------------------------------------------------------
ORDER_LIST_SQL = """
SELECT o.order_id, o.customer_id, c.name AS customer,
       DATE_FORMAT(o.order_date, '%Y-%m-%d %H:%i') AS order_date,
       o.status,
       COUNT(oi.book_id) AS item_count,
       COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS total
FROM orders o
JOIN customers c        ON c.customer_id = o.customer_id
LEFT JOIN order_items oi ON oi.order_id = o.order_id
GROUP BY o.order_id, o.customer_id, c.name, o.order_date, o.status
ORDER BY o.order_id DESC
"""


@app.get("/api/orders")
def list_orders():
    return jsonify(query(ORDER_LIST_SQL))


@app.get("/api/orders/<int:order_id>/items")
def order_items(order_id):
    rows = query("""SELECT oi.book_id, b.title, oi.quantity, oi.unit_price,
                           oi.quantity * oi.unit_price AS subtotal
                    FROM order_items oi JOIN books b ON b.book_id = oi.book_id
                    WHERE oi.order_id = %s""", (order_id,))
    return jsonify(rows)


@app.post("/api/orders")
def create_order():
    data = request.get_json(force=True)
    customer_id = data.get("customer_id")
    items = data.get("items", [])
    if not customer_id or not items:
        return jsonify({"error": "customer_id and at least one item are required"}), 400

    conn = get_conn()
    try:
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        cur.execute("INSERT INTO orders (customer_id) VALUES (%s)", (customer_id,))
        order_id = cur.lastrowid

        for item in items:
            book_id, qty = int(item["book_id"]), int(item["quantity"])
            # Lock the book row so two orders can't oversell the same stock
            cur.execute("SELECT title, price, stock FROM books WHERE book_id = %s FOR UPDATE",
                        (book_id,))
            book = cur.fetchone()
            if book is None:
                raise ValueError(f"Book {book_id} does not exist")
            if book["stock"] < qty:
                raise ValueError(f"Not enough stock for '{book['title']}' (only {book['stock']} left)")
            cur.execute("""INSERT INTO order_items (order_id, book_id, quantity, unit_price)
                           VALUES (%s, %s, %s, %s)""", (order_id, book_id, qty, book["price"]))
            cur.execute("UPDATE books SET stock = stock - %s WHERE book_id = %s", (qty, book_id))

        conn.commit()
        return jsonify({"message": "Order placed", "id": order_id}), 201
    except (ValueError, mysql.connector.Error) as e:
        conn.rollback()
        msg = e.msg if isinstance(e, mysql.connector.Error) else str(e)
        return jsonify({"error": msg}), 400
    finally:
        conn.close()


@app.put("/api/orders/<int:order_id>")
def update_order(order_id):
    status = request.get_json(force=True).get("status")
    _, count = execute("UPDATE orders SET status = %s WHERE order_id = %s", (status, order_id))
    if count == 0 and not query("SELECT 1 FROM orders WHERE order_id=%s", (order_id,)):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"message": "Updated"})


@app.delete("/api/orders/<int:order_id>")
def delete_order(order_id):
    conn = get_conn()
    try:
        conn.start_transaction()
        cur = conn.cursor()
        # Put the books back in stock, then delete (order_items cascade)
        cur.execute("""UPDATE books b JOIN order_items oi ON oi.book_id = b.book_id
                       SET b.stock = b.stock + oi.quantity
                       WHERE oi.order_id = %s""", (order_id,))
        cur.execute("DELETE FROM orders WHERE order_id = %s", (order_id,))
        if cur.rowcount == 0:
            conn.rollback()
            return jsonify({"error": "Not found"}), 404
        conn.commit()
        return jsonify({"message": "Deleted"})
    except mysql.connector.Error as e:
        conn.rollback()
        return jsonify({"error": e.msg}), 400
    finally:
        conn.close()


# ------------------------------------------------------------------
# Report endpoint (uses the book_sales VIEW)
# ------------------------------------------------------------------
@app.get("/api/reports/sales")
def sales_report():
    return jsonify(query("SELECT * FROM book_sales ORDER BY revenue DESC"))


# ------------------------------------------------------------------
# Frontend
# ------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    app.run(debug=True)
