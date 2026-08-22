import asyncio
import json
import os
import random
import urllib.parse
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.functions.messages import RequestWebViewRequest
from playwright.async_api import async_playwright

load_dotenv()
API_ID = int(os.getenv('API_ID', 0))
API_HASH = os.getenv('API_HASH', '')

SWIPE_DELAY_MIN = 1.8   # минимальная пауза между лайками
SWIPE_DELAY_MAX = 3.2   # максимальная пауза
RESTART_EVERY = 60      # перезапускать браузер каждые N свайпов


async def get_webapp_url() -> str:
    async with TelegramClient('ashqua_session', API_ID, API_HASH) as client:
        bot = await client.get_entity('ashqua')
        result = await client(RequestWebViewRequest(
            peer=bot,
            bot=bot,
            platform='android',
            url='https://app.ashqua.ru/',
            from_bot_menu=False,
        ))
    return result.url


def parse_init_data(webapp_url: str):
    fragment = webapp_url.split('#')[1] if '#' in webapp_url else ''
    params = urllib.parse.parse_qs(fragment)
    raw = urllib.parse.unquote(params.get('tgWebAppData', [''])[0])

    parsed = {}
    for part in raw.split('&'):
        if '=' in part:
            k, v = part.split('=', 1)
            try:
                parsed[k] = json.loads(urllib.parse.unquote(v))
            except Exception:
                parsed[k] = urllib.parse.unquote(v)

    return raw, parsed


TG_INIT_SCRIPT = """
(initData, initDataUnsafe) => {
    window.Telegram = {
        WebApp: {
            initData: initData,
            initDataUnsafe: initDataUnsafe,
            version: '7.10',
            platform: 'android',
            colorScheme: 'light',
            themeParams: {
                bg_color: '#ffffff', text_color: '#000000',
                hint_color: '#999999', link_color: '#2481cc',
                button_color: '#2481cc', button_text_color: '#ffffff',
            },
            isExpanded: true,
            viewportHeight: 851, viewportStableHeight: 851,
            isClosingConfirmationEnabled: false,
            ready: () => {}, expand: () => {}, close: () => {},
            enableClosingConfirmation: () => {}, disableClosingConfirmation: () => {},
            onEvent: () => {}, offEvent: () => {},
            sendData: () => {},
            openLink: (url) => { window.open(url); },
            openTelegramLink: () => {},
            showAlert: (msg, cb) => { alert(msg); if(cb) cb(); },
            showConfirm: (msg, cb) => { if(cb) cb(true); },
            showPopup: (params, cb) => { if(cb) cb('ok'); },
            HapticFeedback: { impactOccurred: () => {}, notificationOccurred: () => {}, selectionChanged: () => {} },
            MainButton: {
                text: '', color: '#2481cc', textColor: '#ffffff',
                isVisible: false, isActive: true, isProgressVisible: false,
                show: () => {}, hide: () => {}, enable: () => {}, disable: () => {},
                showProgress: () => {}, hideProgress: () => {},
                onClick: () => {}, offClick: () => {}, setText: () => {}, setParams: () => {},
            },
            BackButton: { isVisible: false, show: () => {}, hide: () => {}, onClick: () => {}, offClick: () => {} },
            SettingsButton: { isVisible: false, show: () => {}, hide: () => {}, onClick: () => {}, offClick: () => {} },
        }
    };
    window.TelegramWebviewProxy = { postEvent: () => {} };
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
}
"""


async def _open_page(playwright, webapp_url: str, init_data: str, init_data_unsafe: dict):
    """Открывает браузер, инжектирует TG WebApp и возвращает (browser, page)."""
    pixel5 = playwright.devices['Pixel 5']
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            '--ignore-certificate-errors',
            '--disable-web-security',
            '--allow-insecure-localhost',
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-blink-features=AutomationControlled',
        ]
    )
    context = await browser.new_context(
        **pixel5,
        ignore_https_errors=True,
        extra_http_headers={'Accept-Language': 'ru-RU,ru;q=0.9'},
    )
    init_data_json = json.dumps(init_data)
    init_data_unsafe_json = json.dumps(init_data_unsafe)
    await context.add_init_script(f"({TG_INIT_SCRIPT})({init_data_json}, {init_data_unsafe_json})")

    page = await context.new_page()

    async def on_response(response):
        url = response.url
        if 'reaction/like' in url or 'reaction/dislike' in url:
            try:
                body = await response.json()
                action = 'LIKE' if 'like' in url else 'DISLIKE'
                err = body.get('e')
                status = 'OK' if not err else f'ERR:{err.get("code", err)}'
                import datetime as _dt
                ts = _dt.datetime.now().strftime('%H:%M:%S')
                print(f'  [{ts}] API {action} → {status}')
            except Exception:
                pass

    page.on('response', on_response)

    print('[*] Открываю приложение...')
    await page.goto(webapp_url, wait_until='commit', timeout=60000)
    await page.wait_for_timeout(6000)
    return browser, page


