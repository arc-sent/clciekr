import asyncio
import os
import signal
import subprocess
import random
import datetime
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.error import NetworkError
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
OWNER_ID = int(os.getenv('OWNER_ID', 0))
DEBUG = os.getenv('DEBUG', '0') == '1'

SCHEDULE_STARTS = [s.strip() for s in os.getenv('SCHEDULE', '10:00,15:00,20:00').split(',')]
SESSION_DURATION_MIN = int(os.getenv('SESSION_DURATION', '150'))
SESSION_JITTER_MIN = int(os.getenv('SESSION_JITTER', '15'))

SWIPER_DIR = os.path.dirname(os.path.abspath(__file__))
SWIPER_PID_FILE = os.path.join(SWIPER_DIR, 'swiper.pid')
SWIPER_LOG_FILE = os.path.join(SWIPER_DIR, 'swiper.log')

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
for _noisy in ('httpcore', 'httpx', 'telegram', 'asyncio'):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def dbg(msg: str):
    if DEBUG:
        print(f'[DBG] {msg}')


session_start_time: datetime.datetime | None = None
like_count = 0
auto_mode = False
_stopping = False  # флаг намеренной остановки


def swiper_pid() -> int | None:
    """Возвращает PID свайпера если он живой, иначе None."""
    try:
        pid = int(open(SWIPER_PID_FILE).read().strip())
        os.kill(pid, 0)  # проверка: процесс существует
        return pid
    except Exception:
        return None


def is_running() -> bool:
    return swiper_pid() is not None


def is_owner(update: Update) -> bool:
    return update.effective_user.id == OWNER_ID


async def start_swiper(context, notify=True):
    global session_start_time, like_count, _stopping

    if is_running():
        dbg('свайпер уже запущен')
        return False

    _stopping = False
    like_count = 0
    session_start_time = datetime.datetime.now()

    log_f = open(SWIPER_LOG_FILE, 'w')
    proc = subprocess.Popen(
        ['python3', 'ashqua_swiper.py'],
        stdout=log_f,
        stderr=log_f,
        start_new_session=True,   # отвязываем от группы процессов бота
        cwd=SWIPER_DIR,
    )
    log_f.close()  # родителю fd не нужен, дочерний процесс держит свой

    with open(SWIPER_PID_FILE, 'w') as f:
        f.write(str(proc.pid))

    dbg(f'свайпер запущен, pid={proc.pid}')
    asyncio.create_task(monitor_output(context))

    if notify:
        await context.bot.send_message(chat_id=OWNER_ID, text='Свайпер запущен.')
    return True


async def stop_swiper(context, notify=True, reason=''):
    global _stopping

    pid = swiper_pid()
    if not pid:
        dbg('свайпер не запущен')
        return False

    _stopping = True  # сначала флаг, потом убиваем — monitor не пошлёт "упал"

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        os.remove(SWIPER_PID_FILE)
    except FileNotFoundError:
        pass

    dbg(f'свайпер остановлен (pid={pid})')

    if notify:
        msg = f'Свайпер остановлен. {reason}\nЛайков за сеанс: {like_count}'
        await context.bot.send_message(chat_id=OWNER_ID, text=msg)
    return True


async def monitor_output(context):
    """Читает swiper.log и считает лайки. Независим от жизни процесса."""
    global like_count
    log_pos = 0

    while True:
        await asyncio.sleep(1)

        try:
            with open(SWIPER_LOG_FILE) as f:
                f.seek(log_pos)
                lines = f.readlines()
                log_pos = f.tell()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                dbg(f'свайпер: {line}')
                if '| tap →' in line:
                    like_count += 1
                    dbg(f'лайк засчитан, всего={like_count}')
                if '[!]' in line or 'Ошибка' in line:
                    await context.bot.send_message(
                        chat_id=OWNER_ID,
                        text=f'Предупреждение: {line}',
                    )
        except FileNotFoundError:
            pass

        if not is_running():
            break

    # Свайпер завершился — упал или был остановлен намеренно?
    if not _stopping:
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text='Свайпер завершился неожиданно. Используй /start для перезапуска.',
        )
        try:
            os.remove(SWIPER_PID_FILE)
        except FileNotFoundError:
            pass


async def scheduler_loop(context):
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
                        text=f'Авто-сеанс {start_str} — длительность {duration} мин.',
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

    running = is_running()
    elapsed = (
        str(datetime.datetime.now() - session_start_time).split('.')[0]
        if session_start_time and running else '—'
    )
    auto_str = 'вкл' if auto_mode else 'выкл'
    schedule_info = ', '.join(SCHEDULE_STARTS)
    pid = swiper_pid()

    if running:
        await update.message.reply_text(
            f'Статус: работает (pid={pid})\n'
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


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, NetworkError):
        dbg(f'сетевая ошибка (автоповтор): {context.error}')
        return
    logging.getLogger(__name__).error('Unhandled exception', exc_info=context.error)


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
    app.add_error_handler(error_handler)
    print('[*] Бот запущен...')
    app.run_polling()


if __name__ == '__main__':
    main()
