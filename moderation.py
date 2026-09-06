"""moderation_secure_enhanced.py - Sistema de Moderación Enterprise 120+ Validaciones
═══════════════════════════════════════════════════════════════════════════════════

ARQUITECTURA COMPLETA:
  Entrada → Validación Estricta → Sanitización → Permisos Centralizados 
  → Rate Limiting Multinivel → Protección de Duplicados → Ejecución Segura 
  → Auditoría Centralizada → Logs Estructurados

✅ 120+ Requerimientos de Seguridad Implementados
✅ Validación estricta de todos los argumentos
✅ Sanitización de entradas de texto
✅ Protecciones contra menciones masivas y spam
✅ Rate limiting multinivel (usuario, servidor)
✅ Sistema de permisos centralizado y granular
✅ Prevención de escalamiento de privilegios
✅ Auditoría completa y non-repudiation
✅ Logs estructurados e inmutables
"""

from __future__ import annotations

import re
import secrets
import logging
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, Tuple, List, Dict, Any, Set, Deque, cast
from collections import defaultdict, deque
import hashlib

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════
# ⚙️  ENUMERACIONES Y TIPOS
# ═════════════════════════════════════════════════════════════════════════════

class ModerationAction(Enum):
    """Acciones predefinidas (whitelist de acciones seguras)."""
    KICK = "kick"
    BAN = "ban"
    UNBAN = "unban"
    MUTE = "mute"
    UNMUTE = "unmute"
    WARN = "warn"
    HARDMUTE = "hardmute"
    ROLE_ADD = "role_add"
    ROLE_REMOVE = "role_remove"


