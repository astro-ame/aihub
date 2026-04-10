# -*- coding: utf-8 -*-
"""Форматирование даты/времени для отображения (московское время)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")


def format_created_at_moscow(created_at_str: str | None) -> str:
    """Преобразовать дату/время из БД (UTC) в строку по Москве. Формат: ДД.ММ.ГГГГ ЧЧ:ММ."""
    if not created_at_str or not created_at_str.strip():
        return ""
    s = created_at_str.strip()[:19]
    try:
        if len(s) <= 10:
            dt = datetime.strptime(s, "%Y-%m-%d")
        else:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
        except ValueError:
            return created_at_str.strip()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    moscow = dt.astimezone(MOSCOW)
    return moscow.strftime("%d.%m.%Y %H:%M")
