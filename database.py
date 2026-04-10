# -*- coding: utf-8 -*-
"""SQLite: пользователи, баланс, рефералы, покупки, платежи, промокоды."""

import json
import secrets
import sqlite3
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "data" / "bot.db"


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS referrals (
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL,
                has_purchased INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (referrer_id, referred_id),
                FOREIGN KEY (referrer_id) REFERENCES users(user_id),
                FOREIGN KEY (referred_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                order_number TEXT NOT NULL,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                amount INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                pally_order_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS promocodes (
                code TEXT PRIMARY KEY,
                bonus_amount INTEGER NOT NULL DEFAULT 0,
                max_uses INTEGER NOT NULL DEFAULT 1,
                used_count INTEGER NOT NULL DEFAULT 0,
                valid_until TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS promo_used (
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                used_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, code),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (code) REFERENCES promocodes(code)
            );
        """)
        conn.commit()
        # Колонка для bill_id из Pally (нужна для проверки статуса)
        try:
            conn.execute("ALTER TABLE payments ADD COLUMN pally_bill_id TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        # Товары: category = neural | avto, activation_type = email | account
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                price INTEGER NOT NULL,
                activation_type TEXT NOT NULL DEFAULT 'account',
                image_file_id TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS tariffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                price INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            CREATE TABLE IF NOT EXISTS product_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                account_data TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                used_at TEXT,
                order_id TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_id INTEGER,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                tariff_id INTEGER,
                quantity INTEGER NOT NULL DEFAULT 1,
                amount INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
        """)
        conn.commit()
        for col in ("discount_type", "discount_value"):
            try:
                conn.execute(f"ALTER TABLE promocodes ADD COLUMN {col} TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute("ALTER TABLE product_accounts ADD COLUMN item_type TEXT DEFAULT 'account'")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE product_accounts ADD COLUMN tariff_id INTEGER REFERENCES tariffs(id)")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE product_accounts ADD COLUMN admin_note TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        for col in ("description", "image_file_id"):
            try:
                conn.execute(f"ALTER TABLE tariffs ADD COLUMN {col} TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute("ALTER TABLE products ADD COLUMN instruction TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE purchases ADD COLUMN email_data TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE purchases ADD COLUMN status TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE purchases ADD COLUMN thank_review_sent INTEGER DEFAULT 0")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE products ADD COLUMN activation_prompt TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        for col, default in (("instruction_images", "[]"), ("activation_prompt_images", "[]")):
            try:
                conn.execute(f"ALTER TABLE products ADD COLUMN {col} TEXT DEFAULT '{default}'")
                conn.commit()
            except sqlite3.OperationalError:
                pass
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS support_faq (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_key TEXT NOT NULL,
                question_text TEXT NOT NULL,
                answer_text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS account_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                issued_count INTEGER NOT NULL DEFAULT 0,
                notification_chat_id INTEGER,
                notification_message_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
        """)
        conn.commit()
        conn.execute(
            "INSERT OR IGNORE INTO promocodes (code, bonus_amount, max_uses) VALUES ('WELCOME', 50, 100)",
        )
        conn.commit()
    finally:
        conn.close()
    logger.info("DB initialized: %s", DB_PATH)


def get_all_user_ids() -> list[int]:
    """Все user_id для рассылки."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT user_id FROM users").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def ensure_user(user_id: int, username: Optional[str] = None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (user_id, username) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET username = COALESCE(?, username)",
            (user_id, username or "", username or ""),
        )
        conn.commit()
    finally:
        conn.close()


def get_user(user_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT user_id, username, balance FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        return {"user_id": row[0], "username": row[1] or "", "balance": row[2]}
    finally:
        conn.close()


def get_balance(user_id: int) -> int:
    u = get_user(user_id)
    return (u["balance"] or 0) if u else 0


def add_balance(user_id: int, amount: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
    finally:
        conn.close()


def clear_referrals() -> None:
    """Очистить всю таблицу рефералов (при смене логики программы)."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM referrals")
        conn.commit()
    finally:
        conn.close()


def get_referral_stats(user_id: int) -> tuple[int, int]:
    """Возвращает (всего приглашённых, 0). Второе значение не используется (бонус за пополнения)."""
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,)).fetchone()[0] or 0
        return (count, 0)
    finally:
        conn.close()


def get_referrer_id(referred_id: int) -> Optional[int]:
    """ID пользователя, который привёл referred_id (или None)."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT referrer_id FROM referrals WHERE referred_id = ?", (referred_id,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_referral_discount_percent(user_id: int) -> int:
    """Скидка от реферальной программы: не используется (бонус только за пополнения приглашённых)."""
    return 0


def add_referral(referrer_id: int, referred_id: int) -> None:
    if referrer_id == referred_id:
        return
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)",
            (referrer_id, referred_id),
        )
        conn.commit()
    finally:
        conn.close()


# --- Поддержка: FAQ по темам (product_key: gemini, capcut, cursor, ...) ---
def clear_support_faq() -> int:
    """Удалить все вопросы и ответы из раздела поддержки. Возвращает количество удалённых строк."""
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM support_faq")
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def add_support_faq(product_key: str, question_text: str, answer_text: str) -> int:
    """Добавить вопрос-ответ в FAQ. Возвращает id записи."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO support_faq (product_key, question_text, answer_text) VALUES (?, ?, ?)",
            (product_key.strip(), question_text.strip(), answer_text.strip()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_support_faq_by_product(product_key: str) -> list[dict]:
    """Список FAQ по ключу темы (id, question_text, answer_text)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, question_text, answer_text FROM support_faq WHERE product_key = ? ORDER BY id",
            (product_key.strip(),),
        ).fetchall()
        return [{"id": r[0], "question_text": r[1], "answer_text": r[2]} for r in rows]
    finally:
        conn.close()


def get_support_faq_by_id(faq_id: int) -> Optional[dict]:
    """Один FAQ по id (для показа ответа)."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, product_key, question_text, answer_text FROM support_faq WHERE id = ?",
            (faq_id,),
        ).fetchone()
        if not row:
            return None
        return {"id": row[0], "product_key": row[1], "question_text": row[2], "answer_text": row[3]}
    finally:
        conn.close()


def get_all_support_faq() -> list[dict]:
    """Все вопросы-ответы FAQ (id, product_key, question_text, answer_text), по product_key и id."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, product_key, question_text, answer_text FROM support_faq ORDER BY product_key, id",
        ).fetchall()
        return [
            {"id": r[0], "product_key": r[1], "question_text": r[2], "answer_text": r[3]}
            for r in rows
        ]
    finally:
        conn.close()


def update_support_faq(faq_id: int, question_text: str, answer_text: str) -> bool:
    """Обновить вопрос и ответ. Возвращает True если запись найдена."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE support_faq SET question_text = ?, answer_text = ? WHERE id = ?",
            (question_text.strip(), answer_text.strip(), faq_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_support_faq(faq_id: int) -> bool:
    """Удалить вопрос-ответ по id. Возвращает True если запись найдена."""
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM support_faq WHERE id = ?", (faq_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def add_purchase(user_id: int, product_name: str, quantity: int, amount: int) -> int:
    """Создать заказ. order_number устанавливается равным id (числовой номер). Возвращает id заказа."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO purchases (user_id, order_number, product_name, quantity, amount) VALUES (?, '0', ?, ?, ?)",
            (user_id, product_name, quantity, amount),
        )
        pid = cur.lastrowid
        conn.execute("UPDATE purchases SET order_number = ? WHERE id = ?", (str(pid), pid))
        conn.commit()
        return pid
    finally:
        conn.close()


