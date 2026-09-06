"""Cog de trivia profesional e interactivo usando OpenTDB API."""
from __future__ import annotations

import asyncio
import html
import random
from dataclasses import dataclass
from functools import partial
from typing import Any, Optional, TypedDict, cast

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Select, View


# ============================================================================
# CONSTANTES Y TIPOS
# ============================================================================

OPENTDB_API = "https://opentdb.com/api.php"
OPENTDB_CATEGORIES = "https://opentdb.com/api_category.php"
OPENTDB_TOKEN = "https://opentdb.com/api_token.php"

TIMEOUT_PREGUNTA = 20  # segundos
MAX_PREGUNTAS = 50
OpenTDBResult = dict[str, Any]


class OpenTDBQuestion(TypedDict, total=False):
    """Estructura de una pregunta desde OpenTDB."""
    category: str
    type: str
    difficulty: str
    question: str
    correct_answer: str
    incorrect_answers: list[str]


class OpenTDBCategoryItem(TypedDict, total=False):
    """Estructura de un item de categoría desde OpenTDB."""
    id: int
    name: str


@dataclass
class Pregunta:
    """Representa una pregunta de trivia."""
    texto: str
    respuestas: list[str]
    correcta: int  # 脥ndice de la respuesta correcta
    categoria: str
    dificultad: str
    tipo: str  # "multiple" o "boolean"


@dataclass
class ConfiguracionTrivia:
    """Configuraci贸n de la trivia."""
    categoria: Optional[int] = None
    dificultad: Optional[str] = None
    tipo: Optional[str] = None
    cantidad: int = 10


@dataclass
class SesionTrivia:
    """Sesi贸n activa de trivia para un usuario."""
    usuario_id: int
    preguntas: list[Pregunta]
    configuracion: ConfiguracionTrivia
    token_sesion: Optional[str]
    pregunta_actual: int = 0
    correctas: int = 0
    incorrectas: int = 0
    sin_responder: int = 0
    mensaje: Optional[discord.Message] = None
    tarea_temporizador: Optional[asyncio.Task[None]] = None


# ============================================================================
# SERVICIOS DE API
# ============================================================================

