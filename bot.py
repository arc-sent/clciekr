import asyncio
import os
import datetime
import subprocess
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
OWNER_ID = int(os.getenv('OWNER_ID', 0))

swiper_process = None
start_time = None
like_count = 0


def is_owner(update: Update) -> bool:
    return update.effective_user.id == OWNER_ID


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    global swiper_process, start_time, like_count

    if swiper_process and swiper_process.poll() is None:
        await update.message.reply_text('Уже запущен.')
        return

    like_count = 0
    start_time = datetime.datetime.now()
    swiper_process = subprocess.Popen(
        ['python3', 'ashqua_swiper.py'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )

    asyncio.create_task(monitor_output(context))
    await update.message.reply_text('Запущен! Используй /status или /stop.')


async def monitor_output(context: ContextTypes.DEFAULT_TYPE):
    global like_count
    while swiper_process and swiper_process.poll() is None:
        line = await asyncio.get_event_loop().run_in_executor(
            None, swiper_process.stdout.readline
        )
        if not line:
            break
        line = line.strip()
        if 'API LIKE → OK' in line:
            like_count += 1
        if '[!]' in line or 'Ошибка' in line:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f'Предупреждение: {line}',
            )

    if swiper_process and swiper_process.returncode not in (None, 0, -15):
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text='Свайпер завершился с ошибкой. Используй /start чтобы перезапустить.',
        )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    global swiper_process

    if not swiper_process or swiper_process.poll() is not None:
        await update.message.reply_text('Не запущен.')
        return

    swiper_process.terminate()
    swiper_process = None
    await update.message.reply_text('Остановлен.')


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return

    running = swiper_process and swiper_process.poll() is None
    if not running:
        await update.message.reply_text('Статус: не запущен.')
        return

    elapsed = str(datetime.datetime.now() - start_time).split('.')[0] if start_time else '—'
    await update.message.reply_text(
        f'Статус: работает\n'
        f'Лайков: {like_count}\n'
        f'Время работы: {elapsed}'
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    await update.message.reply_text(
        '/start — запустить свайпер\n'
        '/stop — остановить\n'
        '/status — статистика\n'
        '/help — помощь'
    )


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('stop', cmd_stop))
    app.add_handler(CommandHandler('status', cmd_status))
    app.add_handler(CommandHandler('help', cmd_help))
    print('[*] Бот запущен...')
    app.run_polling()


if __name__ == '__main__':
    main()
