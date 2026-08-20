import re
import httpx

url = 'https://app.ashqua.ru/assets/index-B0ObqME8.js'

print('[*] Скачиваю index-B0ObqME8.js...')
js = httpx.get(url, verify=False, timeout=60).text
print(f'[+] Размер: {len(js)} байт')

# Ищем все строки похожие на API пути
api_paths = re.findall(r'["\`](/[a-zA-Z0-9/_\-]{3,50})["\`]', js)
api_paths = sorted(set(p for p in api_paths if any(w in p.lower() for w in [
    'react', 'like', 'vote', 'swipe', 'match', 'user', 'profile', 'api'
])))

print('\n[+] API пути найденные в коде:')
for p in api_paths:
    print(f'  {p}')

# Ищем контекст вокруг reaction/like
print('\n[+] Контекст вокруг "reaction":')
for m in re.finditer(r'reaction', js, re.IGNORECASE):
    start = max(0, m.start() - 120)
    end = min(len(js), m.end() + 120)
    snippet = js[start:end].replace('\n', ' ')
    print(f'  ...{snippet}...\n')

# Ищем базовый URL API
print('\n[+] Поиск baseURL / base URL:')
for m in re.finditer(r'(baseURL|baseUrl|base_url|API_URL|apiUrl)\s*[=:]\s*["\`]([^"\'`]+)["\`]', js):
    print(f'  {m.group(0)}')