class ServicioOpenTDB:
    """Gestiona las solicitudes a la API de OpenTDB."""

    def __init__(self):
        self.sesion: Optional[aiohttp.ClientSession] = None
        self.categorias_cache: dict[int, str] = {}

    async def inicializar(self) -> None:
        """Inicializa la sesi贸n de aiohttp."""
        if not self.sesion:
            self.sesion = aiohttp.ClientSession()

    async def cerrar(self) -> None:
        """Cierra la sesi贸n de aiohttp."""
        if self.sesion:
            await self.sesion.close()
            self.sesion = None

    async def obtener_categorias(self) -> dict[int, str]:
        """Obtiene todas las categor铆as disponibles de OpenTDB."""
        if self.categorias_cache:
            return self.categorias_cache

        try:
            if self.sesion is None:
                await self.inicializar()

            if self.sesion is None:
                raise Exception("No se pudo inicializar sesión")

            async with self.sesion.get(OPENTDB_CATEGORIES, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    raise Exception(f"Error HTTP {resp.status}")
                datos_raw: Any = await resp.json()
                datos: dict[str, Any] = cast(dict[str, Any], datos_raw if isinstance(datos_raw, dict) else {})

            categorias_raw: list[Any] = cast(list[Any], datos.get("trivia_categories", []))

            self.categorias_cache = {}
            for item_raw in categorias_raw:
                if not isinstance(item_raw, dict):
                    continue
                item: OpenTDBCategoryItem = item_raw  # type: ignore
                cat_id: Any = item.get("id")
                name: Any = item.get("name")
                if isinstance(cat_id, int) and isinstance(name, str):
                    self.categorias_cache[cat_id] = name

            return self.categorias_cache

        except asyncio.TimeoutError:
            raise Exception("Timeout al obtener categor铆as")
        except Exception as e:
            raise Exception(f"Error al obtener categor铆as: {str(e)}")

    async def crear_token_sesion(self) -> Optional[str]:
        """Crea un nuevo token de sesi贸n."""
        try:
            if self.sesion is None:
                await self.inicializar()

            if self.sesion is None:
                return None

            async with self.sesion.get(
                OPENTDB_TOKEN,
                params={"command": "request"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return None
                datos = await resp.json()
                return datos.get("token")

        except Exception:
            return None

    async def obtener_preguntas(
        self,
        cantidad: int,
        categoria: Optional[int] = None,
        dificultad: Optional[str] = None,
        tipo: Optional[str] = None,
        token: Optional[str] = None,
    ) -> list[Pregunta]:
        """Obtiene preguntas de OpenTDB."""
        params: dict[str, Any] = {"amount": min(cantidad, MAX_PREGUNTAS)}

        if categoria:
            params["category"] = categoria
        if dificultad and dificultad != "random":
            params["difficulty"] = dificultad
        if tipo and tipo != "random":
            params["type"] = tipo
        if token:
            params["token"] = token

        try:
            if self.sesion is None:
                await self.inicializar()
            
            if self.sesion is None:
                raise Exception("No se pudo inicializar sesión")

            async with self.sesion.get(
                OPENTDB_API,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    raise Exception(f"Error HTTP {resp.status}")

                datos_raw: Any = await resp.json()
                datos: dict[str, Any] = cast(dict[str, Any], datos_raw if isinstance(datos_raw, dict) else {})

                response_code = datos.get("response_code")

                if response_code == 0:
                    results: list[Any] = cast(list[Any], datos.get("results", []))
                    return self._procesar_preguntas(results)
                elif response_code == 1:
                    raise Exception("No hay suficientes preguntas disponibles")
                elif response_code == 2:
                    raise Exception("Par谩metros inv谩lidos")
                elif response_code == 4:
                    raise Exception("Token de sesi贸n agotado")
                elif response_code == 5:
                    raise Exception("Demasiadas solicitudes (rate limit)")
                else:
                    raise Exception(f"Error desconocido de API (c贸digo {response_code})")

        except asyncio.TimeoutError:
            raise Exception("Timeout al obtener preguntas")
        except Exception as e:
            if "desconocido" not in str(e):
                raise
            raise Exception("Error de conexi贸n con OpenTDB")

    def _procesar_preguntas(self, resultados: list[Any]) -> list[Pregunta]:
        """Procesa los resultados de OpenTDB."""
        preguntas: list[Pregunta] = []

        for item in resultados:
            try:
                # Decodificar entidades HTML
                texto = html.unescape(item.get("question", ""))
                respuesta_correcta = html.unescape(item.get("correct_answer", ""))
                respuestas_incorrectas = [
                    html.unescape(r) for r in item.get("incorrect_answers", [])
                ]

                # Combinar y mezclar respuestas
                todas_respuestas = [respuesta_correcta] + respuestas_incorrectas
                random.shuffle(todas_respuestas)

                # Encontrar el 铆ndice de la respuesta correcta
                indice_correcta = todas_respuestas.index(respuesta_correcta)

                pregunta = Pregunta(
                    texto=texto,
                    respuestas=todas_respuestas,
                    correcta=indice_correcta,
                    categoria=html.unescape(item.get("category", "")),
                    dificultad=item.get("difficulty", "").capitalize(),
                    tipo=item.get("type", ""),
                )
                preguntas.append(pregunta)

            except Exception:
                continue

        return preguntas


# ============================================================================
# VISTAS DE DISCORD
# ============================================================================

class VistaConfiguracion(View):
    """Interfaz de configuraci贸n de trivia."""

    def __init__(
        self,
        usuario_id: int,
        categorias: dict[int, str],
        timeout: float = 300,
    ):
        super().__init__(timeout=timeout)
        self.usuario_id = usuario_id
        self.configuracion: ConfiguracionTrivia | None = ConfiguracionTrivia()
        self.categorias = categorias
        self.lista_categorias = sorted(categorias.items())

        self._actualizar_selects()

    def _actualizar_selects(self) -> None:
        """Actualiza los select menus con opciones."""
        self.clear_items()

        # Select de categor铆as
        opciones_cat = [
            discord.SelectOption(label="Aleatoria", value="random", emoji="🎲")
        ]
        opciones_cat.extend([
            discord.SelectOption(label=nombre, value=str(cat_id))
            for cat_id, nombre in self.lista_categorias
        ])

        select_categoria: Select[Any] = Select(
            placeholder="Selecciona una categor铆a",
            options=opciones_cat[:25],  # L铆mite de Discord
            custom_id="select_categoria",
        )
        select_categoria.callback = self._callback_categoria
        self.add_item(select_categoria)

        # Select de dificultad
        select_dificultad: Select[Any] = Select(
            placeholder="Selecciona dificultad",
            options=[
                discord.SelectOption(label="Aleatoria", value="random", emoji="🎲"),
                discord.SelectOption(label="Fácil", value="easy", emoji="🟢"),
                discord.SelectOption(label="Media", value="medium", emoji="🟡"),
                discord.SelectOption(label="Difícil", value="hard", emoji="🔴"),
            ],
            custom_id="select_dificultad",
        )
        select_dificultad.callback = self._callback_dificultad
        self.add_item(select_dificultad)

        # Select de tipo
        select_tipo: Select[Any] = Select(
            placeholder="Selecciona tipo de pregunta",
            options=[
                discord.SelectOption(label="Aleatorio", value="random", emoji="🎲"),
                discord.SelectOption(label="Opción múltiple", value="multiple", emoji="💠"),
                discord.SelectOption(label="Verdadero/Falso", value="boolean", emoji="✅"),
            ],
            custom_id="select_tipo",
        )
        select_tipo.callback = self._callback_tipo
        self.add_item(select_tipo)

        # Select de cantidad
        select_cantidad: Select[Any] = Select(
            placeholder="Selecciona cantidad de preguntas",
            options=[
                discord.SelectOption(label=f"{n} preguntas", value=str(n))
                for n in [5, 10, 15, 20, 25, 30]
            ],
            custom_id="select_cantidad",
        )
        select_cantidad.callback = self._callback_cantidad
        self.add_item(select_cantidad)

        # Botones
        btn_comenzar: Button[Any] = Button(
            label="Comenzar",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id="btn_comenzar",
        )
        btn_comenzar.callback = self._callback_comenzar
        self.add_item(btn_comenzar)

        btn_cancelar: Button[Any] = Button(
            label="Cancelar",
            emoji="❌",
            style=discord.ButtonStyle.danger,
            custom_id="btn_cancelar",
        )
        btn_cancelar.callback = self._callback_cancelar
        self.add_item(btn_cancelar)

    async def _verificar_usuario(self, interaction: discord.Interaction) -> bool:
        """Verifica que sea el usuario correcto."""
        if interaction.user.id != self.usuario_id:
            await interaction.response.send_message(
                "❌ Esta trivia no te pertenece / This trivia is not yours.",
                ephemeral=True,
            )
            return False
        return True

    @staticmethod
    def _interaction_values(interaction: discord.Interaction) -> list[str]:
        data = interaction.data
        values: list[Any] = cast(list[Any], data.get("values")) if isinstance(data, dict) else []
        return [str(v) for v in values if v is not None]

    async def _callback_categoria(self, interaction: discord.Interaction) -> None:
        if not await self._verificar_usuario(interaction):
            return

        if self.configuracion is None:
            return

        valores = self._interaction_values(interaction)
        valor = valores[0] if valores else "random"
        if valor == "random":
            self.configuracion.categoria = None
        else:
            try:
                self.configuracion.categoria = int(valor)
            except ValueError:
                self.configuracion.categoria = None

        await interaction.response.defer()
        await self._actualizar_mensaje(interaction)

    async def _callback_dificultad(self, interaction: discord.Interaction) -> None:
        if not await self._verificar_usuario(interaction):
            return
        if self.configuracion is None:
            return

        valores = self._interaction_values(interaction)
        self.configuracion.dificultad = valores[0] if valores else None
        await interaction.response.defer()
        await self._actualizar_mensaje(interaction)

    async def _callback_tipo(self, interaction: discord.Interaction) -> None:
        if not await self._verificar_usuario(interaction):
            return
        if self.configuracion is None:
            return

        valores = self._interaction_values(interaction)
        self.configuracion.tipo = valores[0] if valores else None
        await interaction.response.defer()
        await self._actualizar_mensaje(interaction)

    async def _callback_cantidad(self, interaction: discord.Interaction) -> None:
        if not await self._verificar_usuario(interaction):
            return
        if self.configuracion is None:
            return

        valores = self._interaction_values(interaction)
        valor = valores[0] if valores else "10"
        try:
            self.configuracion.cantidad = int(valor)
        except ValueError:
            self.configuracion.cantidad = 10
        await interaction.response.defer()
        await self._actualizar_mensaje(interaction)

    async def _callback_comenzar(self, interaction: discord.Interaction) -> None:
        if not await self._verificar_usuario(interaction):
            return
        await interaction.response.defer()
        self.stop()

    async def _callback_cancelar(self, interaction: discord.Interaction) -> None:
        if not await self._verificar_usuario(interaction):
            return

        await interaction.response.defer()
        self.stop()
        self.configuracion = None

    async def _actualizar_mensaje(self, interaction: discord.Interaction) -> None:
        """Actualiza el embed de configuración."""
        if self.configuracion is None:
            return

        categoria_nombre = "Aleatoria"
        if self.configuracion.categoria:
            categoria_nombre = self.categorias.get(
                self.configuracion.categoria, "Desconocida"
            )

        dificultad_nombre = {
            "random": "Aleatoria",
            "easy": "F谩cil",
            "medium": "Media",
            "hard": "Dif铆cil",
        }.get(self.configuracion.dificultad or "random", "Aleatoria")

        tipo_nombre = {
            "random": "Aleatorio",
            "multiple": "Opci贸n m煤ltiple",
            "boolean": "Verdadero/Falso",
        }.get(self.configuracion.tipo or "random", "Aleatorio")

        embed = discord.Embed(
            title="🎮 CONFIGURAR TRIVIA / Trivia Setup",
            description="Ajusta los parámetros de la trivia / Adjust the trivia settings",
            color=discord.Color.teal(),
        )
        embed.add_field(name="📚 Categoría / Category", value=categoria_nombre, inline=False)
        embed.add_field(name="⚙️ Dificultad / Difficulty", value=dificultad_nombre, inline=False)
        embed.add_field(name="🧩 Tipo / Type", value=tipo_nombre, inline=False)
        embed.add_field(name="🔢 Preguntas / Questions", value=str(self.configuracion.cantidad), inline=False)

        if interaction.message:
            await interaction.message.edit(embed=embed, view=self)


class VistaPregunta(View):
    """Interfaz para responder preguntas."""

    def __init__(self, pregunta: Pregunta, usuario_id: int, timeout: float = TIMEOUT_PREGUNTA):
        super().__init__(timeout=timeout)
        self.usuario_id = usuario_id
        self.pregunta = pregunta
        self.respondido = False
        self.respuesta_usuario: Optional[int] = None

        self._crear_botones()

    def _crear_botones(self) -> None:
        """Crea los botones de respuesta."""
        self.clear_items()

        if self.pregunta.tipo == "boolean":
            respuestas = ["Verdadero", "Falso"]
        else:
            respuestas = self.pregunta.respuestas

        for i, respuesta in enumerate(respuestas):
            btn: Button[Any] = Button(
                label=respuesta[:80],
                style=discord.ButtonStyle.primary,
                custom_id=f"resp_{i}",
            )
            btn.callback = partial(self._callback_respuesta, indice=i)
            self.add_item(btn)

    async def _callback_respuesta(self, interaction: discord.Interaction, indice: int) -> None:
        """Maneja la selección de respuesta."""
        if interaction.user.id != self.usuario_id:
            await interaction.response.send_message(
                "❌ Esta trivia no te pertenece / This trivia is not yours.",
                ephemeral=True,
            )
            return

        if self.respondido:
            await interaction.response.send_message(
                "✅ Ya respondiste esta pregunta / You already answered this question.",
                ephemeral=True,
            )
            return

        self.respondido = True
        self.respuesta_usuario = indice
        await interaction.response.defer()
        self.stop()


class VistaResultado(View):
    """Interfaz para mostrar resultado y continuar."""

    def __init__(self, usuario_id: int, es_ultima: bool = False):
        super().__init__(timeout=300)
        self.usuario_id = usuario_id
        self.continuar = False
        self.reiniciar = False

        if es_ultima:
            btn: Button[VistaResultado] = Button(
                label="Ver resultado",
                emoji="📊",
                style=discord.ButtonStyle.success,
            )
            btn.callback = self._callback_resultado
            self.add_item(btn)
        else:
            btn = Button(
                label="Siguiente pregunta",
                emoji="➡️",
                style=discord.ButtonStyle.primary,
            )
            btn.callback = self._callback_siguiente
            self.add_item(btn)

        btn_finalizar: Button[Any] = Button(
            label="Finalizar",
            emoji="⏹️",
            style=discord.ButtonStyle.danger,
        )
        btn_finalizar.callback = self._callback_finalizar
        self.add_item(btn_finalizar)

    async def _verificar_usuario(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.usuario_id:
            await interaction.response.send_message(
                "❌ Esta trivia no te pertenece / This trivia is not yours.",
                ephemeral=True,
            )
            return False
        return True

    async def _callback_siguiente(self, interaction: discord.Interaction) -> None:
        if not await self._verificar_usuario(interaction):
            return
        self.continuar = True
        await interaction.response.defer()
        self.stop()

    async def _callback_resultado(self, interaction: discord.Interaction) -> None:
        if not await self._verificar_usuario(interaction):
            return
        self.continuar = True
        await interaction.response.defer()
        self.stop()

    async def _callback_finalizar(self, interaction: discord.Interaction) -> None:
        if not await self._verificar_usuario(interaction):
            return
        self.reiniciar = True
        await interaction.response.defer()
        self.stop()


# ============================================================================
# COG PRINCIPAL
# ============================================================================

class Trivia(commands.Cog):
    """Cog de trivia profesional con OpenTDB."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.servicio = ServicioOpenTDB()
        self.sesiones: dict[int, SesionTrivia] = {}

    async def cog_load(self) -> None:
        """Se ejecuta cuando el cog se carga."""
        await self.servicio.inicializar()

    async def cog_unload(self) -> None:
        """Se ejecuta cuando el cog se descarga."""
        await self.servicio.cerrar()
        # Cancelar todas las sesiones activas
        for sesion in self.sesiones.values():
            if sesion.tarea_temporizador:
                sesion.tarea_temporizador.cancel()

    @app_commands.command(name="trivia", description="Inicia una sesión de trivia interactiva / Start an interactive trivia session")
    async def trivia(self, interaction: discord.Interaction) -> None:
        """Comando principal de trivia."""
        usuario_id = interaction.user.id

        # Verificar si ya hay sesión activa
        if usuario_id in self.sesiones:
            await interaction.response.send_message(
                "⚠️ Ya tienes una trivia en progreso / You already have a trivia in progress.",
                ephemeral=True,
            )
            return

        try:
            # Mostrar indicador de carga
            await interaction.response.defer()

            # Obtener categorías
            categorias = await self.servicio.obtener_categorias()

            # Crear vista de configuración
            vista_config = VistaConfiguracion(usuario_id, categorias)

            embed = discord.Embed(
                title="🎮 CONFIGURAR TRIVIA / Trivia Setup",
                description="Ajusta los parámetros de la trivia / Adjust the trivia settings",
                color=discord.Color.teal(),
            )
            embed.add_field(name="📚 Categoría / Category", value="Aleatoria / Random", inline=False)
            embed.add_field(name="⚙️ Dificultad / Difficulty", value="Aleatoria / Random", inline=False)
            embed.add_field(name="🧩 Tipo / Type", value="Aleatorio / Random", inline=False)
            embed.add_field(name="🔢 Preguntas / Questions", value="10", inline=False)

            mensaje = await interaction.followup.send(embed=embed, view=vista_config, wait=True)

            # Esperar a que se configure
            await asyncio.wait_for(vista_config.wait(), timeout=300)

            if vista_config.configuracion is None:
                await mensaje.edit(content="❌ Trivia cancelada / Trivia cancelled.", embed=None, view=None)
                return

            await mensaje.delete()

            # Crear token de sesión
            token = await self.servicio.crear_token_sesion()

            # Obtener preguntas
            await interaction.followup.send(content="⏳ Obteniendo preguntas... / Getting questions...", ephemeral=True)

            preguntas = await self.servicio.obtener_preguntas(
                cantidad=vista_config.configuracion.cantidad,
                categoria=vista_config.configuracion.categoria,
                dificultad=vista_config.configuracion.dificultad,
                tipo=vista_config.configuracion.tipo,
                token=token,
            )

            if not preguntas:
                await interaction.followup.send(
                    content="❌ No se encontraron preguntas con esos parámetros / No questions found with those settings.",
                    ephemeral=True,
                )
                return

            # Crear sesi贸n
            sesion = SesionTrivia(
                usuario_id=usuario_id,
                preguntas=preguntas,
                configuracion=vista_config.configuracion,
                token_sesion=token,
            )
            self.sesiones[usuario_id] = sesion

            # Mostrar primera pregunta
            await self._mostrar_pregunta(interaction, sesion)

        except asyncio.TimeoutError:
            await interaction.followup.send(
                content="⏰ Tiempo agotado en la configuración / Configuration timed out.",
                ephemeral=True,
            )
        except Exception as e:
            mensaje_error = self._obtener_mensaje_error(str(e))
            await interaction.followup.send(
                content=f"❌ {mensaje_error}",
                ephemeral=True,
            )

    async def _mostrar_pregunta(
        self, interaction: discord.Interaction, sesion: SesionTrivia
    ) -> None:
        """Muestra la pregunta actual."""
        pregunta = sesion.preguntas[sesion.pregunta_actual]
        num_pregunta = sesion.pregunta_actual + 1
        total_preguntas = len(sesion.preguntas)

        embed = discord.Embed(
            title="🎮 TRIVIA / Quiz",
            description=pregunta.texto,
            color=discord.Color.teal(),
        )
        embed.add_field(name="📚 Categoría / Category", value=pregunta.categoria, inline=True)
        embed.add_field(name="⚙️ Dificultad / Difficulty", value=pregunta.dificultad, inline=True)
        embed.add_field(name="❓ Pregunta / Question", value=f"{num_pregunta}/{total_preguntas}", inline=True)
        embed.add_field(name="⏳ Tiempo restante / Time left", value=f"{TIMEOUT_PREGUNTA} segundos / seconds", inline=False)

        vista = VistaPregunta(pregunta, sesion.usuario_id)

        # Validar que el canal puede enviar mensajes
        if not interaction.channel or not isinstance(
            interaction.channel, (discord.TextChannel, discord.Thread)
        ):
            await interaction.followup.send(
                "❌ El canal no es válido para esta operación.",
                ephemeral=True,
            )
            return

        mensaje = await interaction.channel.send(embed=embed, view=vista)
        sesion.mensaje = mensaje

        # Crear tarea del temporizador
        if sesion.tarea_temporizador:
            sesion.tarea_temporizador.cancel()

        sesion.tarea_temporizador = asyncio.create_task(
            self._temporizador(sesion, vista, mensaje)
        )

        # Esperar respuesta
        try:
            await asyncio.wait_for(vista.wait(), timeout=TIMEOUT_PREGUNTA)
            sesion.tarea_temporizador.cancel()
        except asyncio.TimeoutError:
            sesion.tarea_temporizador.cancel()

        # Procesar respuesta
        await self._procesar_respuesta(sesion, vista, mensaje, interaction)

    async def _temporizador(
        self, sesion: SesionTrivia, vista: VistaPregunta, mensaje: discord.Message
    ) -> None:
        """Maneja el temporizador de la pregunta."""
        try:
            for segundo in range(TIMEOUT_PREGUNTA, 0, -1):
                if vista.respondido:
                    return

                await asyncio.sleep(1)

                # Actualizar tiempo en el embed cada 5 segundos
                if segundo % 5 == 0 or segundo <= 3:
                    embed = mensaje.embeds[0]
                    for field in embed.fields:
                        if field.name == "⏳ Tiempo restante / Time left":
                            embed.set_field_at(
                                embed.fields.index(field),
                                name="⏳ Tiempo restante / Time left",
                                value=f"{segundo} segundos / seconds",
                            )
                    try:
                        await mensaje.edit(embed=embed)
                    except discord.NotFound:
                        return

            # Tiempo agotado
            if not vista.respondido:
                vista.respondido = True
                embed = mensaje.embeds[0]
                embed.color = discord.Color.red()
                embed.title = "⏰ TIEMPO AGOTADO / TIME'S UP"

                pregunta = sesion.preguntas[sesion.pregunta_actual]
                respuesta_correcta = pregunta.respuestas[pregunta.correcta]
                embed.add_field(
                    name="La respuesta correcta era / Correct answer was:",
                    value=f"✅ {respuesta_correcta}",
                    inline=False,
                )

                # Desactivar botones
                for item in vista.children:
                    if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                        item.disabled = True

                await mensaje.edit(embed=embed, view=vista)

        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _procesar_respuesta(
        self,
        sesion: SesionTrivia,
        vista: VistaPregunta,
        mensaje: discord.Message,
        interaction: discord.Interaction,
    ) -> None:
        """Procesa la respuesta del usuario."""
        pregunta = sesion.preguntas[sesion.pregunta_actual]
        es_correcta = vista.respuesta_usuario == pregunta.correcta

        embed = mensaje.embeds[0]
        embed.clear_fields()

        if vista.respondido and vista.respuesta_usuario is not None:
            if es_correcta:
                embed.title = "✅ RESPUESTA CORRECTA / CORRECT ANSWER!"
                embed.color = discord.Color.green()
                sesion.correctas += 1
            else:
                embed.title = "❌ RESPUESTA INCORRECTA / WRONG ANSWER"
                embed.color = discord.Color.red()
                sesion.incorrectas += 1

                respuesta_correcta = pregunta.respuestas[pregunta.correcta]
                embed.add_field(
                    name="Respuesta correcta / Correct answer:",
                    value=f"✅ {respuesta_correcta}",
                    inline=False,
                )
        else:
            sesion.sin_responder += 1

        # Desactivar botones
        for item in vista.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        await mensaje.edit(embed=embed, view=vista)

        # Determinar si es la 煤ltima pregunta
        es_ultima = sesion.pregunta_actual >= len(sesion.preguntas) - 1

        # Crear vista de continuaci贸n
        vista_resultado = VistaResultado(sesion.usuario_id, es_ultima=es_ultima)

        await asyncio.sleep(1)

        await mensaje.edit(view=vista_resultado)

        try:
            await asyncio.wait_for(vista_resultado.wait(), timeout=300)
        except asyncio.TimeoutError:
            for item in vista_resultado.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            await mensaje.edit(view=vista_resultado)
            return

        if vista_resultado.reiniciar:
            # Finalizar sesi贸n
            del self.sesiones[sesion.usuario_id]
            for item in vista_resultado.children:
                if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                    item.disabled = True
            await mensaje.edit(view=vista_resultado)
            return

        if vista_resultado.continuar:
            if es_ultima:
                # Mostrar resultado final
                await self._mostrar_resultado_final(sesion, mensaje)
                del self.sesiones[sesion.usuario_id]
            else:
                # Siguiente pregunta
                sesion.pregunta_actual += 1
                await mensaje.delete()
                await self._mostrar_pregunta(interaction, sesion)

    async def _mostrar_resultado_final(
        self, sesion: SesionTrivia, mensaje: discord.Message
    ) -> None:
        """Muestra el resultado final."""
        embed = discord.Embed(
            title="🏁 TRIVIA FINALIZADA / Trivia Finished",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="📝 Preguntas respondidas / Questions answered",
            value=str(len(sesion.preguntas)),
            inline=True,
        )
        embed.add_field(name="✅ Correctas / Correct", value=str(sesion.correctas), inline=True)
        embed.add_field(name="❌ Incorrectas / Incorrect", value=str(sesion.incorrectas), inline=True)

        porcentaje = (sesion.correctas / len(sesion.preguntas) * 100) if sesion.preguntas else 0
        embed.add_field(
            name="📊 Puntuación / Score",
            value=f"{porcentaje:.1f}%",
            inline=False,
        )
        embed.add_field(
            name="💬 Nota / Note",
            value="Estos resultados son únicamente para esta sesión / These results are only for this session.",
            inline=False,
        )
        embed.set_footer(text="Gracias por jugar / Thanks for playing!")

        # Vista sin componentes en el resultado final
        await mensaje.edit(embed=embed, view=None)

    def _obtener_mensaje_error(self, error: str) -> str:
        """Mapea errores de API a mensajes amigables."""
        if "suficientes preguntas" in error.lower():
            return (
                "No se encontraron suficientes preguntas.\n\n"
                "Intenta:\n"
                "• Cambiar la categoría\n"
                "• Seleccionar otra dificultad\n"
                "• Cambiar el tipo de pregunta\n"
                "• Reducir la cantidad de preguntas"
            )
        elif "agotado" in error.lower():
            return "La sesión se agotó. Por favor, intenta de nuevo / The session expired. Please try again."
        elif "rate limit" in error.lower():
            return "Demasiadas solicitudes. Por favor, espera un momento e intenta de nuevo / Too many requests. Please wait a moment and try again."
        elif "conexión" in error.lower() or "timeout" in error.lower():
            return "No fue posible conectar con el servicio de trivia.\n\nPor favor, intenta nuevamente más tarde / It was not possible to connect to the trivia service.\n\nPlease try again later."
        else:
            return f"Error: {error}"


async def setup(bot: commands.Bot) -> None:
    """Carga el cog."""
    cog = Trivia(bot)
    await cog.cog_load()
    await bot.add_cog(cog)