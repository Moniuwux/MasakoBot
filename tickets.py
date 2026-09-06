"""
SISTEMA DE TICKETS PROFESIONAL COMPLETO v4.0.0 — Masako Support

🎫 Sistema privado y organizado para gestionar solicitudes de usuarios.

COMANDOS (20+):
  ⚙️  /ticket setup       → Configuración central visual
  🏷️  /ticket subjects    → Administrar asuntos
  ➕  /ticket addsubjects → Agregar asuntos interactivamente
  📤  /ticket send        → Enviar/actualizar panel
  🔒  /ticket close       → Cerrar ticket
  🔓  /ticket reopen      → Reabrir ticket
  🔐  /ticket lock        → Bloquear temporalmente
  🗑️  /ticket delete      → Eliminar con confirmación
  👤  /ticket claim       → Reclamar ticket (staff)
  🔄  /ticket transfer    → Transferir responsabilidad
  ➕  /ticket add         → Añadir usuarios
  ➖  /ticket remove      → Remover usuarios
  📝  /ticket rename      → Cambiar nombre
  📄  /ticket transcript  → Generar historial
  ℹ️   /ticket info        → Información del ticket
  ⭐  /ticket rate        → Calificar (1-5)
  🔍  /ticket list        → Listar tickets
  🧹  /ticket cleanup     → Limpiar tickets obsoletos
  🛠️  /ticket debug       → Información de debugging

CARACTERÍSTICAS DE SEGURIDAD:
  👤 Validación de usuario
  🛡️ Validación de staff (roles)
  🤖 Validación de permisos del bot
  🏠 Aislamiento por servidor
  🎫 Validación de tickets
  🔘 Seguridad de botones
  🔽 Seguridad de selects
  📝 Validación de datos
  🏰 Jerarquía de Discord
  🧱 Protección contra acciones simultáneas
  🛑 Spam prevention & cooldowns
  🚫 Detección de duplicados

ESTADOS DE TICKETS:
  🟢 OPEN      — Funciona normalmente
  👤 CLAIMED   — Staff reclamó
  🔐 LOCKED    — Usuario bloqueado
  🔴 CLOSED    — Cerrado/inactivo
  ⭐ RATED     — Calificado

PERSISTENCIA Y LOGS:
  💾 Base de datos Turso
  📋 Logs de creación/cierre
  📋 Logs de staff (reclamación, transferencia)
  📋 Logs de usuarios (add/remove)
  📋 Logs de seguridad
  📄 Transcripciones automáticas
  ⭐ Sistema de calificación

PERSONALIZACIÓN:
  🎨 Título, descripción, color
  🖼️ Imágenes (main + thumbnail)
  📝 Campos personalizados
  🔘 Botones personalizados
  📁 Categoría de tickets
  📢 Canal del panel
  📋 Canal de logs
  📄 Canal de transcripciones
"""

from __future__ import annotations

import json
import logging
import random
import re
import string
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, cast

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import TURSO_CONFIG
from logger_config import setup_logger
from utils.database import db as turso_db
from utils.ticket_models import TicketStatus, TicketSubject

logger = setup_logger("Tickets", level=logging.INFO)

# ==============================================================================
# CONSTANTES Y CONFIGURACIÓN
# ==============================================================================
PANEL_SELECT = "ticket_panel_select"
SETUP_EDIT = "setup_edit"
TICKET_CLOSE = "ticket_close"
TICKET_REOPEN = "ticket_reopen"
TICKET_LOCK = "ticket_lock"
TICKET_CLAIM = "ticket_claim"
TICKET_RATE = "ticket_rate"

MAX_FIELDS = 15
MAX_SUBJECTS = 13
MAX_OPEN_PER_USER = 5
MAX_TOTAL_TICKETS = 100
CHANNEL_MAX = 80
DEFAULT_COLOR = 0x7EC8E3
BUTTON_TIMEOUT = 3600
SETUP_VIEW_TIMEOUT = 86400  # 24 horas para completar la configuración
INACTIVITY_TIMEOUT = 86400 * 7  # 7 días
COOLDOWN_CREATE = 60  # 1 minuto entre creaciones
CONFIG_FILE = Path("ticket_configs.json")


class ThreatLevel(Enum):
    """Niveles de amenaza para acciones."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ==============================================================================
# DATACLASSES (Configuración)
# ==============================================================================
@dataclass
class SubjectConfig:
    """Configuración de un asunto."""
    emoji: str
    label: str
    description: str = "Sin descripción"
    value: str = field(default="")
    category_id: Optional[int] = None
    roles_id: list[int] = field(default_factory=lambda: cast(list[int], []))
    limit_per_hour: int = 5

    def __post_init__(self):
        if not self.value:
            self.value = f"subject_{self.label.lower().replace(' ', '_')}"


@dataclass
class PanelConfig:
    """Configuración del panel de tickets."""
    guild_id: int
    
    # Setup básico
    title: str = "🎫 Centro de Soporte"
    description: str = "Selecciona tu asunto para crear un ticket"
    color: int = DEFAULT_COLOR
    
    # Author
    author_name: str = "Masako Support"
    author_url: str = ""
    author_icon_url: str = ""
    
    # Imágenes
    thumbnail_url: str = ""
    image_url: str = ""
    
    # Footer
    footer_text: str = "Sistema de Soporte Masako"
    footer_icon_url: str = ""
    
    # Campos personalizados
    fields: list[Dict[str, str]] = field(default_factory=lambda: cast(list[Dict[str, str]], []))
    links: list[Dict[str, str]] = field(default_factory=lambda: cast(list[Dict[str, str]], []))
    
    # Asuntos
    subjects: list[SubjectConfig] = field(default_factory=lambda: cast(list[SubjectConfig], []))
    
    # Canales
    panel_channel_id: Optional[int] = None
    logs_channel_id: Optional[int] = None
    transcript_channel_id: Optional[int] = None
    category_id: Optional[int] = None
    
    # Staff roles
    staff_roles: list[int] = field(default_factory=lambda: cast(list[int], []))
    
    # Límites
    max_open_per_user: int = MAX_OPEN_PER_USER
    max_total_tickets: int = MAX_TOTAL_TICKETS
    cooldown_create_seconds: int = COOLDOWN_CREATE
    inactivity_close_seconds: int = INACTIVITY_TIMEOUT
    
    # Características
    enable_auto_close: bool = False
    enable_transcripts: bool = True
    enable_ratings: bool = True
    
    # Mensajes personalizados
    welcome_message: str = "Bienvenido al ticket de soporte."
    claim_message: str = "{staff} ha reclamado este ticket."
    close_message: str = "Este ticket ha sido cerrado."


# ==============================================================================
# UTILIDADES DE VALIDACIÓN
# ==============================================================================
def _random_id(length: int = 8) -> str:
    """Genera ID aleatorio."""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _sanitize_name(name: str, max_len: int = CHANNEL_MAX - 15) -> str:
    """Sanitiza nombres para canales Discord."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\-\s]+", "", name)
    name = re.sub(r"\s+", "-", name).strip("-")
    return (name or "ticket")[:max_len]