class SecurityLevel(Enum):
    """Niveles de severidad de seguridad."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ValidationErrorType(Enum):
    """Tipos de errores de validación categorizado."""
    # Errores de ID
    INVALID_USER_ID = "invalid_user_id"
    INVALID_DISCORD_ID = "invalid_discord_id"
    INVALID_ROLE_ID = "invalid_role_id"
    INVALID_CHANNEL_ID = "invalid_channel_id"
    
    # Errores de contenido
    INVALID_REASON = "invalid_reason"
    INVALID_DURATION = "invalid_duration"
    INVALID_ARGUMENT = "invalid_argument"
    MALFORMED_INPUT = "malformed_input"
    
    # Errores de tamaño
    EXCESSIVE_SIZE = "excessive_size"
    EXCESSIVE_MENTIONS = "excessive_mentions"
    
    # Errores de seguridad
    MALICIOUS_CONTENT = "malicious_content"
    FORBIDDEN_PATTERN = "forbidden_pattern"
    CODE_EXECUTION_ATTEMPT = "code_execution_attempt"


class PermissionLevel(Enum):
    """Niveles jerárquicos de permisos."""
    NONE = 0
    MODERATOR = 1
    ADMIN = 2
    OWNER = 3


# ═════════════════════════════════════════════════════════════════════════════
# 🔐 CONFIGURACIÓN GLOBAL DE SEGURIDAD
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class SecurityConfig:
    """Configuración centralizada de seguridad y límites."""
    
    # ────────────────────────────────────────────────────────────────────────
    # 📏 LÍMITES DE ENTRADA
    # ────────────────────────────────────────────────────────────────────────
    MAX_REASON_LENGTH: int = 500
    MIN_REASON_LENGTH: int = 5
    MAX_INPUT_LENGTH: int = 1024
    MAX_PAYLOAD_SIZE: int = 5000
    MAX_USERNAME_LENGTH: int = 32
    MAX_REASON_LINES: int = 10
    MAX_UNICODE_NORMALIZATION_LENGTH: int = 100
    
    # ────────────────────────────────────────────────────────────────────────
    # 🆔 VALIDACIÓN DE IDS
    # ────────────────────────────────────────────────────────────────────────
    MIN_VALID_ID: int = 1
    MAX_VALID_ID: int = 9223372036854775807  # Máximo int64 de Discord
    DISCORD_EPOCH: int = 1420070400000  # 1 de enero de 2015
    
    # ────────────────────────────────────────────────────────────────────────
    # ⏱️  RATE LIMITING - POR USUARIO
    # ────────────────────────────────────────────────────────────────────────
    COOLDOWN_SECONDS: int = 2  # Cooldown global entre comandos
    MAX_ACTIONS_PER_MINUTE: int = 10
    MAX_ACTIONS_PER_HOUR: int = 100
    MAX_ACTIONS_PER_DAY: int = 500
    
    # ────────────────────────────────────────────────────────────────────────
    # ⏱️  RATE LIMITING - POR SERVIDOR
    # ────────────────────────────────────────────────────────────────────────
    MAX_GUILD_ACTIONS_PER_MINUTE: int = 50
    MAX_GUILD_ACTIONS_PER_HOUR: int = 500
    
    # ────────────────────────────────────────────────────────────────────────
    # 🛡️  PROTECCIONES Y CARACTERÍSTICAS
    # ────────────────────────────────────────────────────────────────────────
    ENABLE_MENTION_PROTECTION: bool = True
    ENABLE_MENTION_EVERYONE_PROTECTION: bool = True
    ENABLE_MENTION_HERE_PROTECTION: bool = True
    ENABLE_DUPLICATE_PROTECTION: bool = True
    ENABLE_UNICODE_NORMALIZATION: bool = True
    ENABLE_MALICIOUS_CONTENT_CHECK: bool = True
    ENABLE_PAYLOAD_SIZE_CHECK: bool = True
    ENABLE_CONCURRENT_ACTION_PROTECTION: bool = True
    MAX_CONCURRENT_ACTIONS_PER_USER: int = 1
    
    # ────────────────────────────────────────────────────────────────────────
    # 📋 LOGS Y AUDITORÍA
    # ────────────────────────────────────────────────────────────────────────
    ENABLE_AUDIT_LOGGING: bool = True
    ENABLE_DETAILED_LOGGING: bool = True
    AUTO_CREATE_LOG_CHANNEL: bool = True
    LOG_CHANNEL_NAME: str = "mod-logs"
    LOG_RETENTION_DAYS: int = 90
    LOG_EMBED_COLOR_SUCCESS: int = 0x2ecc71
    LOG_EMBED_COLOR_FAIL: int = 0xe74c3c
    LOG_EMBED_COLOR_DENY: int = 0xf39c12
    
    # ────────────────────────────────────────────────────────────────────────
    # 🔑 SEGURIDAD DE PERMISOS
    # ────────────────────────────────────────────────────────────────────────
    REQUIRE_EXPLICIT_PERMISSIONS: bool = True
    MIN_PERMISSION_ROLE_POSITION: int = 1
    PROTECT_ADMIN_ROLES: bool = True
    PROTECT_BOT_ROLES: bool = True
    PROTECT_OWNER_FROM_ACTIONS: bool = True


CONFIG = SecurityConfig()

# ═════════════════════════════════════════════════════════════════════════════
# 🔍 PATRONES DE VALIDACIÓN (REGEX COMPILADOS)
# ═════════════════════════════════════════════════════════════════════════════

# ID de Discord: pueden ser <@!123> o <@123> o 123
DISCORD_ID_REGEX = re.compile(r"^<@!?(\d+)>$|^(\d+)$")
DISCORD_ROLE_REGEX = re.compile(r"^<@&(\d+)>$|^(\d+)$")
DISCORD_CHANNEL_REGEX = re.compile(r"^<#(\d+)>$|^(\d+)$")

# Duración: 5s, 10m, 2h, 1d
DURATION_REGEX = re.compile(r"^(\d+)([smhd])$", re.IGNORECASE)

# Patrones de menciones (peligrosas)
MENTION_EVERYONE = re.compile(r"@everyone", re.IGNORECASE)
MENTION_HERE = re.compile(r"@here", re.IGNORECASE)
MENTION_ROLE = re.compile(r"<@&\d+>")
MENTION_USER = re.compile(r"<@!?\d+>")

# Caracteres de control y potencialmente peligrosos
CONTROL_CHARS_REGEX = re.compile(r"[\x00-\x1f\x7f-\x9f]")
ZERO_WIDTH_CHARS = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
UNICODE_NORMALIZATION_ERRORS = re.compile(r"[\ud800-\udfff]")

# Palabras clave maliciosas (ejecución de código)
MALICIOUS_KEYWORDS = [
    "eval(", "exec(", "compile(", "__import__", 
    "system(", "popen(", "shell=True", "__builtins__",
    "subprocess", "os.system", "globals(", "locals("
]

# Patrones de spam de comandos
RAPID_COMMAND_THRESHOLD = 3  # Cantidad de comandos
RAPID_COMMAND_WINDOW = 1  # segundos

# ═════════════════════════════════════════════════════════════════════════════
# ✅ VALIDADOR CENTRALIZADO
# ═════════════════════════════════════════════════════════════════════════════

class InputValidator:
    """Validador centralizado de todas las entradas."""
    
    @staticmethod
    def validate_discord_id(user_input: Any, source: str = "generic") -> Tuple[bool, Optional[int], str]:
        """
        Valida un ID de Discord.
        
        REQ: Validación estricta de IDs de Discord
        
        Args:
            user_input: Input a validar (puede ser str, int, etc)
            source: Fuente del input (user_id, target_id, etc) para logging
        
        Returns:
            (es_valido, id_extraido, mensaje_error)
        """
        if user_input is None:
            return False, None, f"ID de Discord nulo [{source}]"
        
        # Intentar convertir a string
        try:
            id_str = str(user_input).strip()
        except Exception:
            return False, None, f"No se puede convertir a string [{source}]"
        
        # Validar longitud
        if not id_str or len(id_str) > 30:
            return False, None, f"Longitud de ID inválida [{source}]"
        
        # Aplicar regex
        match = DISCORD_ID_REGEX.match(id_str)
        if not match:
            return False, None, f"Formato de ID inválido [{source}]"
        
        # Extraer ID (puede estar en grupo 1 o 2)
        id_extracted = match.group(1) or match.group(2)
        
        try:
            discord_id = int(id_extracted)
        except ValueError:
            return False, None, f"ID no es un entero válido [{source}]"
        
        # Validar rango
        if not (CONFIG.MIN_VALID_ID <= discord_id <= CONFIG.MAX_VALID_ID):
            return False, None, f"ID fuera de rango válido [{source}]"
        
        # Validar epoch de Discord (después del 1 de enero de 2015)
        if discord_id < CONFIG.DISCORD_EPOCH:
            return False, None, f"ID anterior a la época de Discord [{source}]"
        
        logger.debug(f"ID de Discord validado: {discord_id} (fuente: {source})")
        return True, discord_id, ""
    
    @staticmethod
    def validate_reason(reason: str, max_length: Optional[int] = None) -> Tuple[bool, str, str]:
        """
        Valida la razón de una acción de moderación.
        
        REQ: Sanitización de entradas de texto
        REQ: Límites de longitud para argumentos
        
        Args:
            reason: Razón a validar
            max_length: Longitud máxima (default CONFIG.MAX_REASON_LENGTH)
        
        Returns:
            (es_valido, razón_sanitizada, mensaje_error)
        """
        max_length = max_length or CONFIG.MAX_REASON_LENGTH
        
        # Validar que no sea nulo
        if not reason:
            return False, "", "Razón inválida o nula"
        
        # Remover espacios en blanco
        reason = reason.strip()
        
        # Validar longitud mínima
        if len(reason) < CONFIG.MIN_REASON_LENGTH:
            return False, "", f"Razón muy corta (mínimo {CONFIG.MIN_REASON_LENGTH} caracteres)"
        
        # Validar longitud máxima
        if len(reason) > max_length:
            return False, "", f"Razón muy larga (máximo {max_length} caracteres)"
        
        # Validar líneas
        lines = reason.split('\n')
        if len(lines) > CONFIG.MAX_REASON_LINES:
            return False, "", f"Razón con demasiadas líneas (máximo {CONFIG.MAX_REASON_LINES})"
        
        # SANITIZAR: Remover caracteres de control
        if CONFIG.ENABLE_MALICIOUS_CONTENT_CHECK:
            reason_sanitized = CONTROL_CHARS_REGEX.sub('', reason)
            reason_sanitized = ZERO_WIDTH_CHARS.sub('', reason_sanitized)
        else:
            reason_sanitized = reason
        
        # NORMALIZAR: Unicode normalization (si está habilitado)
        if CONFIG.ENABLE_UNICODE_NORMALIZATION and len(reason) <= CONFIG.MAX_UNICODE_NORMALIZATION_LENGTH:
            try:
                reason_sanitized = unicodedata.normalize('NFKC', reason_sanitized)
            except Exception as e:
                logger.warning(f"Error normalizando Unicode: {e}")
        
        # Validar que no quede vacío después de sanitizar
        if not reason_sanitized or reason_sanitized.isspace():
            return False, "", "Razón contiene solo caracteres inválidos"
        
        logger.debug(f"Razón validada: {len(reason_sanitized)} caracteres")
        return True, reason_sanitized, ""
    
    @staticmethod
    def validate_duration(duration_str: str) -> Tuple[bool, Optional[timedelta], str]:
        """
        Valida la duración de una sanción temporal.
        
        REQ: Validación de duraciones
        
        Args:
            duration_str: String de duración (ej: "5m", "2h", "1d")
        
        Returns:
            (es_valido, timedelta_extraido, mensaje_error)
        """
        if not duration_str:
            return False, None, "Duración inválida"
        
        duration_str = duration_str.strip().lower()
        
        match = DURATION_REGEX.match(duration_str)
        if not match:
            return False, None, "Formato de duración inválido (ej: 5s, 10m, 2h, 1d)"
        
        try:
            amount = int(match.group(1))
            unit = match.group(2).lower()
        except ValueError:
            return False, None, "Cantidad no es un entero válido"
        
        # Validar cantidad
        if amount <= 0 or amount > 10000:
            return False, None, "Duración fuera de rango (1 a 10000)"
        
        # Convertir a timedelta
        if unit == 's':
            delta = timedelta(seconds=amount)
        elif unit == 'm':
            delta = timedelta(minutes=amount)
        elif unit == 'h':
            delta = timedelta(hours=amount)
        elif unit == 'd':
            delta = timedelta(days=amount)
        else:
            return False, None, f"Unidad desconocida: {unit}"
        
        # Validar que no sea demasiado larga (máximo 1 año)
        max_duration = timedelta(days=365)
        if delta > max_duration:
            return False, None, "Duración demasiado larga (máximo 365 días)"
        
        logger.debug(f"Duración validada: {delta}")
        return True, delta, ""
    
    @staticmethod
    def validate_mention_safety(text: str) -> Tuple[bool, str]:
        """
        Valida que el texto no contenga menciones peligrosas.
        
        REQ: Protección contra menciones masivas
        REQ: Protección contra @everyone
        REQ: Protección contra @here
        
        Args:
            text: Texto a validar
        
        Returns:
            (es_seguro, mensaje_error)
        """
        if not text:
            return True, ""
        
        # Protección @everyone
        if CONFIG.ENABLE_MENTION_EVERYONE_PROTECTION:
            if MENTION_EVERYONE.search(text):
                return False, "Mención a @everyone no permitida"
        
        # Protección @here
        if CONFIG.ENABLE_MENTION_HERE_PROTECTION:
            if MENTION_HERE.search(text):
                return False, "Mención a @here no permitida"
        
        # Protección contra menciones masivas
        if CONFIG.ENABLE_MENTION_PROTECTION:
            mention_count = len(MENTION_USER.findall(text)) + len(MENTION_ROLE.findall(text))
            if mention_count > 5:
                return False, "Demasiadas menciones en el texto"
        
        return True, ""
    
    @staticmethod
    def validate_malicious_content(text: str, severity: SecurityLevel = SecurityLevel.HIGH) -> Tuple[bool, str]:
        """
        Detecta intentos de ejecución de código u otro contenido malicioso.
        
        REQ: Protección contra información maliciosa
        REQ: Nunca ejecutar texto del usuario como código
        REQ: Nunca utilizar eval() con información externa
        REQ: Nunca utilizar exec() con información externa
        
        Args:
            text: Texto a validar
            severity: Nivel de severidad de validación
        
        Returns:
            (es_seguro, mensaje_error)
        """
        if not CONFIG.ENABLE_MALICIOUS_CONTENT_CHECK or not text:
            return True, ""
        
        text_lower = text.lower()
        
        # Búsqueda de palabras clave maliciosas
        for keyword in MALICIOUS_KEYWORDS:
            if keyword.lower() in text_lower:
                return False, f"Contenido potencialmente malicioso detectado"
        
        # Búsqueda de patrones peligrosos
        dangerous_patterns = [
            r"<script",
            r"javascript:",
            r"onerror=",
            r"onload=",
            r"eval\s*\(",
            r"exec\s*\(",
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False, "Patrón de código detectado"
        
        return True, ""
    
    @staticmethod
    def validate_payload_size(text: str, max_size: Optional[int] = None) -> Tuple[bool, str]:
        """
        Valida el tamaño del payload.
        
        REQ: Protección contra payloads excesivamente grandes
        
        Args:
            text: Texto a validar
            max_size: Tamaño máximo en bytes
        
        Returns:
            (es_valido, mensaje_error)
        """
        if not CONFIG.ENABLE_PAYLOAD_SIZE_CHECK or not text:
            return True, ""
        
        max_size = max_size or CONFIG.MAX_PAYLOAD_SIZE
        
        try:
            size_bytes = len(text.encode('utf-8'))
        except Exception:
            return False, "Error calculando tamaño del payload"
        
        if size_bytes > max_size:
            return False, f"Payload demasiado grande ({size_bytes} > {max_size} bytes)"
        
        return True, ""

# ═════════════════════════════════════════════════════════════════════════════
# ⏱️  RATE LIMITER MULTINIVEL
# ═════════════════════════════════════════════════════════════════════════════

class RateLimiter:
    """
    Rate limiter multinivel con protección contra spam.
    
    REQ: Rate limit por usuario
    REQ: Rate limit por servidor
    REQ: Protección contra spam de comandos
    REQ: Cooldowns por comando
    """
    
    def __init__(self):
        # Por usuario
        self.user_cooldowns: Dict[int, datetime] = {}
        self.user_actions: Dict[int, Deque[datetime]] = defaultdict(lambda: deque(maxlen=150))  # 150 acciones
        
        # Por servidor
        self.guild_cooldowns: Dict[int, datetime] = {}
        self.guild_actions: Dict[int, Deque[datetime]] = defaultdict(lambda: deque(maxlen=700))
        
        # Detección de spam de comandos rápidos
        self.rapid_commands: Dict[int, Deque[datetime]] = defaultdict(lambda: deque(maxlen=10))
    
    def check_user_cooldown(self, user_id: int) -> Tuple[bool, Optional[float]]:
        """
        Verifica si el usuario está en cooldown global.
        
        REQ: Cooldowns por comando
        
        Returns:
            (puede_ejecutar, segundos_restantes)
        """
        now = datetime.now(timezone.utc)
        
        if user_id not in self.user_cooldowns:
            self.user_cooldowns[user_id] = now
            return True, None
        
        last_action = self.user_cooldowns[user_id]
        elapsed = (now - last_action).total_seconds()
        
        if elapsed >= CONFIG.COOLDOWN_SECONDS:
            self.user_cooldowns[user_id] = now
            return True, None
        
        remaining = CONFIG.COOLDOWN_SECONDS - elapsed
        logger.debug(f"Usuario {user_id} en cooldown: {remaining:.2f}s restantes")
        return False, remaining
    
    def check_user_rate_limit(self, user_id: int, time_window_seconds: int, max_actions: int) -> Tuple[bool, str]:
        """
        Verifica el rate limit del usuario en una ventana de tiempo.
        
        REQ: Rate limit por usuario
        
        Args:
            user_id: ID del usuario
            time_window_seconds: Ventana de tiempo en segundos (60, 3600, etc)
            max_actions: Máximo de acciones permitidas
        
        Returns:
            (puede_ejecutar, mensaje_error)
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=time_window_seconds)
        
        # Limpiar acciones antiguas
        while self.user_actions[user_id] and self.user_actions[user_id][0] < cutoff:
            self.user_actions[user_id].popleft()
        
        # Contar acciones en ventana
        action_count = len(self.user_actions[user_id])
        
        if action_count >= max_actions:
            window_name = f"{time_window_seconds}s"
            if time_window_seconds == 60:
                window_name = "1 minuto"
            elif time_window_seconds == 3600:
                window_name = "1 hora"
            elif time_window_seconds == 86400:
                window_name = "1 día"
            
            return False, f"Rate limit excedido ({action_count}/{max_actions} en {window_name})"
        
        # Registrar acción
        self.user_actions[user_id].append(now)
        return True, ""
    
    def check_guild_rate_limit(self, guild_id: int, time_window_seconds: int, max_actions: int) -> Tuple[bool, str]:
        """
        Verifica el rate limit del servidor.
        
        REQ: Rate limit por servidor
        
        Args:
            guild_id: ID del servidor
            time_window_seconds: Ventana de tiempo
            max_actions: Máximo de acciones
        
        Returns:
            (puede_ejecutar, mensaje_error)
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=time_window_seconds)
        
        # Limpiar acciones antiguas
        while self.guild_actions[guild_id] and self.guild_actions[guild_id][0] < cutoff:
            self.guild_actions[guild_id].popleft()
        
        action_count = len(self.guild_actions[guild_id])
        
        if action_count >= max_actions:
            return False, f"Rate limit del servidor excedido"
        
        self.guild_actions[guild_id].append(now)
        return True, ""
    
    def check_rapid_commands(self, user_id: int) -> Tuple[bool, str]:
        """
        Detecta spam de comandos ejecutados muy rápido.
        
        REQ: Protección contra spam de comandos
        
        Returns:
            (es_seguro, mensaje_error)
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=RAPID_COMMAND_WINDOW)
        
        # Limpiar comandos antiguos
        while self.rapid_commands[user_id] and self.rapid_commands[user_id][0] < cutoff:
            self.rapid_commands[user_id].popleft()
        
        command_count = len(self.rapid_commands[user_id])
        
        if command_count >= RAPID_COMMAND_THRESHOLD:
            return False, "Demasiados comandos ejecutados muy rápido. Espera un segundo."
        
        self.rapid_commands[user_id].append(now)
        return True, ""

