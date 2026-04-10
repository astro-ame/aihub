# -*- coding: utf-8 -*-
"""Панель менеджера: /manager, пароль, запросить аккаунт, промокоды, наличие, поддержка, рассылка. Уведомления админам."""

import asyncio
import logging

from aiogram import F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import config
import database as db

logger = logging.getLogger(__name__)
manager_router = Router()

# Темы поддержки (как в admin_handlers)
MANAGER_SUPPORT_TOPICS = [
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


class ManagerStates(StatesGroup):
    waiting_password = State()
    waiting_request_quantity = State()
    waiting_promo_value = State()
    waiting_promo_code = State()
    waiting_broadcast = State()


def manager_only(func):
    """Декоратор: только для config.MANAGER_IDS."""
    async def wrapped(event, *args, **kwargs):
        user_id = event.from_user.id if event.from_user else 0
        if user_id not in config.MANAGER_IDS:
            return
        return await func(event, *args, **kwargs)
    return wrapped


async def notify_admins_manager_action(bot, text: str) -> None:
    """Отправить уведомление всем админам о действии менеджера."""
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"📋 **Панель менеджера**\n\n{text}", parse_mode="Markdown")
        except Exception as e:
            logger.warning("Уведомление админу %s о действии менеджера: %s", admin_id, e)


def get_manager_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Запросить аккаунт", callback_data="manager:request_account")],
        [InlineKeyboardButton(text="📋 Список промокодов", callback_data="manager:promo_list")],
        [InlineKeyboardButton(text="🎟 Создать промокод", callback_data="manager:promo_create")],
        [InlineKeyboardButton(text="📦 Наличие товаров (автовыдача)", callback_data="manager:stock")],
        [InlineKeyboardButton(text="💬 Поддержка", callback_data="manager:support")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="manager:broadcast")],
    ])


def _req_acc_message_text(req: dict) -> str:
    return (
        "New order\n"
        f"{req['product_name']}\n"
        f"{req['quantity']}\n"
        "give acc"
    )


def _req_acc_keyboard(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Не в наличии", callback_data=f"req_acc:no_stock:{request_id}"),
            InlineKeyboardButton(text="Отмена", callback_data=f"req_acc:cancel:{request_id}"),
            InlineKeyboardButton(text="Выдать аккаунт", callback_data=f"req_acc:give:{request_id}"),
        ],
    ])


# --- Вход по паролю ---
@manager_router.message(Command("manager"))
@manager_only
async def cmd_manager(message: Message, state: FSMContext, **kwargs) -> None:
    await state.clear()
    await state.set_state(ManagerStates.waiting_password)
    await message.answer("Введите пароль панели менеджера:")


@manager_router.message(ManagerStates.waiting_password, F.text)
@manager_only
async def manager_password(message: Message, state: FSMContext, **kwargs) -> None:
    if message.text != config.MANAGER_PASSWORD:
        await message.answer("Неверный пароль.")
        return
    try:
        await message.delete()
    except Exception:
        pass
    await state.clear()
    await message.answer("Панель менеджера:", reply_markup=get_manager_keyboard())


@manager_router.callback_query(F.data == "manager:back")
@manager_only
async def manager_back(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    try:
        await callback.message.edit_text("Панель менеджера:", reply_markup=get_manager_keyboard())
    except Exception:
        await callback.message.answer("Панель менеджера:", reply_markup=get_manager_keyboard())


# --- Запросить аккаунт ---
@manager_router.callback_query(F.data == "manager:request_account")
@manager_only
async def manager_request_account_start(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    products = db.get_products_for_autovydacha()
    if not products:
        try:
            await callback.message.edit_text(
                "Нет товаров с автовыдачей.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="manager:back")],
                ]),
            )
        except Exception:
            await callback.message.answer("Нет товаров с автовыдачей.", reply_markup=get_manager_keyboard())
        return
    buttons = [[InlineKeyboardButton(text=p["name"], callback_data=f"manager:req_product:{p['id']}")] for p in products]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="manager:back")])
    try:
        await callback.message.edit_text(
            "Выберите товар (автовыдача):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    except Exception:
        await callback.message.answer("Выберите товар (автовыдача):", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@manager_router.callback_query(F.data.startswith("manager:req_product:"))
@manager_only
async def manager_request_account_product(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
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
        await callback.message.edit_text("Товар не найден.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="manager:request_account")],
        ]))
        return
    await state.set_state(ManagerStates.waiting_request_quantity)
    await state.update_data(req_acc_product_id=product_id, req_acc_product_name=prod["name"])
    try:
        await callback.message.edit_text(
            f"Товар: **{prod['name']}**\n\nВведите количество аккаунтов (число):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data="manager:request_account")],
            ]),
            parse_mode="Markdown",
        )
    except Exception:
        await callback.message.answer(
            f"Товар: {prod['name']}\n\nВведите количество аккаунтов (число):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data="manager:request_account")],
            ]),
        )


