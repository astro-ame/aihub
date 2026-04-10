# -*- coding: utf-8 -*-
"""Админ-панель: /admin, пароль, выгрузка БД, промокоды, история покупок, добавление товара."""

import asyncio
import csv
import io
import logging
from datetime import datetime, timezone
from pathlib import Path

from aiogram import F, Router
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey

import config
import database as db
from utils_dt import format_created_at_moscow

# Темы поддержки (ключ, подпись) — должны совпадать с bot.SUPPORT_TOPICS
ADMIN_SUPPORT_TOPICS = [
    ("gemini", "Gemini"),
    ("capcut", "CapCut"),
    ("cursor", "Cursor"),
    ("higgsfield", "Higgsfield"),
    ("midjourney", "midjourney"),
    ("gamma", "gamma"),
    ("grok", "grok"),
    ("chatgpt", "chatGPT"),
    ("claude", "Claude"),
]

logger = logging.getLogger(__name__)
admin_router = Router()

# FSM админки
class AdminStates(StatesGroup):
    waiting_password = State()
    waiting_promo_type = State()
    waiting_promo_usage = State()  # одноразовый / многоразовый
    waiting_promo_max_uses = State()  # сколько активаций (для многоразового)
    waiting_promo_value = State()
    waiting_promo_code = State()
    add_product_category = State()
    add_product_name = State()
    add_product_description = State()
    add_product_price = State()
    add_product_activation = State()
    add_product_image = State()
    add_account_data = State()
    waiting_restock_data = State()  # пополнение склада: ввод ссылки или аккаунта
    waiting_restock_note = State()  # примечание к добавленному аккаунту (опционально)
    # Редактирование товара
    edit_product_name = State()
    edit_product_description = State()
    edit_product_price = State()
    edit_product_image = State()
    edit_product_activation = State()
    instruction_text = State()
    activation_prompt_text = State()  # инструкция активации для товара «на почту»
    waiting_broadcast = State()  # рассылка: ждём текст сообщения
    # Поддержка: добавление вопроса в FAQ
    waiting_support_question = State()
    waiting_support_answer = State()
    # Редактирование вопроса в FAQ
    waiting_support_edit_question = State()
    waiting_support_edit_answer = State()
    # Запросить аккаунт: выбор товара и ввод количества
    waiting_request_quantity = State()


def admin_only(func):
    """Декоратор: только для config.ADMIN_IDS."""
    async def wrapped(event, *args, **kwargs):
        user_id = event.from_user.id if event.from_user else 0
        if user_id not in config.ADMIN_IDS:
            return
        return await func(event, *args, **kwargs)
    return wrapped


def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Базы данных", callback_data="admin:db")],
        [InlineKeyboardButton(text="🎟 Создать промокод", callback_data="admin:promo")],
        [InlineKeyboardButton(text="📋 Список промокодов", callback_data="admin:promo_list")],
        [InlineKeyboardButton(text="📋 История покупок", callback_data="admin:purchases")],
        [InlineKeyboardButton(text="📂 Все товары", callback_data="admin:products")],
        [InlineKeyboardButton(text="📦 Склад", callback_data="admin:warehouse")],
        [InlineKeyboardButton(text="📄 Инструкции", callback_data="admin:instructions")],
        [InlineKeyboardButton(text="📧 Инструкции активаций", callback_data="admin:activation_instructions")],
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin:add_product")],
        [InlineKeyboardButton(text="📥 Пополнить склад", callback_data="admin:restock")],
        [InlineKeyboardButton(text="📩 Запросить аккаунт", callback_data="admin:request_account")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="💬 Поддержка", callback_data="admin:support")],
    ])


@admin_router.message(Command("admin"))
@admin_only
async def cmd_admin(message: Message, state: FSMContext, **kwargs) -> None:
    await state.clear()
    await state.set_state(AdminStates.waiting_password)
    await message.answer("Введите пароль администратора:")


@admin_router.message(AdminStates.waiting_password, F.text)
@admin_only
async def admin_password(message: Message, state: FSMContext, **kwargs) -> None:
    if message.text != config.ADMIN_PASSWORD:
        await message.answer("Неверный пароль.")
        return
    try:
        await message.delete()
    except Exception:
        pass
    await state.clear()
    await message.answer("Меню:", reply_markup=get_admin_keyboard())


async def _admin_edit(callback: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup, parse_mode: str | None = None) -> None:
    """Редактируем сообщение админки (открытие «внутри», как в клиенте)."""
    try:
        await callback.message.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        try:
            await callback.message.edit_text(text=text[:4000] + "…" if len(text) > 4000 else text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            pass


# --- Базы данных ---
@admin_router.callback_query(F.data == "admin:db")
@admin_only
async def admin_db(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    await _admin_edit(callback, "📦 Выгружаю базы данных…", InlineKeyboardMarkup(inline_keyboard=[]))
    data_dir = Path(__file__).parent / "data"
    db_path = data_dir / "bot.db"
    if not db_path.exists():
        await callback.message.edit_text(text="Файл БД не найден.", reply_markup=get_admin_keyboard())
        return
    try:
        with open(db_path, "rb") as f:
            file = BufferedInputFile(f.read(), filename="bot.db")
        await callback.message.answer_document(document=file, caption="Выгрузка bot.db")
    except Exception as e:
        await callback.message.edit_text(text=f"Ошибка выгрузки: {e}", reply_markup=get_admin_keyboard())
        return
    try:
        conn = db.get_connection()
        tables = ["users", "purchases", "payments", "promocodes", "products", "tariffs", "product_accounts"]
        for table in tables:
            try:
                cur = conn.execute(f"SELECT * FROM {table}")
                rows = cur.fetchall()
                col_names = [d[0] for d in cur.description]
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(col_names)
                w.writerows(rows)
                buf.seek(0)
                file = BufferedInputFile(buf.getvalue().encode("utf-8-sig"), filename=f"{table}.csv")
                await callback.message.answer_document(document=file, caption=f"{table}.csv")
            except Exception as e:
                logger.warning("Export %s: %s", table, e)
        conn.close()
    except Exception as e:
        await callback.message.edit_text(text=f"Ошибка экспорта в CSV: {e}", reply_markup=get_admin_keyboard())
        return
    await callback.message.edit_text(text="Меню:", reply_markup=get_admin_keyboard())


# --- Промокод ---
@admin_router.callback_query(F.data == "admin:promo")
@admin_only
async def admin_promo_start(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.set_state(AdminStates.waiting_promo_type)
    await _admin_edit(callback, "Тип промокода:", InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Скидка в %", callback_data="admin:promo_percent")],
        [InlineKeyboardButton(text="Денежный промо", callback_data="admin:promo_fixed")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")],
    ]))


@admin_router.callback_query(F.data.startswith("admin:promo_"), AdminStates.waiting_promo_type)
@admin_only
async def admin_promo_type(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    if callback.data == "admin:promo_percent":
        await state.update_data(promo_type="percent")
    elif callback.data == "admin:promo_fixed":
        await state.update_data(promo_type="fixed")
    else:
        await state.clear()
        await _admin_edit(callback, "Меню:", get_admin_keyboard())
        return
    await state.set_state(AdminStates.waiting_promo_usage)
    await _admin_edit(callback, "Одноразовый или многоразовый? (один клиент может использовать промокод только один раз.)", InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Одноразовый", callback_data="admin:promo_usage_once")],
        [InlineKeyboardButton(text="Многоразовый", callback_data="admin:promo_usage_multi")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")],
    ]))


@admin_router.callback_query(F.data.startswith("admin:promo_usage_"), AdminStates.waiting_promo_usage)
@admin_only
async def admin_promo_usage(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    if callback.data == "admin:promo_usage_once":
        await state.update_data(promo_max_uses=1)
        await state.set_state(AdminStates.waiting_promo_value)
        data = await state.get_data()
        if data.get("promo_type") == "percent":
            await callback.message.answer("Введите размер скидки в процентах (число от 1 до 100):")
        else:
            await callback.message.answer("Введите сумму промокода в рублях (целое число):")
        return
    if callback.data == "admin:promo_usage_multi":
        await state.set_state(AdminStates.waiting_promo_max_uses)
        await callback.message.answer("Сколько раз можно активировать промокод? (введите число):")
        return
    await state.clear()
    await _admin_edit(callback, "Меню:", get_admin_keyboard())


@admin_router.message(AdminStates.waiting_promo_max_uses, F.text)
@admin_only
async def admin_promo_max_uses(message: Message, state: FSMContext, **kwargs) -> None:
    try:
        n = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите целое число.")
        return
    if n < 2:
        await message.answer("Для многоразового укажите число активаций не меньше 2.")
        return
    await state.update_data(promo_max_uses=n)
    await state.set_state(AdminStates.waiting_promo_value)
    data = await state.get_data()
    if data.get("promo_type") == "percent":
        await message.answer("Введите размер скидки в процентах (число от 1 до 100):")
    else:
        await message.answer("Введите сумму промокода в рублях (целое число):")


@admin_router.message(AdminStates.waiting_promo_value, F.text)
@admin_only
async def admin_promo_value(message: Message, state: FSMContext, **kwargs) -> None:
    data = await state.get_data()
    promo_type = data.get("promo_type", "fixed")
    try:
        val = int(message.text.strip())
    except ValueError:
        await message.answer("Введите целое число.")
        return
    if promo_type == "percent" and (val < 1 or val > 100):
        await message.answer("Процент от 1 до 100.")
        return
    if promo_type == "fixed" and val < 1:
        await message.answer("Сумма должна быть больше 0.")
        return
    await state.update_data(promo_value=val)
    await state.set_state(AdminStates.waiting_promo_code)
    await message.answer("Введите код промокода (латиница/цифры, без пробелов):")


@admin_router.message(AdminStates.waiting_promo_code, F.text)
@admin_only
async def admin_promo_code(message: Message, state: FSMContext, **kwargs) -> None:
    code = (message.text or "").strip().upper().replace(" ", "")
    if not code:
        await message.answer("Код не может быть пустым.")
        return
    data = await state.get_data()
    promo_type = data.get("promo_type", "fixed")
    value = data.get("promo_value", 0)
    max_uses = data.get("promo_max_uses", 1)
    try:
        if promo_type == "percent":
            db.add_promo_percent(code, value, max_uses=max_uses)
            uses_text = "одноразовый" if max_uses == 1 else f"многоразовый ({max_uses} активаций)"
            await message.answer(f"Промокод «{code}» создан: скидка {value}%, {uses_text}.")
        else:
            db.add_promo_fixed(code, value, max_uses=max_uses)
            uses_text = "одноразовый" if max_uses == 1 else f"многоразовый ({max_uses} активаций)"
            await message.answer(f"Промокод «{code}» создан: {value} ₽ на баланс, {uses_text}.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}. Возможно, код уже существует.")
    await state.clear()
    await message.answer("Меню:", reply_markup=get_admin_keyboard())


# --- Список промокодов (неиспользованные) ---
@admin_router.callback_query(F.data == "admin:promo_list")
@admin_only
async def admin_promo_list(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    rows = db.get_promocodes_list_unused()
    if not rows:
        text = "Нет промокодов с оставшимися активациями."
    else:
        lines = []
        for r in rows:
            t = "скидка " + str(r["value"]) + "%" if r["promo_type"] == "percent" else str(r["value"]) + " ₽"
            lines.append(f"• {r['code']} — {t} | использовано {r['used_count']}/{r['max_uses']}")
        text = "Промокоды (есть активации):\n\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")]])
    await _admin_edit(callback, text, kb)