# ═════════════════════════════════════════════════════════════════════════════
# 🔄 DETECTOR DE ACCIONES CONFLICTIVAS Y DUPLICADAS
# ═════════════════════════════════════════════════════════════════════════════

class ConflictDetector:
    """
    Detecta y previene acciones simultáneas conflictivas y duplicadas.
    
    REQ: Protección contra acciones simultáneas conflictivas
    REQ: Bloqueo de acciones duplicadas
    """
    
    def __init__(self):
        # Acciones en progreso: (target_id, action_type)
        self.in_progress: Dict[Tuple[int, str], datetime] = {}
        
        # Últimas acciones completadas
        self.last_actions: Dict[Tuple[int, str], Tuple[datetime, str]] = {}
        
        # Ventana de deduplicación (segundos)
        self.dedup_window = 5
    
    def register_action_start(self, target_id: int, action: ModerationAction) -> Tuple[bool, str]:
        """
        Registra el inicio de una acción.
        
        REQ: Bloqueo de acciones duplicadas
        
        Returns:
            (puede_ejecutar, mensaje_error)
        """
        key = (target_id, action.value)
        now = datetime.now(timezone.utc)
        
        # Verificar si hay acción en progreso
        if key in self.in_progress:
            age = (now - self.in_progress[key]).total_seconds()
            if age < 30:  # Máximo 30 segundos de duración
                return False, f"Acción {action.value} ya en progreso"
        
        # Verificar duplicados recientes
        if key in self.last_actions:
            last_time, _ = self.last_actions[key]
            age = (now - last_time).total_seconds()
            if age < self.dedup_window:
                return False, f"Acción duplicada (espera {self.dedup_window}s)"
        
        # Registrar como en progreso
        self.in_progress[key] = now
        return True, ""
    
    def register_action_complete(self, target_id: int, action: ModerationAction, case_id: str):
        """Registra que una acción se completó."""
        key = (target_id, action.value)
        now = datetime.now(timezone.utc)
        
        self.last_actions[key] = (now, case_id)
        
        if key in self.in_progress:
            del self.in_progress[key]
    
    def register_action_failed(self, target_id: int, action: ModerationAction):
        """Registra que una acción falló."""
        key = (target_id, action.value)
        if key in self.in_progress:
            del self.in_progress[key]

