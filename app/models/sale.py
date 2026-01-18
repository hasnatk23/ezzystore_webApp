import sqlite3


class Sale:
    @staticmethod
    def create_table(db):
        db.execute("""
        CREATE TABLE IF NOT EXISTS sales (
          id                 INTEGER PRIMARY KEY AUTOINCREMENT,
          shop_id            INTEGER NOT NULL,
          sale_type          TEXT NOT NULL CHECK(sale_type IN ('sale','return')),
          total_amount       REAL NOT NULL DEFAULT 0,
          customer_id        INTEGER,
          reference_sale_id  INTEGER,
          created_at         TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (shop_id)           REFERENCES shops(id) ON DELETE CASCADE,
          FOREIGN KEY (customer_id)       REFERENCES customers(id) ON DELETE SET NULL,
          FOREIGN KEY (reference_sale_id) REFERENCES sales(id) ON DELETE SET NULL
        );
        """)

        # Backfill customer_id column if table already existed.
        try:
            db.execute("ALTER TABLE sales ADD COLUMN customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL;")
        except sqlite3.OperationalError:
            pass
        try:
            db.execute("ALTER TABLE sales ADD COLUMN reference_sale_id INTEGER REFERENCES sales(id) ON DELETE SET NULL;")
        except sqlite3.OperationalError:
            pass

        db.execute("""
        CREATE TABLE IF NOT EXISTS sale_items (
          id                 INTEGER PRIMARY KEY AUTOINCREMENT,
          sale_id            INTEGER NOT NULL,
          product_id         INTEGER NOT NULL,
          quantity           INTEGER NOT NULL,
          unit_price         REAL NOT NULL,
          returned_quantity  INTEGER NOT NULL DEFAULT 0,
          returned_at        TEXT,
          FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE,
          FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );
        """)
        try:
            db.execute("ALTER TABLE sale_items ADD COLUMN returned_quantity INTEGER NOT NULL DEFAULT 0;")
        except sqlite3.OperationalError:
            pass
        try:
            db.execute("ALTER TABLE sale_items ADD COLUMN returned_at TEXT;")
        except sqlite3.OperationalError:
            pass
        db.execute("""
            UPDATE sale_items
            SET returned_quantity = quantity
            WHERE returned_at IS NOT NULL
              AND (returned_quantity IS NULL OR returned_quantity < quantity);
        """)

    @staticmethod
    def record(
        db,
        shop_id: int,
        sale_type: str,
        items: list[dict],
        customer_id: int | None = None,
        reference_sale_id: int | None = None,
    ):
        total_amount = sum(item["quantity"] * item["unit_price"] for item in items)
        cursor = db.execute("""
            INSERT INTO sales (shop_id, sale_type, total_amount, customer_id, reference_sale_id)
            VALUES (?, ?, ?, ?, ?);
        """, (shop_id, sale_type, total_amount, customer_id, reference_sale_id))
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
            SELECT s.*, c.name AS customer_name, c.phone AS customer_phone,
                   ref.created_at AS reference_created_at
            FROM sales s
            LEFT JOIN customers c ON c.id = s.customer_id
            LEFT JOIN sales ref ON ref.id = s.reference_sale_id
            WHERE s.shop_id = ?
            ORDER BY s.created_at DESC
            LIMIT ?;
        """, (shop_id, limit)).fetchall()

        result = []
        for sale in sales:
            rows = db.execute("""
                SELECT si.id, si.product_id, si.quantity, si.unit_price,
                       si.returned_quantity, si.returned_at, p.name AS product_name
                FROM sale_items si
                JOIN products p ON p.id = si.product_id
                WHERE si.sale_id = ?
                ORDER BY si.id ASC;
            """, (sale["id"],)).fetchall()
            items = []
            for row in rows:
                returned_qty = row["returned_quantity"] or 0
                items.append(
                    {
                        "id": row["id"],
                        "product_id": row["product_id"],
                        "quantity": row["quantity"],
                        "unit_price": row["unit_price"],
                        "product_name": row["product_name"],
                        "returned_quantity": returned_qty,
                        "remaining_quantity": max(row["quantity"] - returned_qty, 0),
                        "returned_at": row["returned_at"],
                    }
                )
            result.append({
                "sale": sale,
                "sale_items": items,
            })
        return result

    @staticmethod
    def get_with_items(db, shop_id: int, sale_id: int):
        sale = db.execute("""
            SELECT s.*, c.name AS customer_name, c.phone AS customer_phone,
                   ref.created_at AS reference_created_at
            FROM sales s
            LEFT JOIN customers c ON c.id = s.customer_id
            LEFT JOIN sales ref ON ref.id = s.reference_sale_id
            WHERE s.id=? AND s.shop_id=?
            LIMIT 1;
        """, (sale_id, shop_id)).fetchone()
        if not sale:
            return None, []
        rows = db.execute("""
            SELECT si.id, si.product_id, si.quantity, si.unit_price,
                   si.returned_quantity, si.returned_at, p.name AS product_name
            FROM sale_items si
            JOIN products p ON p.id = si.product_id
            WHERE si.sale_id = ?
            ORDER BY si.id ASC;
        """, (sale_id,)).fetchall()
        items = []
        for row in rows:
            returned_qty = row["returned_quantity"] or 0
            items.append(
                {
                    "id": row["id"],
                    "product_id": row["product_id"],
                    "quantity": row["quantity"],
                    "unit_price": row["unit_price"],
                    "product_name": row["product_name"],
                    "returned_quantity": returned_qty,
                    "remaining_quantity": max(row["quantity"] - returned_qty, 0),
                    "returned_at": row["returned_at"],
                }
            )
        return sale, items

    @staticmethod
    def by_date_with_items(db, shop_id: int, start_date: str, end_date: str):
        sales = db.execute("""
            SELECT s.*, c.name AS customer_name, c.phone AS customer_phone,
                   ref.created_at AS reference_created_at
            FROM sales s
            LEFT JOIN customers c ON c.id = s.customer_id
            LEFT JOIN sales ref ON ref.id = s.reference_sale_id
            WHERE s.shop_id = ?
              AND date(s.created_at) BETWEEN date(?) AND date(?)
            ORDER BY s.created_at DESC;
        """, (shop_id, start_date, end_date)).fetchall()

        detailed = []
        for sale in sales:
            rows = db.execute("""
                SELECT si.id, si.product_id, si.quantity, si.unit_price,
                       si.returned_quantity, si.returned_at, p.name AS product_name
                FROM sale_items si
                JOIN products p ON p.id = si.product_id
                WHERE si.sale_id = ?
                ORDER BY si.id ASC;
            """, (sale["id"],)).fetchall()
            items = []
            for row in rows:
                returned_qty = row["returned_quantity"] or 0
                items.append(
                    {
                        "id": row["id"],
                        "product_id": row["product_id"],
                        "quantity": row["quantity"],
                        "unit_price": row["unit_price"],
                        "product_name": row["product_name"],
                        "returned_quantity": returned_qty,
                        "remaining_quantity": max(row["quantity"] - returned_qty, 0),
                        "returned_at": row["returned_at"],
                    }
                )
            detailed.append(
                {
                    "sale": sale,
                    "sale_items": items,
                }
            )
        return detailed

    @staticmethod
    def daily_summary(db, shop_id: int, start_date: str, end_date: str):
        rows = db.execute("""
            WITH sale_totals AS (
              SELECT
                s.id,
                s.sale_type,
                date(s.created_at) AS sale_date,
                s.total_amount,
                COALESCE(SUM(si.quantity), 0) AS item_count,
                COALESCE(SUM(si.returned_quantity), 0) AS returned_count
              FROM sales s
              LEFT JOIN sale_items si ON si.sale_id = s.id
              WHERE s.shop_id = ?
                AND date(s.created_at) BETWEEN date(?) AND date(?)
              GROUP BY s.id
            )
            SELECT sale_date,
                   sale_type,
                   COUNT(*) AS txn_count,
                   SUM(total_amount) AS total_amount,
                   SUM(item_count) AS item_quantity,
                   SUM(returned_count) AS returned_count
            FROM sale_totals
            GROUP BY sale_date, sale_type
            ORDER BY sale_date DESC;
        """, (shop_id, start_date, end_date)).fetchall()

        summary_map = {}
        for row in rows:
            sale_date = row["sale_date"]
            entry = summary_map.setdefault(
                sale_date,
                {
                    "sale_date": sale_date,
                    "sales_total": 0.0,
                    "returns_total": 0.0,
                    "sale_count": 0,
                    "return_count": 0,
                    "sold_items": 0,
                    "returned_items": 0,
                },
            )
            amount = row["total_amount"] or 0.0
            count = row["txn_count"] or 0
            item_qty = row["item_quantity"] or 0
            if row["sale_type"] == "sale":
                entry["sales_total"] += amount
                entry["sale_count"] += count
                entry["sold_items"] += item_qty
            else:
                entry["returns_total"] += amount
                entry["return_count"] += count
                entry["returned_items"] += item_qty
        summary = list(summary_map.values())
        summary.sort(key=lambda entry: entry["sale_date"], reverse=True)
        return summary
