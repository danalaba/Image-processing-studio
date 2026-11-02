# Команди для демонстрації

Виконуйте з кореня репозиторію у VS Code. Перший термінал — запуск Compose,
другий — перевірки. Сайт: `http://localhost:8000` у Safari.

## Запуск і стан

```sh
docker compose up --build --remove-orphans
```

В іншому терміналі:

```sh
docker compose ps
```

## HTTP-балансування: без додаткового Python

```sh
for i in {1..8}
do
  curl --fail --silent --show-error http://localhost:8000/api/health
  printf '\n'
done
```

Шукайте обидва `instance_id`: `api-1` і `api-2`.

```sh
curl --fail --silent --show-error --include http://localhost:8000/api/health
docker compose logs --tail=20 nginx
```

У заголовках: `X-Load-Balancer: nginx` і `X-Instance-ID`. У Nginx-журналі —
upstream і API, який відповів. Це не доказ виконання image jobs двома workers.

## Підготовка Python для автоперевірок

Один раз до захисту, якщо Python 3.12 встановлений на Mac:

```sh
python3.12 --version
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
```

Під час показу встановлювати залежності повторно не потрібно.

Повна HTTP-перевірка спільних сесій, історії, результатів, ownership і logout:

```sh
.venv/bin/python scripts/check_load_balancing.py
```

Окрема перевірка двох реальних workers і ZIP:

```sh
.venv/bin/python scripts/check_queue.py --batch --require-two-workers
```

Два рядки з різними `job` і `worker` доводять розподіл пакетів між workers.
Дочекайтеся готовності обох процесів перед запуском. Ці скрипти створюють тестові
акаунти без виводу облікових даних, видаляють свої jobs і залишають акаунти без результатів.

## Черга й скасування

```sh
docker compose stop worker-1 worker-2
```

Створіть задачу на сайті → `QUEUED` → «Скасувати» → `CANCELLED`.
Після цього поверніть workers:

```sh
docker compose start worker-1 worker-2
```

## Відмова API та відновлення

```sh
docker compose stop api-2
curl --fail --silent --show-error http://localhost:8000/api/health
```

Очікується відповідь від `api-1`. Поверніть другий API:

```sh
docker compose start api-2
```

Для повернення всіх сервісів після демонстрацій:

```sh
docker compose up -d --wait
```

## Якщо щось не відповідає

```sh
docker compose ps
docker compose logs --tail=30 nginx api-1 api-2
docker compose logs --tail=30 worker-1 worker-2 scheduler
```

`docker compose start` лише запускає процес, йому може знадобитися кілька секунд.
`studio.dispatch ... succeeded` — службова перевірка, а не обробка фото.
Надійна ознака виконання фото — `COMPLETED` і валідний PNG/ZIP, а workers — поле `worker_id`.

Завершення показу зі збереженням даних:

```sh
docker compose down
```

Іменовані томи лишаються. Прапорець `-v` для цієї демонстрації не використовуйте:
він видаляє збережені акаунти, історію та результати.
