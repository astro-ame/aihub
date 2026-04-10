# -*- coding: utf-8 -*-
"""привет
"""
"""
Ai Hub Market — бот магазина подписок на нейросети (aiogram).
Главное меню, профиль (баланс, рефералка, покупки, промокод), пополнение через Pally.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
    InputMediaPhoto,
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

import config
import database as db


def _get_welcome_photo():
    """Фото для главного меню: локальный файл data/main_menu.png или WELCOME_IMAGE_URL."""
    if getattr(config, "MAIN_MENU_IMAGE_PATH", None) and config.MAIN_MENU_IMAGE_PATH.exists():
        return FSInputFile(config.MAIN_MENU_IMAGE_PATH)
    return config.WELCOME_IMAGE_URL


def _get_avto_menu_photo():
    """Фото для раздела «Автовыдача»: data/avto_menu.png или None (тогда только текст)."""
    if getattr(config, "AVTO_MENU_IMAGE_PATH", None) and config.AVTO_MENU_IMAGE_PATH.exists():
        return FSInputFile(config.AVTO_MENU_IMAGE_PATH)
    return None


def _get_catalog_menu_photo():
    """Фото для раздела «Все нейросети»: data/catalog_menu.png или None."""
    if getattr(config, "CATALOG_MENU_IMAGE_PATH", None) and config.CATALOG_MENU_IMAGE_PATH.exists():
        return FSInputFile(config.CATALOG_MENU_IMAGE_PATH)
    return None


def _get_about_menu_photo():
    """Фото для раздела «О боте»: data/about_menu.png или None."""
    if getattr(config, "ABOUT_MENU_IMAGE_PATH", None) and config.ABOUT_MENU_IMAGE_PATH.exists():
        return FSInputFile(config.ABOUT_MENU_IMAGE_PATH)
    return None


def _get_support_menu_photo():
    """Фото для раздела «Поддержка»: data/support_menu.png или None."""
    if getattr(config, "SUPPORT_MENU_IMAGE_PATH", None) and config.SUPPORT_MENU_IMAGE_PATH.exists():
        return FSInputFile(config.SUPPORT_MENU_IMAGE_PATH)
    return None


def _get_profile_menu_photo():
    """Фото для раздела «Профиль»: data/profile_menu.png или None."""
    if getattr(config, "PROFILE_MENU_IMAGE_PATH", None) and config.PROFILE_MENU_IMAGE_PATH.exists():
        return FSInputFile(config.PROFILE_MENU_IMAGE_PATH)
    return None
from pally_client import create_payment_link, check_payment_status
from utils_dt import format_created_at_moscow
from admin_handlers import admin_router
from manager_handlers import manager_router

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

router = Router()

# --- FSM ---
class ProfileStates(StatesGroup):
    waiting_promo = State()
    waiting_topup_amount = State()


class CatalogStates(StatesGroup):
    waiting_email_order = State()  # заказ «на почту»: ждём почту, пароль, 2FA
    waiting_email_confirm = State()  # ждём подтверждения «данные верны»


# --- Тексты ---
WELCOME_TEXT = """🚀 **Добро пожаловать в AI Hub Market**

Здесь вы получаете доступ к топ-нейросетям быстро, безопасно и без лишних разговоров.

✨ AI Hub — это умный маркет подписок с автоматической выдачей.

Вы выбираете инструмент → оплачиваете → получаете доступ почти мгновенно.

• Никаких ожиданий менеджеров
• Никаких длинных диалогов
• Только удобный сервис и рабочие решения

Мы создали бота, который экономит ваше время и упрощает получение цифровых продуктов.

Всё прозрачно, быстро и понятно.

👇 Выберите нужный раздел и начните пользоваться уже сейчас."""

def _catalog_keyboard(category: str) -> InlineKeyboardMarkup:
    """Клавиатура: список товаров категории (название + ✅/❌)."""
    products = db.get_products_by_category(category)
    rows = []
    for p in products:
        if p.get("activation_type") == "email":
            emo = "✅"
        else:
            stock = db.count_product_accounts_available(p["id"])
            emo = "✅" if stock > 0 else "❌"
        label = f"{p['name']} {emo}"[:64]
        rows.append([InlineKeyboardButton(text=label, callback_data=f"catalog:product:{p['id']}")])
    rows.append([InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
# Темы поддержки (ключ для БД, подпись на кнопке)
SUPPORT_TOPICS = [
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

SUPPORT_INTRO = (
    "Здесь вы можете получить помощь двумя способами:\n\n"
    "⚡ **Быстрые ответы** — выберите нужную категорию или товар и получите готовое решение за пару секунд.\n\n"
    "👤 **Связь с менеджером** — если ситуация нестандартная, подключится специалист и разберётся лично.\n\n"
    "По вопросам доступа, активации, оплаты или работы подписки — всё решается здесь.\n\n"
    "Выберите подходящий вариант ниже и получите помощь без лишних ожиданий."
)
MANAGER_URL = f"tg://user?id={config.SUPPORT_MANAGER_ID}"

ABOUT_BOT_TEXT = """👋 **О боте AI Hub Market**

AI Hub Market — это автоматизированный магазин подписок на нейросети.

Мы создали его для тех, кто не хочет тратить время на переписки и ожидание менеджеров.

Этот бот подойдёт:
— специалистам, работающим с ИИ
— дизайнерам, монтажёрам, маркетологам
— разработчикам
— предпринимателям
— и всем, кто хочет быстрый доступ к современным инструментам

**⚙ Как это работает**

Вы выбираете нужную нейросеть → оплачиваете → получаете доступ.

Автовыдача или активация на вашу почту — в зависимости от продукта.

Всё максимально просто и прозрачно.

**💎 Что есть внутри**

• Каталог популярных нейросетей
• Автоматическая выдача доступов
• Активация подписок на ваш аккаунт
• Личный профиль с историей покупок
• Поддержка, если потребуется помощь

AI Hub — это скорость, удобство и рабочий сервис без лишнего шума.

Мы сделали бота таким, каким сами хотели бы пользоваться 🚀"""


def get_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile"),
            InlineKeyboardButton(text="🤖 Автовыдача", callback_data="menu:avto"),
        ],
        [
            InlineKeyboardButton(text="📧 Активации на почту", callback_data="menu:catalog"),
            InlineKeyboardButton(text="📢 Новости Ai Hub", url=f"tg://resolve?domain={config.CHANNEL_USERNAME}"),
        ],
        [
            InlineKeyboardButton(text="💬 Поддержка", callback_data="menu:support"),
            InlineKeyboardButton(text="ℹ️ О боте", callback_data="menu:about"),
        ],
    ])


BACK_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="menu:main")],
])


def _escape_markdown(s: str) -> str:
    """Экранирует символы Markdown (_ * ` [), чтобы текст не ломал разбор (например ник с подчёркиванием)."""
    for c in ("_", "*", "`", "["):
        s = s.replace(c, "\\" + c)
    return s


def get_profile_text(user_id: int, telegram_username: str | None = None) -> str:
    """Текст профиля. telegram_username — ник из Telegram (@ без собаки), при открытии профиля передавать для актуального отображения."""
    db.ensure_user(user_id, telegram_username)
    u = db.get_user(user_id)
    username = (u.get("username") or "").strip()
    if not username and telegram_username:
        username = telegram_username.strip()
    nick_display = _escape_markdown(f"@{username}") if username else "—"
    balance = u.get("balance") or 0
    return (
        "👤 **Ваш профиль**\n\n"
        "Добро пожаловать в ваш личный кабинет.\n\n"
        f"**Ник:** {nick_display}\n"
        f"**Баланс:** {balance} ₽\n\n"
        "Здесь вы управляете своими покупками и доступами к нейросетям.\n"
        "Всё под контролем — быстро и удобно.\n\n"
        "💳 Пополнить баланс — для мгновенных покупок\n"
        "🎁 Ввести промокод — получить бонус\n"
        "👥 Пригласить друзей — зарабатывать вместе\n"
        "📦 Мои покупки — все активные подписки в одном месте\n\n"
        "Ваш баланс — это быстрый доступ к нужным инструментам без ожиданий.\n\n"
        "Выберите действие ниже и продолжайте работу 🚀"
    )


def get_profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔗 Рефералка", callback_data="profile:ref"),
            InlineKeyboardButton(text="🛒 Мои покупки", callback_data="profile:purchases"),
        ],
        [
            InlineKeyboardButton(text="💰 Баланс", callback_data="profile:balance"),
            InlineKeyboardButton(text="🎟 Промокод", callback_data="profile:promo"),
        ],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main")],
    ])


