from aiogram import Bot, Dispatcher, types, executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.dispatcher.filters import Text
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
import sqlite3
import logging
import asyncio

from backup_to_telegram import backup_to_telegram
import asyncio

# Настройка логирования
logging.basicConfig(level=logging.INFO)

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Подключение к базе данных
conn = sqlite3.connect('aircargo.db')
cursor = conn.cursor()

# Таблица клиентов
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE,
    name TEXT,
    phone TEXT,
    city TEXT,
    personal_code TEXT
)
''')

# Таблица заявок (адреса складов)
cursor.execute('''
CREATE TABLE IF NOT EXISTS addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    warehouse TEXT,
    FOREIGN KEY (user_id) REFERENCES users (id)
)
''')

# Таблица трек-кодов и статусов
cursor.execute('''
CREATE TABLE IF NOT EXISTS trackings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracking_code TEXT,
    status TEXT DEFAULT 'Принят'
)
''')

# Таблица сохранённых заявок клиента
cursor.execute('''
CREATE TABLE IF NOT EXISTS saved_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    tracking_code TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

# Таблица цен для всех городов
cursor.execute('''
CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY,
    guangzhou_price REAL,
    yiwu_price REAL,
    urumqi_price REAL
)
''')
# Если таблица цен пустая — создаём начальные значения
cursor.execute("SELECT COUNT(*) FROM prices")
if cursor.fetchone()[0] == 0:
    cursor.execute("INSERT INTO prices (id, guangzhou_price, yiwu_price, urumqi_price) VALUES (1, 8.5, 9.0, 10.0)")

conn.commit()
conn.close()

# Главное меню клиента
main_menu = ReplyKeyboardMarkup(resize_keyboard=True)
main_menu.add(KeyboardButton("🚫 ВАЖНО! Запрещённые товары"))
main_menu.add(KeyboardButton("📝 Регистрация"), KeyboardButton("📦 Адреса складов"))
main_menu.add(KeyboardButton("🔍 Отслеживание"), KeyboardButton("💰 Калькулятор"))
main_menu.add(KeyboardButton("🗂️ Мои заявки"), KeyboardButton("📞 Поддержка"))
main_menu.add(KeyboardButton("📄 Мои данные"), KeyboardButton("✏️ Изменить мои данные"))
main_menu.add(KeyboardButton("📄 Пример заполнения адреса"))

# Главное меню администратора
admin_menu = ReplyKeyboardMarkup(resize_keyboard=True)
admin_menu.add(KeyboardButton("➕ Добавить трек-код"), KeyboardButton("🗑 Удалить трек-код"))
admin_menu.add(KeyboardButton("💵 Текущие цены"), KeyboardButton("💵 Изменить цены"))
admin_menu.add(KeyboardButton("✏️ Редактировать клиента"), KeyboardButton("✏️ Изменить статус груза"))
admin_menu.add(KeyboardButton("📦 Текущие адреса складов"), KeyboardButton("🏢 Изменить адрес склада"))
admin_menu.add(KeyboardButton("📋 Все заявки"), KeyboardButton("📊 Статистика"))

# Универсальная кнопка Назад
back_menu = ReplyKeyboardMarkup(resize_keyboard=True)
back_menu.add(KeyboardButton("🔙 Назад"))

# Клавиатуры и FSM
def yes_no_keyboard():
    buttons = [[KeyboardButton('✅ Да'), KeyboardButton('❌ Нет')]]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

class RegisterState(StatesGroup):
    name = State()
    phone = State()
    city = State()

class AddressState(StatesGroup):
    warehouse = State()

class TrackingState(StatesGroup):
    code = State()

class TrackCargo(StatesGroup):
    waiting_for_tracking_code = State()
    waiting_for_save_choice = State()

class AddTracking(StatesGroup):
    waiting_for_tracking_code = State()
    waiting_for_status = State()

class EditTrackingStatus(StatesGroup):
    waiting_for_tracking_code = State()
    waiting_for_new_status = State()

class EditClient(StatesGroup):
    waiting_for_code = State()
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_city = State()

class PriceState(StatesGroup):
    waiting_for_new_price = State()

class ChangePriceState(StatesGroup):
    waiting_for_city = State()
    waiting_for_new_price = State()

