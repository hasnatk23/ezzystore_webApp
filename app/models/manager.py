class ManagerAssignment:
    @staticmethod
    def create_table(db):
        db.execute("""
        CREATE TABLE IF NOT EXISTS managers (
          user_id     INTEGER PRIMARY KEY,
          branch_id   INTEGER NOT NULL UNIQUE,
          created_by  INTEGER NOT NULL,
          created_at  TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (user_id)   REFERENCES users(id)     ON DELETE CASCADE,
          FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE,
          FOREIGN KEY (created_by) REFERENCES users(id)    ON DELETE RESTRICT
        );
        """)

    @staticmethod
    def assign(db, manager_user_id: int, branch_id: int, created_by: int):
        db.execute("""
            INSERT INTO managers (user_id, branch_id, created_by)
            VALUES (?, ?, ?);
        """, (manager_user_id, branch_id, created_by))

    @staticmethod
    def all(db):
        return db.execute("""
            SELECT u.username, u.full_name,
                   b.name AS branch_name,
                   s.name AS shop_name
            FROM managers m
            JOIN users u ON u.id = m.user_id
            JOIN branches b ON b.id = m.branch_id
            JOIN shops s ON s.id = b.shop_id
            ORDER BY u.id DESC;
        """).fetchall()
