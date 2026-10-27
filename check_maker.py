"""Генератор PDF-чеков из CSV/JSON по HTML-шаблонам (WeasyPrint)."""

import json
import os
import platform
import subprocess
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import CSS, HTML
from weasyprint.text.fonts import FontConfiguration

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output"
FONTS_DIR = BASE_DIR / "fonts"

# Возможные названия колонки с номером чека (после нормализации ключей)
INVOICE_KEYS = ("invoice_id", "invoiceid", "invoice_no", "invoice_number", "invoice", "id_чека", "чек")
# Поля, которые описывают товарную позицию, а не чек целиком
ITEM_KEYS = ("item", "product", "name", "description", "quantity", "qty", "price", "unit_price", "total", "sku")

LINE = "─" * 50


# ─────────────────────────── Загрузка данных ───────────────────────────

def normalize_key(key):
    return str(key).strip().lower().replace(" ", "_").replace("-", "_")


def normalize_record(record):
    return {normalize_key(k): v for k, v in record.items()}


def find_invoice_key(record):
    for key in INVOICE_KEYS:
        if key in record:
            return key
    return None


def load_csv(path):
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    return [normalize_record(row) for row in df.to_dict(orient="records")]


def load_json(path):
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    # Допускаем как список, так и объект вида {"invoices": [...]}
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        data = lists[0] if lists else [data]
    return [normalize_record(r) for r in data if isinstance(r, dict)]


def to_number(value, default=0.0):
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except ValueError:
        return default


def build_item(raw):
    name = raw.get("item") or raw.get("product") or raw.get("name") or raw.get("description") or ""
    qty = to_number(raw.get("quantity", raw.get("qty")), 1)
    price = to_number(raw.get("price", raw.get("unit_price")))
    total = to_number(raw.get("total"), qty * price)
    return {**raw, "name": name, "quantity": qty, "price": price, "total": total}


def group_invoices(records):
    """Собирает записи в словарь {invoice_id: invoice}.

    Поддерживаются два формата:
    * плоский — каждая строка = одна позиция чека (CSV или JSON);
    * вложенный — у записи есть список "items" (JSON).
    """
    invoices = OrderedDict()
    for rec in records:
        key = find_invoice_key(rec)
        if key is None:
            continue
        inv_id = str(rec[key]).strip()
        if not inv_id:
            continue

        header = {k: v for k, v in rec.items() if k not in ITEM_KEYS and k != "items"}
        invoice = invoices.setdefault(inv_id, {**header, "invoice_id": inv_id, "items": []})

        if isinstance(rec.get("items"), list):
            invoice["items"].extend(build_item(normalize_record(i)) for i in rec["items"])
        else:
            invoice["items"].append(build_item(rec))

    for invoice in invoices.values():
        invoice["total"] = sum(i["total"] for i in invoice["items"])
        invoice["items_count"] = len(invoice["items"])
    return invoices


def load_data_file(path):
    loader = load_csv if path.suffix.lower() == ".csv" else load_json
    return group_invoices(loader(path))


# ─────────────────────────── Консольное меню ───────────────────────────

def list_files(directory, extensions):
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in extensions)


def print_menu(title, options):
    print(f"\n{LINE}\n  {title}\n{LINE}")
    if not options:
        print("  (пусто)")
    for i, option in enumerate(options, 1):
        print(f"  [{i:>2}] {option}")


def choose(prompt, count):
    while True:
        answer = input(f"\n{prompt} (1-{count}, q — выход): ").strip().lower()
        if answer in ("q", "й", "exit", "quit"):
            print("Выход.")
            sys.exit(0)
        if answer.isdigit() and 1 <= int(answer) <= count:
            return int(answer) - 1
        print(f"  ⚠ Введите число от 1 до {count}.")