# --- Инструкции к товарам ---
@admin_router.callback_query(F.data == "admin:instructions")
@admin_only
async def admin_instructions_list(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    products = db.get_all_products()
    if not products:
        await _admin_edit(callback, "Товаров пока нет.", InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")],
        ]))
        return
    buttons = [[InlineKeyboardButton(text=p["name"], callback_data=f"admin:instr_product:{p['id']}")] for p in products]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")])
    await _admin_edit(callback, "Выберите товар для настройки инструкции:", InlineKeyboardMarkup(inline_keyboard=buttons))


@admin_router.callback_query(F.data.startswith("admin:instr_product:"))
@admin_only
async def admin_instruction_product(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    product_id = int(callback.data.split(":")[2])
    product = db.get_product(product_id)
    if not product:
        await _admin_edit(callback, "Товар не найден.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin:instructions")]]))
        return
    instr = (product.get("instruction") or "").strip()
    instr_imgs = product.get("instruction_images") or []
    img_line = f"\nФото: {len(instr_imgs)} шт." if instr_imgs else ""
    text = f"**{product['name']}**\n\nТекущая инструкция:\n{instr or '— не задана —'}{img_line}"
    await _admin_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Задать инструкцию", callback_data=f"admin:instr_set:{product_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:instructions")],
    ]), parse_mode="Markdown")


def _instruction_content_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово (сохранить)", callback_data="admin:instr_done")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin:instructions")],
    ])


@admin_router.callback_query(F.data.startswith("admin:instr_set:"))
@admin_only
async def admin_instruction_set_start(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    product_id = int(callback.data.split(":")[2])
    await state.update_data(instruction_product_id=product_id, instruction_text="", instruction_images=[])
    await state.set_state(AdminStates.instruction_text)
    await callback.message.answer(
        "Отправьте текст и/или фото (можно несколько сообщений с фото). Когда закончите — нажмите «Готово».",
        reply_markup=_instruction_content_kb(product_id),
    )


@admin_router.message(AdminStates.instruction_text, F.text)
@admin_only
async def admin_instruction_text_msg(message: Message, state: FSMContext, **kwargs) -> None:
    data = await state.get_data()
    product_id = data.get("instruction_product_id")
    text = (message.text or "").strip()
    await state.update_data(instruction_text=text)
    n = len(data.get("instruction_images") or [])
    await message.answer(
        f"Текст принят. Фото: {n} шт. Отправьте ещё текст/фото или нажмите «Готово».",
        reply_markup=_instruction_content_kb(product_id),
    )


@admin_router.message(AdminStates.instruction_text, F.photo)
@admin_only
async def admin_instruction_photo_msg(message: Message, state: FSMContext, **kwargs) -> None:
    data = await state.get_data()
    product_id = data.get("instruction_product_id")
    images = list(data.get("instruction_images") or [])
    file_id = message.photo[-1].file_id
    images.append(file_id)
    if (message.caption or "").strip():
        await state.update_data(instruction_text=(message.caption or "").strip(), instruction_images=images)
    else:
        await state.update_data(instruction_images=images)
    await message.answer(
        f"Фото принято. Всего фото: {len(images)}. Отправьте ещё или нажмите «Готово».",
        reply_markup=_instruction_content_kb(product_id),
    )


@admin_router.callback_query(F.data == "admin:instr_done")
@admin_only
async def admin_instruction_done(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    data = await state.get_data()
    product_id = data.get("instruction_product_id")
    await state.clear()
    if not product_id:
        await callback.message.answer("Меню:", reply_markup=get_admin_keyboard())
        return
    text = (data.get("instruction_text") or "").strip()
    images = data.get("instruction_images") or []
    db.update_product(product_id, instruction=text, instruction_images=images)
    await callback.message.answer("Инструкция сохранена (текст + фото).", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="К товару", callback_data=f"admin:instr_product:{product_id}")],
        [InlineKeyboardButton(text="В меню", callback_data="admin:back")],
    ]))


# --- Инструкции активаций (товары «на аккаунт клиента») ---
@admin_router.callback_query(F.data == "admin:activation_instructions")
@admin_only
async def admin_activation_instructions_list(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    all_products = db.get_all_products()
    products = [p for p in all_products if p.get("activation_type") == "email"]
    if not products:
        await _admin_edit(callback, "Нет товаров с типом «на аккаунт клиента» (на почту).", InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")],
        ]))
        return
    buttons = [[InlineKeyboardButton(text=p["name"], callback_data=f"admin:act_instr_product:{p['id']}")] for p in products]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")])
    await _admin_edit(callback, "Выберите товар (на аккаунт клиента). Здесь задаётся текст после оплаты и что потребовать от клиента (почта, пароль, 2FA):", InlineKeyboardMarkup(inline_keyboard=buttons))


@admin_router.callback_query(F.data.startswith("admin:act_instr_product:"))
@admin_only
async def admin_activation_instruction_product(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    product_id = int(callback.data.split(":")[2])
    product = db.get_product(product_id)
    if not product or product.get("activation_type") != "email":
        await _admin_edit(callback, "Товар не найден или не «на почту».", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin:activation_instructions")]]))
        return
    prompt = (product.get("activation_prompt") or "").strip()
    act_imgs = product.get("activation_prompt_images") or []
    img_line = f"\nФото: {len(act_imgs)} шт." if act_imgs else ""
    text = f"**{product['name']}**\n\nТекущий текст запроса (после оплаты):\n{prompt or '— не задан, используется стандартный —'}{img_line}"
    await _admin_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Задать текст запроса", callback_data=f"admin:act_instr_set:{product_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:activation_instructions")],
    ]), parse_mode="Markdown")


def _activation_content_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово (сохранить)", callback_data="admin:act_instr_done")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin:activation_cancel")],
    ])


