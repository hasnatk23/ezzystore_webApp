class ShopSettings:
    @staticmethod
    def create_table(db):
        db.execute("""
        CREATE TABLE IF NOT EXISTS shop_settings (
          shop_id          INTEGER PRIMARY KEY,
          expense_percent  REAL NOT NULL DEFAULT 0,
          updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE
        );
        """)

    @staticmethod
    def get_for_shop(db, shop_id: int):
        row = db.execute(
            "SELECT shop_id, expense_percent FROM shop_settings WHERE shop_id = ?;",
            (shop_id,),
        ).fetchone()
        return row

    @staticmethod
    def set_expense_percent(db, shop_id: int, expense_percent: float):
        db.execute(
            """
            INSERT INTO shop_settings (shop_id, expense_percent, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(shop_id)
            DO UPDATE SET expense_percent = excluded.expense_percent,
                          updated_at = datetime('now');
            """,
            (shop_id, expense_percent),
        )