class EditMyDataState(StatesGroup):
    waiting_for_field = State()
    waiting_for_new_value = State()

class EditWarehouseState(StatesGroup):
    waiting_for_city = State()
    waiting_for_new_address = State()

class CalcState(StatesGroup):
    from_city = State()
    to_city = State()
    weight = State()

class DeleteTracking(StatesGroup):
    waiting_for_code = State()

# Генерация личного кода
def generate_personal_code(name, phone):
    initials = ''.join([part[0].upper() for part in name.split()])
    last_digits = phone[-4:]
    conn = sqlite3.connect('aircargo.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE personal_code LIKE ?", (initials + last_digits + '%',))
    count = cursor.fetchone()[0]
    conn.close()
    return f"{initials}{last_digits}{count+1 if count > 0 else ''}"

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    if message.from_user.id in ADMIN_IDS:
        await message.answer("Привет, админ! Выберите действие:", reply_markup=admin_menu)
    else:
        await message.answer("Добро пожаловать в Aircargo.tj!\nВыберите действие:", reply_markup=main_menu)

@dp.message_handler(Text(equals="📝 Регистрация"))
async def register_start(message: types.Message):
    await message.answer("Введите ваше ФИО:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await RegisterState.name.set()

@dp.message_handler(state=RegisterState.name)
async def register_name(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await message.answer("Вы вернулись в меню.", reply_markup=main_menu)
        await state.finish()
        return
    await state.update_data(name=message.text)
    await message.answer("Введите ваш номер телефона:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await RegisterState.phone.set()

@dp.message_handler(state=RegisterState.phone)
async def register_phone(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await message.answer("Введите ваше ФИО:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
        await RegisterState.name.set()
        return
    await state.update_data(phone=message.text)
    await message.answer("Введите ваш город:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await RegisterState.city.set()

@dp.message_handler(state=RegisterState.city)
async def register_city(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await message.answer("Введите ваш номер телефона:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
        await RegisterState.phone.set()
        return

    data = await state.get_data()
    personal_code = generate_personal_code(data['name'], data['phone'])

    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (telegram_id, name, phone, city, personal_code)
            VALUES (?, ?, ?, ?, ?)
        ''', (message.from_user.id, data['name'], data['phone'], message.text, personal_code))
        conn.commit()

    await message.answer(f"✅ Регистрация завершена!\nВаш личный код: {personal_code}", reply_markup=main_menu)
    await state.finish()

@dp.message_handler(Text(equals="📄 Мои данные"))
async def my_data_button(message: types.Message):
    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, phone, city, personal_code FROM users WHERE telegram_id=?", (message.from_user.id,))
        user = cursor.fetchone()

    if user:
        await message.answer(f"👤 Имя: {user[0]}\n📞 Телефон: {user[1]}\n🏙️ Город: {user[2]}\n🆔 Личный код: {user[3]}")
    else:
        await message.answer("Вы ещё не зарегистрированы. Нажмите 📝 Регистрация.")

@dp.message_handler(Text(equals="📄 Пример заполнения адреса"))
async def example_fill_address(message: types.Message):
    await message.answer("📌 Подробная инструкция по заполнению доступна по ссылке:\nhttps://teletype.in/@aircargo.tj/sVNgt0wYj3e")

@dp.message_handler(Text(equals="📦 Адреса складов"))
async def choose_warehouse(message: types.Message):
    warehouse_menu = ReplyKeyboardMarkup(resize_keyboard=True)
    warehouse_menu.add(KeyboardButton("Гуанчжоу"), KeyboardButton("Иву"), KeyboardButton("Урумчи"))
    warehouse_menu.add(KeyboardButton("🔙 Назад"))
    await message.answer("Выберите склад:", reply_markup=warehouse_menu)
    await AddressState.warehouse.set()

@dp.message_handler(state=AddressState.warehouse)
async def warehouse_selected(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await message.answer("Вы вернулись в меню.", reply_markup=main_menu)
        await state.finish()
        return

    warehouse = message.text

    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        # Получаем personal_code
        cursor.execute("SELECT personal_code FROM users WHERE telegram_id = ?", (message.from_user.id,))
        result = cursor.fetchone()
        if not result:
            await message.answer("❗ Сначала пройдите регистрацию.", reply_markup=main_menu)
            await state.finish()
            return
        personal_code = result[0]

        # Получаем шаблон адреса из таблицы warehouses
        cursor.execute("SELECT address FROM warehouses WHERE city=?", (warehouse,))
        template = cursor.fetchone()

    if template:
        address = template[0].replace("{code}", personal_code).replace("\\n", "\n")
        await message.answer(address, reply_markup=main_menu)
    else:
        await message.answer("❌ Адрес для выбранного склада не найден.", reply_markup=main_menu)

    await state.finish()

@dp.message_handler(commands=["debug_warehouse"])
async def debug_warehouse(message: types.Message):
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("⛔ У вас нет доступа.")
            return

        with sqlite3.connect('aircargo.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT city, address FROM warehouses")
            rows = cursor.fetchall()

        if not rows:
            await message.answer("📭 Нет данных в таблице warehouses.")
            return

        text = "\n\n".join([f"🏢 {city}:\n{addr}" for city, addr in rows])
        await message.answer(f"<pre>{text}</pre>", parse_mode="HTML")


@dp.message_handler(Text(equals="🔍 Отслеживание"))
async def track_order(message: types.Message, state: FSMContext):
    await message.answer("Введите трек-код:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await TrackCargo.waiting_for_tracking_code.set()

@dp.message_handler(state=TrackCargo.waiting_for_tracking_code)
async def track_status(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await message.answer("Вы вернулись в меню.", reply_markup=main_menu)
        await state.finish()
        return

    track_code = message.text.strip()
    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM trackings WHERE tracking_code=?", (track_code,))
        result = cursor.fetchone()

    if result:
        await state.update_data(track_code=track_code)
        await message.answer(f"📦 Статус: {result[0]}\nСохранить в Мои заявки?", reply_markup=yes_no_keyboard())
        await TrackCargo.waiting_for_save_choice.set()
    else:
        await message.answer("❌ Код не найден или ещё не зарегистрирован.")
        await state.finish()

@dp.message_handler(state=TrackCargo.waiting_for_save_choice)
async def save_tracking_choice(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await message.answer("Вы вернулись в меню.", reply_markup=main_menu)
        await state.finish()
        return

    user_response = message.text.strip()
    data = await state.get_data()
    track_code = data.get('track_code')

    if user_response == '✅ Да':
        with sqlite3.connect('aircargo.db') as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO saved_orders (user_id, tracking_code) VALUES (?, ?)", (message.from_user.id, track_code))
            conn.commit()
        await message.answer("✅ Сохранено в 'Мои заявки'", reply_markup=main_menu)
    else:
        await message.answer("Ок, не сохраняем.")
    await state.finish()

@dp.message_handler(Text(equals="🗂️ Мои заявки"))
async def show_my_orders(message: types.Message):
    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tracking_code FROM saved_orders 
            WHERE user_id = ? 
            ORDER BY created_at DESC
        """, (message.from_user.id,))
        orders = cursor.fetchall()

        text = "📋 Ваши сохранённые трек-коды:\n\n"
        if orders:
            for order in orders:
                cursor.execute("SELECT status FROM trackings WHERE tracking_code = ?", (order[0],))
                status = cursor.fetchone()
                if status:
                    emoji = {"Принят": "✅", "В пути": "🚚", "На складе": "🏢", "Доставлен": "🎯"}.get(status[0], "ℹ️")
                    text += f"• {order[0]} — {emoji} {status[0]}\n"
            await message.answer(text)
        else:
            await message.answer("❗ У вас пока нет сохранённых заявок.")

@dp.message_handler(Text(equals="📞 Поддержка"))
async def support(message: types.Message):
    await message.answer("📞 Контактная информация:\n\nТел: +992 000 55 85 58\nEmail: support@aircargo.tj")

@dp.message_handler(Text(equals="🚫 ВАЖНО! Запрещённые товары"))
async def forbidden_goods(message: types.Message):
    text = ("🚫 *Запрещённые к перевозке товары:*\n\n"
            "🔋 Батареи и аккумуляторы (Телефоны, часы, техника с батареей внутри)\n"
            "🔫 Оружие и боеприпасы (пистолеты, ножи, взрывчатые вещества)\n"
            "🔥 Легковоспламеняющиеся вещества (бензин, газовые баллоны, зажигалки)\n"
            "☢️ Радиоактивные и токсичные вещества (химикаты, ртуть, кислоты)\n"
            "💊 Наркотики и сильнодействующие лекарства (без рецепта)\n"
            "🧪 Коррозийные вещества (отбеливатели, щёлочи)\n"
            "💰 Поддельные денежные знаки и ценные бумаги\n"
            "📦 И другие товары, запрещённые авиаперевозками.\n\n"
            "⚠️ *Важно:* Если клиент отправит запрещённый товар, компания *Aircargo.tj* не несёт ответственности за ее конфискацию.\n\n"
            "❓ По вопросам запрещённых товаров обратитесь к администратору.")
    await message.answer(text, parse_mode="Markdown")

@dp.message_handler(Text(equals="💰 Калькулятор"))
async def calc_start(message: types.Message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True).add("Гуанчжоу", "Иву", "Урумчи").add("🔙 Назад")
    await message.answer("Выберите город отправки:", reply_markup=markup)
    await CalcState.from_city.set()

@dp.message_handler(state=CalcState.from_city)
async def calc_from_city(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await message.answer("Вы вернулись в меню.", reply_markup=main_menu)
        await state.finish()
        return
    await state.update_data(from_city=message.text)
    markup = ReplyKeyboardMarkup(resize_keyboard=True).add("Душанбе", "🔙 Назад")
    await message.answer("Выберите город получения:", reply_markup=markup)
    await CalcState.to_city.set()

@dp.message_handler(state=CalcState.to_city)
async def calc_to_city(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        markup = ReplyKeyboardMarkup(resize_keyboard=True).add("Гуанчжоу", "Иву", "Урумчи").add("🔙 Назад")
        await message.answer("Выберите город отправки:", reply_markup=markup)
        await CalcState.from_city.set()
        return
    await state.update_data(to_city=message.text)
    await message.answer("Введите вес груза (в кг), например: 10", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await CalcState.weight.set()

@dp.message_handler(state=CalcState.weight)
async def calc_weight(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        markup = ReplyKeyboardMarkup(resize_keyboard=True).add("Душанбе", "🔙 Назад")
        await message.answer("Выберите город получения:", reply_markup=markup)
        await CalcState.to_city.set()
        return
    try:
        weight = float(message.text.strip())
    except:
        await message.answer("Ошибка в формате. Введите только вес в кг, например: 10")
        return
    data = await state.get_data()
    from_city = data.get('from_city')
    to_city = data.get('to_city')

    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT guangzhou_price, yiwu_price, urumqi_price FROM prices WHERE id = 1")
        prices = cursor.fetchone()

    if from_city == "Гуанчжоу":
        price_per_kg = prices[0]
    elif from_city == "Иву":
        price_per_kg = prices[1]
    elif from_city == "Урумчи":
        price_per_kg = prices[2]
    else:
        await message.answer("Город отправки не найден.", reply_markup=main_menu)
        await state.finish()
        return

    total_price = price_per_kg * weight

    if to_city.lower() == "душанбе":
        await message.answer(f"📦 Примерная стоимость: {total_price} USD\n⏳ Срок доставки: 7–10 дней", reply_markup=main_menu)
    else:
        await message.answer(f"🚫 К сожалению, доставка на данный момент осуществляется только до Душанбе.\n"
                             f"Стоимость доставки до Душанбе: {total_price} USD", reply_markup=main_menu)

    await state.finish()

@dp.message_handler(Text(equals="💵 Текущие цены"))
async def current_prices(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT guangzhou_price, yiwu_price, urumqi_price FROM prices WHERE id=1")
        prices = cursor.fetchone()

    await message.answer(f"💵 Текущие цены по городам:\n\n"
                         f"Гуанчжоу: {prices[0]} USD/кг\n"
                         f"Иву: {prices[1]} USD/кг\n"
                         f"Урумчи: {prices[2]} USD/кг")

@dp.message_handler(Text(equals="💵 Изменить цены"))
async def change_prices(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    markup = ReplyKeyboardMarkup(resize_keyboard=True).add("Гуанчжоу", "Иву", "Урумчи").add("🔙 Назад")
    await message.answer("Выберите город:", reply_markup=markup)
    await ChangePriceState.waiting_for_city.set()

@dp.message_handler(state=ChangePriceState.waiting_for_city)
async def receive_city_price(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.finish()
        await message.answer("Отмена", reply_markup=admin_menu)
        return
    await state.update_data(city=message.text)
    await message.answer("Введите новую цену:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await ChangePriceState.waiting_for_new_price.set()

@dp.message_handler(state=ChangePriceState.waiting_for_new_price)
async def set_city_price(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.finish()
        await message.answer("Отмена", reply_markup=admin_menu)
        return
    data = await state.get_data()
    price = float(message.text.strip())
    city = data['city']

    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        field = {
            "Гуанчжоу": "guangzhou_price",
            "Иву": "yiwu_price",
            "Урумчи": "urumqi_price"
        }.get(city)

        if field:
            cursor.execute(f"UPDATE prices SET {field}=? WHERE id=1", (price,))
            conn.commit()
            await message.answer("✅ Цена обновлена", reply_markup=admin_menu)
        else:
            await message.answer("❌ Неверный город", reply_markup=admin_menu)

    await state.finish()

@dp.message_handler(Text(equals="📦 Текущие адреса складов"))
async def current_warehouses(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT address FROM warehouses WHERE city='Гуанчжоу'")
        g = cursor.fetchone()
        cursor.execute("SELECT address FROM warehouses WHERE city='Иву'")
        y = cursor.fetchone()
        cursor.execute("SELECT address FROM warehouses WHERE city='Урумчи'")
        u = cursor.fetchone()

    g_addr = g[0].replace("\\n", "\n") if g else "❌ Не указано"
    y_addr = y[0].replace("\\n", "\n") if y else "❌ Не указано"
    u_addr = u[0].replace("\\n", "\n") if u else "❌ Не указано"

    await message.answer(f"📦 Текущие адреса складов:\n\n"
                         f"Гуанчжоу:\n{g_addr}\n\n"
                         f"Иву:\n{y_addr}\n\n"
                         f"Урумчи:\n{u_addr}", reply_markup=admin_menu)


@dp.message_handler(Text(equals="🏢 Изменить адрес склада"))
async def change_address_start(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    markup = ReplyKeyboardMarkup(resize_keyboard=True).add("Гуанчжоу", "Иву", "Урумчи").add("🔙 Назад")
    await message.answer("Выберите город склада:", reply_markup=markup)
    await EditWarehouseState.waiting_for_city.set()

@dp.message_handler(state=EditWarehouseState.waiting_for_city)
async def receive_city_for_address(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.finish()
        await message.answer("Отмена", reply_markup=admin_menu)
        return
    await state.update_data(city=message.text)
    await message.answer("Введите новый адрес склада:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await EditWarehouseState.waiting_for_new_address.set()

@dp.message_handler(state=EditWarehouseState.waiting_for_new_address)
async def set_new_warehouse_address(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.finish()
        await message.answer("Отмена", reply_markup=admin_menu)
        return

    data = await state.get_data()
    city = data.get("city")
    new_address = message.text

    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute("REPLACE INTO warehouses (city, address) VALUES (?, ?)", (city, new_address))
        conn.commit()

    await message.answer(
        "Введите новый адрес склада.\n\n"
        "⚠️ В конце адреса обязательно добавьте `{code}` — на его месте клиент увидит свой личный код.\n\n"
        "Пример:\n"
        "收货人: 19960\n"
        "手机号码:13710104098\n"
        "地址：广东省佛山市南海区敦豪物流中心Z栋26号 骏能达航空物流 19960 {code}",
        reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад")
        )

    await message.answer("✅ Адрес обновлён.", reply_markup=admin_menu)
    await state.finish()

@dp.message_handler(Text(equals="✏️ Изменить мои данные"))
async def start_edit_my_data(message: types.Message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Имя", "Телефон", "Город", "🔙 Назад")
    await message.answer("Что вы хотите изменить?", reply_markup=markup)
    await EditMyDataState.waiting_for_field.set()

@dp.message_handler(state=EditMyDataState.waiting_for_field)
async def choose_field(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.finish()
        await message.answer("Вы вернулись в меню.", reply_markup=main_menu)
        return

    field = message.text.lower()
    if field not in ["имя", "телефон", "город"]:
        await message.answer("Пожалуйста, выберите Имя, Телефон или Город.", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("Имя", "Телефон", "Город", "🔙 Назад"))
        return
    await state.update_data(field=field)
    await message.answer(f"Введите новое значение для {field}:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await EditMyDataState.waiting_for_new_value.set()

@dp.message_handler(state=EditMyDataState.waiting_for_new_value)
async def set_new_value(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("Имя", "Телефон", "Город", "🔙 Назад")
        await message.answer("Что вы хотите изменить?", reply_markup=markup)
        await EditMyDataState.waiting_for_field.set()
        return

    data = await state.get_data()
    field = data.get("field")

    if field == "имя":
        sql_field = "name"
    elif field == "телефон":
        sql_field = "phone"
    elif field == "город":
        sql_field = "city"
    else:
        await message.answer("Ошибка. Попробуйте снова.", reply_markup=main_menu)
        await state.finish()
        return

    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE users SET {sql_field} = ? WHERE telegram_id = ?", (message.text, message.from_user.id))
        conn.commit()

        # Получаем обновлённые name и phone
        cursor.execute("SELECT name, phone FROM users WHERE telegram_id = ?", (message.from_user.id,))
        name, phone = cursor.fetchone()
        new_code = generate_personal_code(name, phone)
        cursor.execute("UPDATE users SET personal_code = ? WHERE telegram_id = ?", (new_code, message.from_user.id))
        conn.commit()


    await message.answer("✅ Данные успешно обновлены!", reply_markup=main_menu)
    await state.finish()

@dp.message_handler(Text(equals="📋 Все заявки"))
async def all_trackings(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tracking_code, status FROM trackings")
        rows = cursor.fetchall()

    if rows:
        text = "📋 Все трек-коды:\n\n"
        for row in rows:
            text += f"{row[0]} — {row[1]}\n"
        await message.answer(text)
    else:
        await message.answer("Нет трек-кодов.")

@dp.message_handler(Text(equals="📊 Статистика"))
async def show_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM trackings")
        track_count = cursor.fetchone()[0]

    await message.answer(f"📊 Статистика:\nПользователей: {user_count}\nТрек-кодов: {track_count}")

@dp.message_handler(Text(equals="➕ Добавить трек-код"))
async def admin_add_tracking(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("Введите трек-код:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await AddTracking.waiting_for_tracking_code.set()

@dp.message_handler(state=AddTracking.waiting_for_tracking_code)
async def admin_add_code(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.finish()
        await message.answer("Возврат в админ-меню", reply_markup=admin_menu)
        return
    await state.update_data(code=message.text.strip())
    await message.answer("Введите статус (Принят, В пути, На складе, Доставлен):", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await AddTracking.waiting_for_status.set()

@dp.message_handler(state=AddTracking.waiting_for_status)
async def admin_add_status(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.finish()
        await message.answer("Возврат в админ-меню", reply_markup=admin_menu)
        return
    data = await state.get_data()
    code = data['code']
    status = message.text.strip()

    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO trackings (tracking_code, status) VALUES (?, ?)", (code, status))
        conn.commit()

    await message.answer(f"✅ Трек-код {code} добавлен со статусом: {status}", reply_markup=admin_menu)
    await state.finish()

@dp.message_handler(Text(equals="✏️ Изменить статус груза"))
async def admin_edit_status(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("Введите трек-код для изменения статуса:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await EditTrackingStatus.waiting_for_tracking_code.set()

@dp.message_handler(state=EditTrackingStatus.waiting_for_tracking_code)
async def admin_receive_code_for_edit(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.finish()
        await message.answer("Возврат в админ-меню", reply_markup=admin_menu)
        return
    await state.update_data(code=message.text.strip())
    await message.answer("Введите новый статус:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await EditTrackingStatus.waiting_for_new_status.set()

@dp.message_handler(state=EditTrackingStatus.waiting_for_new_status)
async def admin_set_new_status(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.finish()
        await message.answer("Возврат в админ-меню", reply_markup=admin_menu)
        return
    data = await state.get_data()
    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE trackings SET status=? WHERE tracking_code=?", (message.text.strip(), data['code']))
        conn.commit()

    await message.answer("✅ Статус обновлён", reply_markup=admin_menu)
    await state.finish()

@dp.message_handler(Text(equals="✏️ Редактировать клиента"))
async def edit_client(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("Введите личный код клиента:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await EditClient.waiting_for_code.set()

@dp.message_handler(state=EditClient.waiting_for_code)
async def receive_client_code(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.finish()
        await message.answer("Отмена", reply_markup=admin_menu)
        return

    code = message.text.strip()
    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE personal_code=?", (code,))
        user = cursor.fetchone()

    if user:
        await state.update_data(user_id=user[0])
        await message.answer("Введите новое имя клиента:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
        await EditClient.waiting_for_name.set()
    else:
        await message.answer("❌ Клиент с таким кодом не найден.")
        await state.finish()

@dp.message_handler(state=EditClient.waiting_for_name)
async def receive_new_name(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await message.answer("Введите личный код клиента:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
        await EditClient.waiting_for_code.set()
        return
    await state.update_data(name=message.text.strip())
    await message.answer("Введите новый номер телефона клиента:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await EditClient.waiting_for_phone.set()

@dp.message_handler(state=EditClient.waiting_for_phone)
async def receive_new_phone(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await message.answer("Введите новое имя клиента:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
        await EditClient.waiting_for_name.set()
        return
    await state.update_data(phone=message.text.strip())
    await message.answer("Введите новый город клиента:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await EditClient.waiting_for_city.set()

@dp.message_handler(state=EditClient.waiting_for_city)
async def receive_new_city(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await message.answer("Введите новый номер телефона клиента:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
        await EditClient.waiting_for_phone.set()
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    name = data.get("name")
    phone = data.get("phone")
    city = message.text.strip()

    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET name=?, phone=?, city=? WHERE id=?", (name, phone, city, user_id))
        conn.commit()

    await message.answer("✅ Данные клиента обновлены.", reply_markup=admin_menu)
    await state.finish()

@dp.message_handler(Text(equals="🗑 Удалить трек-код"))
async def delete_tracking_prompt(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("Введите трек-код для удаления:", reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add("🔙 Назад"))
    await DeleteTracking.waiting_for_code.set()

@dp.message_handler(state=DeleteTracking.waiting_for_code)
async def delete_tracking(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await message.answer("Возврат в админ-меню", reply_markup=admin_menu)
        await state.finish()
        return
    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM trackings WHERE tracking_code=?", (message.text.strip(),))
        conn.commit()
    await message.answer("✅ Удалено", reply_markup=admin_menu)
    await state.finish()

# ========== ИНИЦИАЛИЗАЦИЯ БАЗЫ ==========
def init_db():
    with sqlite3.connect('aircargo.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            name TEXT,
            phone TEXT,
            city TEXT,
            personal_code TEXT
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            warehouse TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS trackings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_code TEXT,
            status TEXT DEFAULT 'Принят'
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS saved_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tracking_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY,
            guangzhou_price REAL,
            yiwu_price REAL,
            urumqi_price REAL
        )''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS warehouses (
            city TEXT PRIMARY KEY,
            address TEXT
        )
        ''')

        cursor.execute("SELECT COUNT(*) FROM warehouses")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO warehouses (city, address) VALUES (?, ?)", (
                "Гуанчжоу",
                "收货人: 19960\n手机号码:13710104098\n地址：广东省佛山市南海区敦豪物流中心Z栋26号 骏能达航空物流 19960 {code}"
            ))
            cursor.execute("INSERT INTO warehouses (city, address) VALUES (?, ?)", (
                "Иву",
                "收货人 : 客户名称 19960\n手机号码：18324012203\n地址 : 义乌宏晖纺织有限公司安商路3号宏晖纺织产业园6号楼一楼东仓库 19960 {code}"
            ))
            cursor.execute("INSERT INTO warehouses (city, address) VALUES (?, ?)", (
                "Урумчи",
                "Склад в Урумчи пока не открыт."
            ))

        cursor.execute("SELECT COUNT(*) FROM prices")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO prices (id, guangzhou_price, yiwu_price, urumqi_price) VALUES (1, 8.5, 9.0, 10.0)")

        conn.commit()

# ========== BACKUP + STARTUP ==========
async def on_startup(_):
    init_db()
    asyncio.create_task(backup_to_telegram())

def main():
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)

if __name__ == '__main__':
    main()
