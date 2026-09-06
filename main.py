"""Punto de entrada principal de Masako.

Ejemplo de uso:
    $ python main.py
"""

import asyncio
import logging
import sys

import discord

from bot import create_bot
from config import BOT_CONFIG
from logger_config import setup_logger


# Configuración de logging global
logger = setup_logger("Masako", level=logging.INFO)


class BotLifecycleManager:
    """Gestor del ciclo de vida del bot."""

    def __init__(self) -> None:
        """Inicializa el gestor."""
        self.bot = create_bot()

    async def start(self) -> None:
        """Inicia el bot y maneja excepciones críticas."""
        try:
            logger.info("🚀 Iniciando Masako v%s...", self.bot.version)
            await self.bot.start(BOT_CONFIG.token)

        except discord.LoginFailure:
            logger.critical(
                "❌ Error de autenticación: Token de Discord inválido"
            )
            sys.exit(1)

        except KeyboardInterrupt:
            logger.info("⏹️  Masako detenida por el usuario (Ctrl+C)")

        except discord.ConnectionClosed as exc:
            logger.error(
                "❌ Conexión a Discord cerrada inesperadamente: %s",
                exc,
            )
            sys.exit(1)

        except Exception:
            logger.exception(
                "❌ Error crítico no manejado durante la ejecución"
            )
            sys.exit(1)

        finally:
            await self.bot.close()


async def main() -> None:
    """Función principal."""
    manager = BotLifecycleManager()
    await manager.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Masako terminada")
    except Exception:
        logger.exception("Error fatal durante la inicialización")
        sys.exit(1)