def _has_photo(msg: Message) -> bool:
    return bool(getattr(msg, "photo", None))


# Секунд после создания ссылки, прежде чем кнопка «Проверить оплату» станет доступна
WAIT_BEFORE_CHECK_SEC = 10


async def safe_answer_callback(callback: CallbackQuery, **kwargs) -> None:
    """Ответ на callback; игнорирует ошибку «query is too old» (устаревшее нажатие)."""
    try:
        await callback.answer(**kwargs)
    except TelegramBadRequest as e:
        msg = (getattr(e, "message", None) or str(e) or "").lower()
        if "query is too old" in msg or "response timeout" in msg or "query id is invalid" in msg:
            pass
        else:
            raise


async def _edit_or_caption(msg: Message, text: str, reply_markup: InlineKeyboardMarkup, parse_mode: str | None = "Markdown") -> None:
    kwargs = {"reply_markup": reply_markup}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    if _has_photo(msg):
        await msg.edit_caption(caption=text, **kwargs)
    else:
        await msg.edit_text(text=text, **kwargs)


async def _navigate_to(
    msg: Message,
    bot: Bot,
    text: str,
    kb: InlineKeyboardMarkup,
    photo=None,
    parse_mode: str = "Markdown",
) -> None:
    """
    Плавный переход между разделами через редактирование существующего сообщения.

    Логика:
    - Если оба сообщения (текущее и новое) с фото → edit_media (меняем фото + caption).
    - Если текущее с фото, новое без → edit_caption (оставляем фото, меняем текст).
    - Если текущее без фото → edit_text.
    - Если редактирование недоступно → fallback: удалить + отправить новое.
    """
    chat_id = msg.chat.id
    try:
        if photo and _has_photo(msg):
            await msg.edit_media(
                InputMediaPhoto(media=photo, caption=text, parse_mode=parse_mode),
                reply_markup=kb,
            )
        elif _has_photo(msg):
            await msg.edit_caption(caption=text, parse_mode=parse_mode, reply_markup=kb)
        else:
            await msg.edit_text(text=text, parse_mode=parse_mode, reply_markup=kb)
        return
    except TelegramBadRequest as e:
        err = (getattr(e, "message", None) or str(e) or "").lower()
        if "message is not modified" in err:
            return
        logger.warning("_navigate_to edit failed, fallback to delete+send: %s", e)
    except Exception as e:
        logger.warning("_navigate_to unexpected error, fallback: %s", e)

    # Fallback: удалить старое и отправить новое
    try:
        await msg.delete()
    except Exception:
        pass
    if photo:
        try:
            await bot.send_photo(chat_id, photo=photo, caption=text, parse_mode=parse_mode, reply_markup=kb)
            return
        except Exception as e:
            logger.warning("_navigate_to send_photo fallback failed: %s", e)
    await bot.send_message(chat_id, text, parse_mode=parse_mode, reply_markup=kb)


def _client_line(user_id: int, username: str | None) -> str:
    u = f"@{username}" if username else ""
    return f"Клиент: {user_id} {u}".strip()


def _parse_email_data(raw: str) -> tuple[str, str, str]:
    """Парсит «почта ; пароль ; 2FA» в (email, password, twofa). 2FA может отсутствовать."""
    parts = [p.strip() for p in (raw or "").split(";", 2)]
    email = parts[0] if len(parts) > 0 else ""
    password = parts[1] if len(parts) > 1 else ""
    twofa = parts[2] if len(parts) > 2 else ""
    return (email, password, twofa)


PLATFORM_LINE = "Площадка: Telegram"


async def _notify_group_order_email_with_data(
    bot: Bot,
    purchase_id: int,
    product_name: str,
    quantity: int,
    amount: int,
    email: str,
    password: str,
    twofa: str,
    user_id: int,
    username: str | None,
    order_date: str = "",
) -> None:
    """Краткое уведомление в группу уведомлений (ник, сумма, количество, дата, площадка); полный шаблон — в группу заказов."""
    # Группа уведомлений: ник, сумма, количество, название, дата, площадка
    date_line = f"\nДата: {order_date}" if order_date else ""
    notify_text = (
        "📧 Заказ на почту\n\n"
        f"{_client_line(user_id, username)}\n"
        f"Товар: {product_name}\nКоличество: {quantity} шт.\nСумма заказа: {amount} ₽{date_line}\n\n"
        f"{PLATFORM_LINE}"
    )
    try:
        await bot.send_message(config.NOTIFY_GROUP_ID, notify_text)
    except Exception as e:
        logger.warning("Notify group (email short): %s", e)
    # Группа заказов: полный шаблон New order с данными клиента (на почту).
    order_text = (
        "New order\n"
        f"Название нейросети: {product_name}\n"
        f"Количество: {quantity}\n"
        f"Почта: {email}\n"
        f"Пароль от почты: {password}\n"
        f"2FA ключ: {twofa}\n"
        f"{config.VISIONAI_MANAGER}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Принят", callback_data=f"order:status:{purchase_id}:accepted"),
            InlineKeyboardButton(text="В работе", callback_data=f"order:status:{purchase_id}:in_progress"),
            InlineKeyboardButton(text="Активирован", callback_data=f"order:status:{purchase_id}:activated"),
        ],
    ])
    try:
        await bot.send_message(config.ORDER_GROUP_ID, order_text, reply_markup=kb)
    except Exception as e:
        logger.error("Order group (email slip) chat_id=%s: %s — проверьте, что бот добавлен в группу заказов", config.ORDER_GROUP_ID, e)


def _order_account_kb(purchase_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Ожидает выдачи", callback_data=f"order:acc_status:{purchase_id}:awaiting"),
            InlineKeyboardButton(text="Получен", callback_data=f"order:acc_status:{purchase_id}:received"),
        ],
    ])


async def _notify_group_order_account(
    bot: Bot,
    purchase_id: int,
    order_number: str,
    product_id: int,
    product_name: str,
    quantity: int,
    amount: int,
    user_id: int,
    username: str | None,
) -> None:
    """Уведомление в группу уведомлений: заказ автовыдачи (ник, статус, кнопки, сумма, товар, остаток на складе, площадка)."""
    stock = db.count_product_accounts_available(product_id)
    text = (
        f"🆕 Новый заказ (автовыдача)\n\n"
        f"Товар: {product_name}\nКоличество: {quantity} шт.\nСумма: {amount} ₽\n\n"
        f"Остаток на складе: {stock}\n\n"
        f"Статус: Оплачен\n\n"
        f"{_client_line(user_id, username)}\n\n"
        f"{PLATFORM_LINE}"
    )
    try:
        await bot.send_message(config.NOTIFY_GROUP_ID, text, reply_markup=_order_account_kb(purchase_id))
    except Exception as e:
        logger.warning("Notify group (avto): %s", e)


async def _notify_group_topup(bot: Bot, amount: int, user_id: int, username: str | None) -> None:
    """Уведомление в группу уведомлений: клиент пополнил баланс. Площадка: Telegram."""
    text = f"💰 Клиент пополнил баланс на **{amount}** ₽\n\n{_client_line(user_id, username)}\n\n{PLATFORM_LINE}"
    try:
        await bot.send_message(config.NOTIFY_GROUP_ID, text, parse_mode="Markdown")
    except Exception as e:
        logger.warning("Notify group (topup): %s", e)


STATUS_LABELS = {"accepted": "Принят", "in_progress": "В работе", "activated": "Активирован"}
STATUS_LABELS_ACC = {"paid": "Оплачен", "awaiting": "Ожидает выдачи", "received": "Получен"}
STATUS_LABEL_CANCELLED = "Отменён"

