import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

from db import DB

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL = os.getenv("CHANNEL", "@CristyVPN")
SUPPORT = os.getenv("SUPPORT", "@fymce")

DEFAULT_ADMINS = {7894051808, 8477431361}
env_admins = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
ADMIN_IDS = DEFAULT_ADMINS | env_admins

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
db = DB("cristyvpn.sqlite3")

MSK = timezone(timedelta(hours=3))


def fmt(dt):
    return dt.strftime("%d.%m.%Y, %H:%M (МСК)")


def fmt_date(dt):
    return dt.strftime("%d.%m.%Y")


async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False


def subscribe_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 ПОДПИСАТЬСЯ 💵", url=f"https://t.me/{CHANNEL.lstrip('@')}")],
        [InlineKeyboardButton(text="ПРОВЕРИТЬ ПОДПИСКУ ✅", callback_data="check_sub")]
    ])


def main_kb(user_id: int = 0):
    buttons = []
    active_link = db.get_active_user_link(user_id) if user_id else None
    if active_link:
        buttons.append([InlineKeyboardButton(text="🔌 Подключить VPN", callback_data="vpn")])
    buttons += [
        [InlineKeyboardButton(text="💰 Забрать подписку", callback_data="trial")],
        [InlineKeyboardButton(text="💳 Купить/продлить", callback_data="plans")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="👥 Пригласить друга", callback_data="ref")],
        [InlineKeyboardButton(text="📜 О сервисе", callback_data="about")],
        [InlineKeyboardButton(text="🆘 Поддержка", url=f"https://t.me/{SUPPORT.lstrip('@')}")],
    ]
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="🛠 Админка", callback_data="adm:home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu")]
    ])


def about_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔒 Политика конфиденциальности", url="https://telegra.ph/Politika-konfidencialnosti-10-04-70")],
        [InlineKeyboardButton(text="📋 Пользовательское соглашение", url="https://telegra.ph/Polzovatelskoe-soglashenie-10-04-32")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")]
    ])


def admin_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В админку", callback_data="adm:home")]
    ])


def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:users")],
        [InlineKeyboardButton(text="🔎 Найти пользователя", callback_data="adm:search")],
        [InlineKeyboardButton(text="📈 Покупки", callback_data="adm:purchases")],
        [InlineKeyboardButton(text="📣 Рассылка", callback_data="adm:broadcast")],
        [InlineKeyboardButton(text="ℹ️ Информация", callback_data="adm:info")],
        [InlineKeyboardButton(text="🔗 Ссылки", callback_data="adm:links")],
        [InlineKeyboardButton(text="💸 Выводы", callback_data="adm:withdraws")],
        [InlineKeyboardButton(text="🎁 Скидочные промокоды", callback_data="adm:promo")],
    ])


def links_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Пробная", callback_data="adm:setlink:trial")],
        [InlineKeyboardButton(text="✏️ 30 дней", callback_data="adm:setlink:30")],
        [InlineKeyboardButton(text="✏️ 90 дней", callback_data="adm:setlink:90")],
        [InlineKeyboardButton(text="✏️ LTE", callback_data="adm:setlink:lte")],
        [InlineKeyboardButton(text="⬅️ В админку", callback_data="adm:home")]
    ])


def menu_text(user, active, exp):
    display_name = user.username or user.first_name or "Пользователь"
    return (
        "🦈 Cristy | Главное меню\n\n"
        f"👤 {display_name}\n"
        f"ID: {user.id}\n\n"
        "pay\n\n"
        f"{'🟢 Подписка активна' if active else '🔴 Подписка не активна'}\n\n"
        f"⏳ Истекает: {exp}\n\n"
        "▸ Выберите действие ниже:"
    )


def get_user_view(user):
    u = db.user(user.id, user.username or "")
    active = bool(u["expires_at"]) and datetime.fromisoformat(u["expires_at"]) > datetime.now(timezone.utc)
    if u["expires_at"]:
        exp = fmt(datetime.fromisoformat(u["expires_at"]).astimezone(MSK))
    else:
        exp = "—"
    return u, active, exp


