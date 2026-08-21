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
import base64
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


# poster у видео — такой же адрес ресурса, как src; без него первый кадр
# не подхватится, и на месте видео будет пустота, пока оно грузится
body = re.sub(r'(href|src|poster)="(assets/[^"]+)"', sub_single, body)
body = re.sub(r'(srcset|imagesrcset)="([^"]+)"', sub_set, body)
# внешние подключения больше не нужны — всё внутри блоков
body = re.sub(r'<link rel="stylesheet"[^>]*styles\.css[^>]*>\s*', "", body)
body = re.sub(r'<script[^>]*script\.js[^>]*></script>\s*', "", body)


def js_for_tilda(text):
    r"""JS, безопасный для вставки в блок Тильды.

    Тильда пересохраняет содержимое блока и портит не-ASCII: русские комментарии
    приезжали как «РЁР°РіР°С‚РµР»СЊ», а строка про старт интенсива вышла бы
    крякозябрами прямо на экране. HTML-сущности тут не годятся: внутри <script>
    они не декодируются. Поэтому комментарии срезаем, а кириллицу в коде
    переводим в \uXXXX — это валидный JS-эскейп, и Тильде ломать становится нечего.

    Комментарии режем посимвольно, а не регуляркой: «//» встречается внутри строк
    с адресами (https://...), и регулярка съела бы половину строки.
    """
    out, i, n = [], 0, len(text)
    quote = None
    while i < n:
        c = text[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"`":
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        out.append(c)
        i += 1
    code = "".join(out)
    code = re.sub(r"[ \t]+\n", "\n", code)
    code = re.sub(r"\n{3,}", "\n\n", code)
    return "".join(ch if ord(ch) < 128 else "\\u%04x" % ord(ch) for ch in code)


def to_entities(text):
    return "".join(c if ord(c) < 128 else f"&#{ord(c)};" for c in text)


# ---------- 3. Нарезка --------------------------------------------------
# ---------------------------------------------------------------------------
# ИЗОЛЯЦИЯ ОТ ОСТАЛЬНОЙ СТРАНИЦЫ
# На Тильде рядом с нашими блоками живут чужие: шапка проекта, футер, формы.
# Правила вида `a`, `ul`, `img`, `body` цепляли и их — у ссылок пропадало
# подчёркивание, у списков маркеры, у заголовков отступы. Поэтому разметку
# оборачиваем в .shd-anti, а все правила на голые теги ограничиваем им же.
# ---------------------------------------------------------------------------
SCOPE = ".shd-anti"
_TAG = re.compile(r"^[a-z]+[0-9]?$")


def scope_selector(sel):
    """Префикс получают ВСЕ правила, а не только те, что на голые теги.
    Если ограничить только теги, у `.shd-anti h2` станет выше вес, чем у
    `.section__title`, и тег перебьёт класс — у заголовков пропадали отступы."""
    out = []
    for part in sel.split(","):
        s = part.strip()
        if not s:
            continue
        if s.startswith(":root") or s.startswith("@") or s.startswith(SCOPE):
            out.append(s)
            continue
        head = re.split(r"[\s:\[.#>+~]", s, maxsplit=1)[0]
        if head in ("html", "body"):
            rest = s[len(head):].strip()
            out.append(f"{SCOPE} {rest}".strip() if rest else SCOPE)
        else:
            out.append(f"{SCOPE} {s}")
    return ", ".join(out)


def scope_css(text):
    res, i, n = [], 0, len(text)
    while i < n:
        br = text.find("{", i)
        if br < 0:
            res.append(text[i:])
            break
        sel = text[i:br]
        stripped = sel.strip()
        if stripped.startswith("@"):
            # у @media/@supports внутри лежат обычные правила — заходим внутрь;
            # у @keyframes внутри проценты, их трогать нельзя
            depth, j = 1, br + 1
            while j < n and depth:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                j += 1
            inner = text[br + 1:j - 1]
            if stripped.startswith("@keyframes") or "keyframes" in stripped:
                res.append(sel + "{" + inner + "}")
            else:
                res.append(sel + "{" + scope_css(inner) + "}")
            i = j
            continue
        end = text.find("}", br)
        if end < 0:
            res.append(text[i:])
            break
        res.append(scope_selector(sel) + "{" + text[br + 1:end] + "}")
        i = end + 1
    return "".join(res)


def css_capsule(part):
    """CSS, который Тильда не сможет переписать.

    Тильда переформатирует содержимое блока: она распознала `<svg` внутри
    url(...) как разметку и расставила переносы прямо посреди адреса картинки —
    иконки-галочки перестали грузиться, а следом поехали и другие правила.
    Поэтому отдаём стили не текстом, а строкой base64: там только латиница и
    цифры, форматировать нечего. Скрипт распаковывает её и кладёт <style> в head.
    """
    b64 = base64.b64encode(part.encode("utf-8")).decode("ascii")
    return (
        "<script>(function(){"
        "var d=\"" + b64 + "\";"
        "var b=atob(d),a=new Uint8Array(b.length),i=0;"
        "for(;i<b.length;i++){a[i]=b.charCodeAt(i);}"
        "var t=(typeof TextDecoder!=='undefined')?new TextDecoder('utf-8').decode(a)"
        ":decodeURIComponent(escape(b));"
        "var s=document.createElement('style');"
        "s.appendChild(document.createTextNode(t));"
        "(document.head||document.documentElement).appendChild(s);"
        "})();</script>\n"
    )


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
        if len(cur) + len(b) > limit and cur:
            parts.append(cur)
            cur = ''
        cur += b + '\n'
    if cur:
        parts.append(cur)
    return parts


files = []
head = (f'<link rel="preconnect" href="https://fonts.googleapis.com" />\n'
        f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />\n{FONT_LINK}\n')
css_scoped = scope_css(css_min)
# overflow-x на обёртке создал бы новый контекст прокрутки и сломал бы
# закреплённый баннер, поэтому убираем именно это свойство
css_scoped = re.sub(r"(\.shd-anti\s*\{[^}]*?)overflow-x:\s*hidden;?", r"\1", css_scoped)
print(f"Изоляция: правила на голые теги ограничены {SCOPE}")

# base64 раздувает кусок ровно на треть, плюс ~400 знаков обвязки скрипта
CSS_CHUNK = (LIMIT - 3000) * 3 // 4   # с запасом: впритык к лимиту Тильду лучше не подводить
for i, part in enumerate(split_css(css_scoped, CSS_CHUNK), 1):
    files.append((f"style-{i}.html", (head if i == 1 else "") + css_capsule(part)))


def pos(patt):
    m = re.search(patt, body)
    if not m:
        raise SystemExit(f"Не нашёл: {patt}")
    return m.start()


cuts = [0, pos(r'<section[^>]*id="reviews"'), pos(r'<section[^>]*id="inside"'),
        pos(r'<section[^>]*class="rates-banner"'), pos(r'<section[^>]*id="cases"'),
        pos(r'<section[^>]*id="fork"'), len(body)]
labels = ["топбар+шапка+hero+через 7 дней", "отзывы участниц",
          "как похудеть+фейс-йога и тейпы", "баннер+тарифы",
          "результаты+специалисты", "развилка+финал+помощь+футер"]
for i in range(6):
    chunk = body[cuts[i]:cuts[i+1]]
    files.append((f"block-{i+1}.html",
                  '<div class="shd-anti">\n' + to_entities(chunk) + '\n</div>\n'))

files.append(("script.html", "<script>\n" + js_for_tilda(js) + "\n</script>\n"))

for stale in OUT.glob("*.html"):     # от прошлых сборок могли остаться лишние блоки
    stale.unlink()
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


# ---------- 4. Папка «ДЛЯ ТИЛЬДЫ» — то, что уходит человеку -------------
# Раньше её собирали руками, копируя файлы и переименовывая. Один пропущенный
# файл — и на страницу уезжала половина старой сборки, а искать это потом
# приходилось по внешнему виду. Теперь папку пишет сам сборщик: имена с
# номерами задают порядок вставки, инструкция генерируется тут же.
HUMAN = {
    "style-1.html": "01 — стили, часть 1",
    "style-2.html": "02 — стили, часть 2",
    "block-1.html": "03 — шапка, баннер и первый экран",
    "block-2.html": "04 — отзывы участниц",
    "block-3.html": "05 — как похудеть, фейс-йога и тейпы",
    "block-4.html": "06 — тарифы",
    "block-5.html": "07 — результаты и специалисты",
    "block-6.html": "08 — развилка, финал, помощь, футер",
    "script.html": "09 — скрипт, вставлять последним",
}

HAND = BASE / "ДЛЯ ТИЛЬДЫ"
HAND.mkdir(exist_ok=True)
for old in HAND.glob("*.html"):
    old.unlink()

order = []
for name, content in files:
    human = HUMAN.get(name)
    if not human:
        continue
    (HAND / f"{human}.html").write_text(content, encoding="utf-8")
    order.append(human)

readme = """АНТИОТЁЧНОСТЬ — блоки для Тильды
=================================

Вставлять В ЭТОМ ПОРЯДКЕ, каждый файл — в отдельный блок T123 (HTML-код).
Порядок важен: стили идут первыми, скрипт — последним.

""" + "\n".join(f"  {name}" for name in order) + """

ВАЖНО: то, что стоит на странице от прошлой сборки, нужно удалить полностью —
блоки не «обновляются», а заменяются. Смешивать старые и новые нельзя.

В этих блоках стили и скрипт лежат внутри — ничего постороннего страница не
подгружает.

Стили передаются закодированной строкой, а не обычным текстом. Причина: Тильда
переформатирует содержимое блока. В прошлой сборке она приняла картинку-галочку
внутри стилей за разметку и расставила переносы прямо посреди её адреса —
галочки в тарифах пропали, сноска под тарифами и подвал остались без оформления.
В закодированной строке только латиница и цифры, форматировать там нечего,
поэтому испортить стили Тильда больше не может.

Русские буквы в скрипте тоже закодированы — по той же причине: Тильда портит
кириллицу внутри кода.

Счётчик Метрики не трогаем: он стоит на Тильде. В блоках только отправка целей,
второй счётчик не появится.

Метки из рекламных ссылок (utm_source, utm_medium, utm_campaign, utm_content,
erid) сами подставляются во все кнопки оплаты.

Осталось на нашей стороне: {N} картинок пока грузятся с внешнего адреса.
Загрузите их в Тильду и пришлите ссылки — заменим, и внешних зависимостей
не останется совсем.
""".replace("{N}", str(len(missing)))
(HAND / "ПРОЧТИ ПЕРВЫМ.txt").write_text(readme, encoding="utf-8")
print(f"\nПапка «ДЛЯ ТИЛЬДЫ» обновлена: {len(order)} файлов + инструкция")


# ---------- 5. Локальное превью — блоки, склеенные в том же порядке ------
# Проверять сборку на живой Тильде дорого: каждый прогон — это ручная вставка
# девяти блоков. Здесь тот же результат открывается в браузере одним файлом.
preview = ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width, initial-scale=1">'
           '<title>Превью блоков</title>'
           # Тильда сама обнуляет поля body; без этого превью съезжает на 8px
           # и сравнение со страницей показывает ложные расхождения
           '<style>body{margin:0}</style></head><body>\n'
           + "\n".join(c for _n, c in files) + "\n</body></html>")
(BASE / "_preview.html").write_text(preview, encoding="utf-8")
print(f"Превью: _preview.html ({len(preview)/1024:.0f} КБ) — открыть в браузере и посмотреть глазами")

# Узкий экран отдельным файлом: окно браузера уже ~500px на macOS не делается, и
# «мобильную» проверку легко принять за поехавшую вёрстку, хотя это просто обрезка
# снимка. Внутри iframe медиазапросы считаются от его ширины — 390px честные.
mobile = ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
          '<title>Превью, узкий экран 390px</title><style>'
          'html,body{margin:0;background:#8a8a8a}'
          'iframe{width:390px;height:13000px;border:0;display:block;margin:0 auto;background:#fff}'
          '</style></head><body><iframe src="_preview.html"></iframe></body></html>')
(BASE / "_preview-mobile.html").write_text(mobile, encoding="utf-8")
print("Превью узкого экрана: _preview-mobile.html (390px внутри iframe)")
