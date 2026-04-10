# Конфигурация бота Ai Hub Market
# Секреты лучше хранить в .env (см. .env.example)

import os
from pathlib import Path

# Загружаем .env если есть
_env = Path(__file__).parent / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# Telegram бот
BOT_TOKEN = os.getenv("BOT_TOKEN", "8458961945:AAGhAvZluGArvkVswIAZ58-u-6GSFcKEr7M")
# Имя бота для реферальной ссылки (t.me/BOT_USERNAME?start=ref_123). При запуске подставляется из getMe, если пусто.
BOT_USERNAME: str = os.getenv("BOT_USERNAME", "")

# ID менеджера поддержки (для кнопки «Поддержка»)
SUPPORT_MANAGER_ID = int(os.getenv("SUPPORT_MANAGER_ID", "7210745918"))

# ID канала (3821110723), юзернейм @aihub_media — для кнопки «Новости Ai Hub»
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "3821110723"))
# Юзернейм канала без @ — для кнопки открытия в приложении (tg://resolve?domain=...)
CHANNEL_USERNAME = (os.getenv("CHANNEL_USERNAME", "aihub_media") or "aihub_media").lstrip("@")
# Ссылка для текста/отображения (можно оставить https://t.me/...). Кнопка в боте использует CHANNEL_USERNAME и tg://
CHANNEL_LINK = os.getenv("CHANNEL_LINK", f"https://t.me/{CHANNEL_USERNAME}")

# После «Заказ получен» / «Активирован»: запрос отзыва и персональный промокод
AVITO_REVIEW_URL = os.getenv(
    "AVITO_REVIEW_URL",
    "https://www.avito.ru/user/review?fid=2_f6BNBIyQkmjF8nCPaKK9fujowHx4ZBZ87DElF8B0nlyL6RdaaYzvyPSWRjp4ZyNE",
)
REVIEW_PROMO_AMOUNT = int(os.getenv("REVIEW_PROMO_AMOUNT", "150"))

# Pally (pal24.pro) — платёжная система
# Документация: https://pally.info/merchant/api | Базовый URL API: https://pal24.pro
PALLY_API_TOKEN = os.getenv(
    "PALLY_API_TOKEN",
    "25675|ZU3PAGAg64QFKYHz9MDTJIwpiEcLIHvjHkHWTRpx",
)
PALLY_API_BASE = os.getenv("PALLY_API_BASE", "https://pal24.pro")
# shop_id — из личного кабинета; без него не работают Success URL, Fail URL и Result URL (postback)
PALLY_SHOP_ID = os.getenv("PALLY_SHOP_ID", "Y37jl3rmb6")
# Уведомления о поступлении платежа на почту настраиваются в личном кабинете Pally (настройки магазина / профиля)

# Изображение приветствия (главное меню). Локальный файл имеет приоритет; иначе используется URL.
MAIN_MENU_IMAGE_PATH = Path(__file__).parent / "data" / "main_menu.png"
# Изображение для раздела «Автовыдача»
AVTO_MENU_IMAGE_PATH = Path(__file__).parent / "data" / "avto_menu.png"
# Изображение для раздела «Все нейросети»
CATALOG_MENU_IMAGE_PATH = Path(__file__).parent / "data" / "catalog_menu.png"
# Изображение для раздела «О боте»
ABOUT_MENU_IMAGE_PATH = Path(__file__).parent / "data" / "about_menu.png"
# Изображение для раздела «Поддержка»
SUPPORT_MENU_IMAGE_PATH = Path(__file__).parent / "data" / "support_menu.png"
# Изображение для раздела «Профиль»
PROFILE_MENU_IMAGE_PATH = Path(__file__).parent / "data" / "profile_menu.png"
WELCOME_IMAGE_URL = os.getenv(
    "WELCOME_IMAGE_URL",
    "https://disk.yandex.ru/i/H6BkR_fG7uhMjQ",
)

# Группа «Уведомления» (3825757825): краткие уведомления — новый заказ (автовыдача или на почту), пополнения.
NOTIFY_GROUP_ID = int(os.getenv("NOTIFY_GROUP_ID", "-1003825757825"))
# Группа «Заказы» (3751778090): полный шаблон New order с данными клиента, запросы аккаунтов.
_ORDER_GROUP_RAW = os.getenv("ORDER_GROUP_ID", "-1003751778090")
ORDER_GROUP_ID = int(_ORDER_GROUP_RAW)
# Если на сервере в .env остался старый ID группы заказов — подменяем на новый (3751778090)
if ORDER_GROUP_ID == -1003676124970:
    ORDER_GROUP_ID = -1003751778090
# Упоминание менеджера в шаблоне заказа на почту
VISIONAI_MANAGER = os.getenv("VISIONAI_MANAGER", "@visionai_manager")

# Админ-панель: только эти user_id могут вводить /admin (через запятую в .env)
_admin_ids = os.getenv("ADMIN_IDS", "5568314329").strip()
ADMIN_IDS = [int(x.strip()) for x in _admin_ids.split(",") if x.strip()]
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Artem4ekk")

# Панель менеджера (через запятую в .env)
_manager_ids = os.getenv("MANAGER_IDS", "7210745918").strip()
MANAGER_IDS = [int(x.strip()) for x in _manager_ids.split(",") if x.strip()]
MANAGER_PASSWORD = os.getenv("MANAGER_PASSWORD", "M@nag3rA1Hub")
