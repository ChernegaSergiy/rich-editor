# rich-editor

Веб-редактор Telegram Rich-повідомлень (Bot API 10.3, `sendRichMessage`).

Адмін без Premium збирає допис у браузері — текст абзацами, слайдшоу з фото — і публікує в канал ботом. Правило: довгий текст іде тілом допису (`paragraph`), а не сірим підписом (`caption`).

## Стек

- Backend: Python 3.12, тільки stdlib (без залежностей)
- Frontend: один статичний `index.html`, vanilla JS
- Зберігання: SQLite + `data/uploads` (пости, `file_id` для редагування без перезаливу)
- Деплой: Docker → `blog-server`, мережа `proxy-net`, домен `rich.chernega.eu.org`

## Структура (план)

```
app/
  backend.py        # HTTP-сервер, Telegram API, збірка HTML
  static/index.html # редактор блоків, превʼю, список постів
Dockerfile
docker-compose.yml
rich.conf           # nginx vhost для nginx-proxy
```

## Локальний запуск

```sh
cp .env.example .env   # BOT_TOKEN, ADMIN_KEY, CHANNEL
python3 app/backend.py
# http://127.0.0.1:8080
```