@admin_router.callback_query(F.data.startswith("admin:act_instr_set:"))
@admin_only
async def admin_activation_instruction_set_start(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    product_id = int(callback.data.split(":")[2])
    await state.update_data(activation_prompt_product_id=product_id, activation_prompt_text="", activation_prompt_images=[])
    await state.set_state(AdminStates.activation_prompt_text)
    await callback.message.answer(
        "Отправьте текст и/или фото (что увидит клиент после оплаты и что от него потребовать). Можно несколько сообщений с фото. Когда закончите — нажмите «Готово».",
        reply_markup=_activation_content_kb(),
    )


@admin_router.message(AdminStates.activation_prompt_text, F.text)
@admin_only
async def admin_activation_prompt_text_msg(message: Message, state: FSMContext, **kwargs) -> None:
    data = await state.get_data()
    product_id = data.get("activation_prompt_product_id")
    text = (message.text or "").strip()
    await state.update_data(activation_prompt_text=text)
    n = len(data.get("activation_prompt_images") or [])
    await message.answer(
        f"Текст принят. Фото: {n} шт. Отправьте ещё текст/фото или нажмите «Готово».",
        reply_markup=_activation_content_kb(),
    )


@admin_router.message(AdminStates.activation_prompt_text, F.photo)
@admin_only
async def admin_activation_prompt_photo_msg(message: Message, state: FSMContext, **kwargs) -> None:
    data = await state.get_data()
    images = list(data.get("activation_prompt_images") or [])
    file_id = message.photo[-1].file_id
    images.append(file_id)
    if (message.caption or "").strip():
        await state.update_data(activation_prompt_text=(message.caption or "").strip(), activation_prompt_images=images)
    else:
        await state.update_data(activation_prompt_images=images)
    await message.answer(
        f"Фото принято. Всего фото: {len(images)}. Отправьте ещё или нажмите «Готово».",
        reply_markup=_activation_content_kb(),
    )


@admin_router.callback_query(F.data == "admin:act_instr_done")
@admin_only
async def admin_activation_instruction_done(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    data = await state.get_data()
    product_id = data.get("activation_prompt_product_id")
    await state.clear()
    if not product_id:
        await callback.message.answer("Меню:", reply_markup=get_admin_keyboard())
        return
    text = (data.get("activation_prompt_text") or "").strip()
    images = data.get("activation_prompt_images") or []
    db.update_product(product_id, activation_prompt=text, activation_prompt_images=images)
    await callback.message.answer("Текст и фото запроса сохранены.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="К инструкциям активаций", callback_data="admin:activation_instructions")],
        [InlineKeyboardButton(text="В меню", callback_data="admin:back")],
    ]))


# --- Рассылка ---
@admin_router.callback_query(F.data == "admin:broadcast")
@admin_only
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.set_state(AdminStates.waiting_broadcast)
    await callback.message.answer(
        "Введите сообщение для рассылки (одним сообщением). Поддерживается текст и Markdown.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin:broadcast_cancel")],
        ]),
    )


@admin_router.callback_query(F.data == "admin:activation_cancel")
@admin_only
async def admin_activation_cancel(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("Отменено. Меню:", reply_markup=get_admin_keyboard())


@admin_router.callback_query(F.data == "admin:broadcast_cancel")
@admin_only
async def admin_broadcast_cancel(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("Отменено. Меню:", reply_markup=get_admin_keyboard())


@admin_router.message(AdminStates.waiting_broadcast, F.text | F.caption)
@admin_only
async def admin_broadcast_send(message: Message, state: FSMContext, **kwargs) -> None:
    await state.clear()
    text = ((message.text or message.caption) or "").strip()
    if not text:
        await message.answer("Текст пустой. Меню:", reply_markup=get_admin_keyboard())
        return
    user_ids = db.get_all_user_ids()
    kb_broadcast = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="menu:main")],
    ])
    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await message.bot.send_message(uid, text, parse_mode="Markdown", reply_markup=kb_broadcast)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await message.answer(f"Рассылка завершена. Отправлено: {sent}, не доставлено: {failed}. Меню:", reply_markup=get_admin_keyboard())


# --- Поддержка: FAQ (добавить вопрос) ---
@admin_router.callback_query(F.data == "admin:support")
@admin_only
async def admin_support_menu(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все вопросы", callback_data="admin:support_list")],
        [InlineKeyboardButton(text="➕ Добавить вопрос", callback_data="admin:support_add")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="admin:back")],
    ])
    await _admin_edit(callback, "💬 **Поддержка**\n\nЗдесь можно добавить вопрос и ответ для раздела поддержки бота, а также просматривать и редактировать существующие.", kb, parse_mode="Markdown")


@admin_router.callback_query(F.data == "admin:support_list")
@admin_only
async def admin_support_list(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    """Список всех вопросов из FAQ: текст вопроса и ответа, кнопки для перехода к каждому."""
    await callback.answer()
    await state.clear()
    all_faq = db.get_all_support_faq()
    if not all_faq:
        await _admin_edit(
            callback,
            "📋 **Все вопросы**\n\nПока нет ни одного вопроса. Добавьте вопрос через кнопку «Добавить вопрос».",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить вопрос", callback_data="admin:support_add")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:support")],
            ]),
            parse_mode="Markdown",
        )
        return
    topic_labels = dict(ADMIN_SUPPORT_TOPICS)
    lines = ["📋 **Все вопросы**\n"]
    buttons = []
    for faq in all_faq:
        topic = topic_labels.get(faq["product_key"], faq["product_key"])
        q_short = ((faq["question_text"] or "")[:50]).replace("*", "•").replace("_", " ")
        if len(faq["question_text"] or "") > 50:
            q_short += "…"
        a_short = ((faq["answer_text"] or "")[:80]).replace("*", "•").replace("_", " ")
        if len(faq["answer_text"] or "") > 80:
            a_short += "…"
        lines.append(f"**№{faq['id']}** ({topic})")
        lines.append(f"Вопрос: {q_short}")
        lines.append(f"Ответ: {a_short}")
        lines.append("")
        btn_label = f"№{faq['id']}: {q_short}"[:64]
        buttons.append([InlineKeyboardButton(text=btn_label, callback_data=f"admin:support_faq:{faq['id']}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:support")])
    text = "\n".join(lines).strip()
    if len(text) > 4000:
        text = "\n".join(lines[:1] + [f"Всего вопросов: {len(all_faq)}. Выберите вопрос ниже."])
    await _admin_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")


@admin_router.callback_query(F.data.startswith("admin:support_faq:"))
@admin_only
async def admin_support_faq_detail(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    """Просмотр одного вопроса: полный текст, кнопки Редактировать, Удалить, В главное меню."""
    await callback.answer()
    await state.clear()
    try:
        faq_id = int(callback.data.split(":", 2)[2])
    except (ValueError, IndexError):
        await _admin_edit(callback, "Ошибка.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin:support_list")]]))
        return
    faq = db.get_support_faq_by_id(faq_id)
    if not faq:
        await _admin_edit(callback, "Вопрос не найден.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ К списку вопросов", callback_data="admin:support_list")]]))
        return
    topic_labels = dict(ADMIN_SUPPORT_TOPICS)
    topic = topic_labels.get(faq["product_key"], faq["product_key"])
    q = (faq["question_text"] or "").replace("*", "•").replace("_", " ")
    a = (faq["answer_text"] or "").replace("*", "•").replace("_", " ")
    text = f"📋 Вопрос №{faq['id']} ({topic})\n\nВопрос:\n{q}\n\nОтвет:\n{a}"
    if len(text) > 4000:
        text = f"📋 Вопрос №{faq['id']} ({topic})\n\nТекст слишком длинный. Используйте «Редактировать»."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"admin:support_faq_edit:{faq_id}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin:support_faq_delete:{faq_id}")],
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="admin:back")],
    ])
    await _admin_edit(callback, text, kb)


@admin_router.callback_query(F.data == "admin:support_add")
@admin_only
async def admin_support_add_choose_topic(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    buttons = [[InlineKeyboardButton(text=label, callback_data=f"admin:support_topic:{key}")] for key, label in ADMIN_SUPPORT_TOPICS]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:support")])
    await _admin_edit(callback, "Выберите тему (товар) для вопроса:", InlineKeyboardMarkup(inline_keyboard=buttons))


@admin_router.callback_query(F.data.startswith("admin:support_topic:"))
@admin_only
async def admin_support_topic_chosen(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    key = callback.data.split(":", 2)[2]
    await state.update_data(support_product_key=key)
    await state.set_state(AdminStates.waiting_support_question)
    label = next((lbl for k, lbl in ADMIN_SUPPORT_TOPICS if k == key), key)
    await _admin_edit(callback, f"Тема: **{label}**. Напишите текст вопроса в чат:", InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin:support")],
    ]), parse_mode="Markdown")


@admin_router.message(AdminStates.waiting_support_question, F.text)
@admin_only
async def admin_support_question_received(message: Message, state: FSMContext, **kwargs) -> None:
    question = (message.text or "").strip()
    if not question:
        await message.answer("Введите непустой текст вопроса.")
        return
    await state.update_data(support_question=question)
    await state.set_state(AdminStates.waiting_support_answer)
    await message.answer("Теперь введите ответ на этот вопрос:")


@admin_router.message(AdminStates.waiting_support_answer, F.text)
@admin_only
async def admin_support_answer_received(message: Message, state: FSMContext, **kwargs) -> None:
    answer = (message.text or "").strip()
    if not answer:
        await message.answer("Введите непустой текст ответа.")
        return
    data = await state.get_data()
    key = (data.get("support_product_key") or "").strip()
    question = (data.get("support_question") or "").strip()
    await state.clear()
    if not key or not question:
        await message.answer("Сессия сброшена. Зайдите в Поддержка → Добавить вопрос снова.", reply_markup=get_admin_keyboard())
        return
    faq_id = db.add_support_faq(key, question, answer)
    label = next((lbl for k, lbl in ADMIN_SUPPORT_TOPICS if k == key), key)
    await message.answer(
        f"✅ Вопрос добавлен в FAQ (тема: {label}, id: {faq_id}).",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить ещё вопрос", callback_data="admin:support_add")],
            [InlineKeyboardButton(text="◀️ В меню поддержки", callback_data="admin:support")],
            [InlineKeyboardButton(text="◀️ Главное меню", callback_data="admin:back")],
        ]),
    )