async def _send_thank_you_review(bot: Bot, purchase_id: int) -> None:
    """После «Заказ получен» или «Активирован»: отправить клиенту благодарность, персональный промокод и кнопку отзыва (один раз)."""
    if not getattr(config, "AVITO_REVIEW_URL", ""):
        return
    purchase = db.get_purchase_by_id(purchase_id)
    if not purchase or purchase.get("thank_review_sent"):
        return
    try:
        promo_code = db.create_review_promo_code(getattr(config, "REVIEW_PROMO_AMOUNT", 150))
        db.set_purchase_thank_review_sent(purchase_id)
        text = (
            "🙏 **Спасибо за покупку!**\n\n"
            "Будем рады вашему отзыву — именно отзывы помогают нам становиться лучше и помогают новым клиентам сделать выбор.\n\n"
            f"Ваш персональный промокод на скидку **{getattr(config, 'REVIEW_PROMO_AMOUNT', 150)} ₽** на следующую покупку:\n"
            f"`{promo_code}`\n\n"
            "Одноразовый, только для вас. Введите его в разделе «Профиль» → «Промокод».\n\n"
            "Спасибо за доверие! 😊"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Оставить отзыв", url=config.AVITO_REVIEW_URL)],
            [InlineKeyboardButton(text="◀️ В главное меню", callback_data="menu:main")],
        ])
        await bot.send_message(
            purchase["user_id"],
            text,
            parse_mode="Markdown",
            reply_markup=kb,
        )
    except Exception as e:
        logger.exception("Thank-you review message: %s", e)


def _update_message_status_line(text: str, new_label: str) -> str:
    """Заменить или добавить строку «Статус: ...» в тексте сообщения."""
    if "\n\nСтатус:" in text:
        return text.rsplit("\n\nСтатус:", 1)[0] + f"\n\nСтатус: {new_label}"
    return text + f"\n\nСтатус: {new_label}"


@router.callback_query(F.data.startswith("order:acc_status:"))
async def order_acc_status_callback(callback: CallbackQuery) -> None:
    """Смена статуса заказа автовыдачи: доступно всем участникам группы заказов."""
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer()
        return
    purchase_id = int(parts[2])
    status = parts[3]
    if status not in STATUS_LABELS_ACC:
        await callback.answer()
        return
    purchase = db.get_purchase_by_id(purchase_id)
    if not purchase:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    db.set_purchase_status(purchase_id, status)
    label = STATUS_LABELS_ACC[status]
    try:
        current_text = callback.message.text or ""
        new_text = _update_message_status_line(current_text, label)
        # Когда статус «Получен» — убираем кнопки, чтобы не плодить действия
        new_kb = None if status == "received" else _order_account_kb(purchase_id)
        await callback.message.edit_text(new_text, reply_markup=new_kb)
    except Exception:
        pass
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Перейти к заказу", callback_data=f"order:goto:{purchase_id}")],
            [InlineKeyboardButton(text="◀️ В главное меню", callback_data="order:main")],
        ])
        await callback.bot.send_message(
            purchase["user_id"],
            f"📋 Статус вашего заказа №{purchase['order_number']} изменён: **{label}**",
            parse_mode="Markdown",
            reply_markup=kb,
        )
    except Exception as e:
        logger.warning("Notify client status: %s", e)
    if status == "received":
        await _send_thank_you_review(callback.bot, purchase_id)
    await callback.answer(f"Статус: {label}")


@router.callback_query(F.data.startswith("order:status:"))
async def order_status_callback(callback: CallbackQuery) -> None:
    """Смена статуса заказа «на почту»: доступно всем участникам группы заказов. Клиенту отправляется уведомление."""
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer()
        return
    purchase_id = int(parts[2])
    status = parts[3]
    if status not in STATUS_LABELS:
        await callback.answer()
        return
    purchase = db.get_purchase_by_id(purchase_id)
    if not purchase:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    db.set_purchase_status(purchase_id, status)
    label = STATUS_LABELS[status]
    try:
        current_text = callback.message.text or ""
        new_text = _update_message_status_line(current_text, label)
        await callback.message.edit_text(new_text, reply_markup=callback.message.reply_markup)
    except Exception:
        pass
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Перейти к заказу", callback_data=f"order:goto:{purchase_id}")],
            [InlineKeyboardButton(text="◀️ В главное меню", callback_data="order:main")],
        ])
        await callback.bot.send_message(
            purchase["user_id"],
            f"📋 Статус вашего заказа №{purchase['order_number']} изменён: **{label}**",
            parse_mode="Markdown",
            reply_markup=kb,
        )
    except Exception as e:
        logger.warning("Notify client status: %s", e)
    if status == "activated":
        await _send_thank_you_review(callback.bot, purchase_id)
    await callback.answer(f"Статус: {label}")


@router.callback_query(F.data.startswith("order:goto:"))
async def order_goto_callback(callback: CallbackQuery) -> None:
    """Кнопка «Перейти к заказу» из уведомления о смене статуса: удаляем уведомление, показываем заказ."""
    await safe_answer_callback(callback)
    purchase_id = int(callback.data.split(":")[2])
    user_id = callback.from_user.id if callback.from_user else 0
    try:
        await callback.message.delete()
    except Exception:
        pass
    detail = db.get_purchase_detail(purchase_id, user_id)
    if not detail:
        await callback.bot.send_message(
            callback.message.chat.id,
            "Заказ не найден.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ В главное меню", callback_data="menu:main")],
            ]),
        )
        return
    lines = [
        f"📋 **Заказ №{detail['order_number']}**", "",
        f"📅 Дата: {detail['created_at']}",
        f"🛍 Товар: {detail['product_name']}",
        f"📦 Количество: {detail['quantity']} шт.",
        f"💰 Стоимость: **{detail['amount']}** ₽", "",
    ]
    status = (detail.get("status") or "").strip()
    if status:
        if status == "new":
            label = "Новый"
        elif status == "cancelled":
            label = STATUS_LABEL_CANCELLED
        else:
            label = STATUS_LABELS.get(status) or STATUS_LABELS_ACC.get(status) or status
        lines.append(f"📌 **Статус:** {label}\n")
    if detail.get("email_data"):
        lines.append("📧 **Данные для входа (ваша почта):**")
        lines.append(detail["email_data"].replace(";", " — "))
    if detail.get("accounts"):
        lines.append("🔐 **Данные аккаунта:**")
        for i, acc in enumerate(detail["accounts"]):
            if i > 0:
                lines.append("")
            raw = (acc.get("account_data") or "").strip()
            if acc.get("item_type") == "link":
                lines.append(raw)
            else:
                parts_acc = [p.strip() for p in raw.split(";") if p.strip()]
                if len(parts_acc) >= 2:
                    lines.append(f"Логин: {parts_acc[0]}\nПароль: {parts_acc[1]}")
                    if len(parts_acc) >= 3:
                        lines.append(f"2ФА: {parts_acc[2]}")
                else:
                    lines.append(raw)
            note = (acc.get("admin_note") or "").strip()
            if note:
                lines.append(f"📝 **Примечание:** {note}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к покупкам", callback_data="profile:purchases:1")],
    ])
    await callback.bot.send_message(callback.message.chat.id, "\n".join(lines), parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data == "order:main")
async def order_main_callback(callback: CallbackQuery) -> None:
    """Кнопка «В главное меню» из уведомления о смене статуса: удаляем уведомление, показываем главное меню."""
    await safe_answer_callback(callback)
    try:
        await callback.message.delete()
    except Exception:
        pass
    chat_id = callback.message.chat.id
    kb = get_main_keyboard()
    try:
        await callback.bot.send_photo(
            chat_id,
            photo=_get_welcome_photo(),
            caption=WELCOME_TEXT,
            parse_mode="Markdown",
            reply_markup=kb,
        )
    except Exception:
        await callback.bot.send_message(chat_id, WELCOME_TEXT, parse_mode="Markdown", reply_markup=kb)


# --- Start и главное меню ---
async def send_main_menu(message: Message) -> None:
    """Отправить главное меню с фото (при /start)."""
    kb = get_main_keyboard()
    try:
        await message.answer_photo(
            photo=_get_welcome_photo(),
            caption=WELCOME_TEXT,
            parse_mode="Markdown",
            reply_markup=kb,
        )
    except Exception as e:
        logger.warning("Не удалось отправить фото: %s", e)
        await message.answer(WELCOME_TEXT, parse_mode="Markdown", reply_markup=kb)


