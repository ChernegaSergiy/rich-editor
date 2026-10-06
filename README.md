# rich-editor

[![Docker Image CI](https://github.com/ChernegaSergiy/rich-editor/actions/workflows/docker-image.yml/badge.svg)](https://github.com/ChernegaSergiy/rich-editor/actions/workflows/docker-image.yml)

Web editor for Telegram Rich Messages (Bot API 10.3, `sendRichMessage`).

An admin with no Premium composes a post in the browser — body text in paragraphs, photos as a slideshow — and publishes it to the channel via bot. Rule: long text goes into the post body (`paragraph`), not into the gray caption (`caption`).

## Stack

- Backend: Python 3.12, stdlib only (zero dependencies)
- Frontend: single static `index.html`, Pico.css + vanilla JS
- Storage: SQLite + `data/uploads` (posts, `file_id`s for edit reuse)
- Deploy: Docker → `blog-server`, `proxy-net` network, `rich.chernega.eu.org`

## Layout

```
app/
  backend.py        # HTTP server, Telegram API, HTML builder
  static/index.html # block editor, preview, post list
Dockerfile
docker-compose.yml
rich.conf           # nginx vhost for nginx-proxy
.env.example        # BOT_TOKEN, ADMIN_KEY, CHANNEL (copy to .env)
```

## Local run

```sh
cp .env.example .env   # BOT_TOKEN, ADMIN_KEY, CHANNEL
python3 app/backend.py
# http://127.0.0.1:8080
```

## License

This project is licensed under the CSSM Unlimited License v2.0 (CSSM-ULv2). See the [LICENSE](LICENSE) file for details.