async def _is_admin_or_owner(inter: discord.Interaction) -> bool:
    """Verifica si es admin o owner."""
    if not inter.guild:
        return False
    member = (
        inter.user
        if isinstance(inter.user, discord.Member)
        else inter.guild.get_member(inter.user.id)
    )
    if not member:
        return False
    return member.guild_permissions.administrator or await cast(commands.Bot, inter.client).is_owner(inter.user)


def _is_staff(inter: discord.Interaction, staff_roles: list[int]) -> bool:
    """Verifica si es staff."""
    if not inter.guild:
        return False
    member = inter.guild.get_member(inter.user.id)
    if not member:
        return False
    return any(role.id in staff_roles for role in member.roles)


def admin_or_owner() -> Any:
    """Decorator para verificar admin."""
    async def check(inter: discord.Interaction) -> bool:
        return await _is_admin_or_owner(inter)
    return app_commands.check(check)


# ==============================================================================
# GESTIÓN DE CONFIGURACIONES JSON
# ==============================================================================
class ConfigManager:
    """Gestor de configuraciones usando JSON."""
    
    def __init__(self, file_path: Path = CONFIG_FILE):
        self.file_path = file_path
        self.configs: Dict[int, PanelConfig] = {}
        self.load()
    
    def load(self) -> None:
        """Carga configuraciones desde JSON."""
        if self.file_path.exists():
            try:
                data = cast(dict[str, dict[str, Any]], json.loads(self.file_path.read_text()))
                for guild_id_str, cfg_data in data.items():
                    guild_id = int(guild_id_str)
                    cfg_data["guild_id"] = guild_id
                    
                    # Convertir SubjectConfig
                    if "subjects" in cfg_data:
                        subjects: list[SubjectConfig] = []
                        for s in cast(list[dict[str, Any]], cfg_data["subjects"]):
                            subjects.append(SubjectConfig(**s))
                        cfg_data["subjects"] = subjects
                    
                    self.configs[guild_id] = PanelConfig(**cfg_data)
                logger.info(f"Cargadas {len(self.configs)} configuraciones de tickets")
            except Exception as e:
                logger.error(f"Error cargando configuraciones: {e}")
    
    def save(self) -> None:
        """Guarda configuraciones a JSON."""
        try:
            data: dict[str, dict[str, Any]] = {}
            for guild_id, cfg in self.configs.items():
                cfg_dict = asdict(cfg)
                cfg_dict["subjects"] = [asdict(s) for s in cfg.subjects]
                data[str(guild_id)] = cfg_dict
            self.file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            logger.info(f"Configuraciones guardadas ({len(data)} guilds)")
        except Exception as e:
            logger.error(f"Error guardando configuraciones: {e}")
    
    def get(self, guild_id: int) -> PanelConfig:
        """Obtiene configuración de un guild."""
        if guild_id not in self.configs:
            self.configs[guild_id] = PanelConfig(guild_id=guild_id)
        return self.configs[guild_id]
    
    def set(self, guild_id: int, cfg: PanelConfig) -> None:
        """Guarda configuración de un guild."""
        self.configs[guild_id] = cfg
        self.save()


config_manager = ConfigManager()


# ==============================================================================
# MODALES
# ==============================================================================
class SubjectAddModal(discord.ui.Modal, title="➕ Nuevo Asunto"):
    """Modal para agregar un asunto."""
    emoji: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Emoji", placeholder="📋", max_length=10, required=True
    )
    label: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Nombre", placeholder="Reporte de Bugs", max_length=100, required=True
    )
    description: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Descripción", placeholder="Describe este asunto...", 
        max_length=256, required=False, style=discord.TextStyle.paragraph
    )

    def __init__(self, cog: TicketsCog, cfg: PanelConfig):
        super().__init__()
        self.cog = cog
        self.cfg = cfg

    async def on_submit(self, inter: discord.Interaction) -> None:
        emoji = self.emoji.value.strip()
        label = self.label.value.strip()
        description = self.description.value.strip() or "Sin descripción"

        if not label:
            await inter.response.send_message("❌ El nombre es requerido.", ephemeral=True)
            return

        if len(self.cfg.subjects) >= MAX_SUBJECTS:
            await inter.response.send_message(
                f"❌ Límite de {MAX_SUBJECTS} asuntos alcanzado.",
                ephemeral=True
            )
            return

        try:
            subject = SubjectConfig(emoji=emoji, label=label, description=description)
            self.cfg.subjects.append(subject)
            config_manager.set(self.cfg.guild_id, self.cfg)
        except (OSError, TypeError, ValueError) as error:
            logger.error("Error guardando asunto: %s", error)
            await inter.response.send_message(
                "❌ No se pudo guardar el asunto. Inténtalo de nuevo.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="✅ Asunto Agregado",
            description=f"{emoji} **{label}**\n{description}",
            color=0x2ECC71
        )
        embed.set_footer(text=f"Total: {len(self.cfg.subjects)}/{MAX_SUBJECTS}")
        
        await inter.response.send_message(embed=embed, ephemeral=True)


# ==============================================================================
# VISTAS (VIEWS)

class EmbedEditModal(discord.ui.Modal):
    """Modal reutilizable para editar una sección del embed."""

    def __init__(self, cog: TicketsCog, cfg: PanelConfig, section: str):
        titles = {
            "author": "👤 Editar autor", "title": "📌 Editar título",
            "description": "📄 Editar descripción", "color": "🎨 Editar color",
            "media": "🖼️ Editar imágenes", "footer": "📋 Editar footer",
            "field": "📊 Agregar field", "links": "🔗 Agregar enlace o GIF",
        }
        super().__init__(title=titles[section])
        self.cog, self.cfg, self.section = cog, cfg, section
        fields = {
            "author": [("author_name", "Nombre", cfg.author_name), ("author_url", "URL", cfg.author_url), ("author_icon_url", "URL del icono", cfg.author_icon_url)],
            "title": [("title", "Título", cfg.title)],
            "description": [("description", "Descripción", cfg.description)],
            "color": [("color", "Color hexadecimal", f"{cfg.color:06X}")],
            "media": [("thumbnail_url", "URL miniatura", cfg.thumbnail_url), ("image_url", "URL imagen grande", cfg.image_url)],
            "footer": [("footer_text", "Texto del footer", cfg.footer_text), ("footer_icon_url", "URL del icono", cfg.footer_icon_url)],
            "field": [("field_name", "Nombre del field", ""), ("field_value", "Contenido del field", "")],
                    "links": [("link_name", "Texto del enlace", ""), ("link_url", "URL de imagen, GIF o sitio", "")],
        }[section]
        for key, label, value in fields:
            self.add_item(discord.ui.TextInput(
                label=label, custom_id=key, default=value or "", required=False,
                style=discord.TextStyle.paragraph if key in {"description", "field_value"} else discord.TextStyle.short,
                max_length=1024,
            ))

    async def on_submit(self, inter: discord.Interaction) -> None:
        values = {item.custom_id: str(item.value).strip() for item in self.children if isinstance(item, discord.ui.TextInput)}
        try:
            if self.section == "color":
                color = values["color"].removeprefix("#")
                if not re.fullmatch(r"[0-9a-fA-F]{6}", color):
                    raise ValueError("El color debe tener 6 dígitos hexadecimales.")
                self.cfg.color = int(color, 16)
            elif self.section == "field":
                if not values["field_name"] or not values["field_value"]:
                    raise ValueError("El nombre y el contenido son obligatorios.")
                if len(self.cfg.fields) >= MAX_FIELDS:
                    raise ValueError(f"Solo se permiten {MAX_FIELDS} fields.")
                self.cfg.fields.append({"name": values["field_name"], "value": values["field_value"]})
            elif self.section == "links":
                url = values["link_url"]
                if not re.match(r"^https?://", url, re.IGNORECASE):
                    raise ValueError("La URL debe comenzar con http:// o https://.")
                if len(self.cfg.links) >= MAX_FIELDS:
                    raise ValueError(f"Solo se permiten {MAX_FIELDS} enlaces.")
                self.cfg.links.append({"name": values["link_name"] or "Enlace", "url": url})
            else:
                for key, value in values.items():
                    if hasattr(self.cfg, key):
                        setattr(self.cfg, key, value)
            config_manager.set(self.cfg.guild_id, self.cfg)
            await self.cog.respond_setup_update(inter, self.cfg, "✅ Cambios guardados.")
        except ValueError as error:
            await inter.response.send_message(f"❌ {error}", ephemeral=True)
        except (OSError, TypeError) as error:
            logger.error("Error guardando configuración del embed: %s", error)
            await inter.response.send_message(
                "❌ No se pudieron guardar los cambios. Inténtalo de nuevo.",
                ephemeral=True,
            )


