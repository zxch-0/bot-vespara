"""Chargement de la configuration depuis l'environnement / le fichier .env."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .constants import DEFAULT_STAFF_PERMISSION, STAFF_PERMISSIONS

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    """Charge le .env local (sans écraser les variables déjà définies)."""
    for candidate in (ROOT / ".env", Path.cwd() / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return


def _env(*names: str) -> str | None:
    """Renvoie la première variable d'environnement non vide parmi `names`."""
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _env_int(*names: str) -> int | None:
    raw = _env(*names)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        log.warning("Valeur numérique invalide pour %s : %r (ignorée)", names[0], raw)
        return None


def _env_bool(*names: str, default: bool = False) -> bool:
    raw = _env(*names)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "y", "on", "oui", "vrai"}


def _resolve_path(raw: str | None) -> Path:
    if not raw:
        return ROOT / "data" / "vespara.json"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path


@dataclass(slots=True)
class Settings:
    """Configuration complète du bot."""

    token: str = ""
    guild_id: int | None = None
    staff_role_id: int | None = None
    log_channel_id: int | None = None
    database_path: Path = field(default_factory=lambda: ROOT / "data" / "vespara.json")
    staff_permission: str = DEFAULT_STAFF_PERMISSION
    brand: str = "Vespara"
    tagline: str = "Le serveur chill"
    port: int = 8080
    self_ping: bool = True
    command_scope: str = "guild"  # guild | global | both
    log_level: str = "INFO"

    @property
    def staff_permission_label(self) -> str:
        return STAFF_PERMISSIONS.get(self.staff_permission, self.staff_permission)

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    def describe(self) -> str:
        """Résumé lisible (jamais de token en clair !)."""
        scope = self.command_scope
        if self.guild_id:
            scope = f"guild {self.guild_id}"
        return (
            f"guild_scope={scope}, staff_role={self.staff_role_id or 'non défini'}, "
            f"staff_permission={self.staff_permission}, db={self.database_path}, "
            f"port={self.port}"
        )


def load_settings() -> Settings:
    """Construit la configuration à partir de l'environnement."""
    _load_env()

    staff_permission = (_env("STAFF_PERMISSION") or DEFAULT_STAFF_PERMISSION).lower().replace("-", "_")
    if staff_permission not in STAFF_PERMISSIONS:
        fallback = DEFAULT_STAFF_PERMISSION
        log.warning(
            "STAFF_PERMISSION=%r inconnue, utilisation de %r. Valeurs possibles : %s",
            staff_permission,
            fallback,
            ", ".join(sorted(STAFF_PERMISSIONS)),
        )
        staff_permission = fallback

    scope = (_env("COMMAND_SCOPE") or "guild").lower()
    if scope not in {"guild", "global", "both"}:
        log.warning("COMMAND_SCOPE=%r invalide (guild|global|both), utilisation de 'guild'", scope)
        scope = "guild"

    settings = Settings(
        # Discord et Render utilisent parfois des noms différents : on accepte les deux.
        token=_env("DISCORD_TOKEN", "DISCORD_BOT_TOKEN", "TOKEN") or "",
        guild_id=_env_int("GUILD_ID", "DISCORD_GUILD_ID", "SERVER_ID"),
        staff_role_id=_env_int("STAFF_ROLE_ID", "MOD_ROLE_ID"),
        log_channel_id=_env_int("LOG_CHANNEL_ID"),
        database_path=_resolve_path(_env("DATABASE_PATH", "DATA_PATH")),
        staff_permission=staff_permission,
        brand=_env("BOT_NAME", "BRAND") or "Vespara",
        tagline=_env("BOT_TAGLINE") or "Le serveur chill",
        port=_env_int("PORT") or 8080,
        self_ping=_env_bool("SELF_PING", default=True),
        command_scope=scope,
        log_level=(_env("LOG_LEVEL") or "INFO").upper(),
    )
    return settings