@admin_router.callback_query(F.data.startswith("admin:support_faq_delete:"))
@admin_only
async def admin_support_faq_delete(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    try:
        faq_id = int(callback.data.split(":", 2)[2])
    except (ValueError, IndexError):
        await _admin_edit(callback, "Ошибка.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ К списку вопросов", callback_data="admin:support_list")]]))
        return
    if db.delete_support_faq(faq_id):
        await _admin_edit(
            callback,
            f"✅ Вопрос №{faq_id} удалён.",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Все вопросы", callback_data="admin:support_list")],
                [InlineKeyboardButton(text="◀️ В меню поддержки", callback_data="admin:support")],
                [InlineKeyboardButton(text="◀️ Главное меню", callback_data="admin:back")],
            ]),
        )
    else:
        await _admin_edit(callback, "Вопрос не найден или уже удалён.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ К списку вопросов", callback_data="admin:support_list")]]))


@admin_router.callback_query(F.data.startswith("admin:support_faq_edit:"))
@admin_only
async def admin_support_faq_edit_start(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    try:
        faq_id = int(callback.data.split(":", 2)[2])
    except (ValueError, IndexError):
        await _admin_edit(callback, "Ошибка.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ К списку вопросов", callback_data="admin:support_list")]]))
        return
    faq = db.get_support_faq_by_id(faq_id)
    if not faq:
        await _admin_edit(callback, "Вопрос не найден.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ К списку вопросов", callback_data="admin:support_list")]]))
        return
    await state.update_data(support_edit_faq_id=faq_id)
    await state.set_state(AdminStates.waiting_support_edit_question)
    await _admin_edit(
        callback,
        f"Редактирование вопроса №{faq_id}. Введите новый текст вопроса в чат:",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"admin:support_faq:{faq_id}")],
        ]),
    )


@admin_router.message(AdminStates.waiting_support_edit_question, F.text)
@admin_only
async def admin_support_edit_question_received(message: Message, state: FSMContext, **kwargs) -> None:
    question = (message.text or "").strip()
    if not question:
        await message.answer("Введите непустой текст вопроса.")
        return
    await state.update_data(support_edit_question=question)
    await state.set_state(AdminStates.waiting_support_edit_answer)
    await message.answer("Теперь введите новый текст ответа:")


@admin_router.message(AdminStates.waiting_support_edit_answer, F.text)
@admin_only
async def admin_support_edit_answer_received(message: Message, state: FSMContext, **kwargs) -> None:
    answer = (message.text or "").strip()
    if not answer:
        await message.answer("Введите непустой текст ответа.")
        return
    data = await state.get_data()
    faq_id = data.get("support_edit_faq_id")
    question = (data.get("support_edit_question") or "").strip()
    await state.clear()
    if faq_id is None or not question:
        await message.answer("Сессия сброшена. Зайдите в «Все вопросы» и выберите вопрос для редактирования снова.", reply_markup=get_admin_keyboard())
        return
    if db.update_support_faq(faq_id, question, answer):
        await message.answer(
            f"✅ Вопрос №{faq_id} сохранён.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 Все вопросы", callback_data="admin:support_list")],
                [InlineKeyboardButton(text="◀️ В меню поддержки", callback_data="admin:support")],
                [InlineKeyboardButton(text="◀️ Главное меню", callback_data="admin:back")],
            ]),
        )
    else:
        await message.answer("Не удалось сохранить (вопрос не найден).", reply_markup=get_admin_keyboard())


# --- Пополнить склад ---
@admin_router.callback_query(F.data == "admin:restock")
@admin_only
async def admin_restock_start(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    products = db.get_products_for_restock()
    if not products:
        await _admin_edit(callback, "Нет товаров с типом «готовый аккаунт» для пополнения.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")]]))
        return
    buttons = [[InlineKeyboardButton(text=p["name"], callback_data=f"admin:restock_product:{p['id']}")] for p in products]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")])
    await _admin_edit(callback, "Выберите товар для пополнения:", InlineKeyboardMarkup(inline_keyboard=buttons))


def _restock_product_info_text(product: dict) -> str:
    cat = "🧠 Нейросети" if product.get("category") == "neural" else "🤖 Автовыдача"
    act = "на мою почту" if product.get("activation_type") == "email" else "готовый аккаунт"
    desc = (product.get("description") or "")[:250]
    if len(product.get("description") or "") > 250:
        desc += "…"
    return (
        f"**{product['name']}**\n\n"
        f"Категория: {cat}\n"
        f"Цена: {product.get('price', 0)} ₽\n"
        f"Активация: {act}\n\n"
        f"Описание: {desc or '—'}\n\n"
        "Что добавляете на склад?"
    )


@admin_router.callback_query(F.data.startswith("admin:restock_product:"))
@admin_only
async def admin_restock_product(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    product_id = int(callback.data.split(":")[2])
    await state.update_data(restock_product_id=product_id)
    product = db.get_product(product_id)
    if not product:
        await _admin_edit(callback, "Товар не найден.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin:restock")]]))
        return
    text = _restock_product_info_text(product)
    await _admin_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Ссылка", callback_data="admin:restock_type:link")],
        [InlineKeyboardButton(text="👤 Аккаунт", callback_data="admin:restock_type:account")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:restock")],
    ]), parse_mode="Markdown")


@admin_router.callback_query(F.data.startswith("admin:restock_type:"))
@admin_only
async def admin_restock_type(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    if callback.data == "admin:restock_type:link":
        await state.update_data(restock_type="link")
        await state.set_state(AdminStates.waiting_restock_data)
        await callback.message.answer("Введите ссылку (одним сообщением):")
    elif callback.data == "admin:restock_type:account":
        await state.update_data(restock_type="account")
        await state.set_state(AdminStates.waiting_restock_data)
        await callback.message.answer(
            "Введите данные аккаунта. Формат (разделитель — точка с запятой):\n"
            "• Логин ; Пароль\n"
            "• Логин ; Пароль ; 2ФА ключ\n\n"
            "Пример: user@mail.ru ; mypass123 ; ABCDEF"
        )
    else:
        await state.clear()
        await _admin_edit(callback, "Меню:", get_admin_keyboard())


@admin_router.message(AdminStates.waiting_restock_data, F.text)
@admin_only
async def admin_restock_data(message: Message, state: FSMContext, **kwargs) -> None:
    data = await state.get_data()
    product_id = data.get("restock_product_id")
    restock_type = data.get("restock_type", "account")
    if not product_id:
        await state.clear()
        await message.answer("Меню:", reply_markup=get_admin_keyboard())
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Введите данные (ссылку или аккаунт).")
        return
    await state.update_data(restock_pending_data=text)
    await message.answer(
        "Есть ли рекомендации или примечание? (Этот текст будет выдан клиенту одним сообщением с инструкцией и данными аккаунта.)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data="admin:restock_skip")],
            [InlineKeyboardButton(text="📝 Добавить примечание", callback_data="admin:restock_add_note")],
        ]),
    )


@admin_router.callback_query(F.data == "admin:restock_skip")
@admin_only
async def admin_restock_skip(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    data = await state.get_data()
    product_id = data.get("restock_product_id")
    restock_type = data.get("restock_type", "account")
    pending = (data.get("restock_pending_data") or "").strip()
    await state.clear()
    if not product_id or not pending:
        await callback.message.answer("Меню:", reply_markup=get_admin_keyboard())
        return
    try:
        db.add_product_account(product_id, pending, item_type=restock_type, tariff_id=None, admin_note=None)
        label = "Ссылка" if restock_type == "link" else "Аккаунт"
        await callback.message.answer(
            f"✅ {label} добавлен(а). Добавить ещё или вернуться в меню?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить ещё", callback_data=f"admin:restock_product:{product_id}")],
                [InlineKeyboardButton(text="◀️ В меню", callback_data="admin:back")],
            ]),
        )
    except Exception as e:
        await callback.message.answer(f"Ошибка: {e}")


@admin_router.callback_query(F.data == "admin:restock_add_note")
@admin_only
async def admin_restock_add_note(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.set_state(AdminStates.waiting_restock_note)
    await callback.message.answer("Введите примечание (текст). Оно будет показано клиенту вместе с инструкцией и данными аккаунта:")


@admin_router.message(AdminStates.waiting_restock_note, F.text)
@admin_only
async def admin_restock_note_msg(message: Message, state: FSMContext, **kwargs) -> None:
    data = await state.get_data()
    product_id = data.get("restock_product_id")
    restock_type = data.get("restock_type", "account")
    pending = (data.get("restock_pending_data") or "").strip()
    note = (message.text or "").strip()
    await state.clear()
    if not product_id or not pending:
        await message.answer("Меню:", reply_markup=get_admin_keyboard())
        return
    try:
        db.add_product_account(product_id, pending, item_type=restock_type, tariff_id=None, admin_note=note)
        label = "Ссылка" if restock_type == "link" else "Аккаунт"
        await message.answer(
            f"✅ {label} добавлен(а) с примечанием. Добавить ещё или вернуться в меню?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить ещё", callback_data=f"admin:restock_product:{product_id}")],
                [InlineKeyboardButton(text="◀️ В меню", callback_data="admin:back")],
            ]),
        )
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


