"""
Еженедельный отчёт Яндекс.Директ → Telegram
Запускается каждый понедельник в 08:00 по Москве (05:00 UTC)
Cron: 0 5 * * 1
"""

import requests
import time
from datetime import datetime, timedelta
import pytz

# ============================================================
# НАСТРОЙКИ — заполните перед запуском
# ============================================================

MCP_URL = "https://direct-alert.ru/mcp"
MCP_API_KEY = os.environ.get("MCP_API_KEY", "")  # задаётся в Railway

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8762902441:AAEYtL8ijoStYXHVxPQ1Ce1upbEne4ojZ0I")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "492876421")

# Соответствие логин → понятное название
ACCOUNT_NAMES = {
    "slana-66":           "Перевозки",
    "ya-garant-serwis":   "Мягкие окна",
    "marckiratory":       "Маркираторы",
    "andrewpirogow":      "Недвижимость",
    "oleg-marinchencko2017": "oleg-marinchencko2017",
    "g-c-k":              "Гидроспец",
    "resaltingda":        "СК БА",
    "tdawrora":           "Аврора",
    "itolski":            "itolski",
}

# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {MCP_API_KEY}",
}


def mcp_call(action: str, account_id: int = None, args: dict = None) -> dict:
    """Универсальный вызов MCP-инструмента direct."""
    payload = {"action": action}
    if account_id is not None:
        payload["account_id"] = account_id
    if args:
        payload["args"] = args

    resp = requests.post(
        f"{MCP_URL}/direct",
        json=payload,
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_accounts() -> list[dict]:
    """Получить список всех аккаунтов."""
    data = mcp_call("accounts.list")
    return data.get("data", {}).get("accounts", [])


def submit_report(account_id: int, date_from: str, date_to: str) -> str:
    """Отправить запрос на формирование отчёта, вернуть report_id."""
    result = mcp_call(
        action="reports.submit",
        account_id=account_id,
        args={
            "date_from": date_from,
            "date_to": date_to,
            "date_range_type": "CUSTOM_DATE",
            "field_names": ["Impressions", "Clicks", "Ctr", "AvgCpc", "Conversions"],
            "report_type": "ACCOUNT_PERFORMANCE_REPORT",
        },
    )
    return result["data"]["report_id"]


def get_report(account_id: int, report_id: str, max_attempts: int = 20) -> dict | None:
    """Дождаться готовности отчёта и вернуть данные."""
    time.sleep(20)  # Минимальное ожидание по требованию API
    for attempt in range(max_attempts):
        result = mcp_call("reports.get", account_id=account_id, args={"report_id": report_id})
        status = result["data"]["status"]
        if status == "ready":
            rows = result["data"]["result"]["rows"]
            return rows[0] if rows else None
        time.sleep(5)
    print(f"[WARN] Отчёт {report_id} не готов после {max_attempts} попыток")
    return None


def send_telegram(text: str) -> None:
    """Отправить сообщение в Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()


def format_change(current: float, previous: float, is_currency: bool = False) -> str:
    """Форматировать изменение показателя с динамикой."""
    if previous == 0:
        return "—"
    delta = current - previous
    pct = (delta / previous) * 100
    sign = "+" if delta >= 0 else ""
    arrow = "▲" if delta >= 0 else "▼"
    if is_currency:
        return f"{sign}{delta:,.0f} ₽ ({sign}{pct:.1f}%) {arrow}"
    return f"{sign}{delta:,.0f} ({sign}{pct:.1f}%) {arrow}"


# ============================================================
# ОСНОВНАЯ ЛОГИКА
# ============================================================

def build_report_message(
    account_name: str,
    login: str,
    current: dict,
    previous: dict,
) -> str:
    """Сформировать текст сообщения для одного аккаунта."""
    lines = [
        f"<b>📊 {account_name}</b> (<code>{login}</code>)",
        f"<i>Текущая неделя vs Предыдущая</i>",
        "",
        f"👁 Показы:       <b>{current['Impressions']:,}</b>  {format_change(current['Impressions'], previous['Impressions'])}",
        f"🖱 Клики:        <b>{current['Clicks']:,}</b>  {format_change(current['Clicks'], previous['Clicks'])}",
        f"📈 CTR:          <b>{current['Ctr']:.2f}%</b>",
        f"💰 Ср. клик:     <b>{current['AvgCpc']:,.2f} ₽</b>  {format_change(current['AvgCpc'], previous['AvgCpc'], is_currency=True)}",
        f"🎯 Конверсии:    <b>{int(current['Conversions'])}</b>  {format_change(current['Conversions'], previous['Conversions'])}",
    ]
    return "\n".join(lines)


def run():
    moscow = pytz.timezone("Europe/Moscow")
    now = datetime.now(moscow)

    # Текущая неделя: предыдущие 7 дней (пн–вс)
    date_to = (now - timedelta(days=1)).strftime("%Y-%m-%d")       # вчера (вс)
    date_from = (now - timedelta(days=7)).strftime("%Y-%m-%d")     # 7 дней назад (пн)

    # Предыдущая неделя
    prev_date_to = (now - timedelta(days=8)).strftime("%Y-%m-%d")
    prev_date_from = (now - timedelta(days=14)).strftime("%Y-%m-%d")

    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Запуск еженедельного отчёта")
    print(f"Текущая неделя:   {date_from} – {date_to}")
    print(f"Предыдущая неделя: {prev_date_from} – {prev_date_to}")

    # Получаем список аккаунтов
    accounts = get_accounts()
    if not accounts:
        print("[ERROR] Не удалось получить список аккаунтов")
        return

    sent_count = 0

    for acc in accounts:
        account_id = acc["id"]
        login = acc.get("login", str(account_id))
        name = ACCOUNT_NAMES.get(login, login)

        print(f"\n→ {name} ({login}), id={account_id}")

        try:
            # Запрашиваем оба отчёта
            report_id_curr = submit_report(account_id, date_from, date_to)
            report_id_prev = submit_report(account_id, prev_date_from, prev_date_to)

            current = get_report(account_id, report_id_curr)
            previous = get_report(account_id, report_id_prev)

            # Пропускаем если нет показов и кликов в текущей неделе
            if not current or (current["Impressions"] == 0 and current["Clicks"] == 0):
                print(f"  [SKIP] Нет активности за текущую неделю")
                continue

            # Если нет данных за прошлую неделю — используем нули
            if not previous:
                previous = {"Impressions": 0, "Clicks": 0, "Ctr": 0, "AvgCpc": 0, "Conversions": 0}

            message = build_report_message(name, login, current, previous)
            send_telegram(message)
            sent_count += 1
            print(f"  [OK] Отправлено в Telegram")

            time.sleep(1)  # Небольшая пауза между сообщениями

        except Exception as e:
            print(f"  [ERROR] {e}")
            continue

    # Итоговое сообщение
    if sent_count > 0:
        summary = (
            f"✅ <b>Отчёт за {date_from} – {date_to}</b>\n"
            f"Отправлено отчётов: {sent_count} из {len(accounts)}"
        )
        send_telegram(summary)
        print(f"\nГотово. Отправлено {sent_count} отчётов.")
    else:
        print("\nНет аккаунтов с активностью за текущую неделю.")


if __name__ == "__main__":
    run()