@manager_router.message(ManagerStates.waiting_request_quantity, F.text)
@manager_only
async def manager_request_account_quantity(message: Message, state: FSMContext, **kwargs) -> None:
    data = await state.get_data()
    product_id = data.get("req_acc_product_id")
    product_name = data.get("req_acc_product_name")
    await state.clear()
    if not product_id or not product_name:
        await message.answer("Панель менеджера:", reply_markup=get_manager_keyboard())
        return
    try:
        qty = int((message.text or "").strip())
        if qty < 1:
            raise ValueError("Минимум 1")
    except ValueError:
        await message.answer("Введите целое число (количество). Попробуйте снова:", reply_markup=get_manager_keyboard())
        return
    request_id = db.create_account_request(product_id, qty)
    req = db.get_account_request(request_id)
    if not req:
        await message.answer("Ошибка создания заявки.", reply_markup=get_manager_keyboard())
        return
    text = _req_acc_message_text(req)
    kb = _req_acc_keyboard(request_id)
    try:
        sent = await message.bot.send_message(config.ORDER_GROUP_ID, text, reply_markup=kb)
        db.set_account_request_message(request_id, sent.chat.id, sent.message_id)
    except Exception as e:
        logger.exception("Менеджер: отправка заявки в группу заказов: %s", e)
        await message.answer(f"Не удалось отправить в группу заказов: {e}. Заявка создана (id={request_id}).", reply_markup=get_manager_keyboard())
        return
    await message.answer("✅ Заявка отправлена в группу заказов.", reply_markup=get_manager_keyboard())
    await notify_admins_manager_action(
        message.bot,
        f"Менеджер (id{message.from_user.id}) создал заявку на аккаунт: **{product_name}**, {qty} шт.",
    )


# --- Список промокодов ---
@manager_router.callback_query(F.data == "manager:promo_list")
@manager_only
async def manager_promo_list(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    rows = db.get_promocodes_list_unused()
    if not rows:
        text = "Нет промокодов с оставшимися активациями."
    else:
        lines = ["📋 **Список промокодов**\n"]
        for r in rows:
            t = "скидка " + str(r["value"]) + "%" if r.get("promo_type") == "percent" else str(r["value"]) + " ₽"
            lines.append(f"• **{r['code']}** — {t}, использовано {r['used_count']}/{r['max_uses']}")
        text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3997] + "…"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="manager:back")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")


# --- Создать промокод (упрощённо: только денежный, одноразовый или ввести макс. использований) ---
@manager_router.callback_query(F.data == "manager:promo_create")
@manager_only
async def manager_promo_create_start(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.set_state(ManagerStates.waiting_promo_value)
    try:
        await callback.message.edit_text(
            "Введите сумму промокода в рублях (целое число):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data="manager:back")],
            ]),
        )
    except Exception:
        await callback.message.answer(
            "Введите сумму промокода в рублях (целое число):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data="manager:back")],
            ]),
        )


@manager_router.message(ManagerStates.waiting_promo_value, F.text)
@manager_only
async def manager_promo_value(message: Message, state: FSMContext, **kwargs) -> None:
    try:
        val = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введите целое число.")
        return
    if val < 1:
        await message.answer("Сумма должна быть больше 0.")
        return
    await state.update_data(promo_value=val)
    await state.set_state(ManagerStates.waiting_promo_code)
    await message.answer("Введите код промокода (латиница/цифры, без пробелов):")


