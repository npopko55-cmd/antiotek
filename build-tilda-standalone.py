#!/usr/bin/env python3
"""
Сборка блоков T123 БЕЗ внешнего хостинга — стили и скрипт едут внутрь Тильды.

Зачем: у части российских провайдеров и мобильных операторов GitHub Pages
не открывается или отвечает по несколько секунд. Тогда страница на Тильде
показывается без стилей — «рассыпается», как и пожаловались участницы.
Здесь CSS и JS вставляются прямо в блоки, поэтому вёрстка не зависит ни от
какого внешнего домена.

Картинки остаются на CDN, пока их не загрузят в Тильду. Как загрузят —
вписать адреса в tilda-assets.json (ключ = путь вида assets/hero/x.webp),
и они подставятся автоматически.

Порядок вставки на странице: сначала СТИЛИ, потом блоки разметки,
СКРИПТ — последним.
"""
import json
import re
from pathlib import Path

BASE = Path(__file__).parent
LIMIT = 30000
CDN = "https://npopko55-cmd.github.io/antiotek"
OUT = BASE / "tilda-standalone"
OUT.mkdir(exist_ok=True)

html = (BASE / "index.html").read_text(encoding="utf-8")
css = (BASE / "styles.css").read_text(encoding="utf-8")
js = (BASE / "script.js").read_text(encoding="utf-8")

FONT_LINK = re.search(r'<link[^>]+fonts\.googleapis\.com/css2[^>]*>', html).group(0)


# ---------- 1. Какие классы реально используются ------------------------
used = set()
for chunk in re.findall(r'class="([^"]+)"', html):
    used.update(chunk.split())
used |= set(re.findall(r"classList\.(?:add|toggle|remove)\('([\w-]+)'", js))
used |= set(re.findall(r"querySelector(?:All)?\('\.([\w-]+)", js))


def rule_is_alive(selector):
    """Правило нужно, если хотя бы один его класс есть в разметке.
    Селекторы без классов (body, h2, :root, @-правила) не трогаем."""
    classes = re.findall(r'\.([a-z][\w-]*)', selector)
    if not classes:
        return True
    return any(c in used for c in classes)


def parse_blocks(text):
    """Разбираем CSS на верхнеуровневые куски, считая скобки вручную.
    Регулярками медиа-блоки не режутся надёжно: у них вложенность, и на
    первой же попытке я потерял четыре закрывающие скобки — стили в блоках
    Тильды приехали бы битыми."""
    out, i, n = [], 0, len(text)
    while i < n:
        brace = text.find('{', i)
        if brace == -1:
            tail = text[i:].strip()
            if tail:
                out.append(('raw', tail))
            break
        prelude = text[i:brace]
        # где начинается сам селектор: после предыдущей } или ;
        sep = max(prelude.rfind('}'), prelude.rfind(';'))
        head = prelude[sep + 1:].strip()
        # закрывающая скобка этого блока
        depth, j = 1, brace + 1
        while j < n and depth:
            if text[j] == '{':
                depth += 1
            elif text[j] == '}':
                depth -= 1
            j += 1
        inner = text[brace + 1:j - 1]
        out.append(('at' if head.startswith('@') else 'rule', head, inner))
        i = j
    return out


def keep_selectors(head):
    """Оставляем только те части списка селекторов, чьи классы есть в разметке."""
    kept = [part.strip() for part in head.split(',') if rule_is_alive(part)]
    return ',\n'.join(kept) if kept else None


def clean_css(text):
    # Комментарии убираем ДО разбора: внутри них попадаются скобки и точки с
    # запятой, парсер принимал их за границы правил и терял :root вместе со
    # всеми переменными — цвета и радиусы переставали разрешаться.
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
    pieces = []
    for block in parse_blocks(text):
        kind = block[0]
        if kind == 'raw':
            pieces.append(block[1])
        elif kind == 'at':
            head, inner = block[1], block[2]
            # @media / @supports — внутри снова правила; @font-face и прочее оставляем
            if re.match(r'@(media|supports|container)', head):
                nested = []
                for sub in parse_blocks(inner):
                    if sub[0] == 'rule':
                        sel = keep_selectors(sub[1])
                        if sel:
                            nested.append(sel + '{' + sub[2] + '}')
                    elif sub[0] == 'raw':
                        nested.append(sub[1])
                    else:
                        nested.append(sub[1] + '{' + sub[2] + '}')
                body_inner = '\n'.join(nested).strip()
                if body_inner:
                    pieces.append(head + '{' + body_inner + '}')
            else:
                pieces.append(head + '{' + inner + '}')
        else:
            sel = keep_selectors(block[1])
            if sel:
                pieces.append(sel + '{' + block[2] + '}')

    s = '\n'.join(pieces)
    s = re.sub(r'/\*.*?\*/', '', s, flags=re.DOTALL)
    s = re.sub(r'\s*\n\s*', '\n', s)
    s = re.sub(r'[ \t]{2,}', ' ', s)
    s = re.sub(r'\s*([{};:,>])\s*', r'\1', s)
    s = re.sub(r';\}', '}', s)
    s = re.sub(r'\n{2,}', '\n', s)
    return s.strip()


