# Internet Speed

Скрипт скачивает файл 10 раз подряд. Каждый следующий запрос начинается после полного чтения предыдущего ответа. Файл на диск не записывается.

## Запуск

Установите Python 3.13 или новее. Откройте терминал в папке проекта. Для другого замера замените адрес Hetzner прямой ссылкой HTTP или HTTPS без редиректа. Файл в примере занимает 100 МиБ, за 10 загрузок уйдёт 1000 МиБ трафика плюс служебные данные.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m speedcheck "https://fsn1-speed.hetzner.com/100MB.bin"
```

### Linux и macOS

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m speedcheck "https://fsn1-speed.hetzner.com/100MB.bin"
```

Запуск проверен на Windows 11 с Python 3.13.14. Команды для Linux и macOS пока не проверены.

### Параметры

- `--no-progress` отключает индикатор загрузки. По умолчанию он виден в интерактивном терминале.
- `--timeout 30` задаёт таймаут отдельной сетевой операции в секундах. По умолчанию 15 секунд.
- `--help` показывает справку.

## Результат

Пример замера с Hetzner

```text
Completed requests             10/10
Download speed         140.24 Mbit/s
Average request time         5.982 s
Downloaded data           1048.58 MB
Downloaded bytes          1048576000
```

Скрипт считает байты тела ответа и измеряет время от начала запроса до последнего байта.

- Скорость в мегабитах в секунду (`Mbit/s`) = байты за 10 загрузок × 8 / суммарное время в секундах / 1 000 000.
- Среднее время запроса в секундах (`s`) = суммарное время / 10.
- Объём выводится в байтах и мегабайтах (`MB`). 1 MB = 1 000 000 байт.

## Ошибки

При сетевой ошибке, таймауте, обнаруженном обрыве ответа или статусе HTTP, отличном от 200, скрипт останавливается. Итоговая скорость выводится только после 10 полных загрузок.

Повторы не реализованы. При HTTP 429 смените источник или дождитесь сброса лимита и запустите замер снова. Поддержка `Retry-After` оставлена на будущее.

## Проверки

Запустите тесты и Ruff в PowerShell

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format --check .
```

Для замера памяти и сравнения запусков с прогрессом и без него запустите локальную проверку

```powershell
.\.venv\Scripts\python -m checks.benchmark
```