def describe_invoice(inv_id, invoice):
    parts = [f"№ {inv_id}"]
    for key in ("date", "customer", "client"):
        if invoice.get(key):
            parts.append(str(invoice[key]))
    parts.append(f"позиций: {invoice['items_count']}")
    parts.append(f"сумма: {format_money(invoice['total'])}")
    return "  |  ".join(parts)


# ─────────────────────────── Генерация PDF ───────────────────────────

def format_money(value):
    return f"{value:,.2f}".replace(",", " ")


def format_qty(value):
    return f"{value:g}"


def font_css():
    """@font-face для кириллицы: локальный DejaVu Sans из ./fonts, иначе системный."""
    faces = []
    for weight, filename in (("normal", "DejaVuSans.ttf"), ("bold", "DejaVuSans-Bold.ttf")):
        font_file = FONTS_DIR / filename
        sources = [f"url('{font_file.as_uri()}')"] if font_file.exists() else []
        sources += ["local('DejaVu Sans')", "local('Roboto')"]
        faces.append(
            "@font-face { font-family: 'DejaVu Sans'; font-weight: %s; src: %s; }"
            % (weight, ", ".join(sources))
        )
    # @page — чтобы колонтитулы (номера страниц) тоже были с кириллицей
    family = "'DejaVu Sans', 'Roboto', Arial, sans-serif"
    faces.append(f"@page {{ font-family: {family}; }}")
    faces.append(f"body {{ font-family: {family}; }}")
    return "\n".join(faces)


def render_pdf(template_path, invoice, source_name):
    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=select_autoescape(["html", "htm"]),
    )
    env.filters["money"] = format_money
    env.filters["qty"] = format_qty

    html_str = env.get_template(template_path.name).render(
        invoice=invoice,
        items=invoice["items"],
        source=source_name,
        generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
    )

    OUTPUT_DIR.mkdir(exist_ok=True)
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in invoice["invoice_id"])
    pdf_path = OUTPUT_DIR / f"invoice_{safe_id}_{template_path.stem}.pdf"

    font_config = FontConfiguration()
    HTML(string=html_str, base_url=str(template_path.parent)).write_pdf(
        pdf_path,
        stylesheets=[CSS(string=font_css(), font_config=font_config)],
        font_config=font_config,
    )
    return pdf_path


def open_file(path):
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(path)  # noqa: S606
        elif system == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError as e:
        print(f"  ⚠ Не удалось открыть файл автоматически: {e}")


# ─────────────────────────── main ───────────────────────────

def main():
    data_files = list_files(DATA_DIR, {".csv", ".json"})
    templates = list_files(TEMPLATES_DIR, {".html", ".htm"})

    print_menu(f"Файлы с данными ({DATA_DIR})", [p.name for p in data_files])
    print_menu(f"HTML-шаблоны ({TEMPLATES_DIR})", [p.name for p in templates])

    if not data_files or not templates:
        print("\n✖ Нужен хотя бы один файл данных и один шаблон.")
        sys.exit(1)

    data_path = data_files[choose("Выберите файл данных", len(data_files))]
    template_path = templates[choose("Выберите шаблон", len(templates))]

    try:
        invoices = load_data_file(data_path)
    except (OSError, ValueError, pd.errors.ParserError) as e:
        print(f"\n✖ Не удалось прочитать {data_path.name}: {e}")
        sys.exit(1)

    if not invoices:
        print(f"\n✖ В файле {data_path.name} не найдено чеков (нужна колонка invoice_id).")
        sys.exit(1)

    ids = list(invoices)
    print_menu(f"Чеки в {data_path.name}", [describe_invoice(i, invoices[i]) for i in ids])
    invoice = invoices[ids[choose("Выберите чек", len(ids))]]

    print(f"\n⏳ Генерация PDF для чека № {invoice['invoice_id']}...")
    pdf_path = render_pdf(template_path, invoice, data_path.name)
    print(f"✔ Готово: {pdf_path}")
    open_file(pdf_path)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nПрервано.")