async def _send_main_menu_photo(bot: Bot, chat_id: int, caption: str = WELCOME_TEXT) -> None:
    """Отправить главное меню с фото (без редактирования/удаления)."""
    kb = get_main_keyboard()
    try:
        await bot.send_photo(chat_id, photo=_get_welcome_photo(), caption=caption, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logger.warning("Главное меню с фото: %s", e)
        await bot.send_message(chat_id, caption, parse_mode="Markdown", reply_markup=kb)


async def _show_main_menu_with_photo(bot: Bot, chat_id: int, message: Message | None = None) -> None:
    """Показать главное меню: редактируем существующее сообщение (плавный переход), fallback — отправляем новое."""
    if message:
        await _navigate_to(message, bot, WELCOME_TEXT, get_main_keyboard(), _get_welcome_photo())
    else:
        await _send_main_menu_photo(bot, chat_id)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    db.ensure_user(user_id, username)
    # Реферальная ссылка: /start ref_123456
    args = (message.text or "").strip().split()
    if len(args) >= 2 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
            if referrer_id != user_id:
                db.add_referral(referrer_id, user_id)
        except ValueError:
            pass
    await send_main_menu(message)


@router.callback_query(F.data.startswith("menu:"))
async def menu_callback(callback: CallbackQuery) -> None:
    action = callback.data.split(":", 1)[1]
    await safe_answer_callback(callback)
    msg = callback.message

    if action == "main":
        await _show_main_menu_with_photo(callback.bot, msg.chat.id, msg)
        return

    if action == "news":
        text = (
            "📢 **Новости Ai Hub**\n\n"
            "Подпишитесь на наш канал, чтобы первыми узнавать об обновлениях, новостях и акциях.\n\n"
            "Нажмите кнопку ниже, чтобы перейти в канал."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Открыть канал «Новости Ai Hub»", url=f"tg://resolve?domain={config.CHANNEL_USERNAME}")],
            [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="menu:main")],
        ])
        await _edit_or_caption(msg, text, kb)
        return

    if action == "profile":
        text = get_profile_text(
            callback.from_user.id if callback.from_user else 0,
            callback.from_user.username if callback.from_user else None,
        )
        kb = get_profile_keyboard()
        await _navigate_to(msg, callback.bot, text, kb, _get_profile_menu_photo())
        return

    if action == "avto":
        text = (
            "🤖 **Автовыдача**\n\n"
            "Здесь всё происходит автоматически.\n\n"
            "Вы выбираете продукт — система моментально передаёт данные и открывает доступ.\n\n"
            "Без ожиданий.\n"
            "Без переписок.\n"
            "Без «сейчас уточню у менеджера».\n\n"
            "Мы сделали этот раздел для тех, кто ценит скорость и хочет получать результат сразу после оплаты.\n\n"
            "Выберите нужную подписку ниже и получите доступ в пару шагов.\n\n"
            "AI Hub работает быстро — чтобы вы работали ещё быстрее 🚀"
        )
        await _navigate_to(msg, callback.bot, text, _catalog_keyboard("avto"), _get_avto_menu_photo())
        return
    if action == "catalog":
        text = (
            "📧 **Активации на почту**\n\n"
            "Здесь подписки, которые можно оформить на вашу почту.\n\n"
            "В этом разделе вы можете:\n"
            "— оформить активацию подписки на свою почту\n"
            "— выбрать удобный способ подключения\n\n"
            "Некоторые продукты выдаются автоматически, для других мы подключаем доступ напрямую к вашему аккаунту.\n\n"
            "Выбирайте нужную нейросеть ниже и подключайте удобным способом.\n\n"
            "AI Hub — один каталог, все возможности 🚀"
        )
        await _navigate_to(msg, callback.bot, text, _catalog_keyboard("neural"), _get_catalog_menu_photo())
        return
    if action == "support":
        text = f"💬 **Поддержка AI Hub**\n\n{SUPPORT_INTRO}"
        rows = []
        for i in range(0, len(SUPPORT_TOPICS), 2):
            pair = [
                InlineKeyboardButton(text=SUPPORT_TOPICS[i][1], callback_data=f"support:topic:{SUPPORT_TOPICS[i][0]}")
            ]
            if i + 1 < len(SUPPORT_TOPICS):
                pair.append(InlineKeyboardButton(text=SUPPORT_TOPICS[i + 1][1], callback_data=f"support:topic:{SUPPORT_TOPICS[i + 1][0]}"))
            rows.append(pair)
        rows.append([InlineKeyboardButton(text="💬 Связаться с менеджером", url=MANAGER_URL)])
        rows.append([InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="menu:main")])
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        await _navigate_to(msg, callback.bot, text, kb, _get_support_menu_photo())
        return
    if action == "about":
        kb_back = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в главное меню", callback_data="menu:main")],
        ])
        await _navigate_to(msg, callback.bot, ABOUT_BOT_TEXT, kb_back, _get_about_menu_photo())
        return


# --- Поддержка: выбор темы → список вопросов (постранично) → ответ ---
FAQ_PER_PAGE = 10


@router.callback_query(F.data.startswith("support:topic:"))
async def support_topic(callback: CallbackQuery) -> None:
    await safe_answer_callback(callback)
    parts = callback.data.split(":")
    key = parts[2] if len(parts) > 2 else ""
    page = int(parts[3]) if len(parts) > 3 else 0
    label = next((lbl for k, lbl in SUPPORT_TOPICS if k == key), key)
    faq_list = db.get_support_faq_by_product(key)
    if not faq_list:
        text = f"💬 **{label}**\n\nПо этой теме пока нет готовых ответов. Нажмите «Связаться с менеджером» в предыдущем меню."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:support")],
        ])
    else:
        total = len(faq_list)
        total_pages = (total + FAQ_PER_PAGE - 1) // FAQ_PER_PAGE
        page = max(0, min(page, total_pages - 1))
        start = page * FAQ_PER_PAGE
        chunk = faq_list[start : start + FAQ_PER_PAGE]
        text = f"💬 **{label}**\n\nВыберите вопрос (стр. {page + 1} из {total_pages}):"
        rows = []
        for faq in chunk:
            q = (faq["question_text"] or "").strip()
            if len(q) > 50:
                q = q[:47] + "…"
            rows.append([InlineKeyboardButton(text=q or "Вопрос", callback_data=f"support:faq:{faq['id']}:{key}:{page}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"support:topic:{key}:{page - 1}"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"support:topic:{key}:{page + 1}"))
        if nav:
            rows.append(nav)
        rows.append([InlineKeyboardButton(text="◀️ В меню поддержки", callback_data="menu:support")])
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await _edit_or_caption(callback.message, text, kb)


@router.callback_query(F.data.startswith("support:faq:"))
async def support_faq_answer(callback: CallbackQuery) -> None:
    await safe_answer_callback(callback)
    parts = callback.data.split(":")
    try:
        faq_id = int(parts[2])
    except (IndexError, ValueError):
        return
    key = parts[3] if len(parts) > 3 else ""
    page = int(parts[4]) if len(parts) > 4 else 0
    faq = db.get_support_faq_by_id(faq_id)
    if not faq:
        await _edit_or_caption(callback.message, "Ответ не найден.", InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"support:topic:{key}:{page}" if key else "menu:support")],
        ]))
        return
    key = faq["product_key"]
    label = next((lbl for k, lbl in SUPPORT_TOPICS if k == key), key)
    text = f"💬 {label}\n\nВопрос: {faq['question_text']}\n\nОтвет:\n{faq['answer_text']}"
    if len(text) > 4000:
        text = text[:3997] + "…"
    back_data = f"support:topic:{key}:{page}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=back_data)],
    ])
    await _edit_or_caption(callback.message, text, kb, parse_mode=None)


# --- Каталог: товар, количество, оплата с баланса (без тарифов) ---
@router.callback_query(F.data.startswith("catalog:product:"))
async def catalog_product(callback: CallbackQuery) -> None:
    product_id = int(callback.data.split(":")[2])
    await safe_answer_callback(callback)
    product = db.get_product(product_id)
    if not product:
        await callback.message.answer("Товар не найден.")
        return
    price = product["price"]
    user_id = callback.from_user.id if callback.from_user else 0
    discount_pct = db.get_referral_discount_percent(user_id)
    price_line = f"Цена: **{price}** ₽"
    if discount_pct:
        price_with_discount = price * (100 - discount_pct) // 100
        price_line = f"Цена: ~~{price}~~ ₽\nСо скидкой {discount_pct}%: **{price_with_discount}** ₽"
    text = f"**{product['name']}**\n\n{product['description'] or ''}\n\n{price_line}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить", callback_data=f"catalog:buy:{product_id}:0")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"catalog:list:{product['category']}")],
    ])
    if product.get("image_file_id"):
        try:
            await callback.message.answer_photo(photo=product["image_file_id"], caption=text, parse_mode="Markdown", reply_markup=kb)
            await callback.message.delete()
        except Exception:
            await _edit_or_caption(callback.message, text, kb)
    else:
        await _edit_or_caption(callback.message, text, kb)


