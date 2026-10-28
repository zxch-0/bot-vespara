"""Petit serveur HTTP (santé + page de statut) — indispensable sur Render.

Render exige qu'un service web écoute sur le port fourni par la variable
d'environnement `PORT`. Ce module expose :

* `/`            → page de statut publique (HTML autonome, sans CDN externe)
* `/health`      → JSON minimal pour les health checks
* `/api/status`  → statistiques temps réel utilisées par la page
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import platform
from typing import TYPE_CHECKING, Any

import aiohttp
import discord
from aiohttp import web

from . import __version__
from .helpers import humanize_duration

if TYPE_CHECKING:  # pragma: no cover
    from .main import VesparaBot

log = logging.getLogger(__name__)

INDEX_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="theme-color" content="#8b5cf6" />
<title>__BRAND__ — Statut du bot</title>
<style>
  :root {
    --violet: #8b5cf6;
    --violet-soft: #a78bfa;
    --bg: #0a0612;
    --card: rgba(23, 16, 38, 0.72);
    --border: rgba(167, 139, 250, 0.18);
    --text: #ece8f7;
    --muted: #a89fc0;
    --green: #3ba55d;
    --red: #ed4245;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; min-height: 100%; }
  body {
    font-family: "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
    color: var(--text);
    background:
      radial-gradient(circle at 15% 0%, rgba(139, 92, 246, 0.35), transparent 45%),
      radial-gradient(circle at 85% 10%, rgba(59, 130, 246, 0.22), transparent 40%),
      radial-gradient(circle at 50% 100%, rgba(236, 72, 153, 0.16), transparent 45%),
      var(--bg);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 32px 18px;
  }
  .shell { width: 100%; max-width: 780px; }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 26px;
    padding: 34px;
    backdrop-filter: blur(18px);
    box-shadow: 0 30px 80px rgba(0, 0, 0, 0.45);
  }
  .brand { display: flex; align-items: center; gap: 16px; }
  .logo {
    width: 58px; height: 58px; border-radius: 18px;
    display: grid; place-items: center; font-size: 28px;
    background: linear-gradient(145deg, #8b5cf6, #5b21b6);
    box-shadow: 0 12px 30px rgba(139, 92, 246, 0.45);
  }
  h1 { margin: 0; font-size: 26px; letter-spacing: 0.4px; }
  .tagline { margin: 2px 0 0; color: var(--muted); font-size: 14px; }
  .status-row {
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px; flex-wrap: wrap; margin: 26px 0 20px;
  }
  .pill {
    display: inline-flex; align-items: center; gap: 9px;
    font-size: 13px; font-weight: 600;
    padding: 8px 14px; border-radius: 999px;
    background: rgba(59, 165, 93, 0.12);
    border: 1px solid rgba(59, 165, 93, 0.32);
    color: #7ee2a0;
  }
  .pill.offline { background: rgba(237, 66, 69, 0.12); border-color: rgba(237, 66, 69, 0.35); color: #ff9a9c; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 4px rgba(59,165,93,0.18); animation: pulse 2.4s infinite; }
  .pill.offline .dot { background: var(--red); box-shadow: 0 0 0 4px rgba(237,66,69,0.18); animation: none; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .45; } }
  .version { color: var(--muted); font-size: 13px; }
  .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
  .stat {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 16px; padding: 16px;
  }
  .stat .label { font-size: 12px; text-transform: uppercase; letter-spacing: .09em; color: var(--muted); }
  .stat .value { margin-top: 6px; font-size: 22px; font-weight: 700; }
  .section-title { margin: 28px 0 12px; font-size: 13px; text-transform: uppercase; letter-spacing: .12em; color: var(--muted); }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip {
    font-size: 13px; padding: 7px 12px; border-radius: 10px;
    background: rgba(139, 92, 246, 0.12);
    border: 1px solid rgba(139, 92, 246, 0.25);
    color: #d9cffb; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  footer { margin-top: 26px; text-align: center; color: var(--muted); font-size: 12px; }
  footer a { color: var(--violet-soft); text-decoration: none; }
  @media (max-width: 560px) {
    .card { padding: 24px; border-radius: 20px; }
    .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    h1 { font-size: 22px; }
  }
</style>
</head>
<body>
  <main class="shell">
    <div class="card">
      <div class="brand">
        <div class="logo">🍃</div>
        <div>
          <h1>__BRAND__</h1>
          <p class="tagline">__TAGLINE__ · bot Discord</p>
        </div>
      </div>

      <div class="status-row">
        <span class="pill" id="status-pill"><span class="dot"></span><span id="status-text">Connexion…</span></span>
        <span class="version">v__VERSION__</span>
      </div>

      <div class="grid">
        <div class="stat"><div class="label">Serveurs</div><div class="value" data-stat="guilds">—</div></div>
        <div class="stat"><div class="label">Membres</div><div class="value" data-stat="users">—</div></div>
        <div class="stat"><div class="label">Latence</div><div class="value" data-stat="latency_ms">—</div></div>
        <div class="stat"><div class="label">En ligne depuis</div><div class="value" data-stat="uptime_human">—</div></div>
        <div class="stat"><div class="label">Giveaways actifs</div><div class="value" data-stat="giveaways">—</div></div>
        <div class="stat"><div class="label">Réponses auto</div><div class="value" data-stat="autoresponses">—</div></div>
      </div>

      <p class="section-title">Commandes publiques</p>
      <div class="chips">
        <span class="chip">/menu</span>
        <span class="chip">/rules</span>
        <span class="chip">/giveaways</span>
        <span class="chip">/boule</span>
        <span class="chip">/userinfo</span>
        <span class="chip">/serverinfo</span>
        <span class="chip">/roleinfo</span>
        <span class="chip">/avatar</span>
        <span class="chip">/banner</span>
        <span class="chip">/ping</span>
        <span class="chip">/botinfo</span>
      </div>

      <footer>
        Bot hébergé sur Render · <span id="python">Python</span> · discord.py<br />
        La page se rafraîchit automatiquement toutes les 15 secondes.
      </footer>
    </div>
  </main>

<script>
  const pill = document.getElementById("status-pill");
  const statusText = document.getElementById("status-text");

  function setStatus(online, label) {
    pill.classList.toggle("offline", !online);
    statusText.textContent = label;
  }

  async function refresh() {
    try {
      const response = await fetch("api/status", { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const data = await response.json();
      document.querySelectorAll("[data-stat]").forEach((el) => {
        const key = el.getAttribute("data-stat");
        const value = data[key];
        el.textContent = value === undefined || value === null ? "—" : value;
      });
      if (data.python) {
        document.getElementById("python").textContent = "Python " + data.python;
      }
      const online = data.status === "online";
      setStatus(online, online ? "En ligne" : data.status === "starting" ? "Démarrage…" : "Hors ligne");
    } catch (error) {
      setStatus(false, "Hors ligne");
    }
  }

  refresh();
  setInterval(refresh, 15000);
</script>
</body>
</html>
"""


