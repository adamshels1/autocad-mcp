# Установка на macOS

MCP-сервер `autocad` для Claude: Claude чертит в вашем запущенном AutoCAD.

Проверено на macOS 26 и AutoCAD 2026 for Mac.

## Что нужно

- **AutoCAD for Mac 2026**, полная версия. Для другой версии см. раздел «Другая версия AutoCAD» внизу.
- **Claude Code или Claude Desktop** с платной подпиской.
- **Xcode Command Line Tools** — для сборки маленькой программы-помощника.
- **uv** — менеджер Python. Сам Python ставить не нужно.

## 1. Поставить инструменты

В Терминале:

```bash
xcode-select --install          # если уже стоит, команда скажет об этом
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Закройте и снова откройте Терминал. Проверьте: `swiftc --version` и `uv --version`.

## 2. Скачать проект

```bash
git clone https://github.com/adamshels1/autocad-mcp.git ~/autocad-mcp
```

Обновление позже: `cd ~/autocad-mcp && git pull`, затем повторить шаг 3.

## 3. Собрать помощника и установить зависимости

```bash
cd ~/autocad-mcp/helper && swiftc -O acadctl.swift -o acadctl
cd ../server && uv sync
```

## 4. Выдать разрешения

Системные настройки → Конфиденциальность и безопасность. Включите приложение, в котором запускается Claude (Терминал, iTerm, Claude Desktop), в двух списках:

- **Универсальный доступ** — чтобы вводить команды в AutoCAD и читать его командную строку.
- **Запись экрана и системного аудио** — для скриншотов AutoCAD.

После включения перезапустите это приложение.

## 5. Самопроверка

Запустите AutoCAD, создайте или откройте чертёж (не вкладка Start). Затем, **не трогая клавиатуру** секунд 20:

```bash
cd ~/autocad-mcp/server
uv run autocad-mcp-selftest
```

Должно быть 10 строк `PASS` и `all 10 checks passed`. AutoCAD будет ненадолго выходить на передний план — это нормально. Чертёж самопроверка не меняет. Если есть `FAIL`, пришлите весь вывод целиком.

## 6. Подключить к Claude

**Claude Code:**

```bash
claude mcp add autocad -s user -- uv run --directory ~/autocad-mcp/server autocad-mcp
```

**Claude Desktop:** Settings → Developer → Edit Config, добавить в `claude_desktop_config.json` (замените `ИМЯ` на имя пользователя Mac):

```json
{
  "mcpServers": {
    "autocad": {
      "command": "/Users/ИМЯ/.local/bin/uv",
      "args": ["run", "--directory", "/Users/ИМЯ/autocad-mcp/server", "autocad-mcp"]
    }
  }
}
```

Перезапустите Claude. В списке инструментов появятся `autocad_*`.

## 7. Проверить в Claude

Напишите: «покажи статус AutoCAD», потом «нарисуй в AutoCAD план комнаты 5×4 м».

## Как это ведёт себя на Mac

У AutoCAD for Mac нет программного интерфейса для управления снаружи, поэтому команды вводятся в его командную строку:

- На каждую команду AutoCAD на долю секунды выходит на передний план, потом фокус возвращается.
- Экран должен быть разблокирован.
- Лучше не печатать в момент, когда Claude чертит. Если нажатия всё же попадут в команду, помощник это заметит и введёт строку заново.
- Командная строка AutoCAD должна быть видна. Включить: `Cmd+3` или команда `COMMANDLINE`.

## Если не работает

| Что видно | Что делать |
|---|---|
| `helper not built` | Не выполнен шаг 3: соберите `acadctl`. |
| `no Accessibility permission` | Шаг 4: включите «Универсальный доступ» и перезапустите Терминал или Claude. |
| `AutoCAD (...) is not running` | AutoCAD не запущен или у вас другая версия, см. ниже. |
| `No drawing is open` | Открыта вкладка Start. Создайте или откройте чертёж. |
| `could not bring AutoCAD to the front` | Экран заблокирован или поверх открыт системный диалог. |
| `AutoCAD command line not found` | Командная строка скрыта: включите её. |
| `the AutoCAD command line did not accept the text` | Во время ввода кто-то печатал или фокус ушёл в другое поле AutoCAD. Повторите команду. |
| `screencapture failed` | Шаг 4: включите «Запись экрана». |

## Другая версия AutoCAD

Сервер ищет AutoCAD 2026. Для другой версии укажите её идентификатор:

```bash
osascript -e 'id of app "AutoCAD 2025"'      # покажет, например, com.autodesk.AutoCAD2025
claude mcp add autocad -s user -e ACAD_BUNDLE_ID=com.autodesk.AutoCAD2025 -- uv run --directory ~/autocad-mcp/server autocad-mcp
```

Другие версии не проверялись. AutoCAD LT for Mac не поддерживается: в нём нет AutoLISP.

Необязательные настройки:

- `AUTOCAD_MCP_RESTORE_FOCUS=0` — оставлять AutoCAD на переднем плане после команды.
- `AUTOCAD_MCP_DIR` — папка обмена, по умолчанию `~/.cad-mcp/autocad`.
