# Image Processing Studio

Навчальний вебзастосунок: завантаження одного JPG, PNG або WebP, зміна розміру
зі збереженням пропорцій і завантаження результату у PNG. FastAPI обслуговує API
та статичний інтерфейс; Pillow обробляє зображення.

## Структура

```text
backend/
  app/                    # FastAPI, обробка зображень, обмеження
  tests/                  # unittest: API та зміна розміру
  requirements.txt
  requirements-dev.txt
frontend/                 # HTML, CSS, JavaScript
Dockerfile
compose.yaml
```

## Локальний запуск (macOS / VS Code)

Потрібен Python 3.12. Відкрийте папку репозиторію у VS Code та виконайте
в терміналі з кореня проєкту:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements-dev.txt
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Відкрийте у браузері адресу `http://127.0.0.1:8000`. Оберіть зображення,
задайте максимальні ширину й висоту та натисніть «Обробити зображення».
Для зупинки сервера натисніть Ctrl+C.

## Тести

З кореня проєкту з активованим віртуальним середовищем:

```sh
PYTHONPATH=backend python -m unittest discover -s backend/tests -v
```

Наявний набір містить 21 тест: API, інтерфейс, формати зображень, пропорції,
прозорість, EXIF-орієнтація, некоректні файли, обмеження запитів і зайнятість сервера.

## Docker Compose

Потрібен запущений Docker Desktop із Docker Compose:

```sh
docker compose up --build
```

Застосунок доступний на порту 8000. Зупинка: Ctrl+C, потім `docker compose down`.
Docker збирає backend та frontend безпосередньо з цього репозиторію.
У керованому хмарному середовищі з власним TLS-проксі Dockerfile також підтримує
необов'язковий BuildKit secret `proxy_ca` для довіреного CA bundle під час pip install.

## Поточні можливості та наступні етапи

Backend приймає один файл до 10 MiB, до 12 млн пікселів і 12000 px на сторону.
Результат вписується в рамку до 4096×4096 px без збільшення оригіналу.
Одночасно один процес обробляє максимум два зображення.

Наразі працює один API. Автентифікація, історія задач у PostgreSQL, Redis/Celery,
прогрес, скасування, Nginx і балансування ще не реалізовані.
Для майбутньої демонстрації балансування потрібні окремі перевірки:

1. HTTP-запити через Nginx отримують різні `instance_id` від двох API.
2. Кілька фонових задач виконуються на двох Celery workers; докази — job ID,
   worker ID та журнали. Одна задача автоматично між workers не ділиться.

Обидва API мають використовувати спільні PostgreSQL, Redis і файловий том.
