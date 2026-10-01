# AutoCAD + Claude (MCP)

MCP-сервер `autocad` управляет запущенным AutoCAD через AutoLISP. Работает на macOS и Windows.

| Система | Как команды попадают в AutoCAD | Проверено |
|---|---|---|
| macOS | `helper/acadctl` вводит строку в командную строку AutoCAD | да: macOS 26, AutoCAD 2026 (R25.1) |
| Windows | COM-интерфейс AutoCAD (`PostCommand`), без клавиатуры | только автотестами с имитацией COM |

Установка на Windows: [INSTALL_WINDOWS.md](INSTALL_WINDOWS.md).

## Как это устроено

```
Claude ── MCP (stdio) ──> server/autocad_mcp/server.py        общая логика
                            │ 1. пишет запрос ~/.cad-mcp/autocad/req_<id>.lsp
                            │ 2. бэкенд просит AutoCAD выполнить (progn (load "…req_<id>.lsp"))
                            │      backend_mac.py  → helper/acadctl (Accessibility)
                            │      backend_win.py  → COM, AcadDocument.PostCommand
                            ▼
                  AutoCAD: lisp/mcp_lib.lsp, mcp:run выполняет код
                            │ с перехватом ошибок, одной группой UNDO
                            ▼
                  ~/.cad-mcp/autocad/res_<id>.json   ← сервер ждёт этот файл
                  + вывод командной строки → поле "console"
```

- Код запроса лежит в файле, в AutoCAD уходит только короткая строка `load`. Размер кода не ограничен.
- При первом вызове сервер добавляет папку обмена в `TRUSTEDPATHS`. Без этого `SECURELOAD` отменяет `load`.
- Вывод командной строки на Mac читается через Accessibility, на Windows из лог-файла AutoCAD (`LOGFILEMODE=1`).
- На Mac `acadctl` перед Enter сверяет, что в командной строке ровно нужная строка. Если пользователь в этот момент печатает и текст испортился, ввод повторяется.

## Инструменты

| Инструмент | Что делает |
|---|---|
| `autocad_status` | Запущен ли AutoCAD, открыт ли чертёж, какая платформа |
| `autocad_eval_lisp` | Любой AutoLISP, возвращает значение (JSON) и вывод консоли |
| `autocad_command` | Одна команда: `["_.CIRCLE",[0,0],50]`, `null` = Enter |
| `autocad_drawing_info` | Файл, единицы, границы, число объектов, слои, блоки, стили |
| `autocad_list_layers` | Слои со свойствами |
| `autocad_list_entities` | Объекты с основными DXF-данными, фильтры по типу и слою |
| `autocad_get_entity` | Полный `entget` по handle |
| `autocad_screenshot` | Скриншот окна AutoCAD |
| `autocad_type` | Отправить в командную строку произвольный текст |
| `autocad_new_drawing` | Новый чертёж из шаблона по умолчанию |

## Установка на macOS

```bash
git clone git@github.com:adamshels1/autocad-mcp.git && cd autocad-mcp
cd helper && swiftc -O acadctl.swift -o acadctl
cd ../server && uv sync
claude mcp add autocad -s user -- uv run --directory "$PWD" autocad-mcp
```

Разрешения для приложения, в котором запущен Claude (Терминал и т. п.):
- **Универсальный доступ** (Accessibility): ввод в AutoCAD и чтение командной строки.
- **Запись экрана**: `autocad_screenshot` и заголовок окна.

Переменные окружения (необязательно):
- `AUTOCAD_MCP_RESTORE_FOCUS=0`: оставлять AutoCAD на переднем плане после команды.
- `ACAD_BUNDLE_ID`: другая версия AutoCAD, по умолчанию `com.autodesk.AutoCAD2026`.
- `AUTOCAD_MCP_DIR`: папка обмена, по умолчанию `~/.cad-mcp/autocad`.

## Проверка

```bash
cd server
uv run pytest                    # юнит-тесты, AutoCAD не нужен
uv run autocad-mcp-selftest      # 10 проверок на настоящем AutoCAD с открытым чертежом
AUTOCAD_MCP_LIVE=1 uv run pytest tests/test_live.py   # то же подробнее
```

Самопроверка и живые тесты не меняют чертёж. На Mac во время них не трогайте клавиатуру: AutoCAD выходит на передний план.

## Ограничения

- В AutoCAD должен быть открыт чертёж.
- Mac: экран должен быть разблокирован, на время команды AutoCAD на долю секунды выходит вперёд.
- Код, который ждёт пользователя (`getpoint`, `entsel`, команды с кликами, диалоги), зависнет, и вызов упадёт по таймауту. `autocad_type` с пустым текстом и `enter=false` отправляет Escape.
- Windows: только полный AutoCAD, не LT. Русский текст требует AutoCAD 2021+.

## Отладка на Mac вручную

```bash
helper/acadctl window                  # окно и заголовок
helper/acadctl history | tail -20      # что AutoCAD напечатал
helper/acadctl type '(princ "hi")'     # ввести строку
```