# --- Запросить аккаунт (заявка в группу заказов) ---
class RequestAccountStates(StatesGroup):
    waiting_data = State()


def _parse_add_line(line: str) -> str | None:
    """Парсит одну строку формата: логин | пароль  или  СКУ | логин | пароль  или  логин | пароль | 2fa.
    Возвращает строку для БД: 'логин ; пароль ; 2fa' или None если не распознано."""
    line = line.strip()
    if not line:
        return None
    # Разделитель | (с пробелами или без)
    parts = [p.strip() for p in line.replace(" | ", "|").split("|") if p.strip()]
    if len(parts) == 2:
        return f"{parts[0]} ; {parts[1]}"
    if len(parts) == 3:
        # СКУ | логин | пароль  или  логин | пароль | 2fa (логин обычно с @)
        if "@" in parts[1]:
            return f"{parts[1]} ; {parts[2]}"
        return f"{parts[0]} ; {parts[1]} ; {parts[2]}"
    if len(parts) >= 4:
        return f"{parts[0]} ; {parts[1]} ; {' | '.join(parts[2:])}"
    # Формат: СКУ логин пароль (без pipe, пробелы)
    tokens = line.split()
    if len(tokens) == 2:
        return f"{tokens[0]} ; {tokens[1]}"
    if len(tokens) >= 3:
        # СКУ логин пароль [2fa...] — СКУ первый токен, остальное логин/пароль/2fa
        return f"{tokens[1]} ; {tokens[2]}" + (" ; " + " ".join(tokens[3:]) if len(tokens) > 3 else "")
    return None