def set_purchase_email_data(order_number: str, email_data: str) -> None:
    """Сохранить почту и пароль клиента для заказа «на мою почту»."""
    conn = get_connection()
    try:
        conn.execute("UPDATE purchases SET email_data = ? WHERE order_number = ?", (email_data.strip(), order_number))
        conn.commit()
    finally:
        conn.close()


def set_purchase_status(purchase_id: int, status: str) -> None:
    """Статус заказа «на почту»: new, in_progress, activated."""
    conn = get_connection()
    try:
        conn.execute("UPDATE purchases SET status = ? WHERE id = ?", (status.strip(), purchase_id))
        conn.commit()
    finally:
        conn.close()


def get_purchase_by_id(purchase_id: int) -> Optional[dict]:
    """Заказ по id (user_id, status, product_name, order_number, thank_review_sent) для уведомлений."""
    conn = get_connection()
    try:
        try:
            row = conn.execute(
                """SELECT user_id, order_number, product_name, COALESCE(status, ''), COALESCE(thank_review_sent, 0)
                   FROM purchases WHERE id = ?""",
                (purchase_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = conn.execute(
                "SELECT user_id, order_number, product_name, COALESCE(status, '') FROM purchases WHERE id = ?",
                (purchase_id,),
            ).fetchone()
            row = (row[0], row[1], row[2], row[3], 0) if row else None
        if not row:
            return None
        return {
            "user_id": row[0],
            "order_number": row[1],
            "product_name": row[2],
            "status": (row[3] or "").strip(),
            "thank_review_sent": (row[4] or 0) if len(row) > 4 else 0,
        }
    finally:
        conn.close()


def set_purchase_thank_review_sent(purchase_id: int) -> None:
    """Отметить, что клиенту отправлено сообщение с благодарностью и запросом отзыва."""
    conn = get_connection()
    try:
        conn.execute("UPDATE purchases SET thank_review_sent = 1 WHERE id = ?", (purchase_id,))
        conn.commit()
    finally:
        conn.close()


def get_purchase_detail(purchase_id: int, user_id: int) -> Optional[dict]:
    """Детали одного заказа: дата, данные аккаунта (или email_data), стоимость, название. None если не найден или не свой."""
    conn = get_connection()
    try:
        try:
            row = conn.execute(
                """SELECT id, order_number, product_name, quantity, amount, created_at,
                   COALESCE(email_data, ''), COALESCE(status, '') FROM purchases WHERE id = ? AND user_id = ?""",
                (purchase_id, user_id),
            ).fetchone()
        except sqlite3.OperationalError:
            row = conn.execute(
                """SELECT id, order_number, product_name, quantity, amount, created_at,
                   COALESCE(email_data, '') FROM purchases WHERE id = ? AND user_id = ?""",
                (purchase_id, user_id),
            ).fetchone()
            row = row + ("",) if row else None
        if not row:
            return None
        order_number = row[1]
        # Данные аккаунтов по этому заказу (order_id в product_accounts = order_number)
        acc_rows = conn.execute(
            "SELECT account_data, COALESCE(item_type, 'account'), COALESCE(admin_note, '') FROM product_accounts WHERE order_id = ?",
            (order_number,),
        ).fetchall()
        accounts = [
            {"account_data": r[0], "item_type": (r[1] or "account").strip() or "account", "admin_note": (r[2] or "").strip()}
            for r in acc_rows
        ]
        return {
            "id": row[0],
            "order_number": order_number,
            "product_name": row[2],
            "quantity": row[3],
            "amount": row[4],
            "created_at": row[5][:16] if row[5] else "",
            "email_data": (row[6] or "").strip(),
            "status": (row[7] or "").strip() if len(row) > 7 else "",
            "accounts": accounts,
        }
    finally:
        conn.close()


def get_purchases(user_id: int, limit: int = 5, offset: int = 0) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, order_number, product_name, quantity, amount, created_at
               FROM purchases WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (user_id, limit, offset),
        ).fetchall()
        return [
            {
                "id": r[0],
                "order_number": r[1],
                "product_name": r[2],
                "quantity": r[3],
                "amount": r[4],
                "created_at": r[5][:16] if r[5] else "",
            }
            for r in rows
        ]
    finally:
        conn.close()


def count_purchases(user_id: int) -> int:
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM purchases WHERE user_id = ?", (user_id,)).fetchone()[0]
    finally:
        conn.close()


def create_payment(user_id: int, amount: int, order_id: str, bill_id: Optional[str] = None) -> int:
    """order_id — наш идентификатор (topup_...), bill_id — id счёта из Pally (для проверки статуса)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO payments (user_id, amount, pally_order_id, pally_bill_id, status) VALUES (?, ?, ?, ?, 'pending')",
            (user_id, amount, order_id, bill_id or ""),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_payment_by_order_id(order_id: str) -> Optional[dict]:
    """Найти платёж по нашему order_id (pally_order_id). Возвращает id, user_id, amount, status, pally_bill_id, created_at."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, user_id, amount, status, pally_bill_id, created_at FROM payments WHERE pally_order_id = ?",
            (order_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "user_id": row[1],
            "amount": row[2],
            "status": row[3],
            "pally_bill_id": row[4] if len(row) > 4 else None,
            "created_at": row[5] if len(row) > 5 else None,
        }
    finally:
        conn.close()


def set_payment_paid(payment_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE payments SET status = 'paid' WHERE id = ?", (payment_id,))
        conn.commit()
    finally:
        conn.close()


def get_promocode(code: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT code, bonus_amount, max_uses, used_count, valid_until FROM promocodes WHERE code = ?",
            (code.strip().upper(),),
        ).fetchone()
        if not row:
            return None
        from datetime import datetime
        valid_until = row[4]
        if valid_until and datetime.fromisoformat(valid_until) < datetime.utcnow():
            return None
        if row[3] >= row[2]:
            return None
        return {"code": row[0], "bonus_amount": row[1], "max_uses": row[2], "used_count": row[3]}
    finally:
        conn.close()


def get_promocodes_list_unused() -> list[dict]:
    """Промокоды, у которых ещё есть активации (used_count < max_uses)."""
    conn = get_connection()
    try:
        try:
            rows = conn.execute(
                """SELECT code, bonus_amount, max_uses, used_count, discount_type, discount_value
                   FROM promocodes WHERE used_count < max_uses ORDER BY created_at DESC""",
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT code, bonus_amount, max_uses, used_count FROM promocodes WHERE used_count < max_uses ORDER BY created_at DESC",
            ).fetchall()
            rows = [(*r, None, None) for r in rows]
        out = []
        for r in rows:
            code, bonus_amount, max_uses, used_count = r[0], r[1], r[2], r[3]
            discount_type = r[4] if len(r) > 4 else None
            discount_value = r[5] if len(r) > 5 else None
            if discount_type == "percent" and discount_value is not None:
                promo_type, value = "percent", discount_value
            else:
                promo_type, value = "fixed", bonus_amount
            out.append({
                "code": code,
                "promo_type": promo_type,
                "value": value,
                "max_uses": max_uses,
                "used_count": used_count,
            })
        return out
    finally:
        conn.close()


def use_promocode(user_id: int, code: str) -> tuple[bool, int]:
    """Применить промокод: начислить бонус. Возвращает (успех, сумма бонуса)."""
    code_upper = code.strip().upper()
    promo = get_promocode(code_upper)
    if not promo:
        return False, 0
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO promo_used (user_id, code) VALUES (?, ?)", (user_id, code_upper))
        if conn.total_changes == 0:
            return False, 0  # уже использовал
        bonus = promo["bonus_amount"]
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, user_id))
        conn.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?", (code_upper,))
        conn.commit()
        return True, bonus
    finally:
        conn.close()


