class Branch:
    @staticmethod
    def create_table(db):
        db.execute("""
        CREATE TABLE IF NOT EXISTS branches (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          shop_id     INTEGER NOT NULL,
          name        TEXT NOT NULL,
          address     TEXT,
          created_by  INTEGER NOT NULL,
          created_at  TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (shop_id)    REFERENCES shops(id) ON DELETE CASCADE,
          FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT,
          UNIQUE(shop_id, name)
        );
        """)

    @staticmethod
    def create(db, shop_id: int, name: str, address: str, created_by: int):
        db.execute("""
            INSERT INTO branches (shop_id, name, address, created_by)
            VALUES (?, ?, ?, ?);
        """, (shop_id, name.strip(), address.strip(), created_by))

    @staticmethod
    def all_with_shop(db):
        return db.execute("""
            SELECT b.*, s.name AS shop_name
            FROM branches b
            JOIN shops s ON s.id = b.shop_id
            ORDER BY b.id DESC;
        """).fetchall()