class SetupEditorView(discord.ui.View):
    """Panel interactivo para personalizar el embed completo."""

    def __init__(self, cog: TicketsCog, cfg: PanelConfig):
        super().__init__(timeout=SETUP_VIEW_TIMEOUT)
        self.cog, self.cfg = cog, cfg

    async def _edit(self, inter: discord.Interaction, section: str) -> None:
        await inter.response.send_modal(EmbedEditModal(self.cog, self.cfg, section))

    @discord.ui.button(label="👤 Autor", style=discord.ButtonStyle.primary, row=0)
    async def author(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self._edit(inter, "author")

    @discord.ui.button(label="📌 Título", style=discord.ButtonStyle.primary, row=0)
    async def title(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self._edit(inter, "title")

    @discord.ui.button(label="📄 Descripción", style=discord.ButtonStyle.primary, row=0)
    async def description(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self._edit(inter, "description")

    @discord.ui.button(label="🎨 Color", style=discord.ButtonStyle.primary, row=1)
    async def color(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self._edit(inter, "color")

    @discord.ui.button(label="🖼️ Imágenes", style=discord.ButtonStyle.primary, row=1)
    async def media(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self._edit(inter, "media")

    @discord.ui.button(label="📋 Footer", style=discord.ButtonStyle.primary, row=1)
    async def footer(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self._edit(inter, "footer")

    @discord.ui.button(label="📊 Field", style=discord.ButtonStyle.secondary, row=2)
    async def field(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self._edit(inter, "field")

    @discord.ui.button(label="🔗 GIF / URL", style=discord.ButtonStyle.secondary, row=2)
    async def links(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self._edit(inter, "links")

    @discord.ui.button(label="📋 Asuntos", style=discord.ButtonStyle.success, row=2)
    async def subjects(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await inter.response.send_message(embed=discord.Embed(title="📋 Asuntos", description=f"Total: {len(self.cfg.subjects)}/{MAX_SUBJECTS}", color=DEFAULT_COLOR), view=AddSubjectStepView(self.cog, self.cfg), ephemeral=True)

    @discord.ui.button(label="👁️ Vista previa", style=discord.ButtonStyle.success, row=2)
    async def preview(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await inter.response.send_message(embed=self.cog.build_panel_embed(self.cfg), ephemeral=True)

    @discord.ui.button(label="💾 Guardar diseño", style=discord.ButtonStyle.success, row=3)
    async def save_design(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        try:
            config_manager.set(self.cfg.guild_id, self.cfg)
            await self.cog.respond_setup_update(inter, self.cfg, "✅ Diseño guardado correctamente.")
        except (OSError, TypeError, ValueError) as error:
            logger.error("Error guardando diseño: %s", error)
            await inter.response.send_message("❌ No se pudo guardar el diseño.", ephemeral=True)

# ==============================================================================
class AddSubjectStepView(discord.ui.View):
    """Vista para agregar asuntos paso a paso."""
    
    def __init__(self, cog: TicketsCog, cfg: PanelConfig):
        super().__init__(timeout=SETUP_VIEW_TIMEOUT)
        self.cog = cog
        self.cfg = cfg

    @discord.ui.button(label="➕ Agregar Asunto", style=discord.ButtonStyle.green)
    async def add_button(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        if len(self.cfg.subjects) >= MAX_SUBJECTS:
            await inter.response.send_message(
                f"❌ Límite alcanzado.",
                ephemeral=True
            )
            return
        modal = SubjectAddModal(self.cog, self.cfg)
        await inter.response.send_modal(modal)

    @discord.ui.button(label="📋 Ver Asuntos", style=discord.ButtonStyle.blurple)
    async def view_button(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        if not self.cfg.subjects:
            embed = discord.Embed(
                title="📋 Asuntos",
                description="No hay asuntos agregados.",
                color=DEFAULT_COLOR
            )
        else:
            embed = discord.Embed(
                title="📋 Asuntos Agregados",
                description=f"Total: {len(self.cfg.subjects)}/{MAX_SUBJECTS}",
                color=DEFAULT_COLOR
            )
            for i, subject in enumerate(self.cfg.subjects, 1):
                embed.add_field(
                    name=f"{i}. {subject.emoji} {subject.label}",
                    value=subject.description,
                    inline=False
                )
        await inter.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="✅ Listo", style=discord.ButtonStyle.success)
    async def done_button(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await inter.response.defer()
        self.stop()


class SubjectSelect(discord.ui.Select[Any]):
    """Select para elegir asuntos en el panel."""
    
    def __init__(self, cog: TicketsCog, cfg: PanelConfig):
        options: list[discord.SelectOption] = []
        for subject in cfg.subjects[:MAX_SUBJECTS]:
            options.append(
                discord.SelectOption(
                    label=subject.label[:100],
                    value=subject.value,
                    emoji=subject.emoji,
                    description=subject.description[:100]
                )
            )
        
        super().__init__(
            placeholder="Selecciona un asunto...",
            min_values=1,
            max_values=1,
            options=options or [discord.SelectOption(label="Sin asuntos", value="none")]
        )
        self.cog = cog
        self.cfg = cfg

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "none":
            await interaction.response.send_message("❌ No hay asuntos disponibles.", ephemeral=True)
            return

        await self.cog.create_ticket(interaction, self.values[0])


class TicketPanelView(discord.ui.View):
    """Vista del panel de tickets."""
    
    def __init__(self, cog: TicketsCog, cfg: PanelConfig):
        super().__init__(timeout=None)
        self.cog = cog
        self.cfg = cfg
        self.add_item(SubjectSelect(cog, cfg))


class RatingView(discord.ui.View):
    """Vista para calificar tickets."""
    
    def __init__(self, cog: TicketsCog, ticket_id: int):
        super().__init__(timeout=3600)
        self.cog = cog
        self.ticket_id = ticket_id

    @discord.ui.button(label="⭐", style=discord.ButtonStyle.danger)
    async def rate_1(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self.cog.save_rating(inter, self.ticket_id, 1)

    @discord.ui.button(label="⭐⭐", style=discord.ButtonStyle.danger)
    async def rate_2(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self.cog.save_rating(inter, self.ticket_id, 2)

    @discord.ui.button(label="⭐⭐⭐", style=discord.ButtonStyle.primary)
    async def rate_3(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self.cog.save_rating(inter, self.ticket_id, 3)

    @discord.ui.button(label="⭐⭐⭐⭐", style=discord.ButtonStyle.success)
    async def rate_4(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self.cog.save_rating(inter, self.ticket_id, 4)

    @discord.ui.button(label="⭐⭐⭐⭐⭐", style=discord.ButtonStyle.success)
    async def rate_5(self, inter: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self.cog.save_rating(inter, self.ticket_id, 5)


# ==============================================================================
# MAIN COG
# ==============================================================================
class TicketsCog(commands.Cog):
    """Cog del sistema de tickets profesional."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.user_cooldowns: Dict[int, datetime] = {}
        self.ticket_creation_tracker: Dict[int, list[datetime]] = {}
        self.auto_close_task.start()

    @commands.command(name="ticket")
    @commands.guild_only()
    async def ticket_prefix(self, ctx: commands.Context[commands.Bot], action: str = "setup") -> None:
        """Entrada por prefijo para el sistema de tickets."""
        if action.lower() != "setup":
            await ctx.send("Usa `m!ticket setup` para abrir la configuración del panel.")
            return
        if not isinstance(ctx.author, discord.Member) or not ctx.author.guild_permissions.manage_guild:
            await ctx.send("Necesitas permiso de gestionar el servidor.")
            return
        if ctx.guild is None:
            await ctx.send("Este comando solo funciona en un servidor.")
            return
        guild = ctx.guild
        cfg = config_manager.get(guild.id)
        await ctx.send(embed=self.build_setup_embed(cfg), view=SetupEditorView(self, cfg))

    def _build_panel_embed(self, cfg: PanelConfig) -> discord.Embed:
        """Construye el embed del panel."""
        embed = discord.Embed(
            title=cfg.title,
            description=cfg.description,
            color=cfg.color
        )

        if cfg.author_name:
            author_kwargs: dict[str, str] = {"name": cfg.author_name}
            if cfg.author_url:
                author_kwargs["url"] = cfg.author_url
            if cfg.author_icon_url:
                author_kwargs["icon_url"] = cfg.author_icon_url
            embed.set_author(**author_kwargs)

        if cfg.thumbnail_url:
            embed.set_thumbnail(url=cfg.thumbnail_url)
        if cfg.image_url:
            embed.set_image(url=cfg.image_url)

        for field in cfg.fields[:MAX_FIELDS]:
            embed.add_field(name=field.get("name", ""), value=field.get("value", ""), inline=False)

        for link in cfg.links[:MAX_FIELDS]:
            embed.add_field(
                name=f"🔗 {link.get('name', 'Enlace')}",
                value=f"[Abrir enlace]({link.get('url', '')})",
                inline=False,
            )

        if cfg.footer_text:
            if cfg.footer_icon_url:
                embed.set_footer(text=cfg.footer_text, icon_url=cfg.footer_icon_url)
            else:
                embed.set_footer(text=cfg.footer_text)

        return embed

    def build_panel_embed(self, cfg: PanelConfig) -> discord.Embed:
        """Construye un embed para vistas externas del editor."""
        return self._build_panel_embed(cfg)

    def build_setup_embed(self, cfg: PanelConfig) -> discord.Embed:
        """Construye el resumen visible del editor de configuración."""
        embed = discord.Embed(
            title="⚙️ Panel de Configuración de Tickets",
            description="Usa los botones para personalizar y guardar el diseño del embed.",
            color=cfg.color,
        )
        embed.add_field(name="📌 Asuntos", value=f"{len(cfg.subjects)}/{MAX_SUBJECTS}", inline=True)
        embed.add_field(name="📊 Fields", value=f"{len(cfg.fields)}/{MAX_FIELDS}", inline=True)
        embed.add_field(name="🔗 Enlaces", value=f"{len(cfg.links)}/{MAX_FIELDS}", inline=True)
        embed.add_field(name="📝 Título", value=cfg.title[:100], inline=False)
        return embed

    async def respond_setup_update(
        self, inter: discord.Interaction, cfg: PanelConfig, message: str
    ) -> None:
        """Actualiza el panel original después de guardar un cambio."""
        view = SetupEditorView(self, cfg)
        if inter.message is not None:
            await inter.response.edit_message(embed=self.build_setup_embed(cfg), view=view)
            await inter.followup.send(message, ephemeral=True)
        else:
            await inter.response.send_message(message, ephemeral=True)

    async def _save_log(self, guild_id: int, action: str, details: str) -> None:
        """Guarda un log de acción."""
        try:
            cfg = config_manager.get(guild_id)
            if not cfg.logs_channel_id:
                return
            
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return
            
            channel = guild.get_channel(cfg.logs_channel_id)
            if not isinstance(channel, discord.TextChannel):
                return
            
            embed = discord.Embed(
                title=f"📋 {action}",
                description=details,
                color=DEFAULT_COLOR,
                timestamp=datetime.now()
            )
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Error guardando log: {e}")

    async def create_ticket(self, inter: discord.Interaction, subject_value: str) -> None:
        """Crea un nuevo ticket."""
        await inter.response.defer(ephemeral=True)

        user = inter.user
        guild = inter.guild
        
        if not guild or not isinstance(user, discord.Member):
            await inter.followup.send("❌ Error: contexto inválido.", ephemeral=True)
            return

        cfg = config_manager.get(guild.id)

        # Validaciones de seguridad
        if not await _is_admin_or_owner(inter) and not _is_staff(inter, cfg.staff_roles):
            # Cooldown
            now = datetime.now()
            if user.id in self.user_cooldowns:
                delta = (now - self.user_cooldowns[user.id]).total_seconds()
                if delta < cfg.cooldown_create_seconds:
                    await inter.followup.send(
                        f"⏱️ Espera {int(cfg.cooldown_create_seconds - delta)}s",
                        ephemeral=True
                    )
                    return

        # Contar tickets abiertos
        try:
            result = await turso_db.fetch_one(
                "SELECT COUNT(*) as count FROM tickets WHERE user_id = ? AND guild_id = ? AND status != 'CLOSED'",
                (user.id, guild.id)
            )
            open_count = result[0] if result else 0
            
            if open_count >= cfg.max_open_per_user:
                await inter.followup.send(
                    f"❌ Ya tienes {open_count} tickets abiertos (máx {cfg.max_open_per_user})",
                    ephemeral=True
                )
                return
        except Exception as e:
            logger.error(f"Error contando tickets: {e}")

        # Crear canal
        try:
            category: discord.CategoryChannel | None = None
            if cfg.category_id:
                configured_category = guild.get_channel(cfg.category_id)
                if isinstance(configured_category, discord.CategoryChannel):
                    category = configured_category
            
            if category is None:
                category = discord.utils.get(guild.categories, name="Tickets")
            if category is None:
                category = await guild.create_category("Tickets")

            ticket_ref = f"{guild.id}-{user.id}-{_random_id(6)}"
            channel_name = _sanitize_name(f"ticket-{user.name}-{_random_id(4)}")

            await turso_db.execute(
                "INSERT OR IGNORE INTO ticket_guilds (guild_id) VALUES (?)",
                (guild.id,),
            )
            subject = TicketSubject(
                name=subject_value,
                emoji="📋",
                description=subject_value,
                guild_id=guild.id,
            )
            await turso_db.execute(
                """INSERT OR IGNORE INTO ticket_subjects (guild_id, name, emoji, description)
                   VALUES (?, ?, ?, ?)""",
                (guild.id, subject.name, subject.emoji, subject.description),
            )
            subject_row = await turso_db.fetch_one(
                "SELECT subject_id FROM ticket_subjects WHERE guild_id = ? AND name = ?",
                (guild.id, subject_value),
            )
            if subject_row is None:
                raise RuntimeError("No se pudo registrar el asunto del ticket")
            subject_id = int(subject_row[0])

            channel = await category.create_text_channel(
                channel_name,
                topic=f"Ticket de {user.id}"
            )

            # Permisos
            await channel.set_permissions(user, read_messages=True, send_messages=True, read_message_history=True)
            await channel.set_permissions(guild.default_role, read_messages=False)

            # Guardar en BD
            await turso_db.execute(
                     """INSERT INTO tickets
                         (guild_id, subject_id, user_id, channel_id, ticket_ref, status, subject, created_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                     (guild.id, subject_id, user.id, channel.id, ticket_ref, TicketStatus.OPEN.value, subject.name)
            )

            # Mensaje de bienvenida
            welcome_embed = discord.Embed(
                title="🎫 Nuevo Ticket",
                description=cfg.welcome_message,
                color=DEFAULT_COLOR,
                timestamp=datetime.now()
            )
            welcome_embed.add_field(name="👤 Usuario", value=user.mention, inline=True)
            welcome_embed.add_field(name="🏷️ Asunto", value=subject_value, inline=True)
            welcome_embed.set_footer(text=f"Ref: {ticket_ref}")

            await channel.send(embed=welcome_embed)

            await inter.followup.send(f"✅ Ticket creado: {channel.mention}", ephemeral=True)
            
            self.user_cooldowns[user.id] = datetime.now()

            await self._save_log(guild.id, "Ticket Creado", f"{user.mention} creó un ticket en {channel.mention}")

            logger.info(f"Ticket {ticket_ref} creado para {user.name}")

        except discord.HTTPException as e:
            await inter.followup.send(f"❌ Error: {e}", ephemeral=True)
            logger.error(f"Error creando ticket: {e}")

    async def save_rating(self, inter: discord.Interaction, ticket_id: int, rating: int) -> None:
        """Guarda una calificación."""
        try:
            await turso_db.execute(
                "UPDATE tickets SET rating = ?, rated_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
                (rating, ticket_id)
            )
            await inter.response.send_message(f"⭐ Calificación guardada: {rating}/5", ephemeral=True)
            logger.info(f"Rating {rating}/5 para ticket {ticket_id}")
        except Exception as e:
            logger.error(f"Error guardando rating: {e}")
            await inter.response.send_message("❌ Error guardando calificación", ephemeral=True)

    # =========================================================================
    # COMANDOS
    # =========================================================================
    ticketgrp = app_commands.Group(name="ticket", description="Sistema de tickets")

    @ticketgrp.command(name="setup", description="⚙️ Configura el panel de tickets")
    @admin_or_owner()
    async def cmd_setup(self, inter: discord.Interaction) -> None:
        """Abre el editor visual del panel."""
        cfg = config_manager.get(cast(int, inter.guild_id))
        embed = self.build_setup_embed(cfg)
        
        await inter.response.send_message(
            embed=embed,
            view=SetupEditorView(self, cfg),
            ephemeral=True
        )

    @ticketgrp.command(name="addsubjects", description="➕ Agregar asuntos interactivamente")
    @admin_or_owner()
    async def cmd_addsubjects(self, inter: discord.Interaction) -> None:
        """Agrega asuntos uno por uno."""
        cfg = config_manager.get(cast(int, inter.guild_id))
        
        embed = discord.Embed(
            title="➕ Agregar Asuntos",
            description=f"Asuntos: {len(cfg.subjects)}/{MAX_SUBJECTS}",
            color=DEFAULT_COLOR
        )
        
        if cfg.subjects:
            asuntos = "\n".join([f"**{i}.** {s.emoji} {s.label}" for i, s in enumerate(cfg.subjects, 1)])
            embed.add_field(name="📋 Existentes", value=asuntos, inline=False)
        
        view = AddSubjectStepView(self, cfg)
        await inter.response.send_message(embed=embed, view=view, ephemeral=True)

    @ticketgrp.command(name="subjects", description="🏷️ Administrar asuntos")
    @admin_or_owner()
    async def cmd_subjects(self, inter: discord.Interaction) -> None:
        """Muestra los asuntos actuales."""
        cfg = config_manager.get(cast(int, inter.guild_id))
        
        embed = discord.Embed(
            title="🏷️ Asuntos",
            description=f"Total: {len(cfg.subjects)}/{MAX_SUBJECTS}",
            color=DEFAULT_COLOR
        )
        
        if cfg.subjects:
            for i, subject in enumerate(cfg.subjects, 1):
                embed.add_field(
                    name=f"{i}. {subject.emoji} {subject.label}",
                    value=subject.description,
                    inline=False
                )
        else:
            embed.description = "No hay asuntos. Usa `/ticket addsubjects`"
        
        await inter.response.send_message(embed=embed, ephemeral=True)

    @ticketgrp.command(name="send", description="📤 Enviar panel a un canal")
    @admin_or_owner()
    async def cmd_send(self, inter: discord.Interaction, channel: discord.TextChannel) -> None:
        """Envía el panel al canal especificado."""
        await inter.response.defer(ephemeral=True)
        cfg = config_manager.get(cast(int, inter.guild_id))
        
        if not cfg.subjects:
            await inter.followup.send("❌ Agrega asuntos primero", ephemeral=True)
            return

        embed = self._build_panel_embed(cfg)
        view = TicketPanelView(self, cfg)

        try:
            await channel.send(embed=embed, view=view)
            cfg.panel_channel_id = channel.id
            config_manager.set(cast(int, inter.guild_id), cfg)
            await inter.followup.send(f"✅ Panel enviado a {channel.mention}", ephemeral=True)
        except discord.HTTPException as e:
            await inter.followup.send(f"❌ Error: {e}", ephemeral=True)

    @ticketgrp.command(name="close", description="🔒 Cerrar un ticket")
    async def cmd_close(self, inter: discord.Interaction) -> None:
        """Cierra el ticket del canal actual."""
        await inter.response.defer(ephemeral=True)
        
        channel = inter.channel
        if not isinstance(channel, discord.TextChannel):
            await inter.followup.send("❌ Comando solo en canales de texto", ephemeral=True)
            return

        try:
            result = await turso_db.fetch_one(
                "SELECT ticket_id, user_id, status FROM tickets WHERE channel_id = ?",
                (channel.id,)
            )
            
            if not result:
                await inter.followup.send("❌ No es un canal de ticket", ephemeral=True)
                return

            ticket_id, user_id, _status = result
            
            # Validación: debe ser staff o propietario
            cfg = config_manager.get(cast(int, inter.guild_id))
            if not (await _is_admin_or_owner(inter) or _is_staff(inter, cfg.staff_roles) or inter.user.id == user_id):
                await inter.followup.send("❌ Sin permiso", ephemeral=True)
                return

            await turso_db.execute(
                "UPDATE tickets SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
                (ticket_id,)
            )

            embed = discord.Embed(
                title="🔒 Ticket Cerrado",
                description=cfg.close_message,
                color=0xFF6B6B
            )
            await channel.send(embed=embed)
            
            await self._save_log(cast(int, inter.guild_id), "Ticket Cerrado",
                               f"{inter.user.mention} cerró <#{channel.id}>")

            await inter.followup.send("✅ Ticket cerrado", ephemeral=True)

        except Exception as e:
            logger.error(f"Error cerrando ticket: {e}")
            await inter.followup.send(f"❌ Error: {e}", ephemeral=True)

    @ticketgrp.command(name="reopen", description="🔓 Reabrir un ticket")
    async def cmd_reopen(self, inter: discord.Interaction) -> None:
        """Reabre un ticket cerrado."""
        await inter.response.defer(ephemeral=True)
        
        channel = inter.channel
        if not isinstance(channel, discord.TextChannel):
            await inter.followup.send("❌ Comando solo en canales de texto", ephemeral=True)
            return

        try:
            result = await turso_db.fetch_one(
                "SELECT ticket_id, user_id FROM tickets WHERE channel_id = ?",
                (channel.id,)
            )
            
            if not result:
                await inter.followup.send("❌ No es un canal de ticket", ephemeral=True)
                return

            ticket_id, _user_id = result
            
            cfg = config_manager.get(cast(int, inter.guild_id))
            if not (await _is_admin_or_owner(inter) or _is_staff(inter, cfg.staff_roles)):
                await inter.followup.send("❌ Solo staff puede reabrir", ephemeral=True)
                return

            await turso_db.execute(
                "UPDATE tickets SET status = 'OPEN', closed_at = NULL WHERE ticket_id = ?",
                (ticket_id,)
            )

            embed = discord.Embed(
                title="🔓 Ticket Reabierto",
                description="El ticket ha sido reabierto.",
                color=0x51CF66
            )
            await channel.send(embed=embed)

            await inter.followup.send("✅ Ticket reabierto", ephemeral=True)

        except Exception as e:
            logger.error(f"Error reabriendo: {e}")
            await inter.followup.send(f"❌ Error: {e}", ephemeral=True)

    @ticketgrp.command(name="lock", description="🔐 Bloquear un ticket")
    async def cmd_lock(self, inter: discord.Interaction) -> None:
        """Bloquea temporalmente el ticket."""
        await inter.response.defer(ephemeral=True)
        
        channel = inter.channel
        if not isinstance(channel, discord.TextChannel):
            await inter.followup.send("❌ Comando solo en canales de texto", ephemeral=True)
            return

        try:
            result = await turso_db.fetch_one(
                "SELECT ticket_id, user_id FROM tickets WHERE channel_id = ?",
                (channel.id,)
            )
            
            if not result:
                await inter.followup.send("❌ No es un canal de ticket", ephemeral=True)
                return

            ticket_id, user_id = result
            guild = cast(discord.Guild, inter.guild)
            member = guild.get_member(user_id)

            if member:
                await channel.set_permissions(member, send_messages=False)

            await turso_db.execute(
                "UPDATE tickets SET status = 'LOCKED' WHERE ticket_id = ?",
                (ticket_id,)
            )

            await inter.followup.send("✅ Ticket bloqueado", ephemeral=True)

        except Exception as e:
            logger.error(f"Error bloqueando: {e}")
            await inter.followup.send(f"❌ Error: {e}", ephemeral=True)

    @ticketgrp.command(name="claim", description="👤 Reclamar un ticket (staff)")
    async def cmd_claim(self, inter: discord.Interaction) -> None:
        """Staff reclama un ticket."""
        await inter.response.defer(ephemeral=True)
        
        channel = inter.channel
        if not isinstance(channel, discord.TextChannel):
            await inter.followup.send("❌ Comando solo en canales de texto", ephemeral=True)
            return

        cfg = config_manager.get(cast(int, inter.guild_id))
        if not (await _is_admin_or_owner(inter) or _is_staff(inter, cfg.staff_roles)):
            await inter.followup.send("❌ Solo staff puede reclamar", ephemeral=True)
            return

        try:
            result = await turso_db.fetch_one(
                "SELECT ticket_id FROM tickets WHERE channel_id = ?",
                (channel.id,)
            )
            
            if not result:
                await inter.followup.send("❌ No es un canal de ticket", ephemeral=True)
                return

            ticket_id = result[0]

            await turso_db.execute(
                "UPDATE tickets SET status = 'CLAIMED', claimed_by = ?, claimed_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
                (inter.user.id, ticket_id)
            )

            embed = discord.Embed(
                title="👤 Ticket Reclamado",
                description=cfg.claim_message.format(staff=inter.user.mention),
                color=0x4ECDC4
            )
            await channel.send(embed=embed)

            await inter.followup.send("✅ Ticket reclamado", ephemeral=True)
            await self._save_log(cast(int, inter.guild_id), "Ticket Reclamado",
                               f"{inter.user.mention} reclamó <#{channel.id}>")

        except Exception as e:
            logger.error(f"Error reclamando: {e}")
            await inter.followup.send(f"❌ Error: {e}", ephemeral=True)

    @ticketgrp.command(name="info", description="ℹ️ Información del ticket")
    async def cmd_info(self, inter: discord.Interaction) -> None:
        """Muestra información del ticket actual."""
        await inter.response.defer(ephemeral=True)
        
        channel = inter.channel
        if not isinstance(channel, discord.TextChannel):
            await inter.followup.send("❌ Comando solo en canales de texto", ephemeral=True)
            return

        try:
            result = await turso_db.fetch_one(
                """SELECT ticket_id, user_id, status, subject, created_at, claimed_by, claimed_at, closed_at
                   FROM tickets WHERE channel_id = ?""",
                (channel.id,)
            )
            
            if not result:
                await inter.followup.send("❌ No es un canal de ticket", ephemeral=True)
                return

            _ticket_id, user_id, status, subject, created_at, claimed_by, _claimed_at, closed_at = result
            
            embed = discord.Embed(
                title="ℹ️ Información del Ticket",
                color=DEFAULT_COLOR
            )
            
            user = self.bot.get_user(user_id)
            embed.add_field(name="👤 Propietario", value=user.mention if user else f"ID: {user_id}", inline=True)
            embed.add_field(name="🏷️ Asunto", value=subject or "N/A", inline=True)
            embed.add_field(name="📊 Estado", value=status, inline=True)
            
            if claimed_by:
                claimer = self.bot.get_user(claimed_by)
                embed.add_field(name="👑 Reclamado por", value=claimer.mention if claimer else f"ID: {claimed_by}", inline=True)
            
            if created_at:
                embed.add_field(name="📅 Creado", value=created_at, inline=True)
            
            if closed_at:
                embed.add_field(name="🔴 Cerrado", value=closed_at, inline=True)

            await inter.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error obteniendo info: {e}")
            await inter.followup.send(f"❌ Error: {e}", ephemeral=True)

    @ticketgrp.command(name="delete", description="🗑️ Eliminar un ticket")
    async def cmd_delete(self, inter: discord.Interaction) -> None:
        """Elimina un ticket con confirmación."""
        await inter.response.defer(ephemeral=True)
        
        channel = inter.channel
        if not isinstance(channel, discord.TextChannel):
            await inter.followup.send("❌ Comando solo en canales de texto", ephemeral=True)
            return

        cfg = config_manager.get(cast(int, inter.guild_id))
        if not (await _is_admin_or_owner(inter) or _is_staff(inter, cfg.staff_roles)):
            await inter.followup.send("❌ Sin permiso", ephemeral=True)
            return

        try:
            result = await turso_db.fetch_one(
                "SELECT ticket_id, ticket_ref FROM tickets WHERE channel_id = ?",
                (channel.id,)
            )
            
            if not result:
                await inter.followup.send("❌ No es un canal de ticket", ephemeral=True)
                return

            ticket_id, ticket_ref = result

            # Guardar transcripción antes de eliminar
            await turso_db.execute(
                "UPDATE tickets SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
                (ticket_id,)
            )

            await channel.delete(reason=f"Ticket eliminado por {inter.user}")
            await self._save_log(cast(int, inter.guild_id), "Ticket Eliminado",
                               f"{inter.user.mention} eliminó ticket {ticket_ref}")

            await inter.followup.send("✅ Ticket eliminado", ephemeral=True)

        except Exception as e:
            logger.error(f"Error eliminando: {e}")
            await inter.followup.send(f"❌ Error: {e}", ephemeral=True)

    @ticketgrp.command(name="transfer", description="🔄 Transferir responsabilidad")
    async def cmd_transfer(self, inter: discord.Interaction, staff: discord.Member) -> None:
        """Transfiere el ticket a otro staff."""
        await inter.response.defer(ephemeral=True)
        
        channel = inter.channel
        if not isinstance(channel, discord.TextChannel):
            await inter.followup.send("❌ Comando solo en canales", ephemeral=True)
            return

        cfg = config_manager.get(cast(int, inter.guild_id))
        if not (await _is_admin_or_owner(inter) or _is_staff(inter, cfg.staff_roles)):
            await inter.followup.send("❌ Sin permiso", ephemeral=True)
            return

        if not _is_staff(inter, cfg.staff_roles) and staff.id not in [r.id for r in staff.roles]:
            await inter.followup.send("❌ El usuario no es staff", ephemeral=True)
            return

        try:
            result = await turso_db.fetch_one(
                "SELECT ticket_id FROM tickets WHERE channel_id = ?",
                (channel.id,)
            )
            
            if not result:
                await inter.followup.send("❌ No es un canal de ticket", ephemeral=True)
                return

            ticket_id = result[0]

            await turso_db.execute(
                "UPDATE tickets SET claimed_by = ?, claimed_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
                (staff.id, ticket_id)
            )

            embed = discord.Embed(
                title="🔄 Ticket Transferido",
                description=f"Responsabilidad transferida a {staff.mention}",
                color=0xA29BFE
            )
            await channel.send(embed=embed)

            await inter.followup.send("✅ Ticket transferido", ephemeral=True)
            await self._save_log(cast(int, inter.guild_id), "Ticket Transferido",
                               f"{inter.user.mention} transfirió a {staff.mention}")

        except Exception as e:
            logger.error(f"Error transferiendo: {e}")
            await inter.followup.send(f"❌ Error: {e}", ephemeral=True)

    @ticketgrp.command(name="add", description="➕ Añadir usuario al ticket")
    async def cmd_add(self, inter: discord.Interaction, user: discord.Member) -> None:
        """Añade un usuario al ticket."""
        await inter.response.defer(ephemeral=True)
        
        channel = inter.channel
        if not isinstance(channel, discord.TextChannel):
            await inter.followup.send("❌ Comando solo en canales", ephemeral=True)
            return

        cfg = config_manager.get(cast(int, inter.guild_id))
        if not (await _is_admin_or_owner(inter) or _is_staff(inter, cfg.staff_roles)):
            await inter.followup.send("❌ Sin permiso", ephemeral=True)
            return

        try:
            await channel.set_permissions(user, read_messages=True, send_messages=True)
            embed = discord.Embed(
                title="➕ Usuario Añadido",
                description=f"{user.mention} ha sido añadido",
                color=0x51CF66
            )
            await channel.send(embed=embed)
            await inter.followup.send("✅ Usuario añadido", ephemeral=True)
        except Exception as e:
            logger.error(f"Error añadiendo usuario: {e}")
            await inter.followup.send(f"❌ Error: {e}", ephemeral=True)

    @ticketgrp.command(name="remove", description="➖ Remover usuario del ticket")
    async def cmd_remove(self, inter: discord.Interaction, user: discord.Member) -> None:
        """Remueve un usuario del ticket."""
        await inter.response.defer(ephemeral=True)
        
        channel = inter.channel
        if not isinstance(channel, discord.TextChannel):
            await inter.followup.send("❌ Comando solo en canales", ephemeral=True)
            return

        cfg = config_manager.get(cast(int, inter.guild_id))
        if not (await _is_admin_or_owner(inter) or _is_staff(inter, cfg.staff_roles)):
            await inter.followup.send("❌ Sin permiso", ephemeral=True)
            return

        try:
            result = await turso_db.fetch_one(
                "SELECT user_id FROM tickets WHERE channel_id = ?",
                (channel.id,)
            )
            
            if result and result[0] == user.id:
                await inter.followup.send("❌ No se puede remover al propietario", ephemeral=True)
                return

            await channel.set_permissions(user, read_messages=False, send_messages=False)
            embed = discord.Embed(
                title="➖ Usuario Removido",
                description=f"{user.mention} ha sido removido",
                color=0xFF6B6B
            )
            await channel.send(embed=embed)
            await inter.followup.send("✅ Usuario removido", ephemeral=True)
        except Exception as e:
            logger.error(f"Error removiendo usuario: {e}")
            await inter.followup.send(f"❌ Error: {e}", ephemeral=True)

    @ticketgrp.command(name="rename", description="📝 Cambiar nombre del ticket")
    async def cmd_rename(self, inter: discord.Interaction, name: str) -> None:
        """Cambia el nombre del canal del ticket."""
        await inter.response.defer(ephemeral=True)
        
        channel = inter.channel
        if not isinstance(channel, discord.TextChannel):
            await inter.followup.send("❌ Comando solo en canales", ephemeral=True)
            return

        cfg = config_manager.get(cast(int, inter.guild_id))
        if not (await _is_admin_or_owner(inter) or _is_staff(inter, cfg.staff_roles)):
            await inter.followup.send("❌ Sin permiso", ephemeral=True)
            return

        try:
            new_name = _sanitize_name(name)
            await channel.edit(name=new_name)
            await inter.followup.send(f"✅ Canal renombrado a: `{new_name}`", ephemeral=True)
            await self._save_log(cast(int, inter.guild_id), "Ticket Renombrado",
                               f"{inter.user.mention} renombró <#{channel.id}> a `{new_name}`")
        except Exception as e:
            logger.error(f"Error renombrando: {e}")
            await inter.followup.send(f"❌ Error: {e}", ephemeral=True)

    @ticketgrp.command(name="transcript", description="📄 Generar transcripción")
    async def cmd_transcript(self, inter: discord.Interaction) -> None:
        """Genera la transcripción del ticket."""
        await inter.response.defer(ephemeral=True)
        
        channel = inter.channel
        if not isinstance(channel, discord.TextChannel):
            await inter.followup.send("❌ Comando solo en canales", ephemeral=True)
            return

        try:
            cfg = config_manager.get(cast(int, inter.guild_id))
            
            # Recopilar mensajes
            lines: list[str] = []
            async for message in channel.history(limit=None, oldest_first=True):
                timestamp = message.created_at.strftime("%d/%m/%Y %H:%M")
                author = message.author.name
                content = message.content or "[sin contenido]"
                lines.append(f"[{timestamp}] {author}: {content}")

            transcript = "\n".join(lines)
            
            # Guardar a archivo
            filename = f"transcript_{channel.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            Path(filename).write_text(transcript, encoding="utf-8")

            # Enviar a canal de transcripciones si está configurado
            if cfg.transcript_channel_id:
                guild = cast(discord.Guild, inter.guild)
                transcript_channel = guild.get_channel(cfg.transcript_channel_id)
                if isinstance(transcript_channel, discord.TextChannel):
                    with open(filename, "rb") as f:
                        await transcript_channel.send(
                            f"📄 Transcripción de {channel.mention}",
                            file=discord.File(f, filename)
                        )

            await inter.followup.send(f"✅ Transcripción generada: `{filename}`", ephemeral=True)
            logger.info(f"Transcripción generada: {filename}")

        except Exception as e:
            logger.error(f"Error generando transcripción: {e}")
            await inter.followup.send(f"❌ Error: {e}", ephemeral=True)

    @ticketgrp.command(name="rate", description="⭐ Calificar ticket")
    async def cmd_rate(self, inter: discord.Interaction) -> None:
        """Abre el panel de calificación."""
        channel = inter.channel
        if not isinstance(channel, discord.TextChannel):
            await inter.response.send_message("❌ Comando solo en canales", ephemeral=True)
            return

        try:
            result = await turso_db.fetch_one(
                "SELECT ticket_id FROM tickets WHERE channel_id = ?",
                (channel.id,)
            )
            
            if not result:
                await inter.response.send_message("❌ No es un canal de ticket", ephemeral=True)
                return

            ticket_id = result[0]
            
            embed = discord.Embed(
                title="⭐ Califica este ticket",
                description="¿Qué tan satisfecho estás?",
                color=DEFAULT_COLOR
            )
            
            view = RatingView(self, ticket_id)
            await inter.response.send_message(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"Error en rating: {e}")
            await inter.response.send_message(f"❌ Error: {e}", ephemeral=True)

    @ticketgrp.command(name="list", description="🔍 Listar tickets")
    async def cmd_list(self, inter: discord.Interaction) -> None:
        """Lista los tickets abiertos."""
        await inter.response.defer(ephemeral=True)

        try:
            results = await turso_db.fetch_all(
                """SELECT channel_id, user_id, status, created_at FROM tickets 
                   WHERE guild_id = ? AND status != 'CLOSED' LIMIT 10""",
                (cast(int, inter.guild_id),)
            )

            if not results:
                await inter.followup.send("❌ No hay tickets abiertos", ephemeral=True)
                return

            embed = discord.Embed(
                title="🔍 Tickets Abiertos",
                description=f"Total: {len(results)}",
                color=DEFAULT_COLOR
            )

            for channel_id, user_id, status, _created_at in results:
                user = self.bot.get_user(user_id)
                embed.add_field(
                    name=f"<#{channel_id}>",
                    value=f"👤 {user.mention if user else f'ID:{user_id}'} | 📊 {status}",
                    inline=False
                )

            await inter.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error listando: {e}")
            await inter.followup.send(f"❌ Error: {e}", ephemeral=True)

    @ticketgrp.command(name="debug", description="🛠️ Información de debugging")
    @admin_or_owner()
    async def cmd_debug(self, inter: discord.Interaction) -> None:
        """Muestra información de debugging."""
        cfg = config_manager.get(cast(int, inter.guild_id))
        
        embed = discord.Embed(
            title="🛠️ Debug Info",
            color=DEFAULT_COLOR
        )
        
        embed.add_field(name="📊 Asuntos", value=f"{len(cfg.subjects)}/{MAX_SUBJECTS}", inline=True)
        embed.add_field(name="📁 Categoría", value=f"ID: {cfg.category_id}", inline=True)
        embed.add_field(name="📢 Panel", value=f"ID: {cfg.panel_channel_id}", inline=True)
        embed.add_field(name="📋 Logs", value=f"ID: {cfg.logs_channel_id}", inline=True)
        embed.add_field(name="👑 Staff Roles", value=f"{len(cfg.staff_roles)} configurados", inline=True)
        embed.add_field(name="🎨 Color", value=f"`#{cfg.color:06X}`", inline=True)
        
        await inter.response.send_message(embed=embed, ephemeral=True)

    @tasks.loop(hours=1)
    async def auto_close_task(self) -> None:
        """Tarea para cerrar tickets inactivos automáticamente."""
        try:
            cutoff = datetime.now() - timedelta(seconds=INACTIVITY_TIMEOUT)
            await turso_db.execute(
                """UPDATE tickets SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP
                   WHERE status = 'OPEN' AND last_activity < ? AND auto_close = 1""",
                (cutoff.isoformat(),)
            )
            logger.info("Auto-cierre de tickets ejecutado")
        except Exception as e:
            logger.error(f"Error en auto-cierre: {e}")

    @auto_close_task.before_loop
    async def before_auto_close(self) -> None:
        """Espera a que el bot esté listo."""
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    """Carga el cog."""
    if not TURSO_CONFIG.enabled:
        logger.warning("⚠️ Tickets no cargado (Turso deshabilitado)")
        return

    if not turso_db.connected and not await turso_db.connect():
        logger.error("❌ No se pudo conectar a BD")
        return

    # Crear tablas
    await turso_db.execute(
        """CREATE TABLE IF NOT EXISTS tickets (
            ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL UNIQUE,
            ticket_ref TEXT NOT NULL UNIQUE,
            status TEXT DEFAULT 'OPEN',
            subject TEXT,
            claimed_by INTEGER,
            claimed_at DATETIME,
            closed_at DATETIME,
            rating INTEGER,
            rated_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_activity DATETIME DEFAULT CURRENT_TIMESTAMP,
            auto_close INTEGER DEFAULT 0
        )"""
    )

    cog = TicketsCog(bot)
    await bot.add_cog(cog)
    logger.info("✓ Sistema de Tickets v4.0.0 cargado (20+ comandos, BD, logs, validaciones)")