# --- Товары, тарифы, аккаунты ---

def add_product(category: str, name: str, description: str, price: int, activation_type: str, image_file_id: str = "") -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO products (category, name, description, price, activation_type, image_file_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (category, name, description, price, activation_type, image_file_id or ""),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def add_tariff(product_id: int, name: str, price: Optional[int] = None, description: Optional[str] = None, image_file_id: Optional[str] = None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tariffs (product_id, name, price, description, image_file_id) VALUES (?, ?, ?, ?, ?)",
            (product_id, name, price, description or "", image_file_id or ""),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _images_to_db(value) -> str:
    """Список file_id в JSON-строку для хранения в БД."""
    if value is None:
        return "[]"
    if isinstance(value, list):
        return json.dumps([str(x) for x in value])
    if isinstance(value, str):
        return value.strip() if value.strip() else "[]"
    return "[]"


def update_product(
    product_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    price: Optional[int] = None,
    activation_type: Optional[str] = None,
    image_file_id: Optional[str] = None,
    instruction: Optional[str] = None,
    activation_prompt: Optional[str] = None,
    instruction_images: Optional[list] = None,
    activation_prompt_images: Optional[list] = None,
) -> None:
    """Обновить поля товара (передавать только те, что меняются). instruction_images/activation_prompt_images — списки file_id фото."""
    conn = get_connection()
    try:
        updates, vals = [], []
        if name is not None:
            updates.append("name = ?")
            vals.append(name)
        if description is not None:
            updates.append("description = ?")
            vals.append(description)
        if price is not None:
            updates.append("price = ?")
            vals.append(price)
        if activation_type is not None:
            updates.append("activation_type = ?")
            vals.append(activation_type)
        if image_file_id is not None:
            updates.append("image_file_id = ?")
            vals.append(image_file_id)
        if instruction is not None:
            updates.append("instruction = ?")
            vals.append(instruction)
        if activation_prompt is not None:
            updates.append("activation_prompt = ?")
            vals.append(activation_prompt)
        if instruction_images is not None:
            updates.append("instruction_images = ?")
            vals.append(_images_to_db(instruction_images))
        if activation_prompt_images is not None:
            updates.append("activation_prompt_images = ?")
            vals.append(_images_to_db(activation_prompt_images))
        if not updates:
            return
        vals.append(product_id)
        conn.execute(f"UPDATE products SET {', '.join(updates)} WHERE id = ?", vals)
        conn.commit()
    finally:
        conn.close()


def update_tariff(
    tariff_id: int,
    name: Optional[str] = None,
    price: Optional[int] = None,
    description: Optional[str] = None,
    image_file_id: Optional[str] = None,
) -> None:
    conn = get_connection()
    try:
        updates, vals = [], []
        if name is not None:
            updates.append("name = ?")
            vals.append(name)
        if price is not None:
            updates.append("price = ?")
            vals.append(price)
        if description is not None:
            updates.append("description = ?")
            vals.append(description)
        if image_file_id is not None:
            updates.append("image_file_id = ?")
            vals.append(image_file_id)
        if not updates:
            return
        vals.append(tariff_id)
        conn.execute(f"UPDATE tariffs SET {', '.join(updates)} WHERE id = ?", vals)
        conn.commit()
    finally:
        conn.close()


def set_product_account_tariff(account_id: int, tariff_id: int) -> None:
    """Привязать запись склада к тарифу (после создания тарифа)."""
    conn = get_connection()
    try:
        try:
            conn.execute("UPDATE product_accounts SET tariff_id = ? WHERE id = ?", (tariff_id, account_id))
        except sqlite3.OperationalError:
            pass  # колонка tariff_id может отсутствовать в старых БД
        conn.commit()
    finally:
        conn.close()


def delete_tariff(tariff_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM tariffs WHERE id = ?", (tariff_id,))
        conn.commit()
    finally:
        conn.close()


def delete_product(product_id: int) -> None:
    """Удалить товар, его тарифы и записи склада."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM product_accounts WHERE product_id = ?", (product_id,))
        conn.execute("DELETE FROM tariffs WHERE product_id = ?", (product_id,))
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()
    finally:
        conn.close()


def _parse_images_json(s: Optional[str]) -> list:
    """Разобрать JSON-строку со списком file_id в list."""
    if not s or not (s := s.strip()):
        return []
    try:
        out = json.loads(s)
        return [str(x) for x in out] if isinstance(out, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def get_product(product_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        try:
            row = conn.execute(
                """SELECT id, category, name, description, price, activation_type, image_file_id,
                   instruction, COALESCE(activation_prompt,''), COALESCE(instruction_images,'[]'), COALESCE(activation_prompt_images,'[]')
                   FROM products WHERE id = ?""",
                (product_id,),
            ).fetchone()
            instruction = row[7] if row and len(row) > 7 else ""
            activation_prompt = row[8] if row and len(row) > 8 else ""
            instruction_images = _parse_images_json(row[9] if row and len(row) > 9 else None)
            activation_prompt_images = _parse_images_json(row[10] if row and len(row) > 10 else None)
        except sqlite3.OperationalError:
            row = conn.execute(
                "SELECT id, category, name, description, price, activation_type, image_file_id, instruction, COALESCE(activation_prompt,'') FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()
            instruction = row[7] if row and len(row) > 7 else ""
            activation_prompt = row[8] if row and len(row) > 8 else ""
            instruction_images = []
            activation_prompt_images = []
        if not row:
            return None
        return {
            "id": row[0], "category": row[1], "name": row[2], "description": row[3] or "",
            "price": row[4], "activation_type": row[5], "image_file_id": row[6] or "",
            "instruction": instruction or "",
            "activation_prompt": activation_prompt or "",
            "instruction_images": instruction_images,
            "activation_prompt_images": activation_prompt_images,
        }
    finally:
        conn.close()


def get_all_products() -> list[dict]:
    """Все товары для админки (id, name, category, price, activation_type)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, category, price, activation_type FROM products ORDER BY category, id",
        ).fetchall()
        return [{"id": r[0], "name": r[1], "category": r[2], "price": r[3], "activation_type": r[4]} for r in rows]
    finally:
        conn.close()


def get_products_by_category(category: str) -> list[dict]:
    """Товары для каталога. neural = только активация на почту, avto = только автовыдача (без синхронизации)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, price, activation_type FROM products WHERE category = ? ORDER BY id",
            (category,),
        ).fetchall()
        return [{"id": r[0], "name": r[1], "price": r[2], "activation_type": r[3]} for r in rows]
    finally:
        conn.close()


def get_products_for_autovydacha() -> list[dict]:
    """Товары с автовыдачей (activation_type = 'account') для выбора в «Запросить аккаунт»."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name FROM products WHERE activation_type = 'account' ORDER BY category, name",
        ).fetchall()
        return [{"id": r[0], "name": r[1]} for r in rows]
    finally:
        conn.close()


def get_tariffs(product_id: int) -> list[dict]:
    conn = get_connection()
    try:
        try:
            rows = conn.execute(
                "SELECT id, name, price, description, image_file_id FROM tariffs WHERE product_id = ? ORDER BY id",
                (product_id,),
            ).fetchall()
            return [{"id": r[0], "name": r[1], "price": r[2], "description": (r[3] or "") if len(r) > 3 else "", "image_file_id": (r[4] or "") if len(r) > 4 else ""} for r in rows]
        except sqlite3.OperationalError:
            rows = conn.execute("SELECT id, name, price FROM tariffs WHERE product_id = ? ORDER BY id", (product_id,)).fetchall()
            return [{"id": r[0], "name": r[1], "price": r[2], "description": "", "image_file_id": ""} for r in rows]
    finally:
        conn.close()


def count_product_accounts_available(product_id: int, tariff_id: Optional[int] = None) -> int:
    conn = get_connection()
    try:
        if tariff_id is not None:
            return conn.execute(
                "SELECT COUNT(*) FROM product_accounts WHERE product_id = ? AND used = 0 AND (tariff_id IS NULL OR tariff_id = ?)",
                (product_id, tariff_id),
            ).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM product_accounts WHERE product_id = ? AND used = 0", (product_id,)).fetchone()[0]
    finally:
        conn.close()


def get_products_with_stock() -> list[dict]:
    """Все товары с количеством в наличии и общим количеством аккаунтов (для раздела «Склад»)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT p.id, p.name, p.category, p.activation_type,
               (SELECT COUNT(*) FROM product_accounts a WHERE a.product_id = p.id AND a.used = 0),
               (SELECT COUNT(*) FROM product_accounts a WHERE a.product_id = p.id)
               FROM products p ORDER BY p.category, p.id"""
        ).fetchall()
        return [
            {"id": r[0], "name": r[1], "category": r[2], "activation_type": r[3], "available": r[4], "total": r[5]}
            for r in rows
        ]
    finally:
        conn.close()


