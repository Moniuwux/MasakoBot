"""Cog de Utilidades - Versión Ultra-Optimizada."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional, Literal, cast

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, Select

from utils.nekos_api import InvalidCategoryError, NekosBestError, client as nekos_client

logger = logging.getLogger(__name__)
DATA_DIR = Path("data")
REMINDERS_FILE = DATA_DIR / "reminders.json"
AFK_FILE = DATA_DIR / "afk_status.json"
CONTEXT_MENU_NAME = "Ver Información de Usuario"


class ColorScheme:
    SUCCESS, PRIMARY, INFO, WARNING, ERROR = (
        discord.Color.green(), discord.Color.blurple(), discord.Color.blue(),
        discord.Color.orange(), discord.Color.red(),
    )


class Constants:
    TIMEOUT = 180.0
    MAX_REMINDERS = 10
    MIN_REMINDER = 60
    MAX_REMINDER = 30 * 24 * 60 * 60
    MAX_POLL_OPTIONS = 25
    MAX_AFK_MSG = 200
    MEMBERS_PER_PAGE = 10


HELP_CATEGORIES = {
    "moderación": ("🛡️", "Protege y organiza el servidor.", discord.Color.red()),
    "interacciones": ("💬", "Reacciona y diviértete con otros usuarios.", discord.Color.blue()),
    "utility": ("🔧", "Herramientas prácticas para el día a día.", discord.Color.blurple()),
    "entretenimiento": ("🎮", "Juegos, contenido y comandos para pasarla bien.", discord.Color.gold()),
    "tickets": ("🎫", "Gestiona solicitudes y soporte del servidor.", discord.Color.orange()),
    "nsfw": ("🔞", "Contenido restringido para canales NSFW.", discord.Color.dark_purple()),
}

COMMANDS_BY_CATEGORY = {
    "moderación": ["ban", "kick", "mute", "purge", "sanciones"],
    "interacciones": [
        "baka", "bite", "blush", "boop", "boom", "bored", "cuddle", "cry", "dance",
        "deredere", "drunk", "embrace", "fail", "feed", "fistbump", "glomp", "handhold",
        "heal", "highfive", "hug", "kiss", "laugh", "pat", "peck", "peek", "punch",
        "psycho", "poke", "pout", "sape", "sing", "slap", "smile", "smooch", "snuggle",
        "spray", "splash", "stare", "teehee", "tickle", "wag", "wave", "yandere", "yeet",
        "stats", "interact", "neko", "waifu", "husbando", "kitsune",
    ],
    "utility": [
        "afk", "avatar", "channelinfo", "help", "memberlist", "poll", "remindme",
        "roleinfo", "serverinfo", "userinfo",
    ],
    "entretenimiento": [
        "8ball", "anime-config", "anime-gif", "anime-news", "cat", "choose", "coin",
        "dog", "joke", "meme", "rps", "roll", "say", "ship", "trivia",
        "weather", "weather-config",
    ],
    "tickets": ["ticket"],
    "nsfw": ["lewd", "nsfw"],
}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(exist_ok=True)


def load_json(path: Path, default: Any = None) -> Any:
    ensure_data_dir()
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else (default or {})
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Error leyendo %s: %s", path, exc)
        return default or {}


def save_json(path: Path, data: Any) -> bool:
    ensure_data_dir()
    try:
        path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
        return True
    except OSError as exc:
        logger.error("Error escribiendo %s: %s", path, exc)
        return False


def create_embed(
    title: str,
    color: discord.Color = ColorScheme.INFO,
    author: Optional[discord.abc.User] = None,
    **kwargs: Any,
) -> discord.Embed:
    embed = discord.Embed(title=title[:256], color=color, timestamp=datetime.now(timezone.utc), **kwargs)
    if author:
        embed.set_author(name=str(author)[:256], icon_url=author.display_avatar.url)
    return embed


def format_timestamp(dt: Optional[datetime]) -> str:
    return f"<t:{int(dt.timestamp())}:F>" if dt else "Desconocido"


def parse_time(time_str: str) -> Optional[int]:
    matches = re.fullmatch(r"\s*(\d+\s*[smhd]\s*)+", time_str.lower())
    if not matches:
        return None
    values = re.findall(r"(\d+)\s*([smhd])", time_str.lower())
    total = sum(int(value) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit] for value, unit in values)
    return total if Constants.MIN_REMINDER <= total <= Constants.MAX_REMINDER else None


def format_time_delta(seconds: int) -> str:
    parts: list[str] = []
    for unit, divisor in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= divisor:
            value = seconds // divisor
            parts.append(f"{value}{unit}")
            seconds %= divisor
    return " ".join(parts[:3]) or "0s"


class HelpCategorySelect(Select[Any]):
    def __init__(self, parent: "HelpView") -> None:
        self.parent = parent
        super().__init__(
            placeholder="📂 Explora una categoría...",
            custom_id="help_select",
            options=[
                discord.SelectOption(
                    label=category.title(),
                    value=category,
                    description=description[:100],
                    emoji=emoji,
                )
                for category, (emoji, description, _) in HELP_CATEGORIES.items()
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.parent.author_id:
            await interaction.response.send_message("❌ Solo el autor puede usar este menú.", ephemeral=True)
            return
        await interaction.response.edit_message(embed=self.parent.get_category_embed(self.values[0]))


class HelpView(View):
    def __init__(self, author_id: int, timeout: float = Constants.TIMEOUT) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.add_item(HelpCategorySelect(self))

    def get_category_embed(self, category: str) -> discord.Embed:
        emoji, description, color = HELP_CATEGORIES[category]
        commands_text = "\n".join(
            f"`/{command}`" for command in sorted(COMMANDS_BY_CATEGORY[category])
        )
        embed = create_embed(
            f"{emoji} {category.title()}",
            color=color,
            description=description,
        )
        embed.add_field(
            name=f"Comandos ({len(COMMANDS_BY_CATEGORY[category])})",
            value=commands_text or "No hay comandos disponibles.",
            inline=False,
        )
        embed.set_footer(text="Centro de ayuda • Usa el menú para cambiar de categoría")
        return embed


class PaginatedView(View):
    def __init__(self, pages: list[discord.Embed], author_id: int, timeout: float = Constants.TIMEOUT) -> None:
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current_page = 0
        self.author_id = author_id
        self.message: Optional[discord.Message] = None
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        last = max(0, len(self.pages) - 1)
        self.previous_button.disabled = self.current_page == 0
        self.first_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= last
        self.last_button.disabled = self.current_page >= last

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Solo el autor puede usar esto.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    async def _show(self, interaction: discord.Interaction) -> None:
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="⏮️", style=discord.ButtonStyle.secondary)
    async def first_button(self, interaction: discord.Interaction, _: Button[Any]) -> None:
        self.current_page = 0
        await self._show(interaction)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, _: Button[Any]) -> None:
        self.current_page = max(0, self.current_page - 1)
        await self._show(interaction)

    @discord.ui.button(label="❌", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, _: Button[Any]) -> None:
        await interaction.response.defer()
        if interaction.message:
            try:
                await interaction.message.delete()
            except discord.HTTPException:
                pass

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, _: Button[Any]) -> None:
        self.current_page = min(len(self.pages) - 1, self.current_page + 1)
        await self._show(interaction)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.secondary)
    async def last_button(self, interaction: discord.Interaction, _: Button[Any]) -> None:
        self.current_page = len(self.pages) - 1
        await self._show(interaction)


class PollView(View):
    def __init__(self, question: str, options: list[str], author_id: int, timeout: Optional[int] = None) -> None:
        super().__init__(timeout=timeout)
        self.votes = {index: 0 for index in range(len(options))}
        self.user_votes: defaultdict[int, Optional[int]] = defaultdict(lambda: None)
        self.question, self.options, self.author_id = question, options, author_id
        self.message: Optional[discord.Message] = None
        for index, option in enumerate(options):
            self.add_item(discord.ui.Button(label=f"{index + 1}. {option[:80]}", style=discord.ButtonStyle.secondary, custom_id=f"poll_{index}"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = str((interaction.data or {}).get("custom_id", ""))
        try:
            option_id = int(custom_id.split("_")[1])
        except (IndexError, ValueError):
            return False
        old_vote = self.user_votes[interaction.user.id]
        if old_vote is not None:
            self.votes[old_vote] -= 1
        self.votes[option_id] += 1
        self.user_votes[interaction.user.id] = option_id
        await self._update_embed(interaction)
        return True

    async def _update_embed(self, interaction: discord.Interaction) -> None:
        embed = create_embed("📊 Encuesta", ColorScheme.PRIMARY)
        embed.description = self.question
        total = sum(self.votes.values())
        for index, option in enumerate(self.options):
            votes = self.votes[index]
            percent = f" ({votes / total * 100:.1f}%)" if total else " (0%)"
            bar = "█" * (votes or 1) + " " * (10 - min(votes or 1, 10))
            embed.add_field(name=f"Opción {index + 1}", value=f"`{option}`\n{bar} {votes} votos{percent}", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)


class ReminderManager:
    def __init__(self, cog: "Utility") -> None:
        self.cog = cog
        self.reminders = load_json(REMINDERS_FILE)
        self.tasks: dict[int, asyncio.Task[None]] = {}
        self._schedule_all()

    def _schedule_all(self) -> None:
        for reminder_id, data in self.reminders.items():
            if data.get("active"):
                self.tasks[int(reminder_id)] = asyncio.create_task(self._run_reminder(int(reminder_id)))

    def add_reminder(self, user_id: int, seconds: int, message: str) -> tuple[bool, str]:
        if not Constants.MIN_REMINDER <= seconds <= Constants.MAX_REMINDER:
            return False, f"⏱️ Rango: {Constants.MIN_REMINDER}s - {Constants.MAX_REMINDER // 86400}d"
        active = sum(1 for reminder in self.reminders.values() if reminder.get("user_id") == user_id and reminder.get("active"))
        if active >= Constants.MAX_REMINDERS:
            return False, f"⏱️ Máximo {Constants.MAX_REMINDERS} recordatorios activos"
        reminder_id = max((int(key) for key in self.reminders), default=0) + 1
        now = datetime.now(timezone.utc)
        self.reminders[str(reminder_id)] = {
            "user_id": user_id, "message": message[:500], "created_at": now.isoformat(),
            "remind_at": (now + timedelta(seconds=seconds)).isoformat(), "active": True,
        }
        save_json(REMINDERS_FILE, self.reminders)
        self.tasks[reminder_id] = asyncio.create_task(self._run_reminder(reminder_id))
        return True, f"⏱️ Recordatorio en {format_time_delta(seconds)} (ID: `{reminder_id}`)"

    async def _run_reminder(self, reminder_id: int) -> None:
        reminder = self.reminders.get(str(reminder_id))
        if not reminder:
            return
        try:
            delay = (datetime.fromisoformat(reminder["remind_at"]) - datetime.now(timezone.utc)).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                user = await self.cog.bot.fetch_user(int(reminder["user_id"]))
                embed = create_embed("⏱️ Tu recordatorio", ColorScheme.INFO)
                embed.description = str(reminder["message"])[:4096]
                await user.send(embed=embed)
            except (discord.Forbidden, discord.NotFound):
                pass
            reminder["active"] = False
            save_json(REMINDERS_FILE, self.reminders)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error en recordatorio %s", reminder_id)

    def cancel_reminder(self, reminder_id: int) -> tuple[bool, str]:
        reminder = self.reminders.get(str(reminder_id))
        if not reminder:
            return False, "⏱️ Recordatorio no encontrado"
        reminder["active"] = False
        save_json(REMINDERS_FILE, self.reminders)
        if task := self.tasks.get(reminder_id):
            task.cancel()
        return True, f"✅ Recordatorio {reminder_id} cancelado"


class AFKManager:
    def __init__(self) -> None:
        self.users = load_json(AFK_FILE)

    def set_afk(self, user_id: int, message: str) -> tuple[bool, str]:
        clean_message = message.strip()[:Constants.MAX_AFK_MSG]
        if not clean_message:
            return False, "❌ Mensaje no puede estar vacío"
        self.users[str(user_id)] = {"message": clean_message, "set_at": datetime.now(timezone.utc).isoformat(), "mentions": []}
        save_json(AFK_FILE, self.users)
        return True, f"✅ AFK: {clean_message}"

    def is_afk(self, user_id: int) -> bool:
        return str(user_id) in self.users

    def get_afk_info(self, user_id: int) -> Optional[dict[str, Any]]:
        return self.users.get(str(user_id))

    def remove_afk(self, user_id: int) -> None:
        self.users.pop(str(user_id), None)
        save_json(AFK_FILE, self.users)


class Utility(commands.Cog):
    """Herramientas de ayuda, información, encuestas, recordatorios y AFK."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.cooldowns: defaultdict[str, dict[int, float]] = defaultdict(dict)
        self.reminder_manager = ReminderManager(self)
        self.afk_manager = AFKManager()

    async def cog_unload(self) -> None:
        for task in self.reminder_manager.tasks.values():
            task.cancel()
        self.bot.tree.remove_command(CONTEXT_MENU_NAME, type=discord.AppCommandType.user)

    def _check_cooldown(self, user_id: int, command: str, seconds: float = 3.0) -> bool:
        now = datetime.now(timezone.utc).timestamp()
        last = self.cooldowns[command].get(user_id, 0.0)
        if now - last < seconds:
            return False
        self.cooldowns[command][user_id] = now
        return True

    @app_commands.command(name="help", description="📚 Centro de ayuda interactivo")
    async def help(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        embed = create_embed("📚 Centro de Ayuda", color=ColorScheme.PRIMARY, author=interaction.user)
        embed.description = "Selecciona una categoría para consultar la ayuda del servidor."
        for category in ("hug", "claudie"):
            try:
                asset = await nekos_client.fetch(category)
            except (InvalidCategoryError, NekosBestError, asyncio.TimeoutError) as exc:
                logger.debug("No se pudo obtener el GIF de ayuda '%s': %s", category, exc)
                continue
            if asset.url.startswith(("http://", "https://")):
                embed.set_image(url=asset.url)
                break
        embed.set_footer(text="Centro de ayuda • Selecciona una categoría abajo")
        await interaction.followup.send(embed=embed, view=HelpView(interaction.user.id))

    @app_commands.command(name="serverinfo", description="Información del servidor")
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Solo en servidores", ephemeral=True)
            return
        guild = interaction.guild
        embed = create_embed(f"Información de {guild.name}", ColorScheme.PRIMARY, interaction.user)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Detalles", value=f"**ID:** `{guild.id}`\n**Propietario:** {guild.owner.mention if guild.owner else 'N/A'}\n**Creado:** {format_timestamp(guild.created_at)}\n**Miembros:** {guild.member_count}\n**Roles:** {len(guild.roles)}\n**Canales:** {len(guild.channels)}", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Información de usuario")
    @app_commands.describe(member="Usuario (opcional)")
    async def userinfo(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        target = member or interaction.user
        embed = create_embed(f"Información de {target}", ColorScheme.SUCCESS, interaction.user)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Detalles", value=f"**ID:** `{target.id}`\n**Creado:** {format_timestamp(target.created_at)}\n**Se unió:** {format_timestamp(getattr(target, 'joined_at', None))}\n**Roles:** {max(0, len(getattr(target, 'roles', [])) - 1)}", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="channelinfo", description="Muestra información del canal.")
    @app_commands.describe(channel="Canal que quieres consultar")
    async def channelinfo(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None) -> None:
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("❌ El canal debe ser de texto.", ephemeral=True)
            return
        embed = create_embed(f"Información de #{target.name}", ColorScheme.INFO, interaction.user)
        embed.add_field(name="Detalles", value=f"**ID:** `{target.id}`\n**Categoría:** {target.category.mention if target.category else 'Sin categoría'}\n**Creado:** {format_timestamp(target.created_at)}\n**Tema:** {target.topic or 'Sin tema'}", inline=False)
        embed.add_field(name="Posición", value=str(target.position), inline=True)
        embed.add_field(name="NSFW", value="Sí" if target.is_nsfw() else "No", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roleinfo", description="Muestra información de un rol.")
    @app_commands.describe(role="Rol que quieres consultar")
    async def roleinfo(self, interaction: discord.Interaction, role: discord.Role) -> None:
        permissions = [name.replace("_", " ").title() for name, enabled in role.permissions if enabled]
        embed = create_embed(f"Información del rol {role.name}", ColorScheme.WARNING, interaction.user)
        embed.add_field(name="Detalles", value=f"**ID:** `{role.id}`\n**Color:** {role.color}\n**Posición:** {role.position}\n**Miembros:** {len(role.members)}\n**Mencionable:** {'Sí' if role.mentionable else 'No'}", inline=False)
        embed.add_field(name="Permisos destacados", value=", ".join(permissions[:20]) or "Sin permisos especiales", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="memberlist", description="Lista de miembros con paginación.")
    @app_commands.describe(sort_by="Ordenar por: joined, created, name, roles", role="Filtrar por rol")
    async def memberlist(self, interaction: discord.Interaction, sort_by: Literal["joined", "created", "name", "roles"] = "joined", role: Optional[discord.Role] = None) -> None:
        if not interaction.guild:
            await interaction.response.send_message("❌ Este comando solo funciona en servidores.", ephemeral=True)
            return
        members = [member for member in interaction.guild.members if role is None or role in member.roles]
        if sort_by == "joined":
            members.sort(key=lambda member: member.joined_at or datetime.max.replace(tzinfo=timezone.utc))
        elif sort_by == "created":
            members.sort(key=lambda member: member.created_at)
        elif sort_by == "name":
            members.sort(key=lambda member: member.name.casefold())
        else:
            members.sort(key=lambda member: len(member.roles), reverse=True)
        pages: list[discord.Embed] = []
        for offset in range(0, len(members), Constants.MEMBERS_PER_PAGE):
            chunk = members[offset:offset + Constants.MEMBERS_PER_PAGE]
            embed = create_embed(f"Miembros de {interaction.guild.name}", ColorScheme.PRIMARY, interaction.user)
            embed.description = f"Página {len(pages) + 1} | Total: {len(members)} miembros"
            embed.add_field(name="Miembros", value="\n".join(f"{index}. {member.mention} • {member.name}" for index, member in enumerate(chunk, offset + 1)) or "Sin miembros", inline=False)
            pages.append(embed)
        if not pages:
            await interaction.response.send_message("❌ No hay miembros para mostrar.", ephemeral=True)
            return
        view = PaginatedView(pages, interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="avatar", description="Avatar de usuario")
    @app_commands.describe(member="Usuario (opcional)", size="Tamaño")
    async def avatar(self, interaction: discord.Interaction, member: Optional[discord.Member] = None, size: Literal["small", "medium", "large", "xlarge"] = "large") -> None:
        target = member or interaction.user
        resolution = {"small": 256, "medium": 512, "large": 1024, "xlarge": 2048}[size]
        url = target.display_avatar.with_size(resolution).url
        embed = create_embed(f"Avatar de {target}", ColorScheme.SUCCESS, interaction.user)
        embed.set_image(url=url)
        embed.add_field(name="Info", value=f"**Usuario:** {target.mention}\n**Resolución:** {resolution}x{resolution}", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="poll", description="Crear encuesta")
    @app_commands.describe(question="Pregunta", option1="Opción 1", option2="Opción 2", option3="Opción 3 (opcional)", option4="Opción 4 (opcional)", option5="Opción 5 (opcional)", duration="Duración en minutos")
    async def poll(self, interaction: discord.Interaction, question: str, option1: str, option2: str, option3: Optional[str] = None, option4: Optional[str] = None, option5: Optional[str] = None, duration: Optional[int] = None) -> None:
        if not self._check_cooldown(interaction.user.id, "poll"):
            await interaction.response.send_message("⏱️ Espera antes de crear otra encuesta.", ephemeral=True)
            return
        question = question.strip()[:300]
        options = [option.strip()[:100] for option in (option1, option2, option3, option4, option5) if option and option.strip()]
        if len(options) < 2 or len(options) > Constants.MAX_POLL_OPTIONS:
            await interaction.response.send_message("❌ La encuesta necesita entre 2 y 5 opciones.", ephemeral=True)
            return
        timeout = duration * 60 if duration and 1 <= duration <= 1440 else None
        view = PollView(question, options, interaction.user.id, timeout=timeout)
        embed = create_embed("📊 Encuesta", ColorScheme.PRIMARY, interaction.user)
        embed.description = question
        for index, option in enumerate(options):
            embed.add_field(name=f"Opción {index + 1}", value=option, inline=False)
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="remindme", description="Recordatorio personalizado")
    @app_commands.describe(time="Tiempo (1m, 2h, 1d30m)", message="Mensaje")
    async def remindme(self, interaction: discord.Interaction, time: str, message: str) -> None:
        seconds = parse_time(time)
        if not seconds or not message.strip():
            await interaction.response.send_message("❌ Usa un tiempo válido y un mensaje no vacío.", ephemeral=True)
            return
        _, response = self.reminder_manager.add_reminder(interaction.user.id, seconds, message)
        await interaction.response.send_message(response, ephemeral=True)

    @app_commands.command(name="afk", description="Establece tu estado AFK")
    @app_commands.describe(message="Mensaje de ausencia")
    async def afk(self, interaction: discord.Interaction, message: Optional[str] = None) -> None:
        _, response = self.afk_manager.set_afk(interaction.user.id, message or "Estoy ausente")
        await interaction.response.send_message(response, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        # Escribir en cualquier canal, incluidos los mensajes directos,
        # cancela inmediatamente el estado AFK del autor.
        if self.afk_manager.is_afk(message.author.id):
            self.afk_manager.remove_afk(message.author.id)

        # Las notificaciones de usuarios AFK solo se publican en servidores.
        if message.guild is None:
            return

        for mention in message.mentions:
            info = self.afk_manager.get_afk_info(mention.id)
            if info:
                embed = create_embed(f"🔔 {mention.name} está ausente", ColorScheme.WARNING)
                embed.description = str(info.get("message", "Estoy ausente"))[:4096]
                try:
                    await message.reply(embed=embed, delete_after=30)
                except discord.HTTPException:
                    pass

    async def user_context_menu(self, interaction: discord.Interaction, member: discord.Member) -> None:
        embed = create_embed(str(member), ColorScheme.SUCCESS, interaction.user)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Información", value=f"**ID:** `{member.id}`\n**Creado:** {format_timestamp(member.created_at)}\n**Roles:** {max(0, len(member.roles) - 1)}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Utility(bot))
    utility = cast(Utility, bot.get_cog("Utility"))
    bot.tree.remove_command(CONTEXT_MENU_NAME, type=discord.AppCommandType.user)
    bot.tree.add_command(app_commands.ContextMenu(name=CONTEXT_MENU_NAME, callback=utility.user_context_menu))
    logger.info("✅ Cog de Utilidades cargado")