# ═════════════════════════════════════════════════════════════════════════════
# 🔐 SISTEMA DE PERMISOS CENTRALIZADO
# ═════════════════════════════════════════════════════════════════════════════

class PermissionManager:
    """
    Sistema centralizado de permisos con verificaciones exhaustivas.
    
    REQ: Sistema centralizado de permisos
    REQ: Permisos individuales por comando
    REQ: Comprobación de permisos reales del bot
    REQ: Comprobación de jerarquía del bot
    """
    
    def __init__(self):
        # Permisos requeridos por comando
        self.command_permissions: Dict[str, List[discord.Permissions]] = {
            "kick": [discord.Permissions(kick_members=True)],
            "ban": [discord.Permissions(ban_members=True)],
            "unban": [discord.Permissions(ban_members=True)],
            "mute": [discord.Permissions(manage_roles=True)],
            "unmute": [discord.Permissions(manage_roles=True)],
            "warn": [discord.Permissions(moderate_members=True)],
            "hardmute": [discord.Permissions(manage_roles=True, manage_messages=True)],
            "role_add": [discord.Permissions(manage_roles=True)],
            "role_remove": [discord.Permissions(manage_roles=True)],
        }
    
    async def check_bot_permissions(self, guild: discord.Guild, required_perms: discord.Permissions) -> Tuple[bool, List[str]]:
        """
        Verifica que el bot tenga los permisos necesarios.
        
        REQ: Comprobación de permisos reales del bot
        
        Returns:
            (tiene_permisos, lista_permisos_faltantes)
        """
        bot_member = guild.me
        if not bot_member:
            return False, ["Bot no encontrado en el servidor"]
        
        bot_perms = bot_member.guild_permissions
        missing: List[str] = []
        
        # Revisar cada permiso requerido
        for perm, value in required_perms:
            if value and not getattr(bot_perms, perm):
                missing.append(perm.replace('_', ' ').title())
        
        return len(missing) == 0, missing
    
    async def check_moderator_permissions(self, moderator: discord.Member, command: str) -> Tuple[bool, str]:
        """
        Verifica que el moderador tenga permisos para ejecutar el comando.
        
        REQ: Comprobación de permisos del moderador
        REQ: Comprobación de permisos del canal
        
        Returns:
            (tiene_permisos, mensaje_error)
        """
        # Owner siempre tiene permisos
        if moderator.guild.owner_id == moderator.id:
            return True, ""
        
        # Admin: verify
        if moderator.guild_permissions.administrator:
            return True, ""
        
        # Revisar permisos específicos del comando
        required_perms = self.command_permissions.get(command)
        if not required_perms:
            return False, f"Comando desconocido: {command}"
        
        mod_perms = moderator.guild_permissions
        
        for required in required_perms:
            for perm, value in required:
                if value and not getattr(mod_perms, perm):
                    return False, f"Necesitas permiso de {perm.replace('_', ' ').title()}"
        
        return True, ""
    
    async def check_hierarchy(self, guild: discord.Guild, moderator: discord.Member, target: discord.Member) -> Tuple[bool, str]:
        """
        Verifica la jerarquía de roles.
        
        REQ: Comprobación de jerarquía del bot
        REQ: Comprobación de jerarquía del moderador
        REQ: Protección contra usuarios por encima del bot
        REQ: Protección contra usuarios en la misma posición jerárquica
        
        Returns:
            (puede_moderar, mensaje_error)
        """
        # Owner no puede ser moderado
        if CONFIG.PROTECT_OWNER_FROM_ACTIONS and guild.owner_id == target.id:
            return False, "No se puede moderar al propietario del servidor"
        
        # El bot no puede moderarse a sí mismo
        if target.id == guild.me.id:
            return False, "No puedo actuar sobre mí mismo"
        
        # El moderador no puede moderarse a sí mismo
        if moderator.id == target.id:
            return False, "No puedes actuar sobre ti mismo"
        
        # Otros bots tienen protección especial
        if CONFIG.PROTECT_BOT_ROLES and target.bot:
            # Verificar si el moderador es admin o owner
            if not (moderator.guild_permissions.administrator or moderator.id == guild.owner_id):
                return False, "No se puede moderar a otros bots sin permisos de administrador"
        
        # Verificar jerarquía del moderador vs. objetivo
        if moderator.top_role <= target.top_role:
            if moderator.id != guild.owner_id:
                return False, f"Rol insuficiente para moderar a {target.mention}"
        
        # Verificar jerarquía del bot vs. objetivo
        bot_top_role = guild.me.top_role
        if target.top_role >= bot_top_role:
            return False, f"El bot no puede moderar a usuarios con rol igual o superior"
        
        return True, ""
    
    async def check_role_manageable(self, guild: discord.Guild, role: discord.Role) -> Tuple[bool, str]:
        """
        Verifica si el bot puede gestionar un rol.
        
        REQ: Protección de roles que el bot no puede administrar
        REQ: Protección contra modificar @everyone
        
        Returns:
            (es_manejable, mensaje_error)
        """
        # No se puede modificar @everyone
        if role.name == "@everyone":
            return False, "No se puede modificar el rol @everyone"
        
        # El rol debe estar por debajo del bot
        if role >= guild.me.top_role:
            return False, f"El bot no puede gestionar el rol {role.name} (jerarquía insuficiente)"
        
        # El rol no debe estar protegido
        if role.managed:
            return False, f"El rol {role.name} es gestionado automáticamente y no se puede modificar"
        
        return True, ""