async def _do_swipe(page):
    """Двойной тап + свайп через touch-события."""
    vp = page.viewport_size or {'width': 393, 'height': 851}
    tap_x = vp['width'] // 2
    tap_y = vp['height'] // 3

    # двойной тап — лайк
    await page.touchscreen.tap(tap_x, tap_y)
    await asyncio.sleep(0.12 + random.uniform(0, 0.08))
    await page.touchscreen.tap(tap_x, tap_y)
    await asyncio.sleep(0.4 + random.uniform(0, 0.2))

    # свайп вверх через touch (не mouse) — чтобы сайт воспринял как мобильный жест
    swipe_start_y = int(vp['height'] * 0.72)
    swipe_end_y   = int(vp['height'] * 0.18)
    await page.touchscreen.tap(tap_x, swipe_start_y)  # начало касания

    # эмулируем drag через dispatchEvent
    await page.evaluate(f"""() => {{
        const el = document.elementFromPoint({tap_x}, {swipe_start_y});
        const target = el || document.body;
        const t = (y) => new Touch({{identifier: 1, target, clientX: {tap_x}, clientY: y, radiusX: 5, radiusY: 5}});
        target.dispatchEvent(new TouchEvent('touchstart', {{touches: [t({swipe_start_y})], changedTouches: [t({swipe_start_y})], bubbles: true}}));
        const steps = 12;
        for (let i = 1; i <= steps; i++) {{
            const y = Math.round({swipe_start_y} + ({swipe_end_y} - {swipe_start_y}) * i / steps);
            target.dispatchEvent(new TouchEvent('touchmove', {{touches: [t(y)], changedTouches: [t(y)], bubbles: true}}));
        }}
        target.dispatchEvent(new TouchEvent('touchend', {{touches: [], changedTouches: [t({swipe_end_y})], bubbles: true}}));
    }}""")


async def auto_like(webapp_url: str):
    import datetime
    init_data, init_data_unsafe = parse_init_data(webapp_url)

    count = 0
    errors = 0
    start_time = datetime.datetime.now()
    print('\n[*] Начинаю автолайк. Ctrl+C для остановки.\n')

    async with async_playwright() as p:
        browser, page = await _open_page(p, webapp_url, init_data, init_data_unsafe)

        try:
            while True:
                # Периодически перезапускаем браузер чтобы не накапливать память
                if count > 0 and count % RESTART_EVERY == 0:
                    print(f'[*] Перезапуск браузера после {count} свайпов...')
                    await browser.close()
                    await asyncio.sleep(2)
                    browser, page = await _open_page(p, webapp_url, init_data, init_data_unsafe)

                try:
                    name = await page.evaluate('''() => {
                        for (const s of ['[class*="name"]','[class*="title"]','h1','h2','h3']) {
                            const el = document.querySelector(s);
                            if (el && el.innerText?.trim()) return el.innerText.trim().slice(0, 30);
                        }
                        return null;
                    }''')

                    await _do_swipe(page)

                    count += 1
                    ts = datetime.datetime.now().strftime('%H:%M:%S')
                    elapsed = str(datetime.datetime.now() - start_time).split('.')[0]
                    label = f'"{name}"' if name else '(имя не найдено)'
                    print(f'[{ts}] #{count:>4} | tap → {label} | всего: {count} лайков | время: {elapsed}')

                    delay = random.uniform(SWIPE_DELAY_MIN, SWIPE_DELAY_MAX)
                    await asyncio.sleep(delay)

                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    errors += 1
                    print(f'[!] Ошибка #{errors}: {e}')
                    await asyncio.sleep(3)
                    if errors % 5 == 0:
                        # При серии ошибок — перезагружаем страницу
                        print('[*] Серия ошибок, перезагружаю страницу...')
                        try:
                            await page.reload(wait_until='commit', timeout=30000)
                            await page.wait_for_timeout(4000)
                        except Exception:
                            pass

        except KeyboardInterrupt:
            pass
        finally:
            elapsed = str(datetime.datetime.now() - start_time).split('.')[0]
            print(f'\n{"="*50}')
            print(f'Остановлено.')
            print(f'Лайков поставлено: {count}')
            print(f'Время работы:      {elapsed}')
            print(f'{"="*50}')
            await browser.close()


async def main():
    print('[*] Получаю ссылку на WebApp...')
    webapp_url = await get_webapp_url()
    print('[+] URL получен')

    await auto_like(webapp_url)


if __name__ == '__main__':
    asyncio.run(main())
