"""Entry point for Render.

Runs a tiny HTTP server (so Render's health check on /health succeeds)
alongside the aiogram polling loop.
"""
import os
import asyncio

from aiohttp import web

import bot


async def health(_request):
    return web.Response(text="ok", content_type="text/plain")


async def main():
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/", health)

    port = int(os.getenv("PORT", "8000"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[entrypoint] health server listening on 0.0.0.0:{port}", flush=True)

    # Remove any stale webhook: with a webhook set, Telegram delivers every
    # update twice (once via webhook, once via getUpdates) and the bot
    # answers both copies -> duplicate replies.
    try:
        wh = await bot.bot.get_webhook_info()
        if wh.get("url"):
            print(f"[entrypoint] removing stale webhook: {wh.get('url')}", flush=True)
            await bot.bot.delete_webhook(drop_pending_updates=True)
        else:
            await bot.bot.delete_webhook(drop_pending_updates=False)
    except Exception as exc:
        print(f"[entrypoint] webhook check failed: {exc}", flush=True)

    await bot.dp.start_polling(bot.bot)


if __name__ == "__main__":
    asyncio.run(main())
