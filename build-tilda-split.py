#!/usr/bin/env python3
"""
Сборка блоков T123 для walk-walk.ru/antiotek («Антиотёчность»).

Tilda T123 — лимит ~30 000 символов на блок. Кириллица в T123 часто рендерится
как mojibake → вся не-ASCII кодируется в HTML-сущности &#NNNN; (раздувает ~1.85×).
Поэтому HTML режется на несколько блоков. CSS/JS — внешние ссылки на GitHub Pages.
assets/ → абсолютные URL на CDN.

Блоки:
- Блок 1: head-хинты + топбар + шапка + меню + hero + «Знакомо?» + «Как устроена неделя»
- Блок 2: «Что вас ждёт» + «Разборы» + результат + баннер тарифов + тарифы
- Блок 3: кейсы + помощь + футер + sticky-cta + back-to-top + <script>
"""
import re
from pathlib import Path

BASE = Path(__file__).parent
CDN = "https://npopko55-cmd.github.io/antiotek"
VER = "anti-Z5"

html = (BASE / "index.html").read_text(encoding="utf-8")
body = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL).group(1)

# 1. Комментарии прочь, assets → CDN
body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
body = re.sub(r'(href|src)="(assets/[^"]+)"', lambda m: f'{m.group(1)}="{CDN}/{m.group(2)}"', body)
# srcset/imagesrcset — список «путь дескриптор, путь дескриптор». Нужно
# отдельное правило: общий regex выше ловит только одиночный путь в кавычках.
# Пропустишь — браузер возьмёт srcset (он приоритетнее src), упрётся в
# относительный путь и картинка не отрисуется вообще. Ровно так и вышло с
# фото первого экрана: в блоке Тильды оставалась пустая рамка с alt-текстом.
def _abs_srcset(m):
    attr, val = m.group(1), m.group(2)
    parts = []
    for item in val.split(','):
        item = item.strip()
        if not item:
            continue
        bits = item.split(None, 1)
        url = bits[0]
        rest = (' ' + bits[1]) if len(bits) > 1 else ''
        if url.startswith('assets/'):
            url = f'{CDN}/{url}'
        parts.append(url + rest)
    return f'{attr}="' + ', '.join(parts) + '"'


body = re.sub(r'(srcset|imagesrcset)="([^"]+)"', _abs_srcset, body)
body = re.sub(r"url\((['\"])(assets/[^'\")]+)\1\)", lambda m: f"url({m.group(1)}{CDN}/{m.group(2)}{m.group(1)})", body)
body = re.sub(r"url\((assets/[^'\")]+)\)", lambda m: f"url({CDN}/{m.group(1)})", body)

# 2. Границы секций (RAW, до encoding)
def pos(patt):
    m = re.search(patt, body)
    if not m:
        raise SystemExit(f"Не нашёл: {patt}")
    return m.start()

# Порядок секций (как в прототипе Miro):
# hero → боли → специалисты(+видео) → что внутри → кейсы → тарифы → результат → помощь
p_rev    = pos(r'<section[^>]*id="reviews"')
p_inside = pos(r'<section[^>]*id="inside"')
p_banner = pos(r'<section[^>]*class="rates-banner"')
p_cases  = pos(r'<section[^>]*id="cases"')

part_a  = body[:p_rev]              # топбар+шапка+меню+hero+«через 7 дней»
part_b1 = body[p_rev:p_inside]      # отзывы + специалисты + 2100+
part_b2 = body[p_inside:p_banner]   # что внутри + фейс-фитнес и тейпы
part_b3 = body[p_banner:p_cases]    # баннер + тарифы
tail    = body[p_cases:]            # кейсы + развилка + финал + помощь + футер

# 3. Анти-mojibake: не-ASCII → &#NNNN;
def to_entities(text):
    return "".join(c if ord(c) < 128 else f"&#{ord(c)};" for c in text)

part_a, part_b1, part_b2, part_b3, tail = map(
    to_entities, (part_a, part_b1, part_b2, part_b3, tail))

# 4. Head-хинты (шрифты как в index.html antiotek: Unbounded + Inter)
HEAD_HINTS = f"""<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link rel="preconnect" href="https://npopko55-cmd.github.io" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Unbounded:wght@500;600&family=Inter:wght@400;500;600&display=swap&subset=latin,cyrillic" rel="stylesheet" />
<link rel="preload" as="image" href="{CDN}/assets/hero/hero-antiotek-760.webp" fetchpriority="high"
      imagesrcset="{CDN}/assets/hero/hero-antiotek-760.webp 560w, {CDN}/assets/hero/hero-antiotek.webp 820w"
      imagesizes="(max-width: 900px) 92vw, 42vw" />
<link rel="stylesheet" href="{CDN}/styles.css?v={VER}" />
"""
TAIL_SCRIPT = f'\n<script src="{CDN}/script.js?v={VER}"></script>\n'

block1 = HEAD_HINTS + "\n" + part_a + "\n"
block2 = part_b1
block3 = part_b2
block4 = part_b3
block5 = tail + TAIL_SCRIPT

(BASE / "tilda-block-1.html").write_text(block1, encoding="utf-8")
(BASE / "tilda-block-2.html").write_text(block2, encoding="utf-8")
(BASE / "tilda-block-3.html").write_text(block3, encoding="utf-8")
(BASE / "tilda-block-4.html").write_text(block4, encoding="utf-8")
(BASE / "tilda-block-5.html").write_text(block5, encoding="utf-8")

def sz(s):
    n = len(s)
    ok = "OK помещается" if n < 30000 else "!! ПРЕВЫШЕН ЛИМИТ 30000"
    return f"{n:,} chars ({n/1024:.1f} KB)  {ok}"

print("Готово")
print(f"  tilda-block-1.html: {sz(block1)}  — стили+топбар+шапка+hero+через 7 дней")
print(f"  tilda-block-2.html: {sz(block2)}  — отзывы+специалисты")
print(f"  tilda-block-3.html: {sz(block3)}  — что внутри+фейс-фитнес и тейпы")
print(f"  tilda-block-4.html: {sz(block4)}  — баннер+тарифы")
print(f"  tilda-block-5.html: {sz(block5)}  — кейсы+развилка+финал+помощь+футер+скрипт")
print(f"  Лимит T123: 30 000 chars / блок. CSS/JS — с {CDN}")