def _parse_add_message(text: str) -> list[str]:
    """Парсит сообщение с /add: одна строка или массовое (каждая с новой строки).
    Возвращает список строк для БД: ['логин ; пароль ; 2fa', ...]."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return []
    result = []
    first = lines[0]
    if first.lower().startswith("/add"):
        rest_first = first[4:].strip()
        if rest_first:
            one = _parse_add_line(rest_first)
            if one:
                result.append(one)
        for line in lines[1:]:
            one = _parse_add_line(line)
            if one:
                result.append(one)
        return result
    return []


def _req_acc_message_text(req: dict) -> str:
    return (
        "New order\n"
        f"{req['product_name']}\n"
        f"{req['quantity']}\n"
        "give acc"
    )


def _req_acc_keyboard(request_id: int, status: str) -> InlineKeyboardMarkup:
    if status != "pending":
        return InlineKeyboardMarkup(inline_keyboard=[])
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Не в наличии", callback_data=f"req_acc:no_stock:{request_id}"),
            InlineKeyboardButton(text="Отмена", callback_data=f"req_acc:cancel:{request_id}"),
            InlineKeyboardButton(text="Выдать аккаунт", callback_data=f"req_acc:give:{request_id}"),
        ],
    ])


@admin_router.callback_query(F.data == "admin:request_account")
@admin_only
async def admin_request_account_start(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    products = db.get_products_for_autovydacha()
    if not products:
        await _admin_edit(
            callback,
            "Нет товаров с автовыдачей. Добавьте товары с типом активации «готовый аккаунт».",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")]]),
        )
        return
    buttons = [[InlineKeyboardButton(text=p["name"], callback_data=f"admin:req_product:{p['id']}")] for p in products]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")])
    await _admin_edit(callback, "Выберите товар (автовыдача):", InlineKeyboardMarkup(inline_keyboard=buttons))


@admin_router.callback_query(F.data.startswith("admin:req_product:"))
@admin_only
async def admin_request_account_product(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 3:
        return
    try:
        product_id = int(parts[2])
    except ValueError:
        return
    products = db.get_products_for_autovydacha()
    prod = next((p for p in products if p["id"] == product_id), None)
    if not prod:
        await _admin_edit(callback, "Товар не найден.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin:request_account")]]))
        return
    await state.set_state(AdminStates.waiting_request_quantity)
    await state.update_data(req_acc_product_id=product_id, req_acc_product_name=prod["name"])
    await _admin_edit(
        callback,
        f"Товар: **{prod['name']}**\n\nВведите количество аккаунтов (число):",
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Отмена", callback_data="admin:request_account")]]),
        parse_mode="Markdown",
    )


@admin_router.message(AdminStates.waiting_request_quantity, F.text)
@admin_only
async def admin_request_account_quantity(message: Message, state: FSMContext, **kwargs) -> None:
    data = await state.get_data()
    product_id = data.get("req_acc_product_id")
    product_name = data.get("req_acc_product_name")
    await state.clear()
    if not product_id or not product_name:
        await message.answer("Меню:", reply_markup=get_admin_keyboard())
        return
    try:
        qty = int((message.text or "").strip())
        if qty < 1:
            raise ValueError("Минимум 1")
    except ValueError:
        await message.answer("Введите целое число (количество). Попробуйте снова:", reply_markup=get_admin_keyboard())
        return
    request_id = db.create_account_request(product_id, qty)
    req = db.get_account_request(request_id)
    if not req:
        await message.answer("Ошибка создания заявки.", reply_markup=get_admin_keyboard())
        return
    text = _req_acc_message_text(req)
    kb = _req_acc_keyboard(request_id, "pending")
    try:
        sent = await message.bot.send_message(config.ORDER_GROUP_ID, text, reply_markup=kb)
        db.set_account_request_message(request_id, sent.chat.id, sent.message_id)
    except Exception as e:
        logger.exception("Отправка заявки в группу заказов: %s", e)
        await message.answer(f"Не удалось отправить в группу заказов: {e}. Заявка создана (id={request_id}).", reply_markup=get_admin_keyboard())
        return
    await message.answer("✅ Заявка отправлена в группу заказов.", reply_markup=get_admin_keyboard())


# Обработчики кнопок под заявкой в группе (доступны всем участникам группы заказов)
@admin_router.callback_query(F.data.startswith("req_acc:no_stock:"))
async def req_acc_no_stock(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 3:
        return
    try:
        request_id = int(parts[2])
    except ValueError:
        return
    req = db.get_account_request(request_id)
    if not req:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    if req["status"] != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return
    db.update_account_request_status(request_id, "no_stock")
    new_text = _req_acc_message_text(req) + "\n\n📌 Статус: Не в наличии"
    try:
        await callback.message.edit_text(new_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
    except Exception:
        pass
    try:
        await callback.bot.send_message(
            config.ORDER_GROUP_ID,
            f"📌 Заявка на аккаунт: **{req['product_name']}**, {req['quantity']} шт. — Не в наличии",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning("Уведомление в группу уведомлений (не в наличии): %s", e)


@admin_router.callback_query(F.data.startswith("req_acc:cancel:"))
async def req_acc_cancel(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 3:
        return
    try:
        request_id = int(parts[2])
    except ValueError:
        return
    req = db.get_account_request(request_id)
    if not req:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    if req["status"] != "pending":
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return
    db.update_account_request_status(request_id, "cancelled")
    new_text = _req_acc_message_text(req) + "\n\n📌 Статус: Отменён"
    try:
        await callback.message.edit_text(new_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
    except Exception:
        pass
    try:
        await callback.bot.send_message(
            config.ORDER_GROUP_ID,
            f"📌 Заявка на аккаунт: **{req['product_name']}**, {req['quantity']} шт. — Отменена",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning("Уведомление в группу уведомлений (отмена): %s", e)


@admin_router.callback_query(F.data.startswith("req_acc:give:"))
async def req_acc_give(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 3:
        return
    try:
        request_id = int(parts[2])
    except ValueError:
        return
    req = db.get_account_request(request_id)
    if not req:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    if req["status"] != "pending" and req["status"] != "in_progress":
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return
    # Ждём ввод данных в этом же чате (группа заказов)
    group_chat_id = callback.message.chat.id
    key = StorageKey(bot_id=callback.bot.id, chat_id=group_chat_id, user_id=callback.from_user.id)
    await state.storage.set_state(key=key, state=RequestAccountStates.waiting_data)
    await state.storage.set_data(key=key, data={"req_acc_request_id": request_id})
    await callback.bot.send_message(
        group_chat_id,
        "➕ Добавить аккаунт\n\n"
        "Форматы:\n"
        "/add логин | пароль\n"
        "/add СКУ | логин | пароль\n"
        "/add СКУ логин пароль\n\n"
        "Примеры:\n"
        "/add user@gmail.com | Pass123\n"
        "/add Gemini | user@gmail.com | Pass123\n"
        "/add user@gmail.com | Pass123 | backup codes here\n\n"
        "Массовое (каждый с новой строки):\n"
        "/add Gemini\n"
        "user1@mail.ru | pass1\n"
        "user2@mail.ru | pass2\n\n"
        "Или по-старому: почта ; пароль ; 2FA",
    )


@admin_router.message(RequestAccountStates.waiting_data, F.text)
async def req_acc_receive_data(message: Message, state: FSMContext, **kwargs) -> None:
    data = await state.get_data()
    request_id = data.get("req_acc_request_id")
    await state.clear()
    if not request_id:
        return
    req = db.get_account_request(request_id)
    if not req:
        await message.answer("Заявка не найдена.")
        return
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Данные не введены. Повторите: почта ; пароль ; 2FA или формат /add (см. подсказку выше).")
        await state.set_state(RequestAccountStates.waiting_data)
        await state.update_data(req_acc_request_id=request_id)
        return

    # Формат /add: одна или несколько строк
    if raw.lower().startswith("/add"):
        accounts = _parse_add_message(raw)
        if not accounts:
            await message.answer("Не удалось разобрать формат /add. Пример: /add user@gmail.com | Pass123")
            await state.set_state(RequestAccountStates.waiting_data)
            await state.update_data(req_acc_request_id=request_id)
            return
        issued = 0
        for acc in accounts:
            try:
                db.add_product_account(req["product_id"], acc, item_type="account", tariff_id=None, admin_note=None)
                issued = db.increment_account_request_issued(request_id)
            except Exception as e:
                logger.exception("add_product_account: %s", e)
                await message.answer(f"Ошибка при добавлении одного из аккаунтов: {e}")
        if not issued:
            await state.set_state(RequestAccountStates.waiting_data)
            await state.update_data(req_acc_request_id=request_id)
            return
    else:
        # Классический формат: почта ; пароль ; 2FA
        try:
            db.add_product_account(req["product_id"], raw, item_type="account", tariff_id=None, admin_note=None)
        except Exception as e:
            logger.exception("add_product_account: %s", e)
            await message.answer(f"Ошибка добавления на склад: {e}")
            return
        issued = db.increment_account_request_issued(request_id)

    req = db.get_account_request(request_id)
    all_issued = issued >= req["quantity"]
    if all_issued:
        db.update_account_request_status(request_id, "issued")
    new_text = _req_acc_message_text(req) + f"\n\n📌 Выдано: {issued} из {req['quantity']}"
    if all_issued:
        new_text += "\n\n✅ Заказ добавлен в ассортимент."
    reply_markup = InlineKeyboardMarkup(inline_keyboard=[]) if all_issued else _req_acc_keyboard(request_id, "pending")
    try:
        if req.get("notification_chat_id") and req.get("notification_message_id"):
            await message.bot.edit_message_text(
                chat_id=req["notification_chat_id"],
                message_id=req["notification_message_id"],
                text=new_text,
                reply_markup=reply_markup,
            )
    except Exception as e:
        logger.warning("req_acc: edit group message: %s", e)
    if all_issued:
        await message.answer("✅ Заказ добавлен.")
        try:
            await message.bot.send_message(
                config.ORDER_GROUP_ID,
                f"✅ Заявка на добавление аккаунта одобрена.\n\nТовар: **{req['product_name']}**, {req['quantity']} шт.",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning("Уведомление в группу уведомлений (заявка одобрена): %s", e)
    else:
        await message.answer(f"✅ Аккаунт(ы) добавлены. Осталось внести: {req['quantity'] - issued}.")


# --- История покупок ---
_ADMIN_STATUS_LABELS = {
    "new": "Новый",
    "cancelled": "Отменён",
    "accepted": "Принят",
    "in_progress": "В работе",
    "activated": "Активирован",
    "paid": "Оплачен",
    "awaiting": "Ожидает выдачи",
    "received": "Получен",
}


ADMIN_PURCHASES_PER_PAGE = 10


@admin_router.callback_query(F.data.startswith("admin:purchases"))
@admin_only
async def admin_purchases(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    parts = (callback.data or "").split(":")
    page = int(parts[2]) if len(parts) > 2 else 1
    total = db.count_all_purchases_for_admin()
    total_pages = max(1, (total + ADMIN_PURCHASES_PER_PAGE - 1) // ADMIN_PURCHASES_PER_PAGE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * ADMIN_PURCHASES_PER_PAGE
    rows = db.get_all_purchases_for_admin(limit=ADMIN_PURCHASES_PER_PAGE, offset=offset)
    if not rows:
        await _admin_edit(callback, "Покупок пока нет.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")]]))
        return
    text = f"📋 **История заказов**\n\nСтраница {page} из {total_pages}. Выберите заказ:"
    buttons = []
    for r in rows:
        label = f"№{r['order_number']} {r['product_name'][:20]}{'…' if len(r['product_name']) > 20 else ''} — {r['amount']} ₽"
        if len(label) > 64:
            label = label[:61] + "…"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"admin:purchase:{r['id']}:{page}")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"admin:purchases:{page - 1}"))
    nav.append(InlineKeyboardButton(text="◀️ Главное меню", callback_data="admin:back"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="Далее ▶", callback_data=f"admin:purchases:{page + 1}"))
    buttons.append(nav)
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await _admin_edit(callback, text, kb, parse_mode="Markdown")


@admin_router.callback_query(F.data.startswith("admin:purchase:"))
@admin_only
async def admin_purchase_detail(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    try:
        await callback.answer()
    except Exception:
        pass
    raw_data = (callback.data or "").strip()
    parts = raw_data.split(":")
    if len(parts) < 3:
        return
    try:
        purchase_id = int(parts[2])
        list_page = int(parts[3]) if len(parts) > 3 else 1
    except (ValueError, IndexError):
        list_page = 1
    p = db.get_purchase_detail_for_admin(purchase_id)
    if not p:
        try:
            await callback.message.edit_text(
                "Заказ не найден.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin:purchases:{list_page}")]]),
            )
        except Exception:
            pass
        return
    status = (p.get("status") or "").strip()
    status_label = _ADMIN_STATUS_LABELS.get(status, status or "—")
    nick = f"@{p['username']}" if p.get("username") else f"id{p['user_id']}"
    date_display = format_created_at_moscow(p.get("created_at")) or p.get("created_at", "")
    # Текст без Markdown, чтобы спецсимволы в названии/данных не ломали сообщение
    lines = [
        f"📋 Заказ №{p['order_number']}",
        "",
        f"📌 Статус: {status_label}",
        f"🛍 Товар: {p['product_name']}",
        f"📦 Количество: {p['quantity']} шт.",
        f"💰 Сумма: {p['amount']} ₽",
        f"👤 Покупатель: {nick} (id: {p['user_id']})",
        f"📅 Дата: {date_display}",
        "",
    ]
    if p.get("email_data"):
        lines.append("📧 Данные (почта/пароль/2FA):")
        lines.append(p["email_data"].replace(";", " — "))
        lines.append("")
    if p.get("accounts"):
        lines.append("🔐 Состав (выданные аккаунты):")
        for i, acc in enumerate(p["accounts"], 1):
            raw = (acc.get("account_data") or "").strip()
            if acc.get("item_type") == "link":
                lines.append(f"{i}. {raw}")
            else:
                acc_parts = [x.strip() for x in raw.split(";") if x.strip()]
                if len(acc_parts) >= 2:
                    lines.append(f"{i}. Логин: {acc_parts[0]} | Пароль: {acc_parts[1]}" + (f" | 2FA: {acc_parts[2]}" if len(acc_parts) >= 3 else ""))
                else:
                    lines.append(f"{i}. {raw}")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3997] + "..."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ К списку заказов", callback_data=f"admin:purchases:{list_page}")],
    ])
    try:
        await callback.message.edit_text(text=text, reply_markup=kb)
    except Exception as e:
        logger.warning("Admin purchase detail edit_text: %s", e)
        try:
            await callback.message.answer(text[:4000], reply_markup=kb)
        except Exception:
            pass


# --- Добавить товар ---
@admin_router.callback_query(F.data == "admin:add_product")
@admin_only
async def admin_add_product_start(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.set_state(AdminStates.add_product_category)
    await _admin_edit(callback, "Куда добавить товар?", InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📧 Активация на почту", callback_data="admin:cat_neural")],
        [InlineKeyboardButton(text="🤖 В автовыдачу", callback_data="admin:cat_avto")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")],
    ]))


@admin_router.callback_query(F.data.startswith("admin:cat_"), AdminStates.add_product_category)
@admin_only
async def admin_add_product_category(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    if callback.data == "admin:cat_neural":
        await state.update_data(product_category="neural")
    elif callback.data == "admin:cat_avto":
        await state.update_data(product_category="avto")
    else:
        await state.clear()
        await _admin_edit(callback, "Меню:", get_admin_keyboard())
        return
    await state.set_state(AdminStates.add_product_name)
    await callback.message.answer("Введите название товара:")


@admin_router.message(AdminStates.add_product_name, F.text)
@admin_only
async def admin_add_product_name(message: Message, state: FSMContext, **kwargs) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым.")
        return
    await state.update_data(product_name=name)
    await state.set_state(AdminStates.add_product_description)
    await message.answer("Введите описание товара:")


@admin_router.message(AdminStates.add_product_description, F.text)
@admin_only
async def admin_add_product_description(message: Message, state: FSMContext, **kwargs) -> None:
    await state.update_data(product_description=(message.text or "").strip())
    await state.set_state(AdminStates.add_product_price)
    await message.answer("Введите стоимость в рублях (целое число):")


@admin_router.message(AdminStates.add_product_price, F.text)
@admin_only
async def admin_add_product_price(message: Message, state: FSMContext, **kwargs) -> None:
    try:
        price = int((message.text or "0").strip())
    except ValueError:
        await message.answer("Введите число.")
        return
    if price < 0:
        await message.answer("Стоимость не может быть отрицательной.")
        return
    data = await state.get_data()
    category = data.get("product_category", "neural")
    await state.update_data(product_price=price)
    await state.set_state(AdminStates.add_product_activation)
    if category == "neural":
        await message.answer(
            "Формат активации:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="На мою почту", callback_data="admin:act_email")],
                [InlineKeyboardButton(text="Готовый аккаунт", callback_data="admin:act_account")],
            ]),
        )
    else:
        # Автовыдача: категория остаётся avto, активация — готовый аккаунт (без выбора «нейросети»)
        await state.update_data(product_activation="account", product_category="avto")
        await state.set_state(AdminStates.add_product_image)
        await message.answer("Отправьте изображение товара (фото):")


@admin_router.callback_query(F.data.startswith("admin:act_"), AdminStates.add_product_activation)
@admin_only
async def admin_add_product_activation(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    if callback.data == "admin:act_email":
        await state.update_data(product_activation="email")
    else:
        await state.update_data(product_activation="account")
    await state.set_state(AdminStates.add_product_image)
    await callback.message.answer("Отправьте изображение товара (фото):")


@admin_router.message(AdminStates.add_product_image, F.photo)
@admin_only
async def admin_add_product_image(message: Message, state: FSMContext, **kwargs) -> None:
    photo = message.photo[-1]
    file_id = photo.file_id
    data = await state.get_data()
    category = data.get("product_category", "neural")
    name = data.get("product_name", "")
    description = data.get("product_description", "")
    price = data.get("product_price", 0)
    activation = data.get("product_activation", "account")
    if activation == "email" and category != "neural":
        await message.answer("Формат «На мою почту» доступен только для раздела «Нейросети». Товар не создан. Меню:", reply_markup=get_admin_keyboard())
        await state.clear()
        return
    try:
        product_id = db.add_product(category, name, description, price, activation, file_id)
        await message.answer(f"Товар «{name}» создан (id={product_id}).")
    except Exception as e:
        await message.answer(f"Ошибка создания товара: {e}")
    await state.clear()
    await message.answer("Меню:", reply_markup=get_admin_keyboard())


# --- Все товары (список, удаление, редактирование) ---


def _product_card_text(p: dict) -> str:
    cat = "🧠 нейросети" if p.get("category") == "neural" else "🤖 автовыдача"
    return f"**{p['name']}**\nКатегория: {cat}\nЦена: {p.get('price', 0)} ₽\nАктивация: {p.get('activation_type', 'account')}"


@admin_router.callback_query(F.data == "admin:products")
@admin_only
async def admin_products_list(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    products = db.get_all_products()
    if not products:
        await _admin_edit(callback, "Товаров пока нет.", InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")],
        ]))
        return
    buttons = []
    for p in products:
        label = f"{p['name']} ({p['price']} ₽)"[:60]
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"admin:product:{p['id']}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")])
    await _admin_edit(callback, "Все товары. Выберите товар:", InlineKeyboardMarkup(inline_keyboard=buttons))


# --- Склад: товары и наличие аккаунтов ---
@admin_router.callback_query(F.data == "admin:warehouse")
@admin_only
async def admin_warehouse(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    products = db.get_products_with_stock()
    if not products:
        await _admin_edit(callback, "Товаров пока нет.", InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")],
        ]))
        return
    buttons = []
    for p in products:
        label = f"{p['name']} — в наличии: {p['available']}, всего: {p['total']}"
        if len(label) > 60:
            label = label[:57] + "…"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"admin:wh_product:{p['id']}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")])
    await _admin_edit(callback, "📦 **Склад**\n\nВыберите товар:", InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")


# Числа для подписи аккаунтов (Аккаунт 1, Аккаунт 2, ...)
_ACCOUNT_NUMBERS = ("один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять",
                    "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать",
                    "семнадцать", "восемнадцать", "девятнадцать", "двадцать")


def _account_button_label(index: int) -> str:
    """Подпись для кнопки: Аккаунт один, Аккаунт два, ... или Аккаунт 21, Аккаунт 22..."""
    if 1 <= index <= len(_ACCOUNT_NUMBERS):
        return f"Аккаунт {_ACCOUNT_NUMBERS[index - 1]}"
    return f"Аккаунт {index}"


def _warehouse_product_message(product_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Текст и клавиатура для экрана «аккаунты товара» (Склад → товар)."""
    product = db.get_product(product_id)
    if not product:
        return "Товар не найден.", InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:warehouse")],
        ])
    available = db.count_product_accounts_available(product_id)
    total_used = db.count_product_accounts_used(product_id)
    unused = db.get_product_accounts_unused(product_id, limit=100)
    used_list = db.get_product_accounts_used(product_id, limit=100)
    lines = [
        f"📦 **{product['name']}**",
        "",
        f"✅ В наличии: **{available}**",
        f"📤 Использовано: **{total_used}**",
        "",
        "Выберите аккаунт:",
    ]
    text = "\n".join(lines)
    kb_buttons = []
    num = 1
    for acc in unused[:30]:
        kb_buttons.append([InlineKeyboardButton(
            text=_account_button_label(num),
            callback_data=f"admin:wh_account:{product_id}:{acc['id']}",
        )])
        num += 1
    if used_list:
        for acc in used_list[:20]:
            kb_buttons.append([InlineKeyboardButton(
                text=_account_button_label(num) + " (исп.)",
                callback_data=f"admin:wh_account:{product_id}:{acc['id']}",
            )])
            num += 1
    if not kb_buttons:
        text += "\n\n— аккаунтов пока нет"
    kb_buttons.append([InlineKeyboardButton(text="◀️ Назад к складу", callback_data="admin:warehouse")])
    return text, InlineKeyboardMarkup(inline_keyboard=kb_buttons)