@router.callback_query(F.data == "catalog:email_cancel")
async def catalog_email_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена заказа «на почту». Если оплата уже прошла (есть order_id) — возврат на баланс и уведомление."""
    await safe_answer_callback(callback)
    data = await state.get_data()
    order_id = data.get("email_order_id")
    user_id = callback.from_user.id if callback.from_user else 0
    await state.clear()
    if order_id:
        try:
            purchase_id = int(order_id)
            detail = db.get_purchase_detail(purchase_id, user_id)
            if detail and detail.get("amount"):
                amount = detail["amount"]
                db.add_balance(user_id, amount)
                db.set_purchase_status(purchase_id, "cancelled")
                await callback.message.answer(
                    f"✅ Сделан возврат. На ваш баланс возвращено **{amount}** ₽.",
                    parse_mode="Markdown",
                )
            elif detail:
                db.set_purchase_status(purchase_id, "cancelled")
        except (ValueError, TypeError):
            pass
    await _show_main_menu_with_photo(callback.bot, callback.message.chat.id, callback.message)


@router.callback_query(F.data.startswith("catalog:list:"))
async def catalog_list(callback: CallbackQuery) -> None:
    category = callback.data.split(":")[2]
    await safe_answer_callback(callback)
    title = "📧 **Активации на почту**" if category == "neural" else "🤖 **Автовыдача**"
    text = f"{title}\n\nВыберите товар (✅ — в наличии, ❌ — нет):"
    await _edit_or_caption(callback.message, text, _catalog_keyboard(category))


@router.callback_query(F.data.startswith("catalog:buy:"))
async def catalog_buy(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    product_id, _ = int(parts[2]), int(parts[3])
    await safe_answer_callback(callback)
    product = db.get_product(product_id)
    if not product:
        return
    price = product["price"]
    user_id = callback.from_user.id if callback.from_user else 0
    discount_pct = db.get_referral_discount_percent(user_id)
    total = price * (100 - discount_pct) // 100
    if product["activation_type"] == "email":
        balance = db.get_balance(user_id)
        if balance < total:
            await _edit_or_caption(
                callback.message,
                "❌ Недостаточно средств на балансе. Пополните баланс в разделе «Профиль».",
                InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data=f"catalog:product:{product_id}")],
                ]),
            )
            return
        db.add_balance(user_id, -total)
        purchase_id = db.add_purchase(user_id, product["name"], 1, total)
        order_number = str(purchase_id)
        db.set_purchase_status(purchase_id, "new")
        await state.set_state(CatalogStates.waiting_email_order)
        await state.update_data(email_order_id=order_number)
        remaining = db.get_balance(user_id)
        prompt_custom = (product.get("activation_prompt") or "").strip()
        if prompt_custom:
            request_block = prompt_custom
        else:
            request_block = (
                "Отправьте **почту**, **пароль от аккаунта** и при необходимости **2FA** (одним сообщением).\n"
                "Формат: `почта ; пароль ; 2FA` — 2FA необязателен."
            )
        discount_line = f"\n🎁 Скидка {discount_pct}%: −{price - total} ₽\n" if discount_pct else ""
        text = (
            f"✅ Оплата прошла. Заказ **№{order_number}**\n\n"
            f"💰 **Списано с баланса:** {total} ₽{discount_line}\n"
            f"💳 **Остаток на балансе:** {remaining} ₽\n\n"
            + request_block
        )
        kb_email = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="catalog:email_cancel")],
        ])
        prompt_images = product.get("activation_prompt_images") or []
        # К сообщению с инструкцией прикрепляем изображение из инструкции (нижнее из добавленных в админке), а не картинку товара
        if prompt_images:
            instruction_photo = prompt_images[-1]
            try:
                await callback.bot.send_photo(
                    callback.message.chat.id,
                    instruction_photo,
                    caption=text,
                    parse_mode="Markdown",
                    reply_markup=kb_email,
                )
                await callback.message.delete()
            except Exception:
                await _edit_or_caption(callback.message, text, kb_email)
        else:
            await _edit_or_caption(callback.message, text, kb_email)
        return
    stock = db.count_product_accounts_available(product_id, None)
    if stock <= 0:
        await _edit_or_caption(
            callback.message,
            "❌ Товар временно закончился.",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data=f"catalog:product:{product_id}")],
            ]),
        )
        return
    n = min(10, stock)
    rows = [[InlineKeyboardButton(text=str(i), callback_data=f"catalog:qty:{product_id}:0:{i}")] for i in range(1, n + 1)]
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"catalog:product:{product_id}")])
    await _edit_or_caption(
        callback.message,
        f"Выберите количество аккаунтов (в наличии: {stock}):",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("catalog:qty:"))
async def catalog_qty(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    product_id, qty = int(parts[2]), int(parts[4])
    await safe_answer_callback(callback)
    product = db.get_product(product_id)
    if not product:
        return
    price = product["price"]
    user_id = callback.from_user.id if callback.from_user else 0
    discount_pct = db.get_referral_discount_percent(user_id)
    total_raw = price * qty
    total = total_raw * (100 - discount_pct) // 100
    balance = db.get_balance(user_id)
    discount_line = f"\n🎁 Скидка {discount_pct}%: −{total_raw - total} ₽\n" if discount_pct else ""
    text = f"**Состав заказа**\n\n{product['name']} × {qty} = {total_raw} ₽{discount_line}\nИтого: **{total}** ₽\n\nВаш баланс: **{balance}** ₽"
    if balance < total:
        await _edit_or_caption(
            callback.message,
            "❌ Недостаточно средств на балансе. Пополните баланс в разделе «Профиль».",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data=f"catalog:product:{product_id}")],
            ]),
        )
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оплатить с баланса", callback_data=f"catalog:pay:{product_id}:0:{qty}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"catalog:product:{product_id}")],
    ])
    await _edit_or_caption(callback.message, text, kb)


@router.callback_query(F.data.startswith("catalog:pay:"))
async def catalog_pay(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    product_id, qty = int(parts[2]), int(parts[4])
    await safe_answer_callback(callback)
    product = db.get_product(product_id)
    if not product:
        return
    price = product["price"]
    user_id = callback.from_user.id if callback.from_user else 0
    discount_pct = db.get_referral_discount_percent(user_id)
    total_raw = price * qty
    total = total_raw * (100 - discount_pct) // 100
    balance = db.get_balance(user_id)
    if balance < total:
        await _edit_or_caption(
            callback.message,
            "❌ Недостаточно средств на балансе.",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data=f"catalog:product:{product_id}")],
            ]),
        )
        return
    stock = db.count_product_accounts_available(product_id, None)
    if stock < qty:
        await _edit_or_caption(
            callback.message,
            "❌ Недостаточно товара на складе.",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data=f"catalog:product:{product_id}")],
            ]),
        )
        return
    db.add_balance(user_id, -total)
    purchase_id = db.add_purchase(user_id, product["name"], qty, total)
    order_number = str(purchase_id)
    items = db.get_and_mark_accounts(product_id, qty, order_number, None)
    db.set_purchase_status(purchase_id, "paid")
    await _notify_group_order_account(
        callback.bot, purchase_id, order_number, product_id, product["name"], qty, total, user_id,
        callback.from_user.username if callback.from_user else None,
    )
    remaining = db.get_balance(user_id)

    instruction = (product.get("instruction") or "").strip()
    discount_line = f"\n🎁 Скидка {discount_pct}%: −{total_raw - total} ₽" if discount_pct else ""
    lines = [
        "✅ **Покупка успешно завершена!**",
        "",
        f"📦 **Товар:** {product['name']}",
        f"📊 **Количество:** {qty} шт.",
        f"💰 **Списано с баланса:** {total} ₽{discount_line}",
        f"💳 **Остаток на балансе:** {remaining} ₽",
        "",
    ]
    if items:
        lines.append("🎉 **Ваши аккаунты:**")
        for i, it in enumerate(items, 1):
            raw = (it.get("account_data") or "").strip()
            if it.get("item_type") == "link":
                lines.append(f"**Аккаунт #{i}:** {raw}")
            else:
                parts = [p.strip() for p in raw.split(";") if p.strip()]
                if len(parts) >= 2:
                    lines.append(f"**Аккаунт #{i}:**")
                    lines.append(f"👤 Логин: `{parts[0]}`")
                    lines.append(f"🔑 Пароль: `{parts[1]}`")
                    if len(parts) >= 3:
                        lines.append(f"🔐 2ФА: `{parts[2]}`")
                else:
                    lines.append(f"**Аккаунт #{i}:** {raw}")
            note = (it.get("admin_note") or "").strip()
            if note:
                lines.append(f"📝 **Примечание:** {note}")
            if i < len(items):
                lines.append("")
        lines.append("")
    if instruction:
        lines.append("📖 **Инструкция:**")
        lines.append(instruction if instruction.startswith("http") else f"🔗 {instruction}")
        lines.append("")
    lines.append("⚠️ **Важно:** сохраните данные в надёжном месте, смените пароль после первого входа.")
    lines.append("")
    lines.append("По вопросам — напишите менеджеру.")

    full_text = "\n".join(lines)
    manager_url = f"tg://user?id={config.SUPPORT_MANAGER_ID}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Связаться с менеджером", url=manager_url)],
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="menu:main")],
    ])
    instruction_images = product.get("instruction_images") or []
    if instruction_images:
        # Фото инструкции — сверху, одним сообщением с текстом; карточку товара не показываем
        try:
            await callback.message.delete()
        except Exception:
            pass
        try:
            await callback.bot.send_photo(
                callback.message.chat.id,
                instruction_images[0],
                caption=full_text,
                parse_mode="Markdown",
                reply_markup=kb,
            )
        except Exception as e:
            logger.warning("Покупка с фото инструкции: %s", e)
            await callback.bot.send_message(callback.message.chat.id, full_text, parse_mode="Markdown", reply_markup=kb)
    else:
        # Нет фото инструкции — оставляем карточку товара и редактируем подпись
        await _edit_or_caption(callback.message, full_text, kb)


@router.message(CatalogStates.waiting_email_order, F.text)
async def catalog_email_credentials(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    order_id = data.get("email_order_id")
    if not order_id:
        await state.clear()
        await _send_main_menu_photo(message.bot, message.chat.id, "Сессия истекла.\n\n" + WELCOME_TEXT)
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Введите почту, пароль и при необходимости 2FA. Формат: почта ; пароль ; 2FA (2FA необязательно)")
        return
    email, password, twofa = _parse_email_data(text)
    if not email or not password:
        await message.answer("Укажите минимум почту и пароль. Формат: почта ; пароль ; 2FA")
        return
    await state.update_data(email_data_pending=text, email_pending=email, password_pending=password, twofa_pending=twofa)
    await state.set_state(CatalogStates.waiting_email_confirm)
    display = f"почта: {email}\nПароль от почты: {password}\n2FA: {twofa}" if twofa else f"почта: {email}\nПароль от почты: {password}"
    await message.answer(
        f"Пожалуйста, проверьте ваши данные:\n\n«{display}»",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data="catalog:email_confirm")],
            [InlineKeyboardButton(text="✏️ Изменить", callback_data="catalog:email_change")],
        ]),
    )


@router.callback_query(F.data == "catalog:email_confirm")
async def catalog_email_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Клиент подтвердил данные — сохраняем, говорим «заказ оформлен», отправляем в группу с подставленными данными."""
    await safe_answer_callback(callback)
    data = await state.get_data()
    order_id = data.get("email_order_id")
    raw = data.get("email_data_pending")
    email = data.get("email_pending", "")
    password = data.get("password_pending", "")
    twofa = data.get("twofa_pending", "")
    await state.clear()
    if not order_id or not raw:
        await _send_main_menu_photo(callback.bot, callback.message.chat.id, "Сессия истекла.\n\n" + WELCOME_TEXT)
        return
    purchase_id = int(order_id)
    user_id = callback.from_user.id if callback.from_user else 0
    db.set_purchase_email_data(order_id, raw)
    detail = db.get_purchase_detail(purchase_id, user_id)
    remaining = db.get_balance(user_id)
    lines = [
        "✅ **Заказ оформлен!**",
        "",
        "Данные получены. По вопросам доступа — напишите менеджеру.",
        "",
        f"💳 **Остаток на балансе:** {remaining} ₽",
        "",
    ]
    if detail:
        lines[1:1] = [f"📦 **Товар:** {detail['product_name']}", f"💰 **Сумма заказа:** {detail['amount']} ₽", ""]
    manager_url = f"tg://user?id={config.SUPPORT_MANAGER_ID}"
    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Связаться с менеджером", url=manager_url)],
            [InlineKeyboardButton(text="◀️ В главное меню", callback_data="menu:main")],
        ]),
    )
    order_date = format_created_at_moscow(detail.get("created_at")) if detail else ""
    await _notify_group_order_email_with_data(
        callback.bot, purchase_id,
        detail["product_name"] if detail else "—",
        detail.get("quantity", 1) or 1,
        detail["amount"] if detail else 0,
        email, password, twofa, user_id,
        callback.from_user.username if callback.from_user else None,
        order_date=order_date,
    )


