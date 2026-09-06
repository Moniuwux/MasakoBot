"""Configuración centralizada del bot Masako."""

from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class BotConfig:
    """Configuración inmutable del bot."""

    token: str
    command_prefix: str = "m!"
    case_insensitive: bool = True

    @classmethod
    def from_env(cls) -> "BotConfig":
        """Carga la configuración desde variables de entorno.

        Returns:
            BotConfig: Instancia de configuración del bot.

        Raises:
            RuntimeError: Si no se encuentra DISCORD_TOKEN.
        """
        load_dotenv()
        token = os.getenv("DISCORD_TOKEN")

        if not token:
            msg = "DISCORD_TOKEN no encontrado en .env"
            raise RuntimeError(msg)

        return cls(token=token)


@dataclass(frozen=True)
class EmbedConfig:
    """Configuración visual básica para embeds del bot."""

    # Color azul característico de Masako (color de su cabello)
    primary_color_hex: int = 0x7EC8E3  # Azul clarito
    primary_color_rgb: tuple[int, int, int] = (177, 126, 255)

    footer_text: str = "Masako • Tu idol favorita 💙"


@dataclass(frozen=True)
class ApiConfig:
    """Configuración de servicios HTTP externos."""

    nekos_base_url: str = os.getenv("NEKOS_API_BASE_URL", "https://nekos.best/api/v2").rstrip("/")
    http_timeout: float = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
    http_retries: int = int(os.getenv("HTTP_MAX_RETRIES", "2"))
    cat_api_key: str = os.getenv("CAT_API_KEY", "")
    cat_api_url: str = "https://api.thecatapi.com/v1"
    
    # APIs de entretenimiento
    open_meteo_url: str = "https://api.open-meteo.com/v1"
    dog_ceo_url: str = "https://dog.ceo/api"
    joke_api_url: str = "https://v2.jokeapi.dev"
    anilist_graphql_url: str = "https://graphql.anilist.co"
    anime_gifs_url: str = "https://nekos.best/api/v2/neko"


@dataclass(frozen=True)
class TursoConfig:
    """Configuración opcional de la base de datos de tickets."""

    database_url: str = os.getenv("TURSO_DATABASE_URL", os.getenv("TURSO_URL", "file:local_database.db"))
    auth_token: str = os.getenv("TURSO_AUTH_TOKEN", os.getenv("TURSO_TOKEN", ""))

    @property
    def enabled(self) -> bool:
        return bool(self.database_url)


# Instancias globales de configuración
BOT_CONFIG = BotConfig.from_env()
EMBED_CONFIG = EmbedConfig()
API_CONFIG = ApiConfig()
TURSO_CONFIG = TursoConfig()