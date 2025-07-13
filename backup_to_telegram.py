from aiogram import Bot
import asyncio
import sqlite3
import pandas as pd

# Введи сюда токен бота и свой Telegram ID
API_TOKEN = '7724256533:AAHfI53g877xhnCzwrIhtd0n41Bo2wTDY9U'
ADMIN_ID = 1036507055  # Замени на свой Telegram ID

bot = Bot(token=API_TOKEN)


async def backup_to_telegram():
    while True:
        try:
            # Бэкап aircargo.db
            with open('aircargo.db', 'rb') as db_file:
                await bot.send_document(ADMIN_ID, db_file, caption='🗂️ Автоматический бэкап базы данных')
                print('✅ Бэкап базы успешно отправлен в Telegram!')

            # Бэкап клиентов в Excel
            await backup_clients_to_excel()

        except Exception as e:
            print(f'❌ Ошибка при отправке бэкапа: {e}')

        await asyncio.sleep(86400)  # раз в сутки


async def backup_clients_to_excel():
    try:
        conn = sqlite3.connect('aircargo.db')
        query = "SELECT * FROM users"
        df = pd.read_sql_query(query, conn)
        conn.close()

        excel_filename = 'clients_backup.xlsx'
        df.to_excel(excel_filename, index=False)

        with open(excel_filename, 'rb') as file:
            await bot.send_document(ADMIN_ID, file, caption='🗂️ Бэкап базы клиентов (Excel)')
            print('✅ Бэкап клиентов успешно отправлен в Telegram!')

    except Exception as e:
        print(f'❌ Ошибка при бэкапе клиентов: {e}')
