#!/usr/bin/env python3
"""Import model prices from a saved HTML catalog into SQLite and display them."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import html as html_lib
from html.parser import HTMLParser
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Iterator


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "models.sqlite3"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
             "meta", "param", "source", "track", "wbr"}
PRICE_RE = re.compile(r"([0-9][0-9\s\u00a0]*(?:[.,][0-9]+)?)\s*(₽|руб(?:\.)?|RUB|\$|USD|€|EUR)", re.I)
UNIT_RE = re.compile(r"/\s*([0-9]+(?:[.,][0-9]+)?)\s*([kKmM]?)")


class Element:
    def __init__(self, tag: str, attrs: dict[str, str | None]):
        self.tag = tag
        self.attrs = attrs
        self.children: list[Element | str] = []


class TreeBuilder(HTMLParser):
    """Small tolerant HTML tree builder using only Python's standard library."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = Element(tag, dict(attrs))
        self.stack[-1].children.append(element)
        if tag not in VOID_TAGS:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(Element(tag, dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.stack[-1].children.append(data)


def descendants(node: Element) -> Iterator[Element]:
    for child in node.children:
        if isinstance(child, Element):
            yield child
            yield from descendants(child)


def text_content(node: Element) -> str:
    parts: list[str] = []

    def visit(current: Element) -> None:
        for child in current.children:
            if isinstance(child, Element):
                visit(child)
            else:
                parts.append(child)

    visit(node)
    return " ".join(" ".join(parts).split())


def direct_text_content(node: Element) -> str:
    return " ".join(" ".join(child for child in node.children if isinstance(child, str)).split())


def has_class_suffix(node: Element, suffix: str) -> bool:
    return any(token.endswith(suffix) for token in (node.attrs.get("class") or "").split())


def find_descendant(node: Element, suffix: str) -> Element | None:
    return next((item for item in descendants(node) if has_class_suffix(item, suffix)), None)


def parse_price(value: str) -> tuple[float, str, float]:
    match = PRICE_RE.search(value)
    if not match:
        raise ValueError(f"Cannot read price from: {value!r}")
    amount = float(match.group(1).replace("\u00a0", "").replace(" ", "").replace(",", "."))
    symbol = match.group(2).upper()
    currency = "RUB" if symbol in {"₽", "РУБ", "РУБ."} else "USD" if symbol in {"$", "USD"} else "EUR"

    unit_match = UNIT_RE.search(value)
    if not unit_match:
        raise ValueError(f"Cannot read token unit from: {value!r}")
    unit_size = float(unit_match.group(1).replace(",", "."))
    unit_size *= {"": 1, "K": 1_000, "M": 1_000_000}[unit_match.group(2).upper()]
    if unit_size <= 0:
        raise ValueError(f"Invalid token unit in: {value!r}")
    return amount * 1_000_000 / unit_size, currency, unit_size


def parse_context(value: str) -> int | None:
    numbers = re.findall(r"\d+", value)
    return int("".join(numbers)) if numbers else None


def parse_catalog(source: Path) -> list[dict[str, object]]:
    parser = TreeBuilder()
    parser.feed(source.read_text(encoding="utf-8", errors="replace"))
    cards = [node for node in descendants(parser.root) if has_class_suffix(node, "__card")]
    if not cards:
        raise ValueError("No model cards found in this HTML file")

    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records: list[dict[str, object]] = []
    for card in cards:
        name_node = find_descendant(card, "__cardName")
        link_node = find_descendant(card, "__cardNameLink")
        provider_node = find_descendant(card, "__cardProviderRow")
        description_node = find_descendant(card, "__cardDesc")
        context_node = find_descendant(card, "__cardContextBadge")
        if not name_node or not link_node or not provider_node:
            continue

        prices: dict[str, tuple[float, str, float]] = {}
        for price_node in (n for n in descendants(card) if has_class_suffix(n, "__cardPrice")):
            label_node = next((n for n in descendants(price_node) if n.tag == "span"), None)
            data_node = find_descendant(price_node, "__cardPriceData")
            if label_node is None or data_node is None:
                continue
            label = text_content(label_node).strip().lower()
            field = "input" if label == "ввод" else "output" if label == "вывод" else None
            if field:
                prices[field] = parse_price(text_content(data_node))

        if "input" not in prices or "output" not in prices:
            raise ValueError(f"Model card is missing an input or output price: {text_content(name_node)}")

        href = link_node.attrs.get("href") or ""
        slug = href.rstrip("/").rsplit("/", 1)[-1] or text_content(name_node).lower().replace(" ", "-")
        input_price, input_currency, _ = prices["input"]
        output_price, output_currency, _ = prices["output"]
        records.append({
            "slug": slug,
            "name": text_content(name_node),
            # Provider icons are SVGs whose <title> duplicates the visible provider label.
            "provider": direct_text_content(provider_node) or text_content(provider_node),
            "description": text_content(description_node) if description_node else "",
            "context_tokens": parse_context(context_node.attrs.get("title", "")) if context_node else None,
            "input_price_per_million": input_price,
            "input_currency": input_currency,
            "output_price_per_million": output_price,
            "output_currency": output_currency,
            "source_url": href,
            "source_file": source.name,
            "imported_at": imported_at,
        })
    return records


SCHEMA = """
CREATE TABLE IF NOT EXISTS models (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    context_tokens INTEGER,
    input_price_per_million REAL NOT NULL,
    input_currency TEXT NOT NULL,
    output_price_per_million REAL NOT NULL,
    output_currency TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_file TEXT NOT NULL,
    imported_at TEXT NOT NULL
)
"""


def connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.execute(SCHEMA)
    return connection


def import_catalog(source: Path, db_path: Path) -> int:
    records = parse_catalog(source)
    with connect(db_path) as connection:
        connection.executemany(
            """INSERT INTO models VALUES (
                :slug, :name, :provider, :description, :context_tokens,
                :input_price_per_million, :input_currency,
                :output_price_per_million, :output_currency,
                :source_url, :source_file, :imported_at
            ) ON CONFLICT(slug) DO UPDATE SET
                name=excluded.name, provider=excluded.provider,
                description=excluded.description, context_tokens=excluded.context_tokens,
                input_price_per_million=excluded.input_price_per_million,
                input_currency=excluded.input_currency,
                output_price_per_million=excluded.output_price_per_million,
                output_currency=excluded.output_currency, source_url=excluded.source_url,
                source_file=excluded.source_file, imported_at=excluded.imported_at""",
            records,
        )
    return len(records)


def get_models(db_path: Path, sort_by: str) -> list[tuple[object, ...]]:
    columns = {
        "input": "input_price_per_million ASC, name COLLATE NOCASE",
        "output": "output_price_per_million ASC, name COLLATE NOCASE",
        "name": "name COLLATE NOCASE",
        "context": "context_tokens DESC, name COLLATE NOCASE",
    }
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}. Run the import command first.")
    with connect(db_path) as connection:
        return connection.execute(
            f"""SELECT name, provider, input_price_per_million, input_currency,
                       output_price_per_million, output_currency, context_tokens, slug
                FROM models ORDER BY {columns[sort_by]}"""
        ).fetchall()


def format_price(value: float, currency: str) -> str:
    number = f"{value:,.4f}".replace(",", " ").rstrip("0").rstrip(".")
    symbol = {"RUB": "₽", "USD": "$", "EUR": "€"}.get(currency, currency)
    return f"{number} {symbol}"


def show_table(rows: list[tuple[object, ...]], limit: int | None) -> None:
    if limit is not None:
        rows = rows[:limit]
    headers = ("Модель", "Поставщик", "Ввод / 1M", "Вывод / 1M", "Контекст")
    display_rows = [
        (str(r[0]), str(r[1]), format_price(float(r[2]), str(r[3])),
         format_price(float(r[4]), str(r[5])), f"{int(r[6]):,}".replace(",", " ") if r[6] else "—")
        for r in rows
    ]
    widths = [max(len(headers[i]), *(len(row[i]) for row in display_rows)) if display_rows else len(headers[i])
              for i in range(len(headers))]
    print(" | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("-+-".join("-" * width for width in widths))
    for row in display_rows:
        print(" | ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
    print(f"\nПоказано моделей: {len(display_rows)}")


def export_csv(rows: list[tuple[object, ...]], destination: Path) -> None:
    with destination.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(("Модель", "Поставщик", "Ввод за 1M", "Валюта ввода",
                         "Вывод за 1M", "Валюта вывода", "Контекст токенов", "Slug"))
        writer.writerows(rows)


DASHBOARD_TEMPLATE = r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Каталог AI-моделей</title>
<style>
:root{color-scheme:light;--ink:#182237;--muted:#77839a;--line:#e8edf4;--paper:#fff;--bg:#f2f5fa;--blue:#5269dc;--mint:#c5f6e7;--shadow:0 16px 48px #1e315210}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 8% 0%,#e7edff 0,transparent 35%),var(--bg);color:var(--ink);font:15px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
.shell{max-width:1240px;margin:0 auto;padding:42px 28px 60px}.hero{position:relative;overflow:hidden;border-radius:26px;padding:34px 38px;color:#fff;background:linear-gradient(120deg,#202d52,#435ac1 67%,#7679da);box-shadow:0 20px 60px #34438d35}
.hero:after{content:"";position:absolute;width:360px;height:360px;right:-70px;top:-200px;border:1px solid #ffffff28;border-radius:50%;box-shadow:0 0 0 38px #ffffff0d,0 0 0 82px #ffffff0a}.eyebrow{font-size:11px;font-weight:800;letter-spacing:.17em;color:#b8f6e2}.hero h1{position:relative;margin:10px 0 7px;font-size:clamp(28px,4vw,42px);letter-spacing:-.04em}.hero p{position:relative;margin:0;color:#d9e1ff}.hero-meta{position:relative;display:flex;gap:10px;flex-wrap:wrap;margin-top:23px}.pill{padding:7px 12px;border:1px solid #ffffff31;border-radius:999px;background:#ffffff13;font-size:12px;color:#f0f2ff}
.panel{margin-top:22px;background:var(--paper);border:1px solid #e8edf5;border-radius:20px;box-shadow:var(--shadow);overflow:hidden}.toolbar{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:19px 22px;border-bottom:1px solid var(--line)}.search-wrap{position:relative;flex:1;max-width:540px}.search-wrap:before{content:"⌕";position:absolute;left:14px;top:6px;font-size:25px;color:#8994a8}.search{width:100%;height:44px;padding:0 15px 0 42px;border:1px solid #dfe5ee;border-radius:12px;background:#fbfcfe;color:var(--ink);font:inherit;outline:none}.search:focus{border-color:#8392f0;box-shadow:0 0 0 3px #6476e51c}.sort-label{display:flex;align-items:center;gap:9px;color:var(--muted);font-size:13px}.sort{height:42px;padding:0 34px 0 12px;border:1px solid #dfe5ee;border-radius:11px;background:#fff;color:var(--ink);font:inherit}
.table-scroll{overflow:auto}table{width:100%;border-collapse:collapse;min-width:760px}thead th{position:sticky;top:0;z-index:1;background:#fafbfe;color:#7d899e;text-align:left;font-size:11px;letter-spacing:.09em;text-transform:uppercase;padding:14px 18px;border-bottom:1px solid var(--line);white-space:nowrap}thead th button{all:unset;cursor:pointer}thead th button:hover{color:var(--blue)}tbody td{padding:14px 18px;border-bottom:1px solid #eef1f6;vertical-align:middle}tbody tr:last-child td{border-bottom:0}tbody tr:hover{background:#f8faff}.model{font-weight:750;letter-spacing:-.01em}.description{max-width:410px;margin-top:3px;color:var(--muted);font-size:12px;line-height:1.4}.provider{display:inline-flex;align-items:center;padding:5px 9px;border-radius:999px;background:#eff2ff;color:#4556a6;font-size:12px;font-weight:650;white-space:nowrap}.price{font-variant-numeric:tabular-nums;font-weight:750;white-space:nowrap}.price.in{color:#13795b}.price.out{color:#ab4c81}.context{font-variant-numeric:tabular-nums;color:#59657a;white-space:nowrap}.context small{display:block;color:#9aa3b2;font-size:10px}.count{padding:12px 22px;color:var(--muted);font-size:12px;border-top:1px solid var(--line)}.empty{text-align:center;padding:42px;color:var(--muted)}.foot{padding:16px 4px;color:#8490a3;font-size:12px}
@media(max-width:700px){.shell{padding:18px 12px 32px}.hero{padding:25px 22px;border-radius:20px}.toolbar{align-items:stretch;flex-direction:column}.sort-label{justify-content:space-between}.sort{flex:1}.panel{border-radius:16px}}
</style>
</head>
<body>
<main class="shell">
  <header class="hero">
    <div class="eyebrow">СРАВНЕНИЕ И ВЫБОР</div>
    <h1>Каталог AI-моделей</h1>
    <p>Цены, поставщики и размер контекста — собраны в одной таблице.</p>
    <div class="hero-meta"><span class="pill" id="total-pill">@@COUNT@@ моделей</span><span class="pill">Цена указана за 1 млн токенов</span><span class="pill">Источник: сохранённый каталог</span></div>
  </header>
  <section class="panel" aria-label="Сравнение цен моделей">
    <div class="toolbar">
      <label class="search-wrap"><input class="search" id="search" type="search" placeholder="Найти модель или поставщика…" aria-label="Поиск"></label>
      <label class="sort-label">Сортировка
        <select id="sort" class="sort"><option value="input">Дешевле ввод</option><option value="output">Дешевле вывод</option><option value="name">Название А—Я</option><option value="context">Больше контекст</option></select>
      </label>
    </div>
    <div class="table-scroll"><table>
      <thead><tr><th>Модель</th><th>Поставщик</th><th><button data-sort="input">Ввод / 1M ↕</button></th><th><button data-sort="output">Вывод / 1M ↕</button></th><th><button data-sort="context">Контекст ↕</button></th></tr></thead>
      <tbody id="rows"></tbody>
    </table><div class="empty" id="empty" hidden>По этому запросу моделей не нашлось.</div></div>
    <div class="count" id="count"></div>
  </section>
  <div class="foot">Цены перенесены из приложенного HTML-снимка и могут измениться у поставщика. Контекст показан в токенах.</div>
</main>
<script type="application/json" id="catalog-data">@@DATA@@</script>
<script>
const models=JSON.parse(document.getElementById('catalog-data').textContent);
const tbody=document.getElementById('rows'), search=document.getElementById('search'), sort=document.getElementById('sort');
const nf=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:4});
const colors=[['#edf1ff','#4658a6'],['#e6f8f2','#26795e'],['#fff1e6','#a35d2e'],['#f8eafa','#884a91'],['#e8f5fb','#39708a'],['#fff0f1','#a54d5c']];
function cell(value,className){const e=document.createElement('td');e.className=className||'';e.textContent=value;return e}
function render(){
 const q=search.value.trim().toLocaleLowerCase('ru');
 const visible=models.filter(m=>(m.name+' '+m.provider+' '+m.description).toLocaleLowerCase('ru').includes(q));
 const key=sort.value;
 visible.sort((a,b)=>key==='name'?a.name.localeCompare(b.name,'ru'):
   key==='context'?(b.context_tokens||0)-(a.context_tokens||0):a[key+'_price_per_million']-b[key+'_price_per_million']);
 tbody.replaceChildren();
 for(const m of visible){
   const tr=document.createElement('tr'), model=document.createElement('td');
   const title=document.createElement('div');title.className='model';title.textContent=m.name;model.append(title);
   if(m.description){const d=document.createElement('div');d.className='description';d.textContent=m.description;model.append(d)}
   const provider=document.createElement('td'), badge=document.createElement('span');badge.className='provider';
   const palette=colors[[...m.provider].reduce((n,c)=>n+c.codePointAt(0),0)%colors.length];badge.style.background=palette[0];badge.style.color=palette[1];badge.textContent=m.provider;provider.append(badge);
   tr.append(model,provider,cell(nf.format(m.input_price_per_million)+' '+m.input_currency,'price in'),cell(nf.format(m.output_price_per_million)+' '+m.output_currency,'price out'));
   const context=cell(m.context_tokens?nf.format(m.context_tokens):'—','context');
   if(m.context_tokens){const small=document.createElement('small');small.textContent='токенов';context.append(small)}
   tr.append(context);tbody.append(tr);
 }
 document.getElementById('count').textContent=`Показано ${nf.format(visible.length)} из ${nf.format(models.length)} моделей`;
 document.getElementById('empty').hidden=visible.length!==0;
}
search.addEventListener('input',render);sort.addEventListener('change',render);
document.querySelectorAll('[data-sort]').forEach(b=>b.addEventListener('click',()=>{sort.value=b.dataset.sort;render()}));
render();
</script>
</body>
</html>'''


def generate_dashboard(db_path: Path, destination: Path) -> int:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}. Run the import command first.")
    with connect(db_path) as connection:
        rows = connection.execute(
            """SELECT name, provider, description, context_tokens,
                      input_price_per_million, input_currency,
                      output_price_per_million, output_currency
               FROM models ORDER BY input_price_per_million, name COLLATE NOCASE"""
        ).fetchall()
    data = [
        {"name": row[0], "provider": row[1], "description": row[2], "context_tokens": row[3],
         "input_price_per_million": row[4], "input_currency": row[5],
         "output_price_per_million": row[6], "output_currency": row[7]}
        for row in rows
    ]
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    page = DASHBOARD_TEMPLATE.replace("@@DATA@@", payload).replace("@@COUNT@@", str(len(rows)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, encoding="utf-8")
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Импорт и сравнение цен AI-моделей из HTML-каталога.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite база (по умолчанию: {DEFAULT_DB.name})")
    commands = parser.add_subparsers(dest="command", required=True)
    import_parser = commands.add_parser("import", help="импортировать сохранённый HTML в SQLite")
    import_parser.add_argument("html_file", type=Path)
    list_parser = commands.add_parser("list", help="показать таблицу цен")
    list_parser.add_argument("--sort", choices=("input", "output", "name", "context"), default="input")
    list_parser.add_argument("--limit", type=int, help="ограничить число строк")
    export_parser = commands.add_parser("export", help="экспортировать таблицу в CSV")
    export_parser.add_argument("csv_file", type=Path)
    html_parser = commands.add_parser("html", help="создать цветную интерактивную HTML-таблицу")
    html_parser.add_argument("--output", type=Path, default=BASE_DIR / "catalog.html")
    args = parser.parse_args()

    try:
        if args.command == "import":
            count = import_catalog(args.html_file, args.db)
            print(f"Импортировано моделей: {count}. База: {args.db}")
        elif args.command == "list":
            if args.limit is not None and args.limit < 1:
                parser.error("--limit должен быть больше нуля")
            show_table(get_models(args.db, args.sort), args.limit)
        elif args.command == "export":
            export_csv(get_models(args.db, "name"), args.csv_file)
            print(f"CSV сохранён: {args.csv_file}")
        elif args.command == "html":
            count = generate_dashboard(args.db, args.output)
            print(f"Создана HTML-таблица на {count} моделей: {args.output}")
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
