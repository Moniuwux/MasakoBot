"""Bot principal Masako - Arquitectura profesional."""

import logging
import json
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import BOT_CONFIG
from logger_config import setup_logger
from utils.database import db
from utils.http import http
from utils.nekos_api import client
from utils.turso_database import turso_db


# Configuración de logging
logger = setup_logger("Masako", level=logging.INFO)


class Masako(commands.Bot):
    """Bot de Discord profesional con arquitectura modular.

    Attributes:
        version: Versión del bot.
        author: Autor del bot.
    """

    version: str = "1.0.0"
    author: str = "moniuwu"

    def __init__(self) -> None:
        """Inicializa el bot con configuración profesional."""
        intents = self._setup_intents()
        self._tree_synced = False
        self._synced_guilds: set[int] = set()
        self._application_commands: list[Any] = []
        self._prefixes = self._load_prefixes()
        self._presence_index = 0

        super().__init__(
            command_prefix=self._get_prefixes,
            intents=intents,
            help_command=None,
            case_insensitive=BOT_CONFIG.case_insensitive,
        )
        # Red de seguridad GLOBAL: cualquier excepción no manejada en
        # cualquier cog responde de forma degradada en vez de quedarse
        # muda («está pensando...») o lanzar tracebacks sin control.
        self.tree.on_error = self._on_app_command_error

    def _presence_activities(self) -> list[discord.BaseActivity]:
        """Genera estados cortos con información actual del bot."""
        server_count = len(self.guilds)
        server_label = "servidor" if server_count == 1 else "servidores"
        return [
            discord.Activity(
                type=discord.ActivityType.watching,
                name="/help",
            ),
            discord.Game(name=f"Apoyando a {server_count} {server_label}"),
            discord.Game(name=f"Gestionando {server_count} {server_label}"),
            discord.Activity(
                type=discord.ActivityType.listening,
                name="tus sugerencias",
            ),
        ]

    async def _update_presence(self) -> None:
        """Actualiza la presencia sin detener el bot si Discord falla."""
        activities = self._presence_activities()
        activity = activities[self._presence_index % len(activities)]
        self._presence_index = (self._presence_index + 1) % len(activities)
        try:
            await self.change_presence(status=discord.Status.dnd, activity=activity)
        except discord.HTTPException:
            logger.warning("No se pudo actualizar la presencia del bot")

    @tasks.loop(seconds=30)
    async def _presence_loop(self) -> None:
        await self._update_presence()

    @_presence_loop.before_loop
    async def _before_presence_loop(self) -> None:
        await self.wait_until_ready()

    @staticmethod
    def _load_prefixes() -> dict[int, str]:
        """Carga los prefijos personalizados guardados por servidor."""
        try:
            with Path("prefixes.json").open("r", encoding="utf-8") as file:
                data = json.load(file)
            return {int(guild_id): str(prefix) for guild_id, prefix in data.items()}
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return {}

    def _save_prefixes(self) -> None:
        """Guarda los prefijos personalizados por servidor."""
        with Path("prefixes.json").open("w", encoding="utf-8") as file:
            json.dump(self._prefixes, file, ensure_ascii=False, indent=2)

    def get_guild_prefix(self, guild_id: int | None) -> str:
        """Devuelve el prefijo configurado o el prefijo predeterminado."""
        if guild_id is None:
            return BOT_CONFIG.command_prefix
        return self._prefixes.get(guild_id, BOT_CONFIG.command_prefix)

    def set_guild_prefix(self, guild_id: int, prefix: str | None) -> None:
        """Configura o restaura el prefijo de un servidor."""
        if prefix is None:
            self._prefixes.pop(guild_id, None)
        else:
            self._prefixes[guild_id] = prefix
        self._save_prefixes()

    def _get_prefixes(self, bot: commands.Bot, message: discord.Message) -> list[str]:
        """Acepta prefijo del servidor, ``masako`` y menciones al bot."""
        prefix = self.get_guild_prefix(message.guild.id if message.guild else None)
        return commands.when_mentioned_or(prefix, "masako ", "Masako ")(bot, message)

    @staticmethod
    def _interaction_expired(error: BaseException) -> bool:
        """Detecta interacciones muertas ante Discord (10062/10063)."""
        code = getattr(error, "code", None)
        return isinstance(code, int) and code in {10062, 10063}

    async def _on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Manejador global de errores para TODOS los slash commands."""
        original = getattr(error, "original", error)
        nombre = getattr(getattr(interaction, "command", None), "qualified_name", "?")

        if isinstance(original, app_commands.CommandSignatureMismatch):
            logger.warning(
                "Firma antigua detectada para '%s'; resincronizando comandos globales.",
                nombre,
            )
            try:
                await self.tree.sync()
            except discord.HTTPException as exc:
                logger.error("No se pudo resincronizar el árbol de comandos: %s", exc)
            message = "⚠️ El comando fue actualizado. Vuelve a ejecutarlo en unos segundos."
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(message, ephemeral=True)
                else:
                    await interaction.followup.send(message, ephemeral=True)
            except discord.HTTPException as exc:
                if not self._interaction_expired(exc) and getattr(exc, "code", None) != 40060:
                    raise
            return

        if isinstance(original, app_commands.CheckFailure):
            logger.warning("Permisos insuficientes para el comando '%s'", nombre)
            message = "No tienes permisos suficientes para usar este comando."
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(message, ephemeral=True)
                else:
                    await interaction.followup.send(message, ephemeral=True)
            except discord.HTTPException as exc:
                if not self._interaction_expired(exc) and getattr(exc, "code", None) != 40060:
                    raise
            return

        if self._interaction_expired(original):
            logger.warning(
                "Interacción '%s' expiró ante Discord antes del ACK (red lenta); "
                "se intentará responder por canal.",
                nombre,
            )
            channel = getattr(interaction, "channel", None)
            if isinstance(channel, discord.abc.Messageable):
                try:
                    await channel.send("❌ El comando tardó demasiado. Inténtalo de nuevo.")
                except discord.HTTPException:
                    pass
            return
        else:
            logger.error(
                "Error no controlado en comando '%s': %s: %s",
                nombre, type(original).__name__, original,
            )

        channel = getattr(interaction, "channel", None)
        try:
            if not interaction.response.is_done():
                try:
                    await interaction.response.send_message(
                        "❌ El comando falló. Inténtalo de nuevo.", ephemeral=True
                    )
                    return
                except discord.HTTPException as exc:
                    if not self._interaction_expired(exc):
                        raise
                    logger.warning("Tampoco se pudo ACK la interacción fallida.")
            elif not self._interaction_expired(original):
                try:
                    await interaction.followup.send(
                        "❌ El comando falló. Inténtalo de nuevo.", ephemeral=True
                    )
                    return
                except discord.HTTPException as exc:
                    if not self._interaction_expired(exc):
                        raise
            # Último recurso: mensaje normal por el canal.
            if channel is not None:
                try:
                    await channel.send("❌ El comando falló. Inténtalo de nuevo.")
                except discord.HTTPException:
                    pass
        except Exception:
            logger.exception("No se pudo notificar el fallo del comando '%s'", nombre)

    @staticmethod
    def _setup_intents() -> discord.Intents:
        """Configura los intents necesarios del bot.

        Returns:
            discord.Intents: Intents configurados minimalmente.

        Note:
            Se recomienda no activar message_content a menos que sea estrictamente
            necesario, por razones de privacidad y rendimiento.
        """
        intents = discord.Intents.default()
        intents.message_content = True
        return intents

    async def sync_application_commands(self) -> bool:
        """Registra una única copia del árbol slash en cada servidor."""
        commands_to_register = list(self.tree.get_commands())
        self._application_commands = commands_to_register

        try:
            # Elimina cualquier copia global anterior para evitar duplicados.
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
        except discord.HTTPException as exc:
            logger.error("❌ No se pudo limpiar el registro global: %s", exc)
            return False

        registered = True
        for guild in self.guilds:
            try:
                self.tree.clear_commands(guild=guild)
                for command in commands_to_register:
                    self.tree.add_command(command, guild=guild)
                guild_synced = await self.tree.sync(guild=guild)
                logger.info("✓ %d comandos únicos registrados en %s (%s)", len(guild_synced), guild.name, guild.id)
            except discord.HTTPException as exc:
                registered = False
                logger.error(
                    "❌ No se pudieron sincronizar comandos en %s (%s): %s",
                    guild.name, guild.id, exc,
                )

        logger.info("✓ Registro de comandos completado en %d servidor(es)", len(self.guilds))
        print(f"Comandos registrados por servidor: {len(commands_to_register)}")
        return registered

    async def sync_guild_commands(self, guild: discord.Guild) -> None:
        """Registra el árbol completo una sola vez en un servidor nuevo."""
        try:
            commands_to_register = self._application_commands
            self.tree.clear_commands(guild=guild)
            for command in commands_to_register:
                self.tree.add_command(command, guild=guild)
            guild_synced = await self.tree.sync(guild=guild)
            logger.info("✓ %d comandos registrados en el nuevo servidor %s", len(guild_synced), guild.name)
        except discord.HTTPException as exc:
            logger.error("❌ No se pudieron registrar comandos en %s: %s", guild.name, exc)

    def _decorate_command_descriptions(self) -> None:
        """Añade un emoji visual a comandos que aún no lo tienen."""
        emojis = {
            "ping": "🏓", "prefix": "⚙️", "weather": "🌤️", "weather-config": "⚙️", "trivia": "🧠",
            "anime-news": "📰", "anime-config": "⚙️", "ticket": "🎫",
            "audit": "🔎", "modstats": "📊", "health": "🩺", "help": "❓",
            "serverinfo": "🏠", "userinfo": "👤", "avatar": "🖼️",
            "channelinfo": "📺", "roleinfo": "🎭", "memberlist": "👥",
            "nsfw": "🔞", "interact": "✨", "8ball": "🎱", "cat": "🐱", "dog": "🐶",
            "choose": "🔀", "coin": "🪙", "joke": "😂", "meme": "🖼️",
            "roll": "🎲", "say": "💬", "rps": "✂️", "ship": "💘",
            "kick": "👢", "ban": "🔨", "mute": "🔇", "purge": "🧹", "sanciones": "📋",
            "poll": "📊", "remindme": "⏰", "afk": "💤",
        }
        for command in self.tree.walk_commands():
            if not command.description:
                continue
            first_char = command.description.strip()[:1]
            if first_char and not first_char.isalnum():
                continue
            emoji = emojis.get(command.name, "✨")
            command.description = f"{emoji} {command.description}"[:100]

    async def setup_hook(self) -> None:
        """Hook de inicialización asíncrona.

        Se ejecuta después de que el bot inicia la conexión pero antes de
        que esté completamente listo. Carga todos los cogs disponibles.
        """
        await db.setup()
        await http.start()
        await client.start()

        cogs_to_load = [
            "cogs.general",
            "cogs.interactions",
            "cogs.reactions_extra",
            "cogs.moderation",
            "cogs.entertainment",
            "cogs.anime_news",
            "cogs.trivia",
            "cogs.weather",
            "cogs.nsfw",
            "cogs.utility",
            "cogs.tickets",
        ]

        for cog in cogs_to_load:
            try:
                if cog in self.extensions:
                    logger.debug("Cog %s ya estaba cargado; se omite.", cog)
                    continue
                await self.load_extension(cog)
                if cog == "cogs.tickets" and self.get_cog("TicketsCog") is None:
                    logger.warning("⚠ Cog de tickets omitido: Turso no está habilitado")
                else:
                    logger.info(f"✓ Cog {cog} cargado exitosamente")
            except Exception:
                logger.exception("❌ Error cargando %s", cog)

        self._decorate_command_descriptions()

        logger.info("✓ Setup de Masako v2.0.0 completado")

    async def on_ready(self) -> None:
        """Event handler: Bot conectado y listo.

        Se ejecuta cuando el bot establece conexión con Discord
        y está completamente inicializado.
        """
        if self.user is None:
            logger.error("El usuario del bot no está disponible")
            return

        logger.info(
            "✓ Masako conectada como %s (%s)",
            self.user,
            self.user.id,
        )
        await self._update_presence()
        if not self._presence_loop.is_running():
            self._presence_loop.start()
        logger.debug(
            "✓ Conectada a %d servidor(es)",
            len(self.guilds),
        )
        if not self._tree_synced:
            self._tree_synced = await self.sync_application_commands()

        utility = self.get_cog("Utility")
        start_tasks = getattr(utility, "start_background_tasks", None)
        if callable(start_tasks):
            start_tasks()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Event handler: Bot añadido a un nuevo servidor.

        Args:
            guild: Servidor al que se unió el bot.
        """
        logger.info(
            "➕ Bot añadido a servidor: %s (%s) | Miembros: %d",
            guild.name,
            guild.id,
            guild.member_count or 0,
        )
        await self.sync_guild_commands(guild)

    async def close(self) -> None:
        """Cierra la conexión del bot de forma ordenada."""
        logger.info("🛑 Cerrando Masako...")
        if self._presence_loop.is_running():
            self._presence_loop.cancel()
        await http.close()
        await client.close()
        await turso_db.close()
        await db.close()
        await super().close()


def create_bot() -> Masako:
    """Factory function para crear la instancia del bot.

    Returns:
        Masako: Instancia del bot configurada.
    """
    return Masako()