def get_sub_type(u, active):
    if not active:
        return "Нет"
    if u["trial_used"]:
        orders = db.c.execute(
            "SELECT rub FROM orders WHERE user_id=? AND status='paid' ORDER BY id DESC LIMIT 1",
            (u["id"],)
        ).fetchone()
        if orders:
            rub = float(orders["rub"] or 0)
            if rub == 250:
                return "LTE"
            return "Базовая"
        return "Пробная"
    return "Базовая"


async def send_menu_from_user(user, chat_id: int):
    u, active, exp = get_user_view(user)
    await bot.send_message(chat_id, menu_text(user, active, exp), reply_markup=main_kb(user.id))


async def edit_menu_from_user(c: CallbackQuery):
    u, active, exp = get_user_view(c.from_user)
    try:
        await c.message.edit_text(menu_text(c.from_user, active, exp), reply_markup=main_kb(c.from_user.id))
    except Exception:
        await bot.send_message(c.from_user.id, menu_text(c.from_user, active, exp), reply_markup=main_kb(c.from_user.id))


def link_message(link: str, expires_at: str = None) -> str:
    text = (
        "🔌 Подключение VPN\n\n"
        "💻 Windows/Android/apple • Hiddify / V2RayTun / happ\n\n"
        "🔗 Ссылка:\n\n"
        f"{link}\n\n"
    )
    if expires_at:
        exp = fmt(datetime.fromisoformat(expires_at).astimezone(MSK))
        text += f"📅 Действует до: {exp}\n\n"
    text += (
        "📲 Как подключить:\n"
        "1. Скопируйте ссылку\n"
        "2. Приложение → Добавить → Вставить\n"
        "3. Выберите сервер"
    )
    return text


# ----------------- START -----------------

@dp.message(CommandStart())
async def start(m: Message):
    args = m.text.split(maxsplit=1)
    ref = int(args[1]) if len(args) == 2 and args[1].isdigit() else None
    db.user(m.from_user.id, m.from_user.username or "", ref)
    if not await is_subscribed(m.from_user.id):
        await m.answer(
            "Для использования сервиса необходимо\nподписаться на канал:\n\n"
            "📢 @CristyVPN\n\n"
            "Подпишитесь и нажмите кнопку ниже 👇",
            reply_markup=subscribe_kb()
        )
        return
    await send_menu_from_user(m.from_user, m.chat.id)


# ----------------- ПОДПИСКА -----------------

@dp.callback_query(F.data == "check_sub")
async def check_sub(c: CallbackQuery):
    if not await is_subscribed(c.from_user.id):
        await c.answer("Сначала подпишитесь на канал.", show_alert=True)
        return
    trial = db.activate_trial(c.from_user.id)
    if trial:
        await c.message.edit_text(
            "✅ Подписка подтверждена\n\n"
            "🎁 Пробный период активирован!\n\n"
            "Вы получили 3 дня бесплатного доступа.\n\n"
            "Теперь получите ссылку 👇",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Забрать подписку", callback_data="trial")],
                [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu")]
            ])
        )
    else:
        await c.message.edit_text(
            "✅ Подписка подтверждена\n\nПробный период уже использован.",
            reply_markup=back_kb()
        )


# ----------------- МЕНЮ -----------------

@dp.callback_query(F.data == "menu")
async def menu(c: CallbackQuery):
    await edit_menu_from_user(c)


# ----------------- О СЕРВИСЕ -----------------

