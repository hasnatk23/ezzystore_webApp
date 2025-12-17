class Sale:
    @staticmethod
    def create_table(db):
        db.execute("""
        CREATE TABLE IF NOT EXISTS sales (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          shop_id      INTEGER NOT NULL,
          sale_type    TEXT NOT NULL CHECK(sale_type IN ('sale','return')),
          total_amount REAL NOT NULL DEFAULT 0,
          created_at   TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE
        );
        """)

        db.execute("""
        CREATE TABLE IF NOT EXISTS sale_items (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          sale_id     INTEGER NOT NULL,
          product_id  INTEGER NOT NULL,
          quantity    INTEGER NOT NULL,
          unit_price  REAL NOT NULL,
          FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE,
          FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );
        """)

    @staticmethod
    def record(db, shop_id: int, sale_type: str, items: list[dict]):
        total_amount = sum(item["quantity"] * item["unit_price"] for item in items)
        cursor = db.execute("""
            INSERT INTO sales (shop_id, sale_type, total_amount)
            VALUES (?, ?, ?);
        """, (shop_id, sale_type, total_amount))
        sale_id = cursor.lastrowid

        for item in items:
            db.execute("""
                INSERT INTO sale_items (sale_id, product_id, quantity, unit_price)
                VALUES (?, ?, ?, ?);
            """, (sale_id, item["product_id"], item["quantity"], item["unit_price"]))
        return sale_id

    @staticmethod
    def recent_with_items(db, shop_id: int, limit: int = 5):
        sales = db.execute("""
            SELECT * FROM sales
            WHERE shop_id = ?
            ORDER BY created_at DESC
            LIMIT ?;
        """, (shop_id, limit)).fetchall()

        result = []
        for sale in sales:
            rows = db.execute("""
                SELECT si.id, si.product_id, si.quantity, si.unit_price, p.name AS product_name
                FROM sale_items si
                JOIN products p ON p.id = si.product_id
                WHERE si.sale_id = ?
                ORDER BY si.id ASC;
            """, (sale["id"],)).fetchall()
            items = [
                {
                    "id": row["id"],
                    "product_id": row["product_id"],
                    "quantity": row["quantity"],
                    "unit_price": row["unit_price"],
                    "product_name": row["product_name"],
                }
                for row in rows
            ]
            result.append({
                "sale": sale,
                "sale_items": items,
            })
        return result

    @staticmethod
    def get_with_items(db, shop_id: int, sale_id: int):
        sale = db.execute("""
            SELECT * FROM sales
            WHERE id=? AND shop_id=?
            LIMIT 1;
        """, (sale_id, shop_id)).fetchone()
        if not sale:
            return None, []
        rows = db.execute("""
            SELECT si.id, si.product_id, si.quantity, si.unit_price, p.name AS product_name
            FROM sale_items si
            JOIN products p ON p.id = si.product_id
            WHERE si.sale_id = ?
            ORDER BY si.id ASC;
        """, (sale_id,)).fetchall()
        items = [
            {
                "id": row["id"],
                "product_id": row["product_id"],
                "quantity": row["quantity"],
                "unit_price": row["unit_price"],
                "product_name": row["product_name"],
            }
            for row in rows
        ]
        return sale, items