@manager_router.message(ManagerStates.waiting_promo_code, F.text)
@manager_only
async def manager_promo_code(message: Message, state: FSMContext, **kwargs) -> None:
    code = (message.text or "").strip().upper().replace(" ", "")
    if not code:
        await message.answer("Код не может быть пустым.")
        return
    data = await state.get_data()
    value = data.get("promo_value", 0)
    await state.clear()
    try:
        db.add_promo_fixed(code, value, max_uses=1)
        await message.answer(f"Промокод «{code}» создан: {value} ₽ на баланс.", reply_markup=get_manager_keyboard())
    except Exception as e:
        await message.answer(f"Ошибка: {e}. Возможно, код уже существует.", reply_markup=get_manager_keyboard())
        return
    await notify_admins_manager_action(
        message.bot,
        f"Менеджер (id{message.from_user.id}) создал промокод: **{code}** — {value} ₽.",
    )


# --- Наличие товаров (автовыдача), без данных аккаунтов ---
@manager_router.callback_query(F.data == "manager:stock")
@manager_only
async def manager_stock(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    products = db.get_products_for_autovydacha()
    if not products:
        try:
            await callback.message.edit_text(
                "Нет товаров с автовыдачей.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="manager:back")],
                ]),
            )
        except Exception:
            await callback.message.answer("Нет товаров с автовыдачей.", reply_markup=get_manager_keyboard())
        return
    buttons = []
    for p in products:
        available = db.count_product_accounts_available(p["id"])
        label = f"{p['name']} — в наличии: {available}"[:64]
        buttons.append([InlineKeyboardButton(text=label, callback_data="manager:stock_nodata")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="manager:back")])
    text = "📦 **Наличие товаров (автовыдача)**\n\nТолько количество. Данные аккаунтов не отображаются."
    try:
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="Markdown")


@manager_router.callback_query(F.data == "manager:stock_nodata")
@manager_only
async def manager_stock_nodata(callback: CallbackQuery, **kwargs) -> None:
    await callback.answer("Данные аккаунтов недоступны в панели менеджера.", show_alert=True)


# --- Поддержка (список FAQ, только просмотр) ---
@manager_router.callback_query(F.data == "manager:support")
@manager_only
async def manager_support(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    all_faq = db.get_all_support_faq()
    topic_labels = dict(MANAGER_SUPPORT_TOPICS)
    if not all_faq:
        text = "📋 **Поддержка**\n\nПока нет вопросов в FAQ."
    else:
        lines = ["📋 **Поддержка (FAQ)**\n"]
        for faq in all_faq[:30]:
            topic = topic_labels.get(faq["product_key"], faq["product_key"])
            q_short = ((faq["question_text"] or "")[:50]).replace("*", "•")
            if len(faq["question_text"] or "") > 50:
                q_short += "…"
            lines.append(f"• **{topic}**: {q_short}")
        if len(all_faq) > 30:
            lines.append(f"\n… и ещё {len(all_faq) - 30} вопросов.")
        text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3997] + "…"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="manager:back")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")


# --- Рассылка ---
@manager_router.callback_query(F.data == "manager:broadcast")
@manager_only
async def manager_broadcast_start(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.set_state(ManagerStates.waiting_broadcast)
    try:
        await callback.message.edit_text(
            "Введите сообщение для рассылки (одним сообщением). Поддерживается Markdown.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data="manager:broadcast_cancel")],
            ]),
        )
    except Exception:
        await callback.message.answer(
            "Введите сообщение для рассылки (одним сообщением). Поддерживается Markdown.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data="manager:broadcast_cancel")],
            ]),
        )


@manager_router.callback_query(F.data == "manager:broadcast_cancel")
@manager_only
async def manager_broadcast_cancel(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    await callback.answer()
    await state.clear()
    try:
        await callback.message.edit_text("Отменено. Панель менеджера:", reply_markup=get_manager_keyboard())
    except Exception:
        await callback.message.answer("Отменено. Панель менеджера:", reply_markup=get_manager_keyboard())


@manager_router.message(ManagerStates.waiting_broadcast, F.text | F.caption)
@manager_only
async def manager_broadcast_send(message: Message, state: FSMContext, **kwargs) -> None:
    await state.clear()
    text = ((message.text or message.caption) or "").strip()
    if not text:
        await message.answer("Текст пустой. Панель менеджера:", reply_markup=get_manager_keyboard())
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
    await message.answer(
        f"Рассылка завершена. Отправлено: {sent}, не доставлено: {failed}. Панель менеджера:",
        reply_markup=get_manager_keyboard(),
    )
    await notify_admins_manager_action(
        message.bot,
        f"Менеджер (id{message.from_user.id}) выполнил рассылку. Отправлено: {sent}, не доставлено: {failed}.",
    )