css_min = clean_css(css)
print(f"CSS: {len(css)/1024:.1f} КБ -> {len(css_min)/1024:.1f} КБ (мусор от базового лендинга вычищен)")


# ---------- 2. Адреса картинок -----------------------------------------
asset_map = {}
map_file = BASE / "tilda-assets.json"
if map_file.exists():
    asset_map = json.loads(map_file.read_text(encoding="utf-8"))

body = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL).group(1)
body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)


def sub_single(m):
    attr, path = m.group(1), m.group(2)
    return f'{attr}="{asset_map.get(path, CDN + "/" + path)}"'


def sub_set(m):
    attr, val = m.group(1), m.group(2)
    out = []
    for item in val.split(","):
        item = item.strip()
        if not item:
            continue
        bits = item.split(None, 1)
        url = asset_map.get(bits[0], CDN + "/" + bits[0]) if bits[0].startswith("assets/") else bits[0]
        out.append(url + ((" " + bits[1]) if len(bits) > 1 else ""))
    return f'{attr}="' + ", ".join(out) + '"'


body = re.sub(r'(href|src)="(assets/[^"]+)"', sub_single, body)
body = re.sub(r'(srcset|imagesrcset)="([^"]+)"', sub_set, body)
# внешние подключения больше не нужны — всё внутри блоков
body = re.sub(r'<link rel="stylesheet"[^>]*styles\.css[^>]*>\s*', "", body)
body = re.sub(r'<script[^>]*script\.js[^>]*></script>\s*', "", body)


def to_entities(text):
    return "".join(c if ord(c) < 128 else f"&#{ord(c)};" for c in text)


# ---------- 3. Нарезка --------------------------------------------------
def split_css(text, limit):
    """Режем по ЦЕЛЫМ верхнеуровневым правилам, полученным разбором со счётом
    скобок. Прежняя версия резала регуляркой и разрывала @media-блоки: в
    сумме получалось на четыре закрывающие скобки больше, и часть стилей
    отваливалась. Плюс переменные из :root обязаны попасть в первый блок —
    без них не разрешаются ни цвета, ни радиусы."""
    blocks = []
    for b in parse_blocks(text):
        if b[0] == 'raw':
            blocks.append(b[1])
        else:
            blocks.append(b[1] + '{' + b[2] + '}')

    parts, cur = [], ''
    for b in blocks:
        if len(cur) + len(b) > limit - 900 and cur:
            parts.append(cur)
            cur = ''
        cur += b + '\n'
    if cur:
        parts.append(cur)
    return parts


files = []
head = (f'<link rel="preconnect" href="https://fonts.googleapis.com" />\n'
        f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />\n{FONT_LINK}\n')
for i, part in enumerate(split_css(css_min, LIMIT), 1):
    files.append((f"style-{i}.html", (head if i == 1 else "") + "<style>\n" + part + "\n</style>\n"))


def pos(patt):
    m = re.search(patt, body)
    if not m:
        raise SystemExit(f"Не нашёл: {patt}")
    return m.start()


cuts = [0, pos(r'<section[^>]*id="reviews"'), pos(r'<section[^>]*id="inside"'),
        pos(r'<section[^>]*class="rates-banner"'), pos(r'<section[^>]*id="cases"'), len(body)]
labels = ["топбар+шапка+hero+через 7 дней", "отзывы+специалисты",
          "как похудеть+фейс-йога и тейпы", "баннер+тарифы",
          "кейсы+развилка+финал+помощь+футер"]
for i in range(5):
    files.append((f"block-{i+1}.html", to_entities(body[cuts[i]:cuts[i+1]])))

files.append(("script.html", "<script>\n" + js + "\n</script>\n"))

for name, content in files:
    (OUT / name).write_text(content, encoding="utf-8")

print(f"\nГотово -> {OUT}")
for name, content in files:
    n = len(content)
    flag = "OK" if n < LIMIT else "!! ПРЕВЫШЕН ЛИМИТ"
    label = ""
    if name.startswith("block-"):
        label = "  — " + labels[int(name[6]) - 1]
    print(f"  {name:16} {n:>7,} chars ({n/1024:5.1f} KB)  {flag}{label}")
print(f"\nВсего блоков: {len(files)}. Порядок: стили -> разметка -> скрипт.")
missing = [a for a in sorted(set(re.findall(r'assets/[\w./-]+', html))) if a not in asset_map]
print(f"Картинок пока с внешнего CDN: {len(missing)} (вписать адреса в tilda-assets.json, когда загрузят в Тильду)")
