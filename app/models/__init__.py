from .user import User

def init_models(db):
    User.create_table(db)

    db.execute("""
    CREATE TABLE IF NOT EXISTS shops (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      name        TEXT NOT NULL UNIQUE,
      created_by  INTEGER NOT NULL,
      created_at  TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT
    );
    """)

    # One shop -> one manager (UNIQUE shop_id)
    db.execute("""
    CREATE TABLE IF NOT EXISTS shop_managers (
      shop_id          INTEGER PRIMARY KEY,
      manager_user_id  INTEGER NOT NULL UNIQUE,
      created_by       INTEGER NOT NULL,
      created_at       TEXT NOT NULL DEFAULT (datetime('now')),
      FOREIGN KEY (shop_id)         REFERENCES shops(id) ON DELETE CASCADE,
      FOREIGN KEY (manager_user_id) REFERENCES users(id) ON DELETE CASCADE,
      FOREIGN KEY (created_by)      REFERENCES users(id) ON DELETE RESTRICT
    );
    """)

    User.ensure_default_admin(db)
