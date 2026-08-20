import asyncio
import os
import urllib.parse
from dotenv import load_dotenv
import httpx
from telethon import TelegramClient
from telethon.tl.functions.messages import RequestWebViewRequest

load_dotenv()
API_ID = int(os.getenv('API_ID', 0))
API_HASH = os.getenv('API_HASH', '')

BASE_API = 'https://api.ashqua.ru'
SWIPE_DELAY = 2.0  # секунд между лайками


async def get_init_data() -> str:
    async with TelegramClient('ashqua_session', API_ID, API_HASH) as client:
        bot = await client.get_entity('ashqua')
        result = await client(RequestWebViewRequest(
            peer=bot,
            bot=bot,
            platform='android',
            url='https://app.ashqua.ru/',
            from_bot_menu=False,
        ))
    fragment = result.url.split('#')[1] if '#' in result.url else ''
    params = urllib.parse.parse_qs(fragment)
    raw = params.get('tgWebAppData', [''])[0]
    return urllib.parse.unquote(raw)


def make_client(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=BASE_API,
        headers={
            'content-type': 'application/json',
            'authorization': token,
        },
        timeout=15,
    )


async def auth(init_data: str) -> dict:
    async with httpx.AsyncClient(base_url=BASE_API, timeout=15) as client:
        # Создаём сессию
        r = await client.post('/auth/session', json={})
        print(f'[DEBUG] session: {r.status_code} {r.text[:300]}')
        r.raise_for_status()
        sid = r.json().get('d', {}).get('sid', '')

        # Авторизуемся через Telegram initData
        r2 = await client.get(
            '/auth/telegram',
            headers={'x-telegram': init_data, 'x-session': sid},
        )
        print(f'[DEBUG] auth/telegram: {r2.status_code} {r2.text[:300]}')
        r2.raise_for_status()
        data = r2.json().get('d', {})
        return data


async def get_feed(client: httpx.AsyncClient, exclude: list) -> list:
    r = await client.post('/feed', json={'exclude': exclude[-24:]})
    r.raise_for_status()
    return r.json().get('d', [])


async def like(client: httpx.AsyncClient, target_id: str):
    r = await client.post('/reaction/like', json={'target': target_id})
    r.raise_for_status()
    data = r.json()
    if data.get('e'):
        code = data['e'].get('code', '')
        if code == 'REACTION_LIMIT':
            retry = data['e'].get('payload', {}).get('retryAfter', 60)
            print(f'[!] Лимит лайков! Жду {retry} сек...')
            await asyncio.sleep(retry)
            return None
        if code == 'RATE_LIMIT':
            retry = data['e'].get('payload', {}).get('retryAfter', 30)
            print(f'[!] Rate limit! Жду {retry} сек...')
            await asyncio.sleep(retry)
            return None
        print(f'[!] Ошибка: {data["e"]}')
        return None
    # .next = следующий пользователь (может быть None)
    return data.get('d', {}).get('next')


async def main():
    print('[*] Получаю initData через Telegram...')
    init_data = await get_init_data()
    print('[+] initData получен')

    print('[*] Авторизуюсь в ashqua API...')
    auth_data = await auth(init_data)
    print(f'[DEBUG] auth ответ: {auth_data}')
    if not auth_data:
        print('[!] auth вернул None — смотри DEBUG выше')
        return
    token = auth_data.get('token') or auth_data.get('accessToken')
    if not token:
        print(f'[!] Не удалось получить токен. Ответ: {auth_data}')
        return
    print(f'[+] Авторизован! Токен: {token[:20]}...')

    seen = []
    count = 0

    async with make_client(token) as client:
        print('\n[*] Начинаю автолайк. Ctrl+C для остановки.\n')
        while True:
            # Получаем пачку анкет
            feed = await get_feed(client, seen)
            if not feed:
                print('[!] Лента пуста, жду 30 сек...')
                await asyncio.sleep(30)
                seen = []
                continue

            for profile in feed:
                uid = profile.get('id') or profile.get('userId') or profile.get('target')
                if not uid or uid in seen:
                    continue

                seen.append(uid)
                result = await like(client, uid)
                count += 1
                name = profile.get('name') or profile.get('firstName') or uid
                print(f'[+] Лайк #{count} → {name} (id: {uid})')

                await asyncio.sleep(SWIPE_DELAY)


if __name__ == '__main__':
    asyncio.run(main())
