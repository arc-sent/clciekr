import re
import httpx

BASE = 'https://app.ashqua.ru'

def fetch_and_search():
    print('[*] Загружаю главную страницу...')
    r = httpx.get(BASE + '/', verify=False, timeout=30)
    html = r.text

    # Находим все JS файлы
    js_files = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', html)
    js_files += re.findall(r'"([^"]+\.js)"', html)
    js_files = list(set(js_files))

    print(f'[+] Найдено JS файлов: {len(js_files)}')

    keywords = ['like', 'react', 'vote', 'swipe', 'match', '/api/', 'fetch(', 'axios', 'post(']
    results = {}

    for js_path in js_files:
        url = js_path if js_path.startswith('http') else BASE + '/' + js_path.lstrip('/')
        try:
            print(f'[*] Скачиваю {url}')
            js = httpx.get(url, verify=False, timeout=30).text

            found = []
            for kw in keywords:
                if kw.lower() in js.lower():
                    # Находим контекст вокруг ключевого слова
                    for m in re.finditer(re.escape(kw), js, re.IGNORECASE):
                        start = max(0, m.start() - 80)
                        end = min(len(js), m.end() + 80)
                        snippet = js[start:end].replace('\n', ' ')
                        found.append(f'  [{kw}] ...{snippet}...')

            if found:
                results[url] = found
                print(f'  [+] Найдено совпадений: {len(found)}')

        except Exception as e:
            print(f'  [!] Ошибка: {e}')

    print('\n' + '='*60)
    print('РЕЗУЛЬТАТЫ:')
    print('='*60)

    for url, hits in results.items():
        print(f'\n[FILE] {url}')
        # Показываем только уникальные сниппеты с /api/ и похожие
        api_hits = [h for h in hits if '/api/' in h or 'fetch(' in h or 'post(' in h.lower()]
        shown = api_hits[:20] if api_hits else hits[:10]
        for h in shown:
            print(h)

if __name__ == '__main__':
    fetch_and_search()
