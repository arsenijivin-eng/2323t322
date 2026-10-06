import sqlite3
from datetime import datetime, timedelta, timezone


class DB:
    def __init__(self, path):
        self.c = sqlite3.connect(path, check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        self.init()

    def init(self):
        self.c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, username TEXT, referrer INTEGER,
          trial_used INTEGER DEFAULT 0, trial_link_taken INTEGER DEFAULT 0,
          expires_at TEXT, balance REAL DEFAULT 0,
          state TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS current_links(
          kind TEXT PRIMARY KEY, link TEXT
        );
        CREATE TABLE IF NOT EXISTS user_links(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER, kind TEXT, link TEXT,
          expires_at TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS orders(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, days INTEGER,
          method TEXT, rub REAL, stars INTEGER, kind TEXT,
          status TEXT DEFAULT 'pending', created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS discount_promos(
          code TEXT PRIMARY KEY, percent INTEGER, uses_left INTEGER
        );
        CREATE TABLE IF NOT EXISTS withdrawals(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL,
          card TEXT, status TEXT DEFAULT 'pending', created_at TEXT
        );
        """)
        for ddl in [
            "ALTER TABLE users ADD COLUMN trial_link_taken INTEGER DEFAULT 0",
            "ALTER TABLE orders ADD COLUMN kind TEXT",
        ]:
            try:
                self.c.execute(ddl)
                self.c.commit()
            except sqlite3.OperationalError:
                pass
        self.c.commit()

    # ---------- USERS ----------

    def user(self, uid, username="", referrer=None):
        r = self.c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not r:
            self.c.execute(
                "INSERT INTO users(id,username,referrer,created_at) VALUES(?,?,?,?)",
                (uid, username, referrer if referrer and referrer != uid else None,
                 datetime.now(timezone.utc).isoformat())
            )
            self.c.commit()
            r = self.c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return r

    def activate_trial(self, uid):
        r = self.user(uid)
        if r["trial_used"]:
            return None
        exp = datetime.now(timezone.utc) + timedelta(days=3)
        self.c.execute(
            "UPDATE users SET trial_used=1, expires_at=? WHERE id=?",
            (exp.isoformat(), uid)
        )
        self.c.commit()
        return exp.isoformat()

    def take_trial_link(self, uid):
        """trial-ссылка — 1 раз. Сохраняет её в user_links на 3 дня."""
        r = self.user(uid)
        if r["trial_link_taken"]:
            return None
        link = self.get_link("trial")
        if not link:
            return None
        exp = datetime.now(timezone.utc) + timedelta(days=3)
        self.c.execute(
            "INSERT INTO user_links(user_id,kind,link,expires_at,created_at) VALUES(?,?,?,?,?)",
            (uid, "trial", link, exp.isoformat(), datetime.now(timezone.utc).isoformat())
        )
        self.c.execute("UPDATE users SET trial_link_taken=1 WHERE id=?", (uid,))
        self.c.commit()
        return link, exp.isoformat()

    def balance(self, uid):
        r = self.user(uid)
        return float(r["balance"] or 0)

    # ---------- CURRENT LINKS ----------

    def set_link(self, kind, link):
        self.c.execute(
            "INSERT OR REPLACE INTO current_links(kind,link) VALUES(?,?)",
            (kind, link.strip())
        )
        self.c.commit()

    def get_link(self, kind):
        r = self.c.execute("SELECT link FROM current_links WHERE kind=?", (kind,)).fetchone()
        return r["link"] if r else None

    def all_links(self):
        rows = self.c.execute("SELECT kind,link FROM current_links").fetchall()
        return {r["kind"]: r["link"] for r in rows}

    # ---------- USER LINKS ----------

    def add_user_link(self, uid, kind, link, days):
        """Выдаёт юзеру ссылку и продлевает подписку на N дней."""
        r = self.user(uid)
        now = datetime.now(timezone.utc)
        if r["expires_at"]:
            cur = datetime.fromisoformat(r["expires_at"])
            base = cur if cur > now else now
        else:
            base = now
        new_exp = base + timedelta(days=days)
        self.c.execute("UPDATE users SET expires_at=? WHERE id=?", (new_exp.isoformat(), uid))
        self.c.execute(
            "INSERT INTO user_links(user_id,kind,link,expires_at,created_at) VALUES(?,?,?,?,?)",
            (uid, kind, link, new_exp.isoformat(), now.isoformat())
        )
        self.c.commit()
        return new_exp.isoformat()

    def get_active_user_link(self, uid):
        now = datetime.now(timezone.utc).isoformat()
        return self.c.execute(
            "SELECT * FROM user_links WHERE user_id=? AND expires_at>? "
            "ORDER BY id DESC LIMIT 1",
            (uid, now)
        ).fetchone()

    # ---------- ORDERS ----------

    def create_order(self, uid, days, method, rub, stars, kind=""):
        self.c.execute(
            "INSERT INTO orders(user_id,days,method,rub,stars,kind,created_at) VALUES(?,?,?,?,?,?,?)",
            (uid, days, method, rub, stars, kind, datetime.now(timezone.utc).isoformat())
        )
        self.c.commit()
        return self.c.execute("SELECT last_insert_rowid()").fetchone()[0]

    # ---------- STATE ----------

    def set_state(self, uid, state):
        self.user(uid)
        self.c.execute("UPDATE users SET state=? WHERE id=?", (state, uid))
        self.c.commit()

    def clear_state(self, uid):
        self.set_state(uid, None)

    def get_state(self, uid):
        r = self.user(uid)
        return r["state"]

    # ---------- PROMO ----------

    def add_discount_promo(self, code, percent, uses):
        self.c.execute(
            "INSERT OR REPLACE INTO discount_promos(code,percent,uses_left) VALUES(?,?,?)",
            (code.strip(), percent, uses)
        )
        self.c.commit()

    def check_discount_promo(self, code):
        r = self.c.execute(
            "SELECT * FROM discount_promos WHERE code=? AND uses_left>0", (code.strip(),)
        ).fetchone()
        return int(r["percent"]) if r else None

    def use_discount_promo(self, code):
        self.c.execute(
            "UPDATE discount_promos SET uses_left=uses_left-1 WHERE code=?", (code.strip(),)
        )
        self.c.commit()

    # ---------- STATS ----------

    def all_user_ids(self):
        return [r["id"] for r in self.c.execute("SELECT id FROM users").fetchall()]

    def find_user(self, query):
        r = None
        if query.isdigit():
            r = self.c.execute("SELECT * FROM users WHERE id=?", (int(query),)).fetchone()
        else:
            r = self.c.execute(
                "SELECT * FROM users WHERE lower(username)=lower(?)", (query,)
            ).fetchone()
        if not r:
            return "❌ Пользователь не найден."
        refs = self.c.execute(
            "SELECT COUNT(*) n FROM users WHERE referrer=?", (r["id"],)
        ).fetchone()["n"]
        purchases = self.c.execute(
            "SELECT COUNT(*) n FROM orders WHERE user_id=? AND status='paid'", (r["id"],)
        ).fetchone()["n"]
        exp = r["expires_at"] or "—"
        return (
            f"👤 Пользователь\n\nID: {r['id']}\nUsername: @{r['username'] or 'нет'}\n"
            f"👥 Приглашено: {refs}\n🛒 Покупок: {purchases}\n"
            f"💰 Баланс: {float(r['balance'] or 0):.2f}₽\n"
            f"⏳ Подписка до: {exp}"
        )

    def stats_detailed(self):
        total = self.c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        trials = self.c.execute("SELECT COUNT(*) n FROM users WHERE trial_used=1").fetchone()["n"]
        active = self.c.execute(
            "SELECT COUNT(*) n FROM users WHERE expires_at IS NOT NULL AND expires_at>?",
            (datetime.now(timezone.utc).isoformat(),)
        ).fetchone()["n"]
        orders = self.c.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
        paid = self.c.execute("SELECT COUNT(*) n FROM orders WHERE status='paid'").fetchone()["n"]
        revenue = self.c.execute(
            "SELECT COALESCE(SUM(rub),0) s FROM orders WHERE status='paid'"
        ).fetchone()["s"]
        refs = self.c.execute("SELECT COUNT(*) n FROM users WHERE referrer IS NOT NULL").fetchone()["n"]
        return (
            f"📊 Статистика CristyVPN\n\n👥 Зашли в бота: {total}\n"
            f"🎁 Взяли пробный период: {trials}\n🟢 Активных подписок: {active}\n"
            f"🛒 Заказов: {orders}\n✅ Оплаченных: {paid}\n"
            f"💰 Выручка: {float(revenue or 0):.2f}₽\n"
            f"👥 Пользователей с рефералами: {refs}"
        )

    def purchases_stats(self):
        rows = self.c.execute(
            "SELECT days, COUNT(*) n, COALESCE(SUM(rub),0) s FROM orders "
            "WHERE status='paid' GROUP BY days ORDER BY days"
        ).fetchall()
        if not rows:
            return "📈 Покупок пока нет."
        lines = ["📈 Статистика покупок\n"]
        for r in rows:
            lines.append(f"▸ {r['days']} дней: {r['n']} покупок • {float(r['s']):.2f}₽")
        total = self.c.execute("SELECT COUNT(*) n FROM orders WHERE status='paid'").fetchone()["n"]
        lines.append(f"\nВсего оплачено заказов: {total}")
        return "\n".join(lines)

    def users_page(self):
        rows = self.c.execute(
            "SELECT id,username,trial_used,expires_at,balance FROM users ORDER BY id DESC LIMIT 30"
        ).fetchall()
        if not rows:
            return "👥 Пользователей пока нет."
        out = ["👥 Последние 30 пользователей\n"]
        for r in rows:
            out.append(
                f"ID {r['id']} • @{r['username'] or 'нет'} • "
                f"пробник={'да' if r['trial_used'] else 'нет'} • баланс={float(r['balance'] or 0):.2f}₽"
            )
        return "\n".join(out)

    def withdraws_text(self):
        rows = self.c.execute("SELECT * FROM withdrawals ORDER BY id DESC LIMIT 20").fetchall()
        if not rows:
            return "💸 Заявок на вывод пока нет."
        return "💸 Последние выводы:\n\n" + "\n".join(
            f"#{r['id']} • ID {r['user_id']} • {r['amount']}₽ • {r['status']}"
            for r in rows
        )