@admin_router.callback_query(F.data.startswith("admin:wh_product:"))
@admin_only
async def admin_warehouse_product(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 3:
        return
    try:
        product_id = int(parts[2])
    except ValueError:
        return
    text, kb = _warehouse_product_message(product_id)
    await _admin_edit(callback, text, kb, parse_mode="Markdown")


@admin_router.callback_query(F.data.startswith("admin:wh_used:"))
@admin_only
async def admin_warehouse_used(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 3:
        return
    try:
        product_id = int(parts[2])
    except ValueError:
        return
    product = db.get_product(product_id)
    if not product:
        await _admin_edit(callback, "Товар не найден.", InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:warehouse")],
        ]))
        return
    used_list = db.get_product_accounts_used(product_id)
    lines = [
        f"📤 **Использованные аккаунты — {product['name']}**",
        "",
    ]
    if not used_list:
        lines.append("— нет")
    else:
        for i, acc in enumerate(used_list[:60], 1):
            raw = (acc.get("account_data") or "").strip()
            if len(raw) > 60:
                raw = raw[:57] + "…"
            order_id = (acc.get("order_id") or "").strip()
            used_at = format_created_at_moscow(acc.get("used_at")) or (acc.get("used_at") or "")[:16]
            lines.append(f"{i}. {raw} | заказ {order_id} {used_at}")
        if len(used_list) > 60:
            lines.append(f"… и ещё {len(used_list) - 60}")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3997] + "…"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к товару", callback_data=f"admin:wh_product:{product_id}")],
        [InlineKeyboardButton(text="◀️ Назад к складу", callback_data="admin:warehouse")],
    ])
    await _admin_edit(callback, text, kb, parse_mode="Markdown")


def _format_account_for_admin(acc: dict) -> str:
    """Форматирует данные аккаунта для админа: логин, пароль или ссылка."""
    raw = (acc.get("account_data") or "").strip()
    if (acc.get("item_type") or "account").strip().lower() == "link":
        return f"🔗 Ссылка:\n{raw}"
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    if len(parts) >= 2:
        lines = [f"👤 Логин: {parts[0]}", f"🔑 Пароль: {parts[1]}"]
        if len(parts) >= 3:
            lines.append(f"2ФА: {parts[2]}")
        return "\n".join(lines)
    return raw or "—"