@router.callback_query(F.data == "catalog:email_change")
async def catalog_email_change(callback: CallbackQuery, state: FSMContext) -> None:
    """Клиент нажал «Изменить» — возвращаем к вводу данных."""
    await safe_answer_callback(callback)
    await state.set_state(CatalogStates.waiting_email_order)
    await state.update_data(email_data_pending=None, email_pending=None, password_pending=None, twofa_pending=None)
    await callback.message.edit_text(
        "Отправьте ваши данные ещё раз. Формат: почта ; пароль ; 2FA (2FA необязательно).",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="catalog:email_cancel")],
        ]),
    )


# --- Профиль: рефералка, покупки, баланс, промокод ---
@router.callback_query(F.data == "profile:ref")
async def profile_ref(callback: CallbackQuery) -> None:
    await safe_answer_callback(callback)
    user_id = callback.from_user.id if callback.from_user else 0
    db.ensure_user(user_id)
    invited, _ = db.get_referral_stats(user_id)
    bot_username = config.BOT_USERNAME or "AiHubMarketBot"
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    text = (
        "🔗 **Реферальная программа AI Hub**\n\n"
        f"Приглашено пользователей: **{invited}**\n\n"
        "Начните зарабатывать вместе с AI Hub 💸\n\n"
        "Вы получаете 15% с каждого пополнения баланса приглашённых пользователей — деньги автоматически начисляются на ваш счёт. Без заявок и ожиданий.\n\n"
        "Чем больше активных друзей — тем больше ваш доход.\n\n"
        "💰 **Как это работает?**\n\n"
        "1️⃣ Отправьте свою реферальную ссылку\n"
        "2️⃣ Друг зарегистрируется в боте\n"
        "3️⃣ Он пополнит баланс\n"
        "4️⃣ Вы получите 15% от суммы — мгновенно на свой баланс\n\n"
        "🔗 **Ваша персональная ссылка:**\n\n"
        f"`{ref_link}`\n\n"
        "Поделитесь ею в Telegram, чатах, соцсетях или среди друзей.\n\n"
        "Начните приглашать уже сейчас 🚀"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="profile:main")],
    ])
    await _edit_or_caption(callback.message, text, kb)


@router.callback_query(F.data == "profile:main")
async def profile_main(callback: CallbackQuery) -> None:
    await safe_answer_callback(callback)
    user_id = callback.from_user.id if callback.from_user else 0
    telegram_username = callback.from_user.username if callback.from_user else None
    text = get_profile_text(user_id, telegram_username)
    await _edit_or_caption(callback.message, text, get_profile_keyboard())


PURCHASES_PER_PAGE = 10


