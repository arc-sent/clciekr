import re
import httpx

url = 'https://app.ashqua.ru/assets/index-B0ObqME8.js'
print('[*] Скачиваю...')
js = httpx.get(url, verify=False, timeout=60).text

# Ищем функцию Nc (POST) и Mc (GET) — там должен быть baseURL и заголовки
print('\n[+] Контекст вокруг "Nc(" и "Mc(":')
for m in re.finditer(r'\bNc\b', js):
    start = max(0, m.start() - 200)
    end = min(len(js), m.end() + 200)
    snippet = js[start:end].replace('\n', ' ')
    if 'function' in snippet or 'const' in snippet or '=>' in snippet:
        print(f'  ...{snippet}...\n')
    if js[start:end].count('Nc') > 3:
        break

# Ищем baseURL / fetch с https
print('\n[+] Строки с https://api или /api:')
for m in re.finditer(r'["\`](https://[a-zA-Z0-9._/-]+)["\`]', js):
    v = m.group(1)
    if 'ashqua' in v or 'api' in v.lower():
        start = max(0, m.start() - 60)
        end = min(len(js), m.end() + 60)
        print(f'  {js[start:end].replace(chr(10), " ")}')

# Ищем Authorization / Bearer / token
print('\n[+] Заголовки авторизации:')
for m in re.finditer(r'(Authorization|Bearer|[Tt]oken|[Hh]eader)', js):
    start = max(0, m.start() - 100)
    end = min(len(js), m.end() + 100)
    snippet = js[start:end].replace('\n', ' ')
    if any(w in snippet for w in ['fetch', 'header', 'axios', 'request']):
        print(f'  ...{snippet}...\n')

# Ищем feed endpoint
print('\n[+] Контекст вокруг "feed":')
for m in re.finditer(r'["\`]feed["\`/]', js):
    start = max(0, m.start() - 80)
    end = min(len(js), m.end() + 80)
    print(f'  ...{js[start:end].replace(chr(10), " ")}...')
