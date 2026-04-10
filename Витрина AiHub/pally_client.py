# -*- coding: utf-8 -*-
"""
Клиент Pally API (pal24.pro): создание счёта и проверка статуса.
Документация: https://pally.info/merchant/api
Авторизация: Authorization: Bearer {token}
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

import config

logger = logging.getLogger(__name__)

BASE = config.PALLY_API_BASE.rstrip("/")
AUTH_HEADER = "Authorization"
AUTH_VALUE = f"Bearer {config.PALLY_API_TOKEN}"


async def create_payment_link(
    amount_rub: int,
    order_id: str,
    description: str = "Пополнение баланса Ai Hub Market",
) -> tuple[Optional[str], Optional[str]]:
    """
    Создать счёт на оплату (многоразовая ссылка).
    POST /api/v1/bill/create — form: amount, order_id, description, type=multi, shop_id, currency_in=RUB.
    Возвращает (link_page_url, bill_id) или (None, None).
    """
    url = f"{BASE}/api/v1/bill/create"
    form = {
        "amount": amount_rub,
        "order_id": order_id,
        "description": description,
        "type": "multi",
        "currency_in": "RUB",
        "payer_pays_commission": "0",
        "name": "Пополнение баланса",
    }
    if config.PALLY_SHOP_ID:
        form["shop_id"] = config.PALLY_SHOP_ID

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                url,
                data=form,
                headers={AUTH_HEADER: AUTH_VALUE},
            )
            r.raise_for_status()
            data = r.json()
            if data.get("success") in (True, "true", "True"):
                link = data.get("link_page_url") or data.get("link_url")
                inner = data.get("data") or {}
                if isinstance(inner, dict):
                    bill_id = data.get("bill_id") or data.get("id") or inner.get("bill_id") or inner.get("id")
                else:
                    bill_id = data.get("bill_id") or data.get("id")
                if link and bill_id:
                    logger.info("Pally create: order_id=%s bill_id=%s", order_id, bill_id)
                    return link, str(bill_id)
            logger.warning("Pally bill/create: неверный ответ %s", data)
            return None, None
    except httpx.HTTPStatusError as e:
        logger.warning("Pally bill/create HTTP %s: %s", e.response.status_code, e.response.text)
        return None, None
    except Exception as e:
        logger.exception("Pally bill/create: %s", e)
        return None, None


def _normalize_success(s: str) -> bool:
    if not s:
        return False
    u = (s or "").strip().upper()
    return u in ("SUCCESS", "OVERPAID")


async def _payment_search_has_success_for_bill(bill_id: str) -> bool:
    """GET /api/v1/payment/search — есть ли успешный платёж по этому bill_id за последние 7 дней."""
    if not config.PALLY_SHOP_ID:
        return False
    url = f"{BASE}/api/v1/payment/search"
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    finish = now.strftime("%Y-%m-%d %H:%M:%S")
    headers = {AUTH_HEADER: AUTH_VALUE}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(
                url,
                params={"shop_id": config.PALLY_SHOP_ID, "start_date": start, "finish_date": finish, "per_page": 100},
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            if data.get("success") not in (True, "true", "True"):
                return False
            payments = data.get("data")
            if not isinstance(payments, list):
                return False
            for p in payments:
                if not isinstance(p, dict):
                    continue
                if (p.get("bill_id") or "") != bill_id:
                    continue
                s = (p.get("status") or p.get("Status") or "").strip().upper()
                if _normalize_success(s):
                    logger.info("Pally payment/search: найден SUCCESS по bill_id=%s", bill_id)
                    return True
            return False
    except Exception as e:
        logger.warning("Pally payment/search error: %s", e)
        return False


async def _bill_search_get_bill_id_by_order_id(order_id: str) -> Optional[str]:
    """GET /api/v1/bill/search — найти bill_id по нашему order_id за последние 7 дней."""
    if not config.PALLY_SHOP_ID:
        return None
    url = f"{BASE}/api/v1/bill/search"
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    finish = now.strftime("%Y-%m-%d %H:%M:%S")
    headers = {AUTH_HEADER: AUTH_VALUE}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(
                url,
                params={"shop_id": config.PALLY_SHOP_ID, "start_date": start, "finish_date": finish, "per_page": 100},
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            if data.get("success") not in (True, "true", "True"):
                return None
            bills = data.get("data")
            if not isinstance(bills, list):
                return None
            for b in bills:
                if not isinstance(b, dict):
                    continue
                if (b.get("order_id") or "") == order_id:
                    bid = b.get("id") or b.get("bill_id")
                    if bid:
                        logger.info("Pally bill/search: order_id=%s -> bill_id=%s", order_id, bid)
                        return str(bid)
            return None
    except Exception as e:
        logger.warning("Pally bill/search error: %s", e)
        return None


async def check_payment_status(bill_id: str, order_id: Optional[str] = None) -> str:
    """
    Проверить, оплачен ли счёт. Использует bill/status, bill/payments и запасной вариант payment/search.
    order_id можно передать для поиска счёта по order_id, если bill_id не сработал.
    Возвращает: 'paid' | 'pending' | 'failed'
    """
    url_status = f"{BASE}/api/v1/bill/status"
    url_payments = f"{BASE}/api/v1/bill/payments"
    url_payment_status = f"{BASE}/api/v1/payment/status"
    headers = {AUTH_HEADER: AUTH_VALUE}
    bill_id = (bill_id or "").strip()
    if not bill_id and order_id:
        bill_id = await _bill_search_get_bill_id_by_order_id(order_id) or ""

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if bill_id:
                r = await client.get(url_status, params={"id": bill_id}, headers=headers)
                if not r.is_success:
                    logger.warning("Pally bill/status HTTP %s: %s", r.status_code, r.text)
                else:
                    data = r.json()
                    if data.get("success") in (True, "true", "True"):
                        status = (data.get("status") or data.get("Status") or "").strip().upper()
                        if _normalize_success(status):
                            return "paid"
                        if status == "FAIL":
                            return "failed"
                    r2 = await client.get(url_payments, params={"id": bill_id, "per_page": 100}, headers=headers)
                    if r2.is_success:
                        pay_data = r2.json()
                        if pay_data.get("success") in (True, "true", "True"):
                            payments = pay_data.get("data")
                            if isinstance(payments, list):
                                for p in payments:
                                    if not isinstance(p, dict):
                                        continue
                                    s = (p.get("status") or p.get("Status") or "").strip().upper()
                                    if _normalize_success(s):
                                        return "paid"
                                    pid = p.get("id")
                                    if pid and s in ("NEW", "PROCESS", "UNDERPAID", ""):
                                        try:
                                            r3 = await client.get(url_payment_status, params={"id": pid}, headers=headers)
                                            if r3.is_success:
                                                pdata = r3.json()
                                                ps = (pdata.get("status") or pdata.get("Status") or "").strip().upper()
                                                if _normalize_success(ps):
                                                    return "paid"
                                        except Exception:
                                            pass

            # Запасной вариант: ищем успешный платёж по bill_id в payment/search (деньги уже пришли — он там есть)
            if bill_id and await _payment_search_has_success_for_bill(bill_id):
                return "paid"

            # Если bill_id не нашли по БД — пробуем найти счёт по order_id и проверить его
            if order_id and not bill_id:
                bill_id = await _bill_search_get_bill_id_by_order_id(order_id)
                if bill_id:
                    return await check_payment_status(bill_id, order_id=None)

            return "pending"
    except httpx.HTTPStatusError as e:
        logger.warning("Pally check HTTP %s: %s", e.response.status_code, e.response.text)
        return "failed"
    except Exception as e:
        logger.exception("Pally check: %s", e)
        return "failed"
