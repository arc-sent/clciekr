import asyncio
import os
import random
import datetime
import subprocess
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
OWNER_ID = int(os.getenv('OWNER_ID', 0))
DEBUG = os.getenv('DEBUG', '0') == '1'

# Расписание: 3 старта в сутки (HH:MM), длительность ~2.5ч ± случайный разброс
SCHEDULE_STARTS = [
    s.strip() for s in os.getenv('SCHEDULE', '10:00,15:00,20:00').split(',')
]
SESSION_DURATION_MIN = int(os.getenv('SESSION_DURATION', '150'))  # минут
SESSION_JITTER_MIN = int(os.getenv('SESSION_JITTER', '15'))       # ± минут

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
for _noisy in ('httpcore', 'httpx', 'telegram', 'asyncio'):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def dbg(msg: str):
    if DEBUG:
        print(f'[DBG] {msg}')


swiper_process = None
session_start_time = None
like_count = 0
auto_mode = False  # включён ли автоматический режим по расписанию


def is_owner(update: Update) -> bool:
    return update.effective_user.id == OWNER_ID


async def start_swiper(context, notify=True):
    global swiper_process, session_start_time, like_count

    if swiper_process and swiper_process.poll() is None:
        dbg('свайпер уже запущен')
        return False

    like_count = 0
    session_start_time = datetime.datetime.now()
    swiper_process = subprocess.Popen(
        ['python3', 'ashqua_swiper.py'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    dbg(f'свайпер запущен, pid={swiper_process.pid}')
    asyncio.create_task(monitor_output(context))

    if notify:
        await context.bot.send_message(chat_id=OWNER_ID, text='Свайпер запущен.')
    return True


async def stop_swiper(context, notify=True, reason=''):
    global swiper_process

    if not swiper_process or swiper_process.poll() is not None:
        dbg('свайпер не запущен')
        return False

    swiper_process.terminate()
    swiper_process = None
    dbg('свайпер остановлен')

    if notify:
        msg = f'Свайпер остановлен. {reason}\nЛайков за сеанс: {like_count}'
        await context.bot.send_message(chat_id=OWNER_ID, text=msg)
    return True


async def monitor_output(context):
    global like_count
    while swiper_process and swiper_process.poll() is None:
        line = await asyncio.get_event_loop().run_in_executor(
            None, swiper_process.stdout.readline
        )
        if not line:
            break
        line = line.strip()
        dbg(f'свайпер: {line}')
        if '| tap →' in line:
            like_count += 1
            dbg(f'лайк засчитан, всего={like_count}')
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


async def scheduler_loop(context):
    """Каждую минуту проверяет расписание и запускает/останавливает свайпер."""
    while True:
        await asyncio.sleep(60)
        if not auto_mode:
            continue

        now = datetime.datetime.now()
        now_str = now.strftime('%H:%M')

        for start_str in SCHEDULE_STARTS:
            if now_str == start_str:
                jitter = random.randint(-SESSION_JITTER_MIN, SESSION_JITTER_MIN)
                duration = SESSION_DURATION_MIN + jitter
                dbg(f'авто-старт по расписанию {start_str}, длительность {duration} мин')
                started = await start_swiper(context, notify=True)
                if started:
                    await context.bot.send_message(
                        chat_id=OWNER_ID,
                        text=f'Авто-сеанс {start_str} — длительность {duration} мин.'
                    )
                    asyncio.create_task(auto_stop_after(context, duration))
                break


async def auto_stop_after(context, minutes: int):
    await asyncio.sleep(minutes * 60)
    if auto_mode:
        await stop_swiper(context, notify=True, reason=f'Сеанс {minutes} мин завершён.')


# ── Команды бота ──────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    dbg(f'cmd_start от {update.effective_user.id}')
    started = await start_swiper(context, notify=False)
    if started:
        await update.message.reply_text('Запущен! Используй /status или /stop.')
    else:
        await update.message.reply_text('Уже запущен.')


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    dbg(f'cmd_stop от {update.effective_user.id}')
    stopped = await stop_swiper(context, notify=False)
    if stopped:
        await update.message.reply_text(f'Остановлен. Лайков за сеанс: {like_count}')
    else:
        await update.message.reply_text('Не запущен.')


async def cmd_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Включить/выключить автоматический режим по расписанию."""
    if not is_owner(update):
        return
    global auto_mode
    auto_mode = not auto_mode
    status = 'включён' if auto_mode else 'выключен'
    schedule_info = ', '.join(SCHEDULE_STARTS)
    msg = (
        f'Авторежим {status}.\n'
        f'Расписание: {schedule_info}\n'
        f'Длительность: ~{SESSION_DURATION_MIN} мин ± {SESSION_JITTER_MIN} мин'
    ) if auto_mode else f'Авторежим {status}.'
    await update.message.reply_text(msg)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return

    running = swiper_process and swiper_process.poll() is None
    elapsed = str(datetime.datetime.now() - session_start_time).split('.')[0] if session_start_time and running else '—'
    auto_str = 'вкл' if auto_mode else 'выкл'
    schedule_info = ', '.join(SCHEDULE_STARTS)

    if running:
        await update.message.reply_text(
            f'Статус: работает\n'
            f'Лайков: {like_count}\n'
            f'Время работы: {elapsed}\n'
            f'Авторежим: {auto_str} ({schedule_info})'
        )
    else:
        await update.message.reply_text(
            f'Статус: не запущен\n'
            f'Авторежим: {auto_str} ({schedule_info})'
        )


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать расписание следующих сеансов."""
    if not is_owner(update):
        return
    now = datetime.datetime.now()
    lines = []
    for s in SCHEDULE_STARTS:
        h, m = map(int, s.split(':'))
        t = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if t < now:
            t += datetime.timedelta(days=1)
        lines.append(f'  {s} — через {str(t - now).split(".")[0]}')
    await update.message.reply_text(
        f'Расписание (авторежим {"вкл" if auto_mode else "выкл"}):\n' + '\n'.join(lines) +
        f'\nДлительность: ~{SESSION_DURATION_MIN} мин ± {SESSION_JITTER_MIN} мин'
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    await update.message.reply_text(
        '/start — запустить свайпер вручную\n'
        '/stop — остановить\n'
        '/auto — вкл/выкл авторежим по расписанию\n'
        '/schedule — показать расписание\n'
        '/status — статистика\n'
        '/help — помощь'
    )


async def post_init(app):
    asyncio.create_task(scheduler_loop(app))


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('stop', cmd_stop))
    app.add_handler(CommandHandler('auto', cmd_auto))
    app.add_handler(CommandHandler('schedule', cmd_schedule))
    app.add_handler(CommandHandler('status', cmd_status))
    app.add_handler(CommandHandler('help', cmd_help))
    print('[*] Бот запущен...')
    app.run_polling()


if __name__ == '__main__':
    main()