def get_product_accounts_unused(product_id: int, limit: int = 500) -> list[dict]:
    """Неиспользованные аккаунты товара (id, account_data, item_type)."""
    conn = get_connection()
    try:
        try:
            rows = conn.execute(
                "SELECT id, account_data, COALESCE(item_type, 'account') FROM product_accounts WHERE product_id = ? AND used = 0 ORDER BY id LIMIT ?",
                (product_id, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT id, account_data FROM product_accounts WHERE product_id = ? AND used = 0 ORDER BY id LIMIT ?",
                (product_id, limit),
            ).fetchall()
            rows = [(r[0], r[1], "account") for r in rows]
        return [{"id": r[0], "account_data": r[1], "item_type": (r[2] or "account").strip() or "account"} for r in rows]
    finally:
        conn.close()


def count_product_accounts_used(product_id: int) -> int:
    """Количество использованных аккаунтов по товару."""
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM product_accounts WHERE product_id = ? AND used = 1", (product_id,)).fetchone()[0]
    finally:
        conn.close()


def get_product_accounts_used(product_id: int, limit: int = 500) -> list[dict]:
    """Использованные аккаунты товара (id, account_data, item_type, used_at, order_id)."""
    conn = get_connection()
    try:
        try:
            rows = conn.execute(
                """SELECT id, account_data, COALESCE(item_type, 'account'), COALESCE(used_at, ''), COALESCE(order_id, '')
                   FROM product_accounts WHERE product_id = ? AND used = 1 ORDER BY used_at DESC LIMIT ?""",
                (product_id, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT id, account_data, used_at, order_id FROM product_accounts WHERE product_id = ? AND used = 1 ORDER BY used_at DESC LIMIT ?",
                (product_id, limit),
            ).fetchall()
            rows = [(r[0], r[1], "account", r[2] or "", r[3] or "") for r in rows]
        return [
            {"id": r[0], "account_data": r[1], "item_type": (r[2] or "account").strip() or "account", "used_at": r[3], "order_id": r[4]}
            for r in rows
        ]
    finally:
        conn.close()


def get_product_account_by_id(account_id: int) -> Optional[dict]:
    """Один аккаунт по id (product_id, account_data, item_type, used, used_at, order_id, admin_note). None если не найден."""
    conn = get_connection()
    try:
        try:
            row = conn.execute(
                """SELECT product_id, account_data, COALESCE(item_type, 'account'), used, COALESCE(used_at, ''), COALESCE(order_id, ''), COALESCE(admin_note, '')
                   FROM product_accounts WHERE id = ?""",
                (account_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = conn.execute(
                "SELECT product_id, account_data, used, used_at, order_id FROM product_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if row:
                row = (row[0], row[1], "account", row[2], row[3] or "", row[4] or "", "")
        if not row:
            return None
        return {
            "id": account_id,
            "product_id": row[0],
            "account_data": row[1],
            "item_type": (row[2] or "account").strip() or "account",
            "used": bool(row[3]),
            "used_at": row[4] or "",
            "order_id": row[5] or "",
            "admin_note": row[6] or "" if len(row) > 6 else "",
        }
    finally:
        conn.close()


def delete_product_account(account_id: int) -> bool:
    """Удалить аккаунт из склада по id. Возвращает True если запись найдена и удалена."""
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM product_accounts WHERE id = ?", (account_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def add_product_account(
    product_id: int,
    account_data: str,
    item_type: str = "account",
    tariff_id: Optional[int] = None,
    admin_note: Optional[str] = None,
) -> int:
    """item_type: 'account' | 'link'. tariff_id: привязка к тарифу. admin_note: примечание (выдаётся клиенту с аккаунтом)."""
    conn = get_connection()
    try:
        note = (admin_note or "").strip()
        try:
            cur = conn.execute(
                "INSERT INTO product_accounts (product_id, account_data, item_type, tariff_id, admin_note) VALUES (?, ?, ?, ?, ?)",
                (product_id, account_data.strip(), item_type, tariff_id, note),
            )
        except sqlite3.OperationalError:
            try:
                cur = conn.execute(
                    "INSERT INTO product_accounts (product_id, account_data, item_type, admin_note) VALUES (?, ?, ?, ?)",
                    (product_id, account_data.strip(), item_type, note),
                )
            except sqlite3.OperationalError:
                cur = conn.execute(
                    "INSERT INTO product_accounts (product_id, account_data, item_type) VALUES (?, ?, ?)",
                    (product_id, account_data.strip(), item_type),
                )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_products_for_restock() -> list[dict]:
    """Товары с активацией «готовый аккаунт» — для пополнения склада."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name FROM products WHERE activation_type = 'account' ORDER BY category, id",
            (),
        ).fetchall()
        return [{"id": r[0], "name": r[1]} for r in rows]
    finally:
        conn.close()


def get_and_mark_accounts(product_id: int, quantity: int, order_id: str, tariff_id: Optional[int] = None) -> list[dict]:
    """Взять quantity неиспользованных позиций, пометить used. Возвращает [{"account_data", "item_type", "admin_note"}, ...]."""
    conn = get_connection()
    try:
        if tariff_id is not None:
            try:
                rows = conn.execute(
                    """SELECT id, account_data, item_type, COALESCE(admin_note, '') FROM product_accounts
                       WHERE product_id = ? AND used = 0 AND (tariff_id IS NULL OR tariff_id = ?) LIMIT ?""",
                    (product_id, tariff_id, quantity),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    """SELECT id, account_data FROM product_accounts
                       WHERE product_id = ? AND used = 0 AND (tariff_id IS NULL OR tariff_id = ?) LIMIT ?""",
                    (product_id, tariff_id, quantity),
                ).fetchall()
                rows = [(r[0], r[1], "account", "") for r in rows]
        else:
            try:
                rows = conn.execute(
                    "SELECT id, account_data, item_type, COALESCE(admin_note, '') FROM product_accounts WHERE product_id = ? AND used = 0 LIMIT ?",
                    (product_id, quantity),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT id, account_data FROM product_accounts WHERE product_id = ? AND used = 0 LIMIT ?",
                    (product_id, quantity),
                ).fetchall()
                rows = [(r[0], r[1], "account", "") for r in rows]
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        out = []
        for r in rows:
            conn.execute("UPDATE product_accounts SET used = 1, used_at = ?, order_id = ? WHERE id = ?", (now, order_id, r[0]))
            note = (r[3] or "").strip() if len(r) > 3 else ""
            out.append({
                "account_data": r[1],
                "item_type": (r[2] or "account").strip() or "account",
                "admin_note": note,
            })
        conn.commit()
        return out
    finally:
        conn.close()


def count_all_purchases_for_admin() -> int:
    """Общее количество заказов для админки (пагинация)."""
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0] or 0
    finally:
        conn.close()


def get_all_purchases_for_admin(limit: int = 100, offset: int = 0) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT p.id, p.user_id, p.order_number, p.product_name, p.quantity, p.amount, p.created_at
               FROM purchases p ORDER BY p.created_at DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        return [{"id": r[0], "user_id": r[1], "order_number": r[2], "product_name": r[3], "quantity": r[4], "amount": r[5], "created_at": (r[6] or "")[:16]} for r in rows]
    finally:
        conn.close()


def get_purchase_detail_for_admin(purchase_id: int) -> Optional[dict]:
    """Полные данные заказа для админки: статус, состав, товар, количество, сумма, ник покупателя."""
    conn = get_connection()
    try:
        try:
            row = conn.execute(
                """SELECT p.id, p.user_id, p.order_number, p.product_name, p.quantity, p.amount, p.created_at,
                   COALESCE(p.email_data, ''), COALESCE(p.status, '')
                   FROM purchases p WHERE p.id = ?""",
                (purchase_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = conn.execute(
                """SELECT p.id, p.user_id, p.order_number, p.product_name, p.quantity, p.amount, p.created_at,
                   COALESCE(p.email_data, '')
                   FROM purchases p WHERE p.id = ?""",
                (purchase_id,),
            ).fetchone()
            row = row + ("",) if row else None
        if not row:
            return None
        user_id = row[1]
        order_number = row[2]
        username_row = conn.execute("SELECT username FROM users WHERE user_id = ?", (user_id,)).fetchone()
        username = (username_row[0] or "").strip() if username_row else ""
        acc_rows = conn.execute(
            "SELECT account_data, COALESCE(item_type, 'account'), COALESCE(admin_note, '') FROM product_accounts WHERE order_id = ?",
            (order_number,),
        ).fetchall()
        accounts = [
            {"account_data": r[0], "item_type": (r[1] or "account").strip() or "account", "admin_note": (r[2] or "").strip()}
            for r in acc_rows
        ]
        return {
            "id": row[0],
            "user_id": user_id,
            "order_number": order_number,
            "product_name": row[3],
            "quantity": row[4],
            "amount": row[5],
            "created_at": row[6][:16] if row[6] else "",
            "email_data": (row[7] or "").strip(),
            "status": (row[8] or "").strip() if len(row) > 8 else "",
            "accounts": accounts,
            "username": username,
        }
    finally:
        conn.close()


def add_promo_percent(code: str, percent: int, max_uses: int = 1) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO promocodes (code, bonus_amount, max_uses) VALUES (?, 0, ?)",
            (code.strip().upper(), max_uses),
        )
        conn.commit()
        try:
            conn.execute(
                "UPDATE promocodes SET discount_type = 'percent', discount_value = ? WHERE code = ?",
                (str(percent), code.strip().upper()),
            )
            conn.commit()
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()


def add_promo_fixed(code: str, amount: int, max_uses: int = 1) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO promocodes (code, bonus_amount, max_uses) VALUES (?, ?, ?)",
            (code.strip().upper(), amount, max_uses),
        )
        conn.commit()
    finally:
        conn.close()


def create_review_promo_code(amount: int = 150) -> str:
    """Создать уникальный одноразовый промокод на скидку amount ₽. Возвращает код (например AIHubRenew_XXXX)."""
    for _ in range(30):
        code = f"AIHubRenew_{secrets.token_hex(4).upper()}"
        if get_promocode(code) is None:
            add_promo_fixed(code, amount, max_uses=1)
            return code
    code = f"AIHubRenew_{secrets.token_hex(4).upper()}"
    add_promo_fixed(code, amount, max_uses=1)
    return code


def clear_all_production_data() -> None:
    """
    Очистка БД перед запуском в бой: история покупок, пользователи, балансы,
    промокоды и история их использования, платежи, рефералы.
    Товары, тарифы, склады, FAQ не трогаем.
    """
    conn = get_connection()
    try:
        conn.execute("DELETE FROM promo_used")
        conn.execute("DELETE FROM promocodes")
        conn.execute("DELETE FROM order_items")
        conn.execute("DELETE FROM purchases")
        conn.execute("DELETE FROM payments")
        conn.execute("DELETE FROM referrals")
        conn.execute("DELETE FROM users")
        conn.execute("UPDATE product_accounts SET used = 0, used_at = NULL, order_id = NULL")
        conn.commit()
        logger.info("clear_all_production_data: история покупок, пользователи, промокоды, платежи и рефералы очищены; выданные аккаунты сброшены в «не использованы».")
    finally:
        conn.close()


# --- Запрос аккаунта (заявка в группу уведомлений) ---

def create_account_request(product_id: int, quantity: int) -> int:
    """Создать заявку на аккаунт(ы). Возвращает id заявки."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO account_requests (product_id, quantity, status) VALUES (?, ?, 'pending')",
            (product_id, quantity),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_account_request(request_id: int) -> Optional[dict]:
    """Заявка по id (product_id, quantity, status, issued_count, notification_chat_id, notification_message_id, product_name)."""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT ar.product_id, ar.quantity, ar.status, ar.issued_count,
                      ar.notification_chat_id, ar.notification_message_id, p.name
               FROM account_requests ar
               JOIN products p ON p.id = ar.product_id
               WHERE ar.id = ?""",
            (request_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": request_id,
            "product_id": row[0],
            "quantity": row[1],
            "status": row[2],
            "issued_count": row[3],
            "notification_chat_id": row[4],
            "notification_message_id": row[5],
            "product_name": row[6],
        }
    finally:
        conn.close()


def set_account_request_message(request_id: int, chat_id: int, message_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE account_requests SET notification_chat_id = ?, notification_message_id = ? WHERE id = ?",
            (chat_id, message_id, request_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_account_request_status(request_id: int, status: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE account_requests SET status = ? WHERE id = ?", (status, request_id))
        conn.commit()
    finally:
        conn.close()


def increment_account_request_issued(request_id: int) -> int:
    """Увеличить issued_count на 1. Возвращает новый issued_count."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE account_requests SET issued_count = issued_count + 1 WHERE id = ?",
            (request_id,),
        )
        conn.commit()
        row = conn.execute("SELECT issued_count FROM account_requests WHERE id = ?", (request_id,)).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()