@router.callback_query(F.data.startswith("profile:purchases"))
async def profile_purchases(callback: CallbackQuery) -> None:
    await safe_answer_callback(callback)
    user_id = callback.from_user.id if callback.from_user else 0
    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 1
    total = db.count_purchases(user_id)
    total_pages = max(1, (total + PURCHASES_PER_PAGE - 1) // PURCHASES_PER_PAGE)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PURCHASES_PER_PAGE
    items = db.get_purchases(user_id, limit=PURCHASES_PER_PAGE, offset=offset)
    text = (
        "🛒 **Мои покупки**\n\n"
        "Здесь хранятся все ваши оформленные подписки и доступы к нейросетям.\n\n"
        f"Всего покупок: **{total}**\n"
        f"Страница: {page} из {total_pages}"
    )
    rows = []
    for p in items:
        date_fmt = format_created_at_moscow(p.get("created_at"))
        date_short = (date_fmt[:10] if date_fmt else "") or (p.get("created_at") or "")[:10]
        btn_text = f"{date_short} #{p['order_number']} {p['product_name'][:15]} {p['quantity']} шт. {p['amount']}₽"
        rows.append([InlineKeyboardButton(text=btn_text[:64], callback_data=f"purchase:item:{p['id']}:{page}")])
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"profile:purchases:{page - 1}"))
    nav.append(InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="Далее ▶", callback_data=f"profile:purchases:{page + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="profile:main")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await _edit_or_caption(callback.message, text, kb)


@router.callback_query(F.data.startswith("purchase:item:"))
async def purchase_item_detail(callback: CallbackQuery) -> None:
    await safe_answer_callback(callback)
    user_id = callback.from_user.id if callback.from_user else 0
    parts = callback.data.split(":")
    purchase_id = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 1
    detail = db.get_purchase_detail(purchase_id, user_id)
    if not detail:
        await _edit_or_caption(
            callback.message,
            "Заказ не найден.",
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад к покупкам", callback_data=f"profile:purchases:{page}")],
            ]),
        )
        return
    # Дата, название, стоимость, данные аккаунта (или почта), статус для заказов «на почту»
    date_display = format_created_at_moscow(detail.get("created_at")) or detail.get("created_at", "")
    lines = [
        f"📋 **Заказ №{detail['order_number']}**",
        "",
        f"📅 Дата: {date_display}",
        f"🛍 Товар: {detail['product_name']}",
        f"📦 Количество: {detail['quantity']} шт.",
        f"💰 Стоимость: **{detail['amount']}** ₽",
        "",
    ]
    status = (detail.get("status") or "").strip()
    if status:
        if status == "new":
            label = "Новый"
        elif status == "cancelled":
            label = STATUS_LABEL_CANCELLED
        else:
            label = STATUS_LABELS.get(status) or STATUS_LABELS_ACC.get(status) or status
        lines.append(f"📌 **Статус:** {label}\n")
    if detail.get("email_data"):
        lines.append("📧 **Данные для входа (ваша почта):**")
        lines.append(detail["email_data"].replace(";", " — "))
    if detail.get("accounts"):
        lines.append("🔐 **Данные аккаунта:**")
        for i, acc in enumerate(detail["accounts"]):
            if i > 0:
                lines.append("")
            raw = (acc.get("account_data") or "").strip()
            if acc.get("item_type") == "link":
                lines.append(raw)
            else:
                parts_acc = [p.strip() for p in raw.split(";") if p.strip()]
                if len(parts_acc) >= 2:
                    lines.append(f"Логин: {parts_acc[0]}\nПароль: {parts_acc[1]}")
                    if len(parts_acc) >= 3:
                        lines.append(f"2ФА: {parts_acc[2]}")
                else:
                    lines.append(raw)
            note = (acc.get("admin_note") or "").strip()
            if note:
                lines.append(f"📝 **Примечание:** {note}")
    text = "\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"profile:purchases:{page}")],
    ])
    await _edit_or_caption(callback.message, text, kb)


@router.callback_query(F.data == "profile:balance")
async def profile_balance(callback: CallbackQuery) -> None:
    await safe_answer_callback(callback)
    user_id = callback.from_user.id if callback.from_user else 0
    balance = db.get_balance(user_id)
    text = (
        "💰 **Ваш баланс — это ваш доступ к возможностям**\n\n"
        f"На счёте сейчас: **{balance}** ₽\n\n"
        "Каждое пополнение — это не просто цифры.\n"
        "Это мгновенный доступ к новым нейросетям, инструментам и функциям без ожиданий и переписок.\n\n"
        "Пополнили → выбрали продукт → получили автоматически.\n\n"
        "Никаких менеджеров. Никаких пауз. Только результат.\n\n"
        "Хотите быстро подключать нужные подписки в один клик?\n"
        "Держите баланс готовым и используйте AI Hub на максимум 🚀\n\n"
        "Нажмите «Пополнить баланс» и продолжайте без ограничений."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="balance:topup")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main")],
    ])
    await _edit_or_caption(callback.message, text, kb)


@router.callback_query(F.data == "balance:topup")
async def balance_topup(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_answer_callback(callback)
    await state.clear()
    text = "Выберите сумму пополнения или укажите свою:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="+100 ₽", callback_data="balance:add:100"),
            InlineKeyboardButton(text="+500 ₽", callback_data="balance:add:500"),
        ],
        [
            InlineKeyboardButton(text="+1000 ₽", callback_data="balance:add:1000"),
            InlineKeyboardButton(text="+2000 ₽", callback_data="balance:add:2000"),
        ],
        [InlineKeyboardButton(text="Другая сумма", callback_data="balance:custom")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="profile:balance")],
    ])
    await _edit_or_caption(callback.message, text, kb)


@router.callback_query(F.data == "balance:custom")
async def balance_custom(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_answer_callback(callback)
    await state.set_state(ProfileStates.waiting_topup_amount)
    await state.update_data(
        edit_message_id=callback.message.message_id,
        edit_chat_id=callback.message.chat.id,
        edit_has_photo=_has_photo(callback.message),
    )
    text = "Введите сумму пополнения в рублях (целое число, например 300):"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="balance:topup")],
    ])
    await _edit_or_caption(callback.message, text, kb)


@router.callback_query(F.data.startswith("balance:add:"))
async def balance_add(callback: CallbackQuery) -> None:
    await safe_answer_callback(callback)
    amount = int(callback.data.split(":")[2])
    user_id = callback.from_user.id if callback.from_user else 0
    order_id = f"topup_{user_id}_{uuid.uuid4().hex[:12]}"
    link, bill_id = await create_payment_link(amount, order_id)
    if not link or not bill_id:
        await callback.message.answer("Не удалось создать ссылку на оплату. Попробуйте позже или выберите другую сумму.")
        return
    db.create_payment(user_id, amount, order_id, bill_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=link)],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="balance:topup")],
    ])
    text = (
        f"Пополнение на **{amount}** ₽\n\n"
        "Нажмите «Оплатить» — откроется страница оплаты.\n"
        f"Кнопка «Проверить оплату» появится через {WAIT_BEFORE_CHECK_SEC} сек."
    )
    await _edit_or_caption(callback.message, text, kb)
    asyncio.create_task(_add_check_button_after_delay(callback.bot, callback.message.chat.id, callback.message.message_id, order_id, link))


async def _add_check_button_after_delay(bot: Bot, chat_id: int, message_id: int, order_id: str, link: str) -> None:
    """Через WAIT_BEFORE_CHECK_SEC сек. добавляет кнопку «Проверить оплату» в сообщение."""
    await asyncio.sleep(WAIT_BEFORE_CHECK_SEC)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=link)],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"balance:check:{order_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="balance:topup")],
    ])
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=kb)
    except Exception:
        pass


def _seconds_since_created(created_at_str: str | None) -> float | None:
    """Секунд с момента created_at (формат SQLite datetime). Если не удалось разобрать — None."""
    if not created_at_str:
        return None
    try:
        # SQLite: '2026-02-22 07:00:00'
        created = datetime.strptime(created_at_str[:19], "%Y-%m-%d %H:%M:%S")
        created = created.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created).total_seconds()
    except Exception:
        return None


@router.callback_query(F.data.startswith("balance:check:"))
async def balance_check(callback: CallbackQuery) -> None:
    order_id = callback.data.replace("balance:check:", "")
    payment = db.get_payment_by_order_id(order_id)
    if not payment:
        await safe_answer_callback(callback)
        await callback.message.answer("Платёж не найден.")
        return
    # Проверка доступна только через WAIT_BEFORE_CHECK_SEC секунд после создания ссылки
    elapsed = _seconds_since_created(payment.get("created_at"))
    if elapsed is not None and elapsed < WAIT_BEFORE_CHECK_SEC:
        sec_left = max(1, int(WAIT_BEFORE_CHECK_SEC - elapsed))
        try:
            await callback.answer(f"Подождите ещё {sec_left} сек., затем нажмите «Проверить оплату» снова.", show_alert=True)
        except TelegramBadRequest:
            pass
        return
    await safe_answer_callback(callback)
    bill_id = (payment.get("pally_bill_id") or "").strip()
    # Передаём order_id: при пустом bill_id или если по bill_id не нашли — ищем счёт по order_id и проверяем через payment/search
    status = await check_payment_status(bill_id, order_id=order_id)
    if status == "paid":
        if payment["status"] != "paid":
            db.set_payment_paid(payment["id"])
            db.add_balance(payment["user_id"], payment["amount"])
            await _notify_group_topup(
                callback.bot, payment["amount"], payment["user_id"],
                callback.from_user.username if callback.from_user else None,
            )
            # Реферальный бонус: 15% от пополнения — пригласившему на баланс и уведомление
            referrer_id = db.get_referrer_id(payment["user_id"])
            if referrer_id and payment["amount"] > 0:
                bonus = payment["amount"] * 15 // 100
                if bonus > 0:
                    db.add_balance(referrer_id, bonus)
                    ref_username = callback.from_user.username if callback.from_user else None
                    ref_display = f"@{ref_username}" if ref_username else "ваш приглашённый друг"
                    ref_text = (
                        f"🎉 **{ref_display}** пополнил баланс на **{payment['amount']}** ₽.\n\n"
                        f"Вам зачислено **15%** с его пополнения: **{bonus}** ₽ на ваш баланс."
                    )
                    ref_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="menu:main")],
                        [InlineKeyboardButton(text="💰 Баланс", callback_data="profile:balance")],
                    ])
                    try:
                        await callback.bot.send_message(referrer_id, ref_text, parse_mode="Markdown", reply_markup=ref_kb)
                    except Exception as e:
                        logger.warning("Не удалось отправить реферальное уведомление %s: %s", referrer_id, e)
        text = f"✅ Оплата прошла успешно! На баланс зачислено **{payment['amount']}** ₽."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Баланс", callback_data="profile:balance")],
            [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main")],
        ])
        await _edit_or_caption(callback.message, text, kb)
    else:
        text = "❌ Оплата пока не прошла. Проверьте платёж и нажмите «Проверить оплату» снова."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"balance:check:{order_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="balance:topup")],
        ])
        await _edit_or_caption(callback.message, text, kb)