@dp.callback_query(F.data == "about")
async def about(c: CallbackQuery):
    text = (
        "📜 О сервисе Cristy\n\n"
        "Cristy — VPN сервис, который работает с 1 октября 2026 года. "
        "Мы предоставляем возможность использования защищённого канала связи "
        "через серверы в разных странах для безопасности ваших данных и "
        "комфортной работы в интернете.\n\n"
        "Для нас важны клиенты и их мнение, поэтому мы стремимся предоставить "
        "хорошее качество за доступную цену.\n\n"
        "В боте работает команда поддержки, с ней можно связаться в любой день "
        "без выходных с 11:00 до 23:00. Также можно напрямую обратиться к "
        "администратору сервиса @fymce. Он всегда готов выслушать вас и помочь.\n\n"
        "Используя сервис, вы принимаете условия пользовательского соглашения "
        "и политики конфиденциальности."
    )
    await c.message.edit_text(text, reply_markup=about_kb())


# ----------------- ПРОБНАЯ ПОДПИСКА -----------------

@dp.callback_query(F.data == "trial")
async def trial(c: CallbackQuery):
    u = db.user(c.from_user.id)
    if not u["trial_used"]:
        await c.answer("Сначала активируйте пробный период (подпишитесь на канал).", show_alert=True)
        return
    if u["trial_link_taken"]:
        await c.answer("❌ Вы уже получали пробную ссылку.\n\nОна доступна в «🔌 Подключить VPN».", show_alert=True)
        return
    res = db.take_trial_link(c.from_user.id)
    if not res:
        await c.message.edit_text(
            "⏳ Ссылка пока не добавлена администратором. Ожидайте.",
            reply_markup=back_kb()
        )
        return
    link, exp = res
    await c.message.edit_text(link_message(link, exp), reply_markup=back_kb())


# ----------------- ПОДКЛЮЧИТЬ VPN -----------------

@dp.callback_query(F.data == "vpn")
async def vpn(c: CallbackQuery):
    row = db.get_active_user_link(c.from_user.id)
    if not row:
        await c.answer("❌ Активной подписки нет.", show_alert=True)
        return
    await c.message.edit_text(
        link_message(row["link"], row["expires_at"]),
        reply_markup=back_kb()
    )


# ----------------- ТАРИФЫ -----------------

@dp.callback_query(F.data == "plans")
async def plans(c: CallbackQuery):
    await c.message.edit_text(
        "⚡️ Покупка подписки CristyVPN\n\n"
        "Что вы получаете:\n\n"
        "▸ 🚀 Безлимитный трафик\n"
        "▸ 🌐 8 стран на выбор\n"
        "▸ 🔒 Защищённое шифрование Reality\n"
        "▸ ⚙️ Работает на всех устройствах\n"
        "▸ 🎮 YouTube, TikTok, Telegram — без лагов\n\n"
        "↓ Выберите срок подписки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="30 дней — 199₽", callback_data="buy:30")],
            [InlineKeyboardButton(text="90 дней — 500₽", callback_data="buy:90")],
            [InlineKeyboardButton(text="📡 LTE — 250₽", callback_data="buy:lte")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")]
        ])
    )


@dp.callback_query(F.data.startswith("buy:"))
async def buy(c: CallbackQuery):
    key = c.data.split(":")[1]
    if key == "lte":
        rub = 250
        stars = 200
        label = "LTE, 30 дней"
        days = 30
    else:
        days = int(key)
        rub = 199 if days == 30 else 500
        stars = 150 if days == 30 else 400
        label = f"{days} дней"

    await c.message.edit_text(
        "💳 Оформление подписки\n\n"
        f"📦 Тариф: {label}\n"
        f"💰 К оплате: {rub}₽\n\n"
        "▸ Выберите способ оплаты:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏦 СБП", callback_data=f"pay:sbp:{key}")],
            [InlineKeyboardButton(text=f"⭐ Stars — {stars}", callback_data=f"pay:stars:{key}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="plans")]
        ])
    )


