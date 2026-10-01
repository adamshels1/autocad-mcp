# Установка на Windows

MCP-сервер `autocad` для Claude: Claude чертит в вашем запущенном AutoCAD.

> Версия для Windows пока проверена только автотестами с имитацией AutoCAD. На настоящем AutoCAD под Windows её ещё не запускали. Первым делом выполните самопроверку из шага 4 и пришлите её вывод, если что-то упадёт.

## Что нужно

- **AutoCAD 2021 или новее, полная версия.** AutoCAD LT не подойдёт: в нём нет COM-интерфейса, через который работает сервер.
- **Claude Code или Claude Desktop** с платной подпиской.
- **uv** — менеджер Python. Сам Python ставить не нужно, uv скачает его сам.

## 1. Поставить uv

В PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Закройте и снова откройте PowerShell, проверьте: `uv --version`.

## 2. Скачать проект

Если стоит git:

```powershell
git clone https://github.com/adamshels1/autocad-mcp.git C:\cad-mcp\autocad
```

Или распакуйте архив в `C:\cad-mcp\autocad`. Внутри должны быть папки `server` и `lisp`. Папка `helper` нужна только на Mac.

Обновление позже: `cd C:\cad-mcp\autocad` и `git pull`, затем `uv sync` в папке `server`.

## 3. Установить зависимости

```powershell
cd C:\cad-mcp\autocad\server
uv sync
```

## 4. Самопроверка

Запустите AutoCAD, откройте или создайте чертёж, затем:

```powershell
cd C:\cad-mcp\autocad\server
uv run autocad-mcp-selftest
```

Должно быть 10 строк `PASS` и `all 10 checks passed`. Чертёж самопроверка не меняет. Если есть `FAIL`, пришлите весь вывод целиком.

## 5. Подключить к Claude

**Claude Code:**

```powershell
claude mcp add autocad -s user -- uv run --directory C:\cad-mcp\autocad\server autocad-mcp
```

**Claude Desktop:** Settings → Developer → Edit Config, добавить в `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "autocad": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\cad-mcp\\autocad\\server", "autocad-mcp"]
    }
  }
}
```

Перезапустите Claude. В списке инструментов появятся `autocad_*`.

## 6. Проверить в Claude

Напишите: «покажи статус AutoCAD», потом «нарисуй в AutoCAD план комнаты 5×4 м».

## Если не работает

| Что видно | Что делать |
|---|---|
| `AutoCAD is not running (no COM object ...)` | AutoCAD не запущен, либо это AutoCAD LT. Claude и AutoCAD должны работать под одним пользователем и с одинаковыми правами: если один запущен «от имени администратора», а другой нет, они друг друга не видят. |
| `AutoCAD is busy` | В AutoCAD открыт диалог или идёт команда. Нажмите Esc в AutoCAD и повторите. |
| `No drawing is open` | Откройте или создайте чертёж. |
| `No answer from AutoCAD within 60s` при первом вызове | AutoCAD спрашивает, загружать ли файл из недоверенной папки. Разрешите загрузку или добавьте папку `%USERPROFILE%\.cad-mcp\autocad` в Options → Files → Trusted Locations. |
| Вместо русских букв знаки вопроса | AutoCAD старше 2021. Обновите его или используйте латиницу в именах слоёв и текстах. |
| `pywin32 is not installed` | Выполните `uv sync` в папке `server`. |

Настройки через переменные окружения (обычно не нужны):

- `AUTOCAD_PROGID` — другая программа на платформе AutoCAD, например `BricscadApp.AcadApplication`. Не проверялось.
- `AUTOCAD_MCP_DIR` — папка обмена, по умолчанию `%USERPROFILE%\.cad-mcp\autocad`.
