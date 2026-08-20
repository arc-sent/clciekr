import asyncio
import json
import os
import urllib.parse
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.functions.messages import RequestWebViewRequest
from playwright.async_api import async_playwright

load_dotenv()
API_ID = int(os.getenv('API_ID', 0))
API_HASH = os.getenv('API_HASH', '')

SWIPE_DELAY = 2.0  # секунд между лайками


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


def parse_init_data(webapp_url: str) -> tuple[str, dict]:
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


async def auto_like(webapp_url: str):
    init_data, init_data_unsafe = parse_init_data(webapp_url)

    async with async_playwright() as p:
        # Эмулируем Pixel 5 с тач-экраном
        pixel5 = p.devices['Pixel 5']

        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--ignore-certificate-errors',
                '--disable-web-security',
                '--allow-insecure-localhost',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
            ]
        )

        context = await browser.new_context(
            **pixel5,
            ignore_https_errors=True,
        )

        page = await context.new_page()

        # Инжектируем Telegram.WebApp до загрузки страницы
        await page.add_init_script(f"""
            const initData = {json.dumps(init_data)};
            const initDataUnsafe = {json.dumps(init_data_unsafe)};

            window.Telegram = {{
                WebApp: {{
                    initData: initData,
                    initDataUnsafe: initDataUnsafe,
                    version: '7.10',
                    platform: 'android',
                    colorScheme: 'light',
                    themeParams: {{
                        bg_color: '#ffffff',
                        text_color: '#000000',
                        hint_color: '#999999',
                        link_color: '#2481cc',
                        button_color: '#2481cc',
                        button_text_color: '#ffffff',
                    }},
                    isExpanded: true,
                    viewportHeight: 851,
                    viewportStableHeight: 851,
                    isClosingConfirmationEnabled: false,
                    ready: () => {{ console.log('[TG] ready'); }},
                    expand: () => {{}},
                    close: () => {{}},
                    enableClosingConfirmation: () => {{}},
                    disableClosingConfirmation: () => {{}},
                    onEvent: (e, cb) => {{}},
                    offEvent: (e, cb) => {{}},
                    sendData: (data) => {{}},
                    openLink: (url) => {{ window.open(url); }},
                    openTelegramLink: (url) => {{}},
                    showAlert: (msg, cb) => {{ alert(msg); if(cb) cb(); }},
                    showConfirm: (msg, cb) => {{ if(cb) cb(true); }},
                    showPopup: (params, cb) => {{ if(cb) cb('ok'); }},
                    HapticFeedback: {{
                        impactOccurred: () => {{}},
                        notificationOccurred: () => {{}},
                        selectionChanged: () => {{}},
                    }},
                    MainButton: {{
                        text: '', color: '#2481cc', textColor: '#ffffff',
                        isVisible: false, isActive: true, isProgressVisible: false,
                        show: () => {{}}, hide: () => {{}},
                        enable: () => {{}}, disable: () => {{}},
                        showProgress: () => {{}}, hideProgress: () => {{}},
                        onClick: (cb) => {{}}, offClick: (cb) => {{}},
                        setText: (t) => {{}}, setParams: (p) => {{}},
                    }},
                    BackButton: {{
                        isVisible: false,
                        show: () => {{}}, hide: () => {{}},
                        onClick: (cb) => {{}}, offClick: (cb) => {{}},
                    }},
                    SettingsButton: {{
                        isVisible: false,
                        show: () => {{}}, hide: () => {{}},
                        onClick: (cb) => {{}}, offClick: (cb) => {{}},
                    }},
                }}
            }};

            // Блокируем попытки открыть внешние ссылки
            window.TelegramWebviewProxy = {{
                postEvent: (name, data) => {{ console.log('[TG proxy]', name, data); }}
            }};
        """)

        # Перехватываем ответы API для логирования
        like_log = []

        async def on_response(response):
            url = response.url
            if 'reaction/like' in url or 'reaction/dislike' in url or 'feed' in url:
                try:
                    body = await response.json()
                    action = 'like' if 'like' in url else 'dislike' if 'dislike' in url else 'feed'
                    if action in ('like', 'dislike'):
                        err = body.get('e')
                        nxt = body.get('d', {}).get('next') if body.get('d') else None
                        status = 'OK' if not err else f'ERR:{err.get("code", err)}'
                        like_log.append({'action': action, 'status': status, 'next': nxt})
                        ts = __import__('datetime').datetime.now().strftime('%H:%M:%S')
                        print(f'  [{ts}] API {action.upper()} → {status}' + (f' | next: {nxt}' if nxt else ''))
                except Exception:
                    pass

        page.on('response', on_response)

        print('[*] Открываю приложение...')
        await page.goto(webapp_url, wait_until='domcontentloaded', timeout=60000)
        await page.wait_for_timeout(4000)

        print('[*] Ищу карточку профиля...')
        print('[!] Если видишь экран авторизации — подожди 5-10 сек, приложение загружается')
        await page.wait_for_timeout(3000)

        count = 0
        errors = 0
        import datetime
        start_time = datetime.datetime.now()
        print('\n[*] Начинаю автолайк. Ctrl+C для остановки.\n')

        while True:
            try:
                # Тапаем по центру экрана (где находится фото профиля)
                vp = page.viewport_size or {'width': 393, 'height': 851}
                tap_x = vp['width'] // 2
                tap_y = vp['height'] // 3  # верхняя треть — зона фото

                # Пытаемся вытащить имя профиля из DOM
                name = await page.evaluate('''() => {
                    const selectors = [
                        '[class*="name"]', '[class*="title"]',
                        'h1', 'h2', 'h3',
                    ];
                    for (const s of selectors) {
                        const el = document.querySelector(s);
                        if (el && el.innerText?.trim()) return el.innerText.trim().slice(0, 30);
                    }
                    return null;
                }''')

                ts = datetime.datetime.now().strftime('%H:%M:%S')
                elapsed = str(datetime.datetime.now() - start_time).split('.')[0]
                label = f'"{name}"' if name else '(имя не найдено)'

                # Двойной тап — лайк
                await page.touchscreen.tap(tap_x, tap_y)
                await asyncio.sleep(0.15)
                await page.touchscreen.tap(tap_x, tap_y)
                await asyncio.sleep(0.5)

                # Свайп вверх через PointerEvent (используется в ashqua)
                swipe_start_y = int(vp['height'] * 0.7)
                swipe_end_y   = int(vp['height'] * 0.2)
                await page.mouse.move(tap_x, swipe_start_y)
                await page.mouse.down()
                await asyncio.sleep(0.05)
                steps = 40
                for i in range(1, steps + 1):
                    y = swipe_start_y + (swipe_end_y - swipe_start_y) * i // steps
                    await page.mouse.move(tap_x, y)
                    await asyncio.sleep(0.03)
                await page.mouse.up()

                count += 1
                print(f'[{ts}] #{count:>4} | tap → {label} | всего: {count} лайков | время: {elapsed}')

                await asyncio.sleep(SWIPE_DELAY)

            except KeyboardInterrupt:
                elapsed = str(datetime.datetime.now() - start_time).split('.')[0]
                print(f'\n{"="*50}')
                print(f'Остановлено.')
                print(f'Лайков поставлено: {count}')
                print(f'Время работы:      {elapsed}')
                print(f'{"="*50}')
                break
            except Exception as e:
                errors += 1
                print(f'[!] Ошибка #{errors}: {e}')
                await asyncio.sleep(2)

        await browser.close()


async def main():
    print('[*] Получаю ссылку на WebApp...')
    webapp_url = await get_webapp_url()
    print('[+] URL получен')

    await auto_like(webapp_url)


if __name__ == '__main__':
    asyncio.run(main())