@admin_router.callback_query(F.data.startswith("admin:wh_account:"))
@admin_only
async def admin_warehouse_account(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    """Просмотр одного аккаунта: логин/пароль или ссылка, кнопки Удалить и Назад к списку."""
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 4:
        return
    try:
        product_id = int(parts[2])
        account_id = int(parts[3])
    except ValueError:
        return
    acc = db.get_product_account_by_id(account_id)
    if not acc or acc["product_id"] != product_id:
        await callback.answer("Аккаунт не найден.", show_alert=True)
        return
    text = _format_account_for_admin(acc)
    if acc.get("used"):
        text = "📤 Использован\n\n" + text
    if acc.get("admin_note"):
        text += f"\n\n📝 Примечание: {acc['admin_note']}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin:wh_account_delete:{account_id}:{product_id}")],
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data=f"admin:wh_product:{product_id}")],
    ])
    await _admin_edit(callback, text, kb, parse_mode=None)


@admin_router.callback_query(F.data.startswith("admin:wh_account_delete:"))
@admin_only
async def admin_warehouse_account_delete(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    """Удалить аккаунт из склада и вернуться к списку аккаунтов товара."""
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 4:
        return
    try:
        account_id = int(parts[2])
        product_id = int(parts[3])
    except ValueError:
        return
    deleted = db.delete_product_account(account_id)
    if not deleted:
        await callback.answer("Аккаунт уже удалён.", show_alert=True)
        # Всё равно показываем список товара
    else:
        await callback.answer("Аккаунт удалён.", show_alert=True)
    text, kb = _warehouse_product_message(product_id)
    await _admin_edit(callback, text, kb, parse_mode="Markdown")


@admin_router.callback_query(F.data.startswith("admin:product:"))
@admin_only
async def admin_product_detail(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    data = callback.data
    if ":del_yes" in data:
        parts = data.replace(":del_yes", "").split(":")
        pid = int(parts[2])
        db.delete_product(pid)
        await state.clear()
        await admin_products_list(callback, state, **kwargs)
        return
    if ":del:" in data or data.endswith(":del"):
        pid = int(data.split(":")[2])
        product = db.get_product(pid)
        if not product:
            await admin_products_list(callback, state, **kwargs)
            return
        await _admin_edit(callback, f"Удалить товар «{product['name']}»? Остатки склада будут удалены.", InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin:product:{pid}:del_yes")],
            [InlineKeyboardButton(text="◀️ Нет, назад", callback_data=f"admin:product:{pid}")],
        ]))
        return
    try:
        pid = int(data.split(":")[2])
    except (IndexError, ValueError):
        await admin_products_list(callback, state, **kwargs)
        return
    await _show_product_detail(callback, pid)


async def _show_product_detail(callback: CallbackQuery, product_id: int) -> None:
    product = db.get_product(product_id)
    if not product:
        await _admin_edit(callback, "Товар не найден.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin:products")]]))
        return
    text = _product_card_text(product)
    desc = (product.get("description") or "")[:200]
    if desc:
        text += f"\n\nОписание: {desc}…" if len(product.get("description") or "") > 200 else f"\n\nОписание: {desc}"
    buttons = [
        [InlineKeyboardButton(text="🗑 Удалить товар", callback_data=f"admin:product:{product_id}:del")],
        [InlineKeyboardButton(text="✏️ Редактировать товар", callback_data=f"admin:pedit:{product_id}:menu")],
        [InlineKeyboardButton(text="◀️ К списку товаров", callback_data="admin:products")],
    ]
    await _admin_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")


@admin_router.callback_query(F.data.startswith("admin:pedit:"))
@admin_only
async def admin_product_edit_menu(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    parts = callback.data.split(":")
    if len(parts) < 4:
        return
    product_id = int(parts[2])
    field = parts[3]
    product = db.get_product(product_id)
    if not product:
        await _show_product_detail(callback, product_id)
        return
    if field == "menu":
        await state.update_data(edit_product_id=product_id)
        cat = product.get("category") == "neural"
        buttons = [
            [InlineKeyboardButton(text="Название", callback_data=f"admin:pedit:{product_id}:name")],
            [InlineKeyboardButton(text="Описание", callback_data=f"admin:pedit:{product_id}:desc")],
            [InlineKeyboardButton(text="Цена", callback_data=f"admin:pedit:{product_id}:price")],
            [InlineKeyboardButton(text="Фото", callback_data=f"admin:pedit:{product_id}:photo")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin:product:{product_id}")],
        ]
        if cat:
            buttons.insert(4, [InlineKeyboardButton(text="Тип активации", callback_data=f"admin:pedit:{product_id}:act")])
        await _admin_edit(callback, f"Что изменить у товара «{product['name']}»?", InlineKeyboardMarkup(inline_keyboard=buttons))
        return
    if field == "name":
        await state.set_state(AdminStates.edit_product_name)
        await state.update_data(edit_product_id=product_id)
        await callback.message.answer("Введите новое название товара:")
        return
    if field == "desc":
        await state.set_state(AdminStates.edit_product_description)
        await state.update_data(edit_product_id=product_id)
        await callback.message.answer("Введите новое описание товара:")
        return
    if field == "price":
        await state.set_state(AdminStates.edit_product_price)
        await state.update_data(edit_product_id=product_id)
        await callback.message.answer("Введите новую цену (целое число, ₽):")
        return
    if field == "photo":
        await state.set_state(AdminStates.edit_product_image)
        await state.update_data(edit_product_id=product_id)
        await callback.message.answer("Отправьте новое фото товара:")
        return
    if field == "act":
        await state.set_state(AdminStates.edit_product_activation)
        await state.update_data(edit_product_id=product_id)
        await callback.message.answer("Выберите тип активации:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="На мою почту", callback_data="admin:pedit_act:email")],
            [InlineKeyboardButton(text="Готовый аккаунт", callback_data="admin:pedit_act:account")],
        ]))
        return


@admin_router.callback_query(F.data.startswith("admin:pedit_act:"))
@admin_only
async def admin_product_edit_activation(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    data = await state.get_data()
    pid = data.get("edit_product_id")
    if not pid:
        await state.clear()
        await _admin_edit(callback, "Меню:", get_admin_keyboard())
        return
    act = "email" if "email" in callback.data else "account"
    db.update_product(pid, activation_type=act)
    await state.clear()
    await callback.message.answer("Тип активации сохранён.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="К товару", callback_data=f"admin:product:{pid}")],
        [InlineKeyboardButton(text="В меню", callback_data="admin:back")],
    ]))


@admin_router.message(AdminStates.edit_product_name, F.text)
@admin_only
async def admin_product_edit_name_msg(message: Message, state: FSMContext, **kwargs) -> None:
    data = await state.get_data()
    pid = data.get("edit_product_id")
    await state.clear()
    if not pid:
        await message.answer("Меню:", reply_markup=get_admin_keyboard())
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("Название не может быть пустым.")
        return
    db.update_product(pid, name=name)
    await message.answer("Название сохранено.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="К товару", callback_data=f"admin:product:{pid}")],
        [InlineKeyboardButton(text="В меню", callback_data="admin:back")],
    ]))


@admin_router.message(AdminStates.edit_product_description, F.text)
@admin_only
async def admin_product_edit_desc_msg(message: Message, state: FSMContext, **kwargs) -> None:
    data = await state.get_data()
    pid = data.get("edit_product_id")
    await state.clear()
    if not pid:
        await message.answer("Меню:", reply_markup=get_admin_keyboard())
        return
    db.update_product(pid, description=(message.text or "").strip())
    await message.answer("Описание сохранено.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="К товару", callback_data=f"admin:product:{pid}")],
        [InlineKeyboardButton(text="В меню", callback_data="admin:back")],
    ]))


@admin_router.message(AdminStates.edit_product_price, F.text)
@admin_only
async def admin_product_edit_price_msg(message: Message, state: FSMContext, **kwargs) -> None:
    data = await state.get_data()
    pid = data.get("edit_product_id")
    await state.clear()
    if not pid:
        await message.answer("Меню:", reply_markup=get_admin_keyboard())
        return
    try:
        price = int((message.text or "0").strip())
    except ValueError:
        await message.answer("Введите целое число.")
        return
    if price < 0:
        await message.answer("Цена не может быть отрицательной.")
        return
    db.update_product(pid, price=price)
    await message.answer("Цена сохранена.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="К товару", callback_data=f"admin:product:{pid}")],
        [InlineKeyboardButton(text="В меню", callback_data="admin:back")],
    ]))


@admin_router.message(AdminStates.edit_product_image, F.photo)
@admin_only
async def admin_product_edit_image_msg(message: Message, state: FSMContext, **kwargs) -> None:
    data = await state.get_data()
    pid = data.get("edit_product_id")
    await state.clear()
    if not pid:
        await message.answer("Меню:", reply_markup=get_admin_keyboard())
        return
    file_id = message.photo[-1].file_id
    db.update_product(pid, image_file_id=file_id)
    await message.answer("Фото сохранено.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="К товару", callback_data=f"admin:product:{pid}")],
        [InlineKeyboardButton(text="В меню", callback_data="admin:back")],
    ]))


@admin_router.callback_query(F.data == "admin:back")
@admin_only
async def admin_back(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    await _admin_edit(callback, "Меню:", get_admin_keyboard())