@dp.callback_query(F.data.startswith("pay:"))
async def pay(c: CallbackQuery):
    _, method, key = c.data.split(":")

    if key == "lte":
        days = 30
        rub = 250
        stars = 200
        label = "LTE, 30 дней"
        kind = "lte"
    elif key == "30":
        days = 30
        rub = 199
        stars = 150
        label = "30 дней"
        kind = "30"
    else:
        days = 90
        rub = 500
        stars = 400
        label = "90 дней"
        kind = "90"

    discount = 0
    user_state = db.get_state(c.from_user.id)
    if user_state and user_state.startswith("discount:"):
        try:
            discount = int(user_state.split(":")[1])
        except Exception:
            discount = 0
        db.clear_state(c.from_user.id)

    if discount > 0:
        rub = int(rub * (100 - discount) / 100)
        label = f"{label} (скидка {discount}%)"

    link = db.get_link(kind)
    if not link:
        await c.message.edit_text(
            "⏳ Ссылка для этого тарифа пока не добавлена администратором.\n"
            "Напишите в поддержку.",
            reply_markup=back_kb()
        )
        return

    exp_iso = db.add_user_link(c.from_user.id, kind, link, days)
    order_id = db.create_order(c.from_user.id, days, method, rub, stars, kind)

    exp_str = fmt(datetime.fromisoformat(exp_iso).astimezone(MSK))
    await c.message.edit_text(
        "✅ Подписка активирована!\n\n"
        f"📦 Тариф: {label}\n"
        f"⏳ Действует до: {exp_str}\n\n"
        f"🔗 Ссылка для подключения:\n\n{link}\n\n"
        "Скопируйте ссылку и вставьте в приложение.\n\n"
        "Также ссылка доступна в «🔌 Подключить VPN».",
        reply_markup=back_kb()
    )

    for admin in ADMIN_IDS:
        try:
            await bot.send_message(
                admin,
                f"🛒 Новый заказ #{order_id}\nПользователь: {c.from_user.id}\n"
                f"Тариф: {label}\nМетод: {method}\nТип ссылки: {kind}"
            )
        except Exception:
            pass


# ----------------- ПРОФИЛЬ -----------------

@dp.callback_query(F.data == "profile")
async def profile(c: CallbackQuery):
    user = c.from_user
    u = db.user(user.id, user.username or "")
    active = bool(u["expires_at"]) and datetime.fromisoformat(u["expires_at"]) > datetime.now(timezone.utc)
    exp = fmt(datetime.fromisoformat(u["expires_at"]).astimezone(MSK)) if u["expires_at"] else "—"
    reg = datetime.fromisoformat(u["created_at"]).astimezone(MSK) if u["created_at"] else None
    reg_s = fmt_date(reg) if reg else "—"
    bal = float(u["balance"] or 0)
    sub_type = get_sub_type(u, active)
    display_name = user.username or user.first_name or "Пользователь"

    text = (
        "👤 Ваш профиль\n\n"
        f"🆔 ID: {user.id}\n"
        f"📛 Имя: {display_name}\n"
        f"📅 Регистрация: {reg_s}\n\n"
        f"{'🟢 Подписка активна' if active else '🔴 Подписка не активна'}\n"
        f"📦 Тип подписки: {sub_type}\n"
        f"⏳ Истекает: {exp}\n\n"
        f"💰 Баланс: {bal:.2f}₽"
    )
    await c.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Ввести промокод", callback_data="promo")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu")]
        ])
    )


# ----------------- ПРОМОКОД -----------------

@dp.callback_query(F.data == "promo")
async def promo(c: CallbackQuery):
    await c.message.edit_text(
        "🎁 Промокод на скидку\n\n"
        "Введите промокод следующим сообщением — он даст скидку на следующую покупку.",
        reply_markup=back_kb()
    )
    db.set_state(c.from_user.id, "promo")


# ----------------- РЕФЕРАЛЫ + ВЫВОД -----------------

@dp.callback_query(F.data == "ref")
async def ref(c: CallbackQuery):
    bal = db.balance(c.from_user.id)
    link = f"https://t.me/{(await bot.me()).username}?start={c.from_user.id}"
    await c.message.edit_text(
        "👥 Пригласить друга\n\n"
        "Получайте 10% от покупок приглашённых друзей.\n"
        "Баланс можно потратить на подписку или вывести от 1000₽.\n\n"
        f"🔗 Ваша ссылка:\n{link}\n\n"
        f"💰 Баланс: {bal:.2f}₽",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 Вывести", callback_data="withdraw")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu")]
        ])
    )


