# -*- coding: utf-8 -*-
"""
Однократный сброс данных перед запуском бота в бой.
Очищает: историю покупок, пользователей, балансы, промокоды и историю использования,
платежи, рефералов. Товары, тарифы, склад и FAQ не трогаются.
Запуск: из корня проекта: python scripts/clear_production_data.py
"""

import sys
from pathlib import Path

# корень проекта
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database as db

if __name__ == "__main__":
    db.clear_all_production_data()
    print("Готово: история покупок, пользователи, балансы, промокоды, платежи и рефералы очищены.")