@router.callback_query(F.data == "profile:promo")
async def profile_promo(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_answer_callback(callback)
    await state.set_state(ProfileStates.waiting_promo)
    await state.update_data(
        edit_message_id=callback.message.message_id,
        edit_chat_id=callback.message.chat.id,
        edit_has_photo=_has_photo(callback.message),
    )
    text = (
        "🎟 **Промокод**\n\n"
        "Есть бонус? Самое время его активировать 💸\n\n"
        "Введите промокод одним сообщением в чат — и получите начисление на баланс.\n\n"
        "Без ожиданий.\n"
        "Без проверки вручную.\n"
        "Система всё обработает автоматически.\n\n"
        "Если код действителен — бонус появится сразу.\n\n"
        "Введите его ниже и заберите своё."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="profile:promo_back")],
    ])
    await _edit_or_caption(callback.message, text, kb)


@router.callback_query(F.data == "profile:promo_back")
async def profile_promo_back(callback: CallbackQuery, state: FSMContext) -> None:
    await safe_answer_callback(callback)
    await state.clear()
    user_id = callback.from_user.id if callback.from_user else 0
    telegram_username = callback.from_user.username if callback.from_user else None
    text = get_profile_text(user_id, telegram_username)
    await _edit_or_caption(callback.message, text, get_profile_keyboard())


@router.message(ProfileStates.waiting_promo, F.text)
async def apply_promocode(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip()
    user_id = message.from_user.id if message.from_user else 0
    data = await state.get_data()
    edit_message_id = data.get("edit_message_id")
    edit_chat_id = data.get("edit_chat_id")
    ok, bonus = db.use_promocode(user_id, code)
    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="profile:promo_back")],
    ])
    if ok:
        text = f"✅ Промокод принят! На ваш баланс зачислено **{bonus}** ₽."
    else:
        text = "❌ Промокод недействителен, уже использован или истёк."
    if edit_chat_id and edit_message_id:
        try:
            edit_has_photo = data.get("edit_has_photo")
            if edit_has_photo:
                await message.bot.edit_message_caption(chat_id=edit_chat_id, message_id=edit_message_id, caption=text, parse_mode="Markdown", reply_markup=kb)
            else:
                await message.bot.edit_message_text(chat_id=edit_chat_id, message_id=edit_message_id, text=text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            await message.answer(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await message.answer(text, parse_mode="Markdown", reply_markup=kb)


@router.message(ProfileStates.waiting_topup_amount, F.text)
async def apply_custom_amount(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    edit_message_id = data.get("edit_message_id")
    edit_chat_id = data.get("edit_chat_id")
    edit_has_photo = data.get("edit_has_photo")
    try:
        amount = int((message.text or "").strip())
    except ValueError:
        try:
            await message.delete()
        except Exception:
            pass
        if edit_chat_id and edit_message_id:
            err_text = "Введите целое число (например 300)."
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="balance:topup")]])
            try:
                if edit_has_photo:
                    await message.bot.edit_message_caption(chat_id=edit_chat_id, message_id=edit_message_id, caption=err_text, reply_markup=kb)
                else:
                    await message.bot.edit_message_text(chat_id=edit_chat_id, message_id=edit_message_id, text=err_text, reply_markup=kb)
            except Exception:
                await message.answer(err_text, reply_markup=kb)
        else:
            await message.answer("Введите целое число (например 300).")
        return
    if amount < 10 or amount > 100_000:
        try:
            await message.delete()
        except Exception:
            pass
        if edit_chat_id and edit_message_id:
            err_text = "Сумма должна быть от 10 до 100 000 ₽."
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="balance:topup")]])
            try:
                if edit_has_photo:
                    await message.bot.edit_message_caption(chat_id=edit_chat_id, message_id=edit_message_id, caption=err_text, reply_markup=kb)
                else:
                    await message.bot.edit_message_text(chat_id=edit_chat_id, message_id=edit_message_id, text=err_text, reply_markup=kb)
            except Exception:
                await message.answer(err_text, reply_markup=kb)
        else:
            await message.answer("Сумма должна быть от 10 до 100 000 ₽.")
        return
    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass
    user_id = message.from_user.id if message.from_user else 0
    order_id = f"topup_{user_id}_{uuid.uuid4().hex[:12]}"
    link, bill_id = await create_payment_link(amount, order_id)
    if not link or not bill_id:
        if edit_chat_id and edit_message_id:
            err_text = "Не удалось создать ссылку на оплату. Попробуйте позже."
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="balance:topup")]])
            try:
                if edit_has_photo:
                    await message.bot.edit_message_caption(chat_id=edit_chat_id, message_id=edit_message_id, caption=err_text, reply_markup=kb)
                else:
                    await message.bot.edit_message_text(chat_id=edit_chat_id, message_id=edit_message_id, text=err_text, reply_markup=kb)
            except Exception:
                await message.answer(err_text, reply_markup=kb)
        else:
            await message.answer("Не удалось создать ссылку на оплату. Попробуйте позже.")
        return
    db.create_payment(user_id, amount, order_id, bill_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=link)],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="balance:topup")],
    ])
    text = (
        f"Пополнение на **{amount}** ₽\n\n"
        "Нажмите «Оплатить» — откроется страница оплаты.\n"
        f"Кнопка «Проверить оплату» появится через {WAIT_BEFORE_CHECK_SEC} сек."
    )
    if edit_chat_id and edit_message_id:
        try:
            if edit_has_photo:
                await message.bot.edit_message_caption(chat_id=edit_chat_id, message_id=edit_message_id, caption=text, parse_mode="Markdown", reply_markup=kb)
            else:
                await message.bot.edit_message_text(chat_id=edit_chat_id, message_id=edit_message_id, text=text, parse_mode="Markdown", reply_markup=kb)
            asyncio.create_task(_add_check_button_after_delay(message.bot, edit_chat_id, edit_message_id, order_id, link))
        except Exception:
            sent = await message.answer(text, parse_mode="Markdown", reply_markup=kb)
            asyncio.create_task(_add_check_button_after_delay(message.bot, sent.chat.id, sent.message_id, order_id, link))
    else:
        sent = await message.answer(text, parse_mode="Markdown", reply_markup=kb)
        asyncio.create_task(_add_check_button_after_delay(message.bot, sent.chat.id, sent.message_id, order_id, link))


async def main() -> None:
    db.init_db()
    # Очистка рефералов при переходе на новую систему (15% с пополнений). Удалить строку ниже после первого запуска.
    db.clear_referrals()
    bot = Bot(token=config.BOT_TOKEN)
    me = await bot.get_me()
    if me and me.username:
        config.BOT_USERNAME = me.username
        logger.info("Bot username: %s", config.BOT_USERNAME)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(manager_router)
    dp.include_router(admin_router)
    dp.include_router(router)
    logger.info("Бот запущен (aiogram) | NOTIFY_GROUP_ID=%s ORDER_GROUP_ID=%s", config.NOTIFY_GROUP_ID, config.ORDER_GROUP_ID)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
