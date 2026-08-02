import sqlite3
import os
import config
import secrets

# ============================================================
# تغيير مسار قاعدة البيانات إلى /tmp (متوافق مع Vercel)
# ============================================================

# في بيئة Vercel، نستخدم /tmp للكتابة
if os.environ.get('VERCEL'):
    DB_PATH = "/tmp/users.db"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            points INTEGER DEFAULT 1,
            invited_by INTEGER DEFAULT NULL,
            invite_count INTEGER DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY,
            banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS gift_links (
            code TEXT PRIMARY KEY,
            points INTEGER NOT NULL,
            max_uses INTEGER NOT NULL,
            used_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    print(f"✅ قاعدة البيانات مهيأة في: {DB_PATH}")

# ============================================================
# باقي الدوال كما هي (بدون تغيير)
# ============================================================

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT points, invited_by, invite_count FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"points": row[0], "invited_by": row[1], "invite_count": row[2]}
    return None

def add_user(user_id, invited_by=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if c.fetchone():
        conn.close()
        return False
    if invited_by and invited_by != user_id:
        c.execute("INSERT INTO users (user_id, points, invited_by) VALUES (?, 1, ?)", (user_id, invited_by))
        c.execute("UPDATE users SET points = points + 1, invite_count = invite_count + 1 WHERE user_id=?", (invited_by,))
    else:
        c.execute("INSERT INTO users (user_id, points) VALUES (?, 1)", (user_id,))
    conn.commit()
    conn.close()
    return True

def add_points(user_id, amount=1):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET points = points + ? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def get_invite_link(user_id):
    return f"https://t.me/{config.BOT_USERNAME}?start=ref_{user_id}"

def has_invited_before(inviter_id, invitee_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=? AND invited_by=?", (invitee_id, inviter_id))
    row = c.fetchone()
    conn.close()
    return row is not None

def get_invited_count(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE invited_by=?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def is_banned(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM banned_users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row is not None

def ban_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM banned_users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_banned_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, banned_at FROM banned_users ORDER BY banned_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def create_gift_link(points, max_uses):
    code = secrets.token_hex(6)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO gift_links (code, points, max_uses) VALUES (?, ?, ?)", (code, points, max_uses))
    conn.commit()
    conn.close()
    return code

def get_gift_info(code):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT points, max_uses, used_count FROM gift_links WHERE code=?", (code,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"points": row[0], "max_uses": row[1], "used_count": row[2]}
    return None

def use_gift(code):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT max_uses, used_count FROM gift_links WHERE code=?", (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    max_uses, used_count = row
    if used_count >= max_uses:
        conn.close()
        return "expired"
    c.execute("UPDATE gift_links SET used_count = used_count + 1 WHERE code=?", (code,))
    conn.commit()
    conn.close()
    return "success"