@dp.callback_query(F.data == "withdraw")
async def withdraw(c: CallbackQuery):
    bal = db.balance(c.from_user.id)
    if bal < 1000:
        await c.answer(f"❌ Минимум для вывода — 1000₽.\nВаш баланс: {bal:.2f}₽", show_alert=True)
        return
    db.set_state(c.from_user.id, "withdraw_card")
    await c.message.edit_text(
        "💸 Вывод средств\n\n"
        f"💰 Ваш баланс: {bal:.2f}₽\n"
        "Минимум для вывода: 1000₽\n\n"
        "Отправьте номер карты (или реквизиты) одним сообщением:",
        reply_markup=back_kb()
    )


# ----------------- /admin -----------------

@dp.message(Command("admin"))
async def admin(m: Message):
    if m.from_user.id not in ADMIN_IDS:
        await m.answer(f"Нет доступа. Ваш ID: {m.from_user.id}")
        return
    await m.answer("🛠 Админка CristyVPN", reply_markup=admin_kb())


async def admin_only(c: CallbackQuery) -> bool:
    if c.from_user.id not in ADMIN_IDS:
        await c.answer("Нет доступа", show_alert=True)
        return False
    return True


@dp.callback_query(F.data.startswith("adm:"))
async def admin_cb(c: CallbackQuery):
    if not await admin_only(c):
        return
    parts = c.data.split(":")
    action = parts[1]

    if action == "links":
        links = db.all_links()

        def short(x):
            if not x:
                return "— не задана"
            return x if len(x) <= 60 else x[:57] + "..."

        text = (
            "🔗 Текущие ссылки\n\n"
            f"▸ Пробная: {short(links.get('trial'))}\n"
            f"▸ 30 дней: {short(links.get('30'))}\n"
            f"▸ 90 дней: {short(links.get('90'))}\n"
            f"▸ LTE: {short(links.get('lte'))}\n\n"
            "Нажмите на нужную, чтобы заменить."
        )
        await c.message.edit_text(text, reply_markup=links_kb())
    elif action == "setlink":
        kind = parts[2]
        db.set_state(c.from_user.id, f"setlink:{kind}")
        await c.message.edit_text(
            f"✏️ Введите новую ссылку для «{kind}».\n\n"
            "Она заменит текущую и будет выдаваться всем новым пользователям этого тарифа.",
            reply_markup=admin_back_kb()
        )
    elif action == "stats":
        await c.message.edit_text(db.stats_detailed(), reply_markup=admin_back_kb())
    elif action == "users":
        await c.message.edit_text(db.users_page(), reply_markup=admin_back_kb())
    elif action == "search":
        db.set_state(c.from_user.id, "search_user")
        await c.message.edit_text(
            "🔎 Поиск пользователя\n\n"
            "Отправьте Telegram ID или @username.",
            reply_markup=admin_back_kb()
        )
    elif action == "purchases":
        await c.message.edit_text(db.purchases_stats(), reply_markup=admin_back_kb())
    elif action == "broadcast":
        db.set_state(c.from_user.id, "broadcast")
        await c.message.edit_text(
            "📣 Рассылка\n\nОтправьте текст сообщения, которое нужно отправить всем пользователям.",
            reply_markup=admin_back_kb()
        )
    elif action == "info":
        await c.message.edit_text(
            "ℹ️ Информация\n\n"
            "CristyVPN — управление подписками, покупками и рефералами.\n\n"
            "Ссылки для выдачи задаются в разделе «🔗 Ссылки»:\n"
            "▸ Пробная\n▸ 30 дней\n▸ 90 дней\n▸ LTE\n\n"
            "Каждая ссылка одна на тип и выдаётся пользователю на срок тарифа.",
            reply_markup=admin_back_kb()
        )
    elif action == "withdraws":
        await c.message.edit_text(db.withdraws_text(), reply_markup=admin_back_kb())
    elif action == "promo":
        db.set_state(c.from_user.id, "newpromo")
        await c.message.edit_text(
            "🎁 Создание скидочного промокода\n\n"
            "Формат:\nКОД процент количество_использований\n\n"
            "Пример: SKIDKA 10 5",
            reply_markup=admin_back_kb()
        )
    elif action == "home":
        await c.message.edit_text("🛠 Админка CristyVPN", reply_markup=admin_kb())


# ----------------- ОБЩИЙ ОБРАБОТЧИК -----------------

@dp.message()
async def all_messages(m: Message):
    if m.from_user.id in ADMIN_IDS:
        state = db.get_state(m.from_user.id)
        if state and state.startswith("setlink:"):
            kind = state.split(":")[1]
            db.set_link(kind, m.text.strip())
            db.clear_state(m.from_user.id)
            await m.answer(
                f"✅ Ссылка для «{kind}» обновлена.",
                reply_markup=admin_back_kb()
            )
            return
        if state == "search_user":
            db.clear_state(m.from_user.id)
            query = m.text.strip().lstrip("@")
            result = db.find_user(query)
            await m.answer(result, reply_markup=admin_back_kb())
            return
        if state == "broadcast":
            db.clear_state(m.from_user.id)
            users = db.all_user_ids()
            sent = failed = 0
            for uid in users:
                try:
                    await bot.send_message(uid, m.text)
                    sent += 1
                except Exception:
                    failed += 1
            await m.answer(
                f"📣 Рассылка завершена.\n\n✅ Отправлено: {sent}\n❌ Не доставлено: {failed}",
                reply_markup=admin_back_kb()
            )
            return
        if state == "newpromo":
            try:
                parts = m.text.strip().split()
                if len(parts) != 3:
                    raise ValueError
                code, percent, uses = parts
                db.add_discount_promo(code, int(percent), int(uses))
                db.clear_state(m.from_user.id)
                await m.answer("✅ Скидочный промокод создан.", reply_markup=admin_back_kb())
            except ValueError:
                await m.answer("Формат: КОД процент количество_использований\nПример: SKIDKA 10 5")
            return
        return

    state = db.get_state(m.from_user.id)

    if state == "promo":
        db.clear_state(m.from_user.id)
        code = m.text.strip()
        percent = db.check_discount_promo(code)
        if percent is None:
            await m.answer("❌ Промокод недействителен.", reply_markup=back_kb())
            return
        db.use_discount_promo(code)
        db.set_state(m.from_user.id, f"discount:{percent}")
        await m.answer(
            f"✅ Промокод применён!\n\nСкидка {percent}% на следующую покупку.",
            reply_markup=back_kb()
        )
        return

    if state == "withdraw_card":
        db.clear_state(m.from_user.id)
        card = m.text.strip()
        bal = db.balance(m.from_user.id)
        if bal < 1000:
            await m.answer(f"❌ Минимум для вывода — 1000₽.\nВаш баланс: {bal:.2f}₽", reply_markup=back_kb())
            return
        await m.answer(
            "✅ Заявка на вывод создана!\n\n"
            f"💰 Сумма: {bal:.2f}₽\n"
            f"💳 Реквизиты: {card}\n\n"
            "Ожидайте обработки администратором.",
            reply_markup=back_kb()
        )
        for admin in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin,
                    f"💸 Новая заявка на вывод\n\n"
                    f"👤 ID: {m.from_user.id}\n"
                    f"💰 Сумма: {bal:.2f}₽\n"
                    f"💳 Реквизиты: {card}"
                )
            except Exception:
                pass
        return


# ----------------- ЗАПУСК -----------------

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Укажите BOT_TOKEN в .env")
    print("ADMIN_IDS =", ADMIN_IDS)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())