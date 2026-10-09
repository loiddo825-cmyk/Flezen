# Flezen Telegram Bot (starter)

A Telegram bot webhook starter for Render. It supports:
- `/start` and `/help`
- Direct HTTPS video-file URLs ending in `.mp4`, `.m4v`, `.mov`, `.webm` (up to 45 MiB)
- Detection of Flezen share links

## Important limitation
This starter does **not** extract videos from Flezen share pages. The Flezen adapter is intentionally not implemented because a verified official/authorized download API or documented flow has not been provided. Add an adapter only for a source you are authorized to access.

## Deploy on Render
1. Upload these files to a GitHub repository.
2. In Render, create a **Web Service** from that repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn bot:app --host 0.0.0.0 --port $PORT`
5. Add environment variable `BOT_TOKEN` with the token from @BotFather.
6. Add `WEBHOOK_SECRET` as a random long secret (Render blueprint may generate it automatically).
7. Deploy. Render sets `RENDER_EXTERNAL_URL` automatically.

The free Render web service can sleep when idle, so uninterrupted 24/7 operation is not guaranteed on the free plan.

## Security
- Never commit your bot token or `.env` file.
- Rotate the token with @BotFather if it is exposed.
- Only download videos you have permission to access.
