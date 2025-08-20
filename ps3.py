import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timedelta

import smbus2
from bme280 import BME280
import RPi.GPIO as GPIO
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram import F

# Настройки
BOT_TOKEN = 'YOUR_BOT_TOKEN'  # Замени на свой токен
USER_ID = 154966995  # Твой user_id для авторизации
DB_FILE = 'plants.db'  # База в текущей папке
MEASUREMENT_INTERVAL = 1200  # 20 минут в секундах

# Пины для LED (BCM mode)
RED_PIN = 17  # GPIO11 -> BCM17
GREEN_PIN = 27  # GPIO13 -> BCM27
BLUE_PIN = 22  # GPIO15 -> BCM22
LED_GND = 14  # Не используется в коде, просто подключен

# Инициализация GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)  # Отключаем предупреждения о пинах
GPIO.setup(RED_PIN, GPIO.OUT)
GPIO.setup(GREEN_PIN, GPIO.OUT)
GPIO.setup(BLUE_PIN, GPIO.OUT)

# Инициализация BME280 (используем класс BME280)
bus = smbus2.SMBus(1)
bme = BME280(i2c_dev=bus, i2c_addr=0x76)  # Или 0x77, проверь i2cdetect

# Инициализация БД
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS measurements (
    timestamp TEXT,
    temperature REAL,
    humidity REAL,
    pressure REAL
)
''')
conn.commit()


# Функции для LED
def update_led(temp):
    GPIO.output(RED_PIN, GPIO.LOW)
    GPIO.output(GREEN_PIN, GPIO.LOW)
    GPIO.output(BLUE_PIN, GPIO.LOW)
    if temp < 22:
        GPIO.output(BLUE_PIN, GPIO.HIGH)
    elif temp > 30:
        GPIO.output(RED_PIN, GPIO.HIGH)
    else:
        GPIO.output(GREEN_PIN, GPIO.HIGH)


# Функция чтения и сохранения данных
async def read_and_save(bot):
    try:
        temp = bme.get_temperature()
        hum = bme.get_humidity()
        pres = bme.get_pressure()
        timestamp = datetime.now().isoformat()

        cursor.execute('INSERT INTO measurements VALUES (?, ?, ?, ?)', (timestamp, temp, hum, pres))
        conn.commit()

        update_led(temp)

        message = f"Новый замер:\nТемпература: {temp:.2f}°C\nВлажность: {hum:.2f}%\nДавление: {pres:.2f} hPa"
        await bot.send_message(USER_ID, message)

        # Проверка на опасность и предупреждение
        if temp < 22 or temp > 30:
            warning = f"Внимание! Температура вне нормы: {temp:.2f}°C"
            await bot.send_message(USER_ID, warning)

    except Exception as e:
        error_msg = f"Ошибка: {str(e)}"
        await bot.send_message(USER_ID, error_msg)
        logging.error(error_msg)


# Функция для статистики (только текст)
def get_stats(period_days):
    end = datetime.now()
    start = end - timedelta(days=period_days)
    cursor.execute('SELECT * FROM measurements WHERE timestamp BETWEEN ? AND ?', (start.isoformat(), end.isoformat()))
    data = cursor.fetchall()

    if not data:
        return "Нет данных за период."

    temps = [row[1] for row in data]
    hums = [row[2] for row in data]
    press = [row[3] for row in data]

    stats = f"Статистика за {period_days} дней:\n"
    stats += f"Температура: мин {min(temps):.2f}, макс {max(temps):.2f}, среднее {sum(temps) / len(temps):.2f}\n"
    stats += f"Влажность: мин {min(hums):.2f}, макс {max(hums):.2f}, среднее {sum(hums) / len(hums):.2f}\n"
    stats += f"Давление: мин {min(press):.2f}, макс {max(press):.2f}, среднее {sum(press) / len(press):.2f}"

    return stats


# Бот
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Inline клавиатура
inline_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Текущие показатели", callback_data="current")],
    [InlineKeyboardButton(text="Статистика за неделю", callback_data="week")],
    [InlineKeyboardButton(text="Статистика за месяц", callback_data="month")]
])


@dp.message(Command("start"))
async def start(message: types.Message):
    if message.from_user.id != USER_ID:
        await message.answer("Доступ запрещен.")
        return
    await message.answer("Меню:", reply_markup=inline_kb)


@dp.callback_query(F.data == "current")
async def current(callback: types.CallbackQuery):
    if callback.from_user.id != USER_ID:
        await callback.answer("Доступ запрещен.")
        return
    try:
        temp = bme.get_temperature()
        hum = bme.get_humidity()
        pres = bme.get_pressure()
        await callback.message.answer(f"Текущие:\nТемп: {temp:.2f}°C\nВлаж: {hum:.2f}%\nДавл: {pres:.2f} hPa")
    except Exception as e:
        await callback.message.answer(f"Ошибка: {str(e)}")


@dp.callback_query(F.data == "week")
async def week_stats(callback: types.CallbackQuery):
    if callback.from_user.id != USER_ID:
        await callback.answer("Доступ запрещен.")
        return
    stats = get_stats(7)
    await callback.message.answer(stats)


@dp.callback_query(F.data == "month")
async def month_stats(callback: types.CallbackQuery):
    if callback.from_user.id != USER_ID:
        await callback.answer("Доступ запрещен.")
        return
    stats = get_stats(30)
    await callback.message.answer(stats)


# Основной цикл
async def main():
    # Запуск бота
    asyncio.create_task(dp.start_polling(bot))

    # Цикл измерений
    while True:
        await read_and_save(bot)
        await asyncio.sleep(MEASUREMENT_INTERVAL)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()
        GPIO.cleanup()