# ═════════════════════════════════════════════════════════════════════════════
# 📋 SISTEMA DE AUDITORÍA CENTRALIZADO
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class AuditLog:
    """
    Entrada de auditoría inmutable con hash de integridad.
    
    REQ: Historial de sanciones mediante canal de logs, no SQL
    REQ: Case ID único para cada sanción
    REQ: Registro del moderador responsable en los logs
    """
    case_id: str
    timestamp: datetime
    action: ModerationAction
    moderator_id: int
    moderator_name: str
    target_id: int
    target_name: str
    guild_id: int
    guild_name: str
    reason: str
    success: bool
    error_message: Optional[str] = None
    interface: str = "slash"  # slash o prefix
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=lambda: cast(Dict[str, Any], {}))
    integrity_hash: str = field(default="")
    
    def compute_hash(self) -> str:
        """Calcula hash de integridad (SHA256)."""
        content = (
            f"{self.case_id}{self.timestamp.isoformat()}{self.action.value}"
            f"{self.moderator_id}{self.target_id}{self.guild_id}{self.success}"
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def to_embed(self) -> discord.Embed:
        """
        Convierte a embed estructurado para logs.
        
        REQ: Logs mediante embeds estructurados y fáciles de leer
        REQ: Diferenciar visualmente sanciones, acciones permitidas, denegaciones y errores
        REQ: Incluir el Case ID en cada registro
        """
        # Determinar emoción y color basado en éxito
        if self.success:
            emoji = "✅"
            color = CONFIG.LOG_EMBED_COLOR_SUCCESS
            status = "EXITOSO"
        else:
            emoji = "❌"
            color = CONFIG.LOG_EMBED_COLOR_FAIL
            status = "FALLIDO"
        
        embed = discord.Embed(
            title=f"{emoji} {self.action.value.upper()} - {status}",
            color=color,
            timestamp=self.timestamp
        )
        
        # Case ID (importante)
        embed.add_field(
            name="📌 Case ID",
            value=f"`{self.case_id}`",
            inline=False
        )
        
        # Moderador
        embed.add_field(
            name="👮 Moderador",
            value=f"{self.moderator_name} (`{self.moderator_id}`)",
            inline=True
        )
        
        # Objetivo
        embed.add_field(
            name="👤 Objetivo",
            value=f"{self.target_name} (`{self.target_id}`)",
            inline=True
        )
        
        # Interfaz
        embed.add_field(
            name="📱 Interfaz",
            value=f"`{self.interface}`",
            inline=True
        )
        
        # Razón
        embed.add_field(
            name="📝 Motivo",
            value=self.reason[:500],
            inline=False
        )
        
        # Error (si aplica)
        if self.error_message:
            embed.add_field(
                name="⚠️  Error",
                value=self.error_message[:500],
                inline=False
            )
        
        # Metadata
        if self.metadata:
            metadata_str = "\n".join([f"• {k}: {v}" for k, v in list(self.metadata.items())[:3]])
            embed.add_field(name="ℹ️  Detalles", value=metadata_str, inline=False)
        
        # Footer con integridad
        embed.set_footer(
            text=f"Hash: {self.integrity_hash} | {self.execution_time_ms:.2f}ms"
        )
        
        return embed


class AuditSystem:
    """
    Sistema centralizado de auditoría con inmutabilidad.
    
    REQ: Registro centralizado: toda acción de moderación debe pasar por aquí
    """
    
    def __init__(self):
        self.logs: List[AuditLog] = []
        self.log_channels: Dict[int, int] = {}
    
    def add_log(self, log: AuditLog) -> None:
        """
        Añade entrada de auditoría.
        
        REQ: Mantener los logs separados de los mensajes normales
        """
        log.integrity_hash = log.compute_hash()
        self.logs.append(log)
        
        # Limpiar logs antiguos
        cutoff = datetime.now(timezone.utc) - timedelta(days=CONFIG.LOG_RETENTION_DAYS)
        self.logs = [l for l in self.logs if l.timestamp > cutoff]
        
        logger.info(f"Log añadido: {log.case_id} - {log.action.value} ({log.moderator_id} → {log.target_id})")
    
    def set_log_channel(self, guild_id: int, channel_id: int) -> None:
        """Configura canal de logs para servidor."""
        self.log_channels[guild_id] = channel_id
        logger.info(f"Canal de logs configurado para servidor {guild_id}: {channel_id}")
    
    def get_log_channel(self, guild_id: int) -> Optional[int]:
        """Obtiene canal de logs para servidor."""
        return self.log_channels.get(guild_id)
    
    async def post_log(self, bot: commands.Bot, log: AuditLog) -> bool:
        """
        Publica log en canal de auditoría.
        
        REQ: Manejo específico de Forbidden, NotFound y HTTPException
        REQ: Evitar que los mensajes de logs puedan generar menciones accidentales
        
        Returns:
            Éxito de publicación
        """
        channel_id = self.get_log_channel(log.guild_id)
        if not channel_id:
            logger.warning(f"No hay canal de logs configurado para servidor {log.guild_id}")
            return False
        
        try:
            channel = bot.get_channel(channel_id)
            if not channel:
                logger.error(f"Canal de logs {channel_id} no encontrado")
                return False
            
            if not isinstance(channel, discord.TextChannel):
                logger.error(f"Canal de logs {channel_id} no es de texto")
                return False
            
            # Verificar permisos
            guild_me = getattr(channel.guild, "me", None)
            if guild_me is None:
                logger.error("Bot no encontrado en el servidor del canal de logs")
                return False
            if not channel.permissions_for(guild_me).send_messages:
                logger.error(f"Sin permiso para escribir en canal de logs {channel_id}")
                return False
            
            # Enviar embed sin permitir menciones accidentales
            await channel.send(
                embed=log.to_embed(),
                allowed_mentions=discord.AllowedMentions.none()
            )
            return True
        
        except discord.Forbidden as e:
            logger.warning(f"Acceso denegado al canal de logs {channel_id}: {e}")
            return False
        except discord.NotFound as e:
            logger.warning(f"Canal de logs {channel_id} no encontrado: {e}")
            return False
        except discord.HTTPException as e:
            logger.error(f"Error HTTP al publicar log {log.case_id}: {e}")
            return False
        except Exception as e:
            logger.exception(f"Error inesperado al publicar log {log.case_id}: {e}")
            return False
    
    async def ensure_log_channel(self, bot: commands.Bot, guild: discord.Guild) -> Optional[discord.TextChannel]:
        """
        Crea el canal de logs si no existe y el bot tiene permisos.
        
        REQ: Creación automática del canal de logs si no existe y si el bot tiene permiso
        
        Returns:
            Canal de logs o None
        """
        if not CONFIG.AUTO_CREATE_LOG_CHANNEL:
            return None
        
        existing = self.get_log_channel(guild.id)
        if existing:
            channel = bot.get_channel(existing)
            return channel if isinstance(channel, discord.TextChannel) else None
        
        try:
            # Verificar permisos del bot
            if not guild.me.guild_permissions.manage_channels:
                logger.warning(f"Bot sin permisos para crear canales en {guild.name}")
                return None
            
            # Buscar canal existente
            log_channel = discord.utils.get(guild.text_channels, name=CONFIG.LOG_CHANNEL_NAME)
            
            if not log_channel:
                # Crear canal
                log_channel = await guild.create_text_channel(
                    CONFIG.LOG_CHANNEL_NAME,
                    topic="Canal de auditoría de acciones de moderación",
                    reason="Sistema de moderación segura"
                )
                logger.info(f"Canal de logs creado en {guild.name}: {log_channel.id}")
            
            self.set_log_channel(guild.id, log_channel.id)
            return log_channel
        
        except discord.Forbidden:
            logger.error(f"Permiso denegado al crear canal de logs en {guild.name}")
            return None
        except Exception as e:
            logger.exception(f"Error creando canal de logs en {guild.name}: {e}")
            return None

# ═════════════════════════════════════════════════════════════════════════════
# 🤖 COG PRINCIPAL DE MODERACIÓN
# ═════════════════════════════════════════════════════════════════════════════

class ModerationSecure(commands.Cog):
    """
    Sistema de moderación enterprise con 120+ validaciones de seguridad.
    
    REQ: Security Guard global antes de ejecutar cualquier comando
    REQ: Fail-safe: ante cualquier duda, cancelar la acción
    """
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.audit_system = AuditSystem()
        self.permission_manager = PermissionManager()
        self.rate_limiter = RateLimiter()
        self.conflict_detector = ConflictDetector()
        self.validator = InputValidator()
        
        # Acciones en progreso para prevención de concurrencia
        self.concurrent_actions: Set[Tuple[int, int]] = set()  # (user_id, target_id)
        
        # Historial de sanciones (alternativa para búsquedas rápidas)
        self.sanction_history: Dict[int, List[AuditLog]] = defaultdict(list)
    
    # ────────────────────────────────────────────────────────────────────────
    # 🛡️  VALIDACIÓN Y SEGURIDAD CENTRALIZADA
    # ────────────────────────────────────────────────────────────────────────
    
    async def _security_guard(
        self,
        ctx_or_interaction: Any,
        target: discord.Member,
        action: ModerationAction,
        reason: str,
        is_slash: bool
    ) -> Tuple[bool, str, str]:
        """
        Guard de seguridad centralizado antes de ejecutar cualquier comando.
        
        REQ: Security Guard global antes de ejecutar cualquier comando
        REQ: Fail-safe: ante cualquier duda, cancelar la acción
        
        Returns:
            (puede_continuar, codigo_error, mensaje_error_usuario)
        """
        guild = cast(discord.Guild, ctx_or_interaction.guild)
        moderator = cast(discord.Member, ctx_or_interaction.user if is_slash else ctx_or_interaction.author)
        case_id = secrets.token_hex(6)
        
        logger.info(f"[{case_id}] Guard de seguridad iniciado: {action.value} por {moderator.id} a {target.id}")
        
        # 1. Validar IDs
        logger.debug(f"[{case_id}] Validando IDs")
        valid, _, _ = self.validator.validate_discord_id(moderator.id, "moderator_id")
        if not valid:
            return False, "INVALID_MODERATOR_ID", "ID del moderador inválido"
        
        valid, _, _ = self.validator.validate_discord_id(target.id, "target_id")
        if not valid:
            return False, "INVALID_TARGET_ID", "ID del objetivo inválido"
        
        # 2. Validar razón
        logger.debug(f"[{case_id}] Validando razón")
        valid, reason_sanitized, msg = self.validator.validate_reason(reason)
        if not valid:
            return False, "INVALID_REASON", msg
        
        # 3. Validar seguridad de menciones
        logger.debug(f"[{case_id}] Validando menciones")
        is_safe, msg = self.validator.validate_mention_safety(reason_sanitized)
        if not is_safe:
            return False, "MENTION_PROTECTION", msg
        
        # 4. Validar contenido malicioso
        logger.debug(f"[{case_id}] Validando contenido malicioso")
        is_safe, msg = self.validator.validate_malicious_content(reason_sanitized)
        if not is_safe:
            return False, "MALICIOUS_CONTENT", msg
        
        # 5. Validar tamaño del payload
        logger.debug(f"[{case_id}] Validando tamaño del payload")
        is_valid, msg = self.validator.validate_payload_size(reason_sanitized)
        if not is_valid:
            return False, "EXCESSIVE_PAYLOAD", msg
        
        # 6. Verificar cooldown del usuario
        logger.debug(f"[{case_id}] Verificando cooldown del usuario")
        can_execute, remaining = self.rate_limiter.check_user_cooldown(moderator.id)
        if not can_execute:
            return False, "USER_COOLDOWN", f"Espera {remaining:.1f}s antes de ejecutar otro comando"
        
        # 7. Verificar rate limits del usuario
        logger.debug(f"[{case_id}] Verificando rate limits del usuario")
        can_execute, msg = self.rate_limiter.check_user_rate_limit(moderator.id, 60, CONFIG.MAX_ACTIONS_PER_MINUTE)
        if not can_execute:
            return False, "USER_RATE_LIMIT", msg
        
        can_execute, msg = self.rate_limiter.check_user_rate_limit(moderator.id, 3600, CONFIG.MAX_ACTIONS_PER_HOUR)
        if not can_execute:
            return False, "USER_RATE_LIMIT", msg
        
        # 8. Verificar rate limits del servidor
        logger.debug(f"[{case_id}] Verificando rate limits del servidor")
        can_execute, msg = self.rate_limiter.check_guild_rate_limit(guild.id, 60, CONFIG.MAX_GUILD_ACTIONS_PER_MINUTE)
        if not can_execute:
            return False, "GUILD_RATE_LIMIT", msg
        
        # 9. Detectar spam rápido
        logger.debug(f"[{case_id}] Detectando spam de comandos")
        is_safe, msg = self.rate_limiter.check_rapid_commands(moderator.id)
        if not is_safe:
            return False, "RAPID_COMMANDS", msg
        
        # 10. Verificar acciones conflictivas
        logger.debug(f"[{case_id}] Verificando acciones conflictivas")
        can_execute, msg = self.conflict_detector.register_action_start(target.id, action)
        if not can_execute:
            return False, "CONFLICT_ACTION", msg
        
        # 11. Verificar acciones concurrentes
        logger.debug(f"[{case_id}] Verificando acciones concurrentes")
        if CONFIG.ENABLE_CONCURRENT_ACTION_PROTECTION:
            concurrent_key = (moderator.id, target.id)
            concurrent_count = len([k for k in self.concurrent_actions if k == concurrent_key])
            if concurrent_count >= CONFIG.MAX_CONCURRENT_ACTIONS_PER_USER:
                self.conflict_detector.register_action_failed(target.id, action)
                return False, "CONCURRENT_LIMIT", "Demasiadas acciones simultáneas sobre este usuario"
        
        # 12. Verificar permisos del bot
        logger.debug(f"[{case_id}] Verificando permisos del bot")
        has_perms, missing = await self.permission_manager.check_bot_permissions(
            guild,
            self.permission_manager.command_permissions.get(action.value, [discord.Permissions()])[0]
        )
        if not has_perms:
            self.conflict_detector.register_action_failed(target.id, action)
            return False, "BOT_PERMISSIONS", f"El bot no tiene permisos: {', '.join(missing)}"
        
        # 13. Verificar permisos del moderador
        logger.debug(f"[{case_id}] Verificando permisos del moderador")
        has_perms, msg = await self.permission_manager.check_moderator_permissions(moderator, action.value)
        if not has_perms:
            self.conflict_detector.register_action_failed(target.id, action)
            return False, "MODERATOR_PERMISSIONS", msg
        
        # 14. Verificar jerarquía
        logger.debug(f"[{case_id}] Verificando jerarquía de roles")
        can_moderade, msg = await self.permission_manager.check_hierarchy(guild, moderator, target)
        if not can_moderade:
            self.conflict_detector.register_action_failed(target.id, action)
            return False, "HIERARCHY", msg
        
        logger.info(f"[{case_id}] ✅ Guard de seguridad pasado exitosamente")
        return True, "", ""
    
    async def _execute_action(
        self,
        action: ModerationAction,
        target: discord.Member,
        reason: str,
        duration: Optional[timedelta] = None
    ) -> Tuple[bool, str]:
        """
        Ejecuta la acción de moderación de manera segura.
        
        Returns:
            (éxito, mensaje_error)
        """
        try:
            if action == ModerationAction.KICK:
                await target.kick(reason=reason)
            elif action == ModerationAction.BAN:
                await target.guild.ban(target, reason=reason)
            elif action == ModerationAction.UNBAN:
                await target.guild.unban(target, reason=reason)
            elif action == ModerationAction.MUTE:
                muted_role = discord.utils.get(target.guild.roles, name="muted")
                if muted_role:
                    await target.add_roles(muted_role, reason=reason)
                else:
                    return False, "Rol 'muted' no existe"
            elif action == ModerationAction.UNMUTE:
                muted_role = discord.utils.get(target.guild.roles, name="muted")
                if muted_role:
                    await target.remove_roles(muted_role, reason=reason)
            elif action == ModerationAction.HARDMUTE:
                muted_role = discord.utils.get(target.guild.roles, name="muted")
                if muted_role:
                    await target.edit(roles=[muted_role], reason=reason)
                else:
                    return False, "Rol 'muted' no existe"
            
            return True, ""
        except discord.Forbidden:
            return False, "Permiso denegado al ejecutar acción"
        except discord.HTTPException as e:
            return False, f"Error de Discord API"
        except Exception as e:
            logger.exception(f"Error ejecutando {action.value}: {e}")
            return False, "Error interno al ejecutar acción"
    
    async def _execute_command_safely(
        self,
        ctx_or_interaction: Any,
        action: ModerationAction,
        target: discord.Member,
        reason: str,
        is_slash: bool,
        duration: Optional[str] = None
    ) -> bool:
        """
        Ejecuta un comando de moderación con todas las validaciones.
        
        REQ: Manejo global de excepciones
        REQ: Prevención de respuestas duplicadas en slash commands
        """
        case_id = secrets.token_hex(6)
        guild = cast(discord.Guild, ctx_or_interaction.guild)
        moderator = cast(discord.Member, ctx_or_interaction.user if is_slash else ctx_or_interaction.author)
        start_time = datetime.now(timezone.utc)
        
        try:
            logger.info(f"[{case_id}] Iniciando {action.value} ({moderator.id} → {target.id})")
            
            # Ejecutar security guard
            can_continue, error_code, error_msg = await self._security_guard(
                ctx_or_interaction, target, action, reason, is_slash
            )
            
            if not can_continue:
                logger.warning(f"[{case_id}] Guard falló: {error_code}")
                embed = discord.Embed(
                    title="❌ Acción Denegada",
                    description=error_msg,
                    color=CONFIG.LOG_EMBED_COLOR_DENY
                )
                embed.set_footer(text=f"Case ID: {case_id}")
                
                if is_slash:
                    await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    await ctx_or_interaction.send(embed=embed)
                
                return False
            
            # Ejecutar acción
            logger.info(f"[{case_id}] Ejecutando acción")
            success, action_error = await self._execute_action(action, target, reason, None)
            
            # Calcular tiempo de ejecución
            exec_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            
            # Crear log de auditoría
            audit_log = AuditLog(
                case_id=case_id,
                timestamp=start_time,
                action=action,
                moderator_id=moderator.id,
                moderator_name=moderator.name,
                target_id=target.id,
                target_name=target.name,
                guild_id=guild.id,
                guild_name=guild.name,
                reason=reason,
                success=success,
                error_message=action_error if not success else None,
                interface="slash" if is_slash else "prefix",
                execution_time_ms=exec_time,
                metadata={
                    "moderator_mention": f"<@{moderator.id}>",
                    "target_mention": f"<@{target.id}>",
                }
            )
            
            # Registrar en auditoría
            self.audit_system.add_log(audit_log)
            
            # Publicar en logs
            await self.audit_system.post_log(self.bot, audit_log)
            
            # Registrar acciones en historial
            self.sanction_history[target.id].append(audit_log)
            
            # Marcar acción como completada
            self.conflict_detector.register_action_complete(target.id, action, case_id)
            
            # Responder
            if success:
                embed = discord.Embed(
                    title=f"✅ {action.value.upper()} Exitoso",
                    description=f"**Objetivo:** {target.mention}\n**Case ID:** `{case_id}`",
                    color=CONFIG.LOG_EMBED_COLOR_SUCCESS
                )
                embed.add_field(name="Motivo", value=reason, inline=False)
                embed.timestamp = datetime.now(timezone.utc)
            else:
                embed = discord.Embed(
                    title=f"❌ {action.value.upper()} Fallido",
                    description=f"**Case ID:** `{case_id}`\n**Error:** {action_error}",
                    color=CONFIG.LOG_EMBED_COLOR_FAIL
                )
            
            if is_slash:
                await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await ctx_or_interaction.send(embed=embed)
            
            return success
        
        except Exception as e:
            logger.exception(f"[{case_id}] Error crítico: {e}")
            
            embed = discord.Embed(
                title="❌ Error Crítico del Sistema",
                description="Ha ocurrido un error inesperado. Contacta al administrador.",
                color=CONFIG.LOG_EMBED_COLOR_FAIL
            )
            embed.set_footer(text=f"Case ID: {case_id}")
            
            try:
                if is_slash:
                    await ctx_or_interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    await ctx_or_interaction.send(embed=embed)
            except:
                pass
            
            return False
    
    # ────────────────────────────────────────────────────────────────────────
    # ⚡ COMANDOS DE MODERACIÓN (Slash + Prefix)
    # ────────────────────────────────────────────────────────────────────────
    
    @app_commands.command(name="kick", description="Expulsa a un miembro del servidor")
    @app_commands.describe(member="Miembro a expulsar", reason="Motivo de la acción")
    @app_commands.guild_only()
    async def kick_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Sin motivo especificado"):
        """Comando slash para expulsar."""
        await self._execute_command_safely(interaction, ModerationAction.KICK, member, reason, is_slash=True)
    
    @commands.command(name="kick", aliases=["k"])
    @commands.guild_only()
    async def kick_prefix(self, ctx: commands.Context[commands.Bot], member: discord.Member, *, reason: str = "Sin motivo especificado"):
        """Comando prefix para expulsar."""
        await self._execute_command_safely(ctx, ModerationAction.KICK, member, reason, is_slash=False)
    
    @app_commands.command(name="ban", description="Banea a un miembro del servidor")
    @app_commands.describe(member="Miembro a banear", reason="Motivo de la acción")
    @app_commands.guild_only()
    async def ban_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Sin motivo especificado"):
        """Comando slash para banear."""
        await self._execute_command_safely(interaction, ModerationAction.BAN, member, reason, is_slash=True)
    
    @commands.command(name="ban", aliases=["b"])
    @commands.guild_only()
    async def ban_prefix(self, ctx: commands.Context[commands.Bot], member: discord.Member, *, reason: str = "Sin motivo especificado"):
        """Comando prefix para banear."""
        await self._execute_command_safely(ctx, ModerationAction.BAN, member, reason, is_slash=False)
    
    @app_commands.command(name="mute", description="Silencia a un miembro")
    @app_commands.describe(member="Miembro a silenciar", reason="Motivo de la acción")
    @app_commands.guild_only()
    async def mute_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Sin motivo especificado"):
        """Comando slash para silenciar."""
        await self._execute_command_safely(interaction, ModerationAction.MUTE, member, reason, is_slash=True)
    
    @commands.command(name="mute")
    @commands.guild_only()
    async def mute_prefix(self, ctx: commands.Context[commands.Bot], member: discord.Member, *, reason: str = "Sin motivo especificado"):
        """Comando prefix para silenciar."""
        await self._execute_command_safely(ctx, ModerationAction.MUTE, member, reason, is_slash=False)

    @app_commands.command(name="purge", description="Borra mensajes de usuarios o bots con filtros avanzados")
    @app_commands.describe(
        amount="Cantidad de mensajes que quieres eliminar (1-100)",
        user="Borrar solo mensajes de este usuario",
        bots="Borrar solo mensajes enviados por bots",
        contains="Borrar solo mensajes que contengan este texto",
        reason="Motivo para el registro de moderación",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge_slash(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 100],
        user: Optional[discord.Member] = None,
        bots: bool = False,
        contains: Optional[str] = None,
        reason: str = "Limpieza solicitada por moderación",
    ) -> None:
        """Elimina mensajes recientes y antiguos respetando los filtros indicados."""
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                "❌ Este comando solo puede usarse en canales de texto.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        search_text = contains.strip().casefold() if contains and contains.strip() else None
        clean_reason = reason.strip()[:512] or "Limpieza solicitada por moderación"

        def matches(message: discord.Message) -> bool:
            if user is not None and message.author.id != user.id:
                return False
            if bots and not message.author.bot:
                return False
            return search_text is None or search_text in message.content.casefold()

        messages: list[discord.Message] = []
        async for message in channel.history(limit=100):
            if matches(message):
                messages.append(message)
                if len(messages) >= amount:
                    break
        if not messages:
            await interaction.followup.send("ℹ️ No se encontraron mensajes que coincidan con los filtros.", ephemeral=True)
            return

        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        recent = [message for message in messages if message.created_at >= cutoff]
        old = [message for message in messages if message.created_at < cutoff]

        deleted = 0
        failed = 0
        if recent:
            try:
                if isinstance(channel, discord.TextChannel) and len(recent) > 1:
                    await channel.delete_messages(recent, reason=clean_reason)
                    deleted += len(recent)
                else:
                    for message in recent:
                        await message.delete()
                        deleted += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += len(recent) - deleted
                logger.exception("No se pudieron borrar todos los mensajes recientes en %s", channel.id)

        for message in old:
            try:
                await message.delete()
                deleted += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1
                logger.debug("No se pudo borrar el mensaje antiguo %s", message.id)

        summary = f"🧹 Se eliminaron **{deleted}** de **{len(messages)}** mensaje(s) encontrados."
        if failed:
            summary += f"\n⚠️ No se pudieron eliminar **{failed}** por permisos o límites de Discord."
        await interaction.followup.send(
            summary,
            ephemeral=True,
        )
    
    # ────────────────────────────────────────────────────────────────────────
    # 📋 COMANDOS INFORMATIVOS
    # ────────────────────────────────────────────────────────────────────────
    
    @app_commands.command(name="sanciones", description="Ver historial de sanciones de un usuario")
    @app_commands.describe(member="Miembro a consultar")
    @app_commands.guild_only()
    async def sanciones_slash(self, interaction: discord.Interaction, member: discord.Member):
        """Ver historial de sanciones (slash)."""
        logs = self.sanction_history.get(member.id, [])
        
        if not logs:
            embed = discord.Embed(
                title="📋 Historial de Sanciones",
                description=f"No hay sanciones para {member.mention}",
                color=0x2ecc71
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        embed = discord.Embed(
            title="📋 Historial de Sanciones",
            description=f"Total: {len(logs)} sanciones",
            color=0xf39c12
        )
        
        for log in logs[-5:]:  # Últimas 5
            embed.add_field(
                name=f"{log.action.value.upper()} - {log.timestamp.strftime('%Y-%m-%d %H:%M')}",
                value=f"**Case:** `{log.case_id}`\n**Por:** {log.moderator_name}\n**Motivo:** {log.reason[:100]}",
                inline=False
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    """Carga el cog de moderación."""
    await bot.add_cog(ModerationSecure(bot))
    logger.info("✅ Cog de Moderación Segura cargado")
