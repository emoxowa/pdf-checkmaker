# PDF Check Maker

Генерирует PDF-чеки из CSV/JSON по HTML-шаблонам (WeasyPrint + Jinja2).

## Установка

**macOS**
```bash
brew install pango
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

**Windows**
1. Установите GTK3 runtime для WeasyPrint (MSYS2: `pacman -S mingw-w64-x86_64-pango`),
   см. https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows
2. ```bat
   python -m venv .venv && .venv\Scripts\activate
   pip install -r requirements.txt
   ```

## Запуск
```bash
python check_maker.py
```

## Структура
- `data/` — CSV и JSON с чеками
- `templates/` — HTML-шаблоны (Jinja2)
- `output/` — готовые PDF
- `fonts/` — DejaVu Sans (кириллица)

## Формат данных
Обязательна колонка/поле `invoice_id`. Каждая строка CSV — одна позиция чека:
`invoice_id, date, customer, item, quantity, price` (строки с одинаковым `invoice_id` объединяются).

JSON — список записей в том же плоском виде или со вложенным списком `items`:
```json
[{"invoice_id": "A-501", "date": "...", "customer": "...",
  "items": [{"name": "...", "quantity": 1, "price": 100}]}]
```
Все поля записи доступны в шаблоне как `invoice.<поле>`.

## Переменные шаблона
- `invoice` — поля чека + `invoice.total`, `invoice.items_count`
- `items` — позиции: `name`, `quantity`, `price`, `total`
- `source` — имя файла данных, `generated_at` — дата генерации
- фильтры: `{{ x|money }}` → `3 422.50`, `{{ x|qty }}` → `2`