class StatusServer:
    """Serveur aiohttp embarqué dans le bot."""

    def __init__(self, bot: "VesparaBot") -> None:
        self.bot = bot
        self.runner: web.AppRunner | None = None
        self._ping_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ #
    # Cycle de vie
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/", self.handle_index)
        app.router.add_get("/health", self.handle_health)
        app.router.add_get("/healthz", self.handle_health)
        app.router.add_get("/api/status", self.handle_status)

        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        port = int(self.bot.settings.port)
        site = web.TCPSite(self.runner, "0.0.0.0", port)
        try:
            await site.start()
        except OSError as exc:
            log.error("Impossible de démarrer le serveur web sur le port %s : %s", port, exc)
            return

        log.info("Serveur web de statut à l'écoute sur 0.0.0.0:%s", port)

        if self.bot.settings.self_ping:
            external = os.getenv("RENDER_EXTERNAL_URL")
            if external:
                self._ping_task = asyncio.create_task(self._self_ping(external), name="vespara-self-ping")
                log.info("Auto-ping activé vers %s", external)

    async def stop(self) -> None:
        if self._ping_task is not None:
            self._ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ping_task
            self._ping_task = None
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None

    # ------------------------------------------------------------------ #
    # Handlers
    # ------------------------------------------------------------------ #
    async def handle_index(self, request: web.Request) -> web.Response:
        html = (
            INDEX_HTML.replace("__BRAND__", self.bot.settings.brand)
            .replace("__TAGLINE__", self.bot.settings.tagline)
            .replace("__VERSION__", __version__)
        )
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def handle_health(self, request: web.Request) -> web.Response:
        ready = self.bot.is_ready()
        return web.json_response(
            {"status": "ok" if ready else "starting", "version": __version__},
            status=200,
        )

    async def handle_status(self, request: web.Request) -> web.Response:
        return web.json_response(self.status_payload())

    # ------------------------------------------------------------------ #
    def status_payload(self) -> dict[str, Any]:
        bot = self.bot
        ready = bot.is_ready()
        try:
            stats = bot.db.stats()
        except Exception:  # pragma: no cover - page de statut jamais fatale
            stats = {"active_giveaways": 0, "autoresponses": 0}

        users = sum(guild.member_count or 0 for guild in bot.guilds) if ready else 0
        latency = round(bot.latency * 1000) if ready else 0
        uptime = bot.uptime
        return {
            "status": "online" if ready else ("starting" if bot.user is None else "offline"),
            "brand": bot.settings.brand,
            "version": __version__,
            "uptime": int(uptime),
            "uptime_human": humanize_duration(uptime),
            "latency_ms": latency,
            "guilds": len(bot.guilds) if ready else 0,
            "users": users,
            "commands": getattr(bot, "command_count", None) or len(bot.tree.get_commands()),
            "giveaways": stats.get("active_giveaways", 0),
            "autoresponses": stats.get("autoresponses", 0),
            "python": platform.python_version(),
            "discord_py": discord.__version__,
        }

    # ------------------------------------------------------------------ #
    async def _self_ping(self, base_url: str) -> None:
        """Garde le service Render réveillé (offre gratuite)."""
        target = base_url.rstrip("/") + "/health"
        await asyncio.sleep(45)
        timeout = aiohttp.ClientTimeout(total=25)
        while True:
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(target) as response:
                        await response.read()
            except asyncio.CancelledError:  # pragma: no cover
                raise
            except Exception as exc:  # pragma: no cover - réseau
                log.debug("Auto-ping échoué : %s", exc)
            await asyncio.sleep(600)
