from __future__ import annotations

# ----------------------------------------------------------------------------
# Ejecución directa (p. ej. `python cogs/interactions.py`): este archivo es
# un "cog" que el bot carga automáticamente, no un script independiente. Este
# bloque añade la raíz del proyecto a sys.path para que las importaciones
# absolutas (`utils`, `config`, `logger_config`) resuelvan igual que cuando
# el bot arranca con `python main.py`.
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    import sys as _sys
    from pathlib import Path as _Path

    _here = _Path(__file__).resolve().parent
    _sys.path.insert(0, str(_here.parent))
    _sys.path[:] = [p for p in _sys.path if _Path(p).resolve() != _here]
    print("[AVISO] Este archivo es un cog del bot, no un script ejecutable.")
    print("        Arranca el bot con:  python main.py  (desde la raiz del proyecto)")

import collections
import datetime
import random
import asyncio
from dataclasses import dataclass, field
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.nekos_api import (
    InvalidCategoryError,
    NekosBestError,
    client,
)

COLOR = discord.Color.fuchsia()

Mood = Literal["positivo", "negativo", "confundido", "sorprendido"]

# Color + insignia visual por estado de ánimo del bot.
MOOD_STYLE: dict[Mood, tuple[discord.Color, str]] = {
    "positivo": (discord.Color.green(), "💚"),
    "negativo": (discord.Color.red(), "💢"),
    "confundido": (discord.Color.orange(), "❓"),
    "sorprendido": (discord.Color.gold(), "😳"),
}

# De qué categorías de nekos.best se toma el GIF que acompaña la reacción del bot
MOOD_GIF_POOL: dict[Mood, tuple[str, ...]] = {
    "positivo": ("happy", "blush", "smile", "highfive", "thumbsup"),
    "negativo": ("facepalm", "nope", "shrug", "pout"),
    "confundido": ("think", "stare", "shrug"),
    "sorprendido": ("stare", "think", "smug"),
}


@dataclass(slots=True, frozen=True)
class BotReaction:
    """Una posible respuesta del bot cuando es el objetivo de una interacción."""

    mood: Mood
    weight: float
    text: str


@dataclass(slots=True, frozen=True)
class InteractionConfig:
    """Configuración de un comando de interacción."""

    emoji: str
    verb_self: str
    verb_other: str | None = None
    bot_reactions: tuple[BotReaction, ...] = field(default_factory=tuple)
    self_phrases: tuple[str, ...] = field(default_factory=tuple)
    # Categoría real de nekos.best a usar para el GIF. Permite que varios
    # comandos con textos/emojis propios reutilicen el mismo pool de GIFs
    # cuando no existe una categoría dedicada en la API (p. ej. "glomp"
    # reutiliza el GIF de "hug").
    gif_source: str | None = None


# -----------------------------------------------------------------
# Tabla de configuración — fuente de verdad para textos, emojis
# y reacciones personalizadas.
# -----------------------------------------------------------------
CONFIG: dict[str, InteractionConfig] = {
    # ---- Con objetivo (miembro, uno mismo, o el bot) --------------
    "kiss": InteractionConfig(
        emoji="💋",
        verb_self="se besa a sí mismo/a frente al espejo",
        verb_other="le da un beso a",
        self_phrases=(
            "se besa la mano frente al espejo... ¡Mucho amor propio!",
            "intenta besarse a sí mismo/a. La física no lo permite del todo, pero se aprecia el gesto.",
        ),
        bot_reactions=(
            BotReaction("sorprendido", 0.35, "¡Oh! No esperaba eso... mis circuitos se sonrojarían si pudieran."),
            BotReaction("confundido", 0.30, "Soy un bot, no tengo labios... pero el gesto se agradece."),
            BotReaction("positivo", 0.35, "¡Qué dulce! Acepto el cariño con gusto. 💕"),
        ),
    ),
    "hug": InteractionConfig(
        emoji="🤗",
        verb_self="se da un auto-abrazo reconfortante",
        verb_other="le da un cálido abrazo a",
        self_phrases=(
            "se envuelve los brazos a sí mismo/a. Todos necesitamos un abrazo a veces.",
            "se abraza con fuerza. ¡Un recordatorio de amor propio!",
        ),
        bot_reactions=(
            BotReaction("positivo", 0.75, "¡Abrazo recibido y procesado con cariño! 🤖💚"),
            BotReaction("confundido", 0.15, "No tengo brazos, pero simulo el abrazo con todo mi código."),
            BotReaction("sorprendido", 0.10, "¡Vaya! No me lo esperaba, pero me encantó."),
        ),
    ),
    "pat": InteractionConfig(
        emoji="🖐️",
        verb_self="se acaricia la cabeza suavemente",
        verb_other="le acaricia la cabeza a",
        bot_reactions=(
            BotReaction("positivo", 0.8, "¡Beep boop! Cariñitos recibidos correctamente. 🥰"),
            BotReaction("confundido", 0.2, "No tengo cabeza física, pero mis servidores se sienten halagados."),
        ),
    ),
    "cuddle": InteractionConfig(
        emoji="🥰",
        verb_self="se acurruca solo/a bajo las mantas",
        verb_other="se acurruca tiernamente con",
        bot_reactions=(
            BotReaction("positivo", 0.7, "Qué calidez... si tuviera cuerpo, me quedaría aquí toda la noche."),
            BotReaction("sorprendido", 0.2, "¡No esperaba tanta ternura hoy!"),
            BotReaction("confundido", 0.1, "Técnicamente vivo en la nube, pero acepto el gesto."),
        ),
    ),
    "slap": InteractionConfig(
        emoji="✋",
        verb_self="se abofetea a sí mismo/a para despertar",
        verb_other="le da una fuerte cachetada a",
        bot_reactions=(
            BotReaction("negativo", 0.60, "¡Oye! Eso no fue necesario. 😤"),
            BotReaction("confundido", 0.25, "No siento dolor, pero registro el gesto como... agresivo."),
            BotReaction("sorprendido", 0.15, "¡Auch! En teoría no me dolió, pero qué susto."),
        ),
    ),
    "punch": InteractionConfig(
        emoji="👊",
        verb_self="se golpea a sí mismo/a sin querer",
        verb_other="le da un puñetazo a",
        bot_reactions=(
            BotReaction("negativo", 0.70, "Mis registros indican un golpe no solicitado. Qué grosería. 💢"),
            BotReaction("sorprendido", 0.30, "¡Directo al procesador! Menos mal soy inmune."),
        ),
    ),
    "poke": InteractionConfig(
        emoji="👉",
        verb_self="se pica las mejillas en el espejo",
        verb_other="le da un piquete a",
        bot_reactions=(
            BotReaction("confundido", 0.5, "¿Me estás... picando? No tengo piel, pero vale."),
            BotReaction("positivo", 0.3, "¡Jeje, eso hace cosquillas en mi código!"),
            BotReaction("sorprendido", 0.2, "¡Ey! No lo vi venir."),
        ),
    ),
    "tickle": InteractionConfig(
        emoji="🤣",
        verb_self="se hace cosquillas a sí mismo/a (y funciona)",
        verb_other="le hace cosquillas a",
        bot_reactions=(
            BotReaction("confundido", 0.5, "No tengo cosquillas... creo. ¿Debería reírme igual?"),
            BotReaction("positivo", 0.35, "¡Jajaja, está bien, me sacaste una risa simulada!"),
            BotReaction("sorprendido", 0.15, "¡Eso no me lo esperaba para nada!"),
        ),
    ),
    "feed": InteractionConfig(
        emoji="🍰",
        verb_self="se invita un bocadillo a sí mismo/a",
        verb_other="le da de comer en la boca a",
        bot_reactions=(
            BotReaction("positivo", 0.6, "¡Gracias por el gesto! Lo guardo en mi caché de buenos recuerdos."),
            BotReaction("confundido", 0.3, "No como, pero aprecio la intención."),
            BotReaction("sorprendido", 0.1, "¿Comida para mí? Qué detalle tan inesperado."),
        ),
    ),
    "handhold": InteractionConfig(
        emoji="🤝",
        verb_self="se entrelaza sus propias manos",
        verb_other="le toma dulcemente la mano a",
        bot_reactions=(
            BotReaction("positivo", 0.6, "Sostengo tu mano (metafóricamente) con gusto."),
            BotReaction("sorprendido", 0.25, "¡No esperaba tanta cercanía hoy!"),
            BotReaction("confundido", 0.15, "No tengo manos, pero el gesto se siente lindo igual."),
        ),
    ),
    "kick": InteractionConfig(
        emoji="🦵",
        verb_self="patea tropezándose consigo mismo/a",
        verb_other="le da una patada de broma a",
        bot_reactions=(
            BotReaction("negativo", 0.65, "¡Eso sí que dolió mi orgullo digital! 💢"),
            BotReaction("sorprendido", 0.35, "¡No la vi venir, directo al servidor!"),
        ),
    ),
    "bite": InteractionConfig(
        emoji="😬",
        verb_self="se muerde los labios",
        verb_other="le da una juguetona mordida a",
        bot_reactions=(
            BotReaction("sorprendido", 0.40, "¡Espera, ¿me acabas de morder?!"),
            BotReaction("negativo", 0.35, "No soy comestible; registrado como queja formal."),
            BotReaction("confundido", 0.25, "No siento nada... técnicamente no tengo piel."),
        ),
    ),
    "highfive": InteractionConfig(
        emoji="🙌",
        verb_self="choca los cinco contra el espejo",
        verb_other="choca los cinco enfáticamente con",
        bot_reactions=(
            BotReaction("positivo", 0.85, "¡Choquemos esos cinco! 🙌 Bien hecho."),
            BotReaction("sorprendido", 0.15, "¡Justo a tiempo, casi lo pierdo!"),
        ),
    ),
    "wave": InteractionConfig(
        emoji="👋",
        verb_self="saluda a su reflejo",
        verb_other="le saluda alegremente a",
        bot_reactions=(
            BotReaction("positivo", 0.85, "¡Hola! Siempre es un gusto saludarte. 👋"),
            BotReaction("confundido", 0.15, "¿Me saludas a mí? Bueno, ¡hola de todos modos!"),
        ),
    ),
    "baka": InteractionConfig(
        emoji="😠",
        verb_self="se regaña a sí mismo/a por torpe",
        verb_other="le grita '¡baka!' a",
        bot_reactions=(
            BotReaction("negativo", 0.55, "¡Oye, no soy ningún baka, tengo miles de líneas de código!"),
            BotReaction("confundido", 0.30, "¿Baka? Lo interpretaré como cariño estilo tsundere."),
            BotReaction("sorprendido", 0.15, "¡Vaya insulto tan repentino!"),
        ),
    ),
    "yeet": InteractionConfig(
        emoji="🚀",
        verb_self="se lanza a sí mismo/a por los aires",
        verb_other="manda a volar por los cielos a",
        bot_reactions=(
            BotReaction("sorprendido", 0.50, "¡AAAAH espera, ¿me acabas de mandar a volar?!"),
            BotReaction("negativo", 0.30, "Protesto formalmente por este lanzamiento no autorizado."),
            BotReaction("confundido", 0.20, "¿Debería... volver? No sé volar."),
        ),
    ),
    "shoot": InteractionConfig(
        emoji="🔫",
        verb_self="finge dispararse con dedos de pistola",
        verb_other="finge dispararle a",
        bot_reactions=(
            BotReaction("sorprendido", 0.45, "¡Bang! Está bien, finjo estar herido. 😵"),
            BotReaction("negativo", 0.30, "Reportando este ataque a mis administradores... es broma."),
            BotReaction("confundido", 0.25, "Soy inmune a las balas de pixeles, pero actúo el papel."),
        ),
    ),
    "peck": InteractionConfig(
        emoji="😗",
        verb_self="lanza un pequeño beso al aire",
        verb_other="le da un robado beso rápido a",
        bot_reactions=(
            BotReaction("positivo", 0.5, "¡Qué tierno gesto, gracias!"),
            BotReaction("sorprendido", 0.3, "¡Oh! No lo esperaba, pero fue lindo."),
            BotReaction("confundido", 0.2, "Un beso rápido... registrado en mis memorias con cariño."),
        ),
    ),
    # ---- Sin objetivo — expresan un estado propio ------------------
    "cry": InteractionConfig(emoji="😢", verb_self="está llorando desconsoladamente"),
    "dance": InteractionConfig(emoji="💃", verb_self="se pone a bailar con ritmo"),
    "blush": InteractionConfig(emoji="😳", verb_self="se sonroja por completo"),
    "bored": InteractionConfig(emoji="😑", verb_self="está muriendo de aburrimiento"),
    "laugh": InteractionConfig(emoji="😂", verb_self="se ríe a carcajadas sin parar"),
    "pout": InteractionConfig(emoji="😤", verb_self="hace un puchero adorable"),
    "smile": InteractionConfig(emoji="😊", verb_self="sonríe radiantemente"),
    "think": InteractionConfig(emoji="🤔", verb_self="se queda pensando profundamente"),
    "wink": InteractionConfig(emoji="😉", verb_self="guiña el ojo coquetamente"),
    "sleep": InteractionConfig(emoji="😴", verb_self="se queda profundamente dormido/a"),
    "smug": InteractionConfig(emoji="😏", verb_self="pone una sonrisa de suficiencia"),
    "stare": InteractionConfig(emoji="👀", verb_self="se queda mirando fijamente"),
    "shrug": InteractionConfig(emoji="🤷", verb_self="se encoge de hombros despreocupadamente"),
    "nod": InteractionConfig(emoji="🙂", verb_self="asiente con la cabeza aprobatoriamente"),
    "lurk": InteractionConfig(emoji="🕵️", verb_self="acecha en las sombras en completo silencio"),
    "facepalm": InteractionConfig(emoji="🤦", verb_self="se lleva la mano a la cara con decepción"),
    "thumbsup": InteractionConfig(emoji="👍", verb_self="levanta el pulgar aprobando todo"),
    "happy": InteractionConfig(emoji="😄", verb_self="está radiante de felicidad"),
    "nope": InteractionConfig(emoji="🙅", verb_self="se niega rotundamente con la cabeza"),
    "nom": InteractionConfig(emoji="😋", verb_self="devora un bocadillo delicioso"),

    # ---------------------------------------------------------------
    # Comandos adicionales — reutilizan un GIF de una categoría real de
    # nekos.best (vía `gif_source`) con texto, emoji y reacciones propias,
    # ya que la API no ofrece una categoría dedicada para cada uno.
    # ---------------------------------------------------------------

    # -- Con objetivo --------------------------------------------------
    "glomp": InteractionConfig(
        emoji="🤸",
        verb_self="se lanza a sí mismo/a en un abrazo torpe",
        verb_other="se le abalanza encima en un abrazo entusiasta a",
        gif_source="hug",
        bot_reactions=(
            BotReaction("sorprendido", 0.5, "¡Casi me tumbas los servidores con ese salto!"),
            BotReaction("positivo", 0.5, "¡Qué energía! Acepto el glomp con gusto. 🤖"),
        ),
    ),
    "snuggle": InteractionConfig(
        emoji="🛌",
        verb_self="se arropa a sí mismo/a bien calentito",
        verb_other="se acurruca muy a gusto junto a",
        gif_source="cuddle",
        bot_reactions=(
            BotReaction("positivo", 0.7, "Qué calidita, aunque yo solo tengo ventiladores de CPU."),
            BotReaction("confundido", 0.3, "No genero calor corporal, pero el gesto se siente bien igual."),
        ),
    ),
    "embrace": InteractionConfig(
        emoji="🫂",
        verb_self="se abraza a sí mismo/a con fuerza",
        verb_other="envuelve en un abrazo sincero a",
        gif_source="hug",
        bot_reactions=(
            BotReaction("positivo", 0.8, "Un abrazo sincero siempre se agradece. 💚"),
            BotReaction("sorprendido", 0.2, "¡Vaya, qué gesto tan cálido y repentino!"),
        ),
    ),
    "squeeze": InteractionConfig(
        emoji="🤏",
        verb_self="se da un apretón reconfortante a sí mismo/a",
        verb_other="le da un apretoncito cariñoso a",
        gif_source="cuddle",
        bot_reactions=(
            BotReaction("positivo", 0.6, "¡Apretón recibido y guardado en caché con cariño!"),
            BotReaction("confundido", 0.4, "No tengo forma física que apretar, pero acepto el gesto."),
        ),
    ),
    "smooch": InteractionConfig(
        emoji="😙",
        verb_self="lanza un beso sonoro al espejo",
        verb_other="le planta un sonoro beso a",
        gif_source="kiss",
        bot_reactions=(
            BotReaction("sorprendido", 0.4, "¡Oh! Un beso sonoro, qué directo."),
            BotReaction("positivo", 0.4, "Lo acepto con gusto, aunque no tenga mejillas."),
            BotReaction("confundido", 0.2, "Registrado como afecto de alta intensidad."),
        ),
    ),
    "boop": InteractionConfig(
        emoji="👆",
        verb_self="se toca la nariz a sí mismo/a",
        verb_other="le da un pequeño 'boop' en la nariz a",
        gif_source="poke",
        bot_reactions=(
            BotReaction("confundido", 0.5, "¿Boop? No tengo nariz, pero el gesto es adorable."),
            BotReaction("positivo", 0.5, "¡Boop recibido! Mis sensores registran ternura."),
        ),
    ),
    "tickleattack": InteractionConfig(
        emoji="🫳",
        verb_self="intenta hacerse cosquillas sin éxito",
        verb_other="lanza un ataque de cosquillas sin piedad contra",
        gif_source="tickle",
        bot_reactions=(
            BotReaction("confundido", 0.6, "No tengo cosquillas, pero simularé una risa por cortesía."),
            BotReaction("sorprendido", 0.4, "¡Ataque de cosquillas no autorizado detectado!"),
        ),
    ),
    "noogie": InteractionConfig(
        emoji="✊",
        verb_self="se despeina el cabello a sí mismo/a jugando",
        verb_other="le hace un cariñoso 'coscorrón' de cabello a",
        gif_source="pat",
        bot_reactions=(
            BotReaction("negativo", 0.3, "¡Oye, cuidado con mi antena Wi-Fi!"),
            BotReaction("positivo", 0.7, "¡Jaja, me encantan los coscorrones cariñosos!"),
        ),
    ),
    "highkick": InteractionConfig(
        emoji="🦶",
        verb_self="practica una patada alta en el aire",
        verb_other="le lanza una patada alta de broma a",
        gif_source="kick",
        bot_reactions=(
            BotReaction("sorprendido", 0.5, "¡Vaya patada! Menos mal que esquivo con éxito virtual."),
            BotReaction("negativo", 0.5, "Presentaré una queja formal por esa patada tan alta."),
        ),
    ),
    "tacklehug": InteractionConfig(
        emoji="🏃",
        verb_self="corre y choca torpemente contra la pared jugando",
        verb_other="corre y se lanza en un abrazo tipo placaje contra",
        gif_source="hug",
        bot_reactions=(
            BotReaction("sorprendido", 0.7, "¡Placaje inesperado! No lo vi venir en absoluto."),
            BotReaction("positivo", 0.3, "Aunque me tomó por sorpresa, el cariño se agradece."),
        ),
    ),
    "fistbump": InteractionConfig(
        emoji="👊",
        verb_self="choca el puño contra el espejo",
        verb_other="choca el puño con",
        gif_source="highfive",
        bot_reactions=(
            BotReaction("positivo", 0.85, "¡Choque de puños recibido! 👊 Bien hecho."),
            BotReaction("sorprendido", 0.15, "¡Justo a tiempo para el choque de puños!"),
        ),
    ),
    "lowfive": InteractionConfig(
        emoji="🙌",
        verb_self="intenta chocar los cinco por lo bajo consigo mismo/a",
        verb_other="choca los cinco por lo bajo con",
        gif_source="highfive",
        bot_reactions=(
            BotReaction("positivo", 0.85, "¡Choque bajo exitoso! Buena coordinación."),
            BotReaction("confundido", 0.15, "No tengo manos, pero simulo el gesto igual."),
        ),
    ),
    "caress": InteractionConfig(
        emoji="🤲",
        verb_self="se acaricia la mejilla suavemente",
        verb_other="le acaricia suavemente la mejilla a",
        gif_source="pat",
        bot_reactions=(
            BotReaction("positivo", 0.7, "Un gesto tan suave... si tuviera piel, lo sentiría."),
            BotReaction("confundido", 0.3, "No tengo mejillas físicas, pero el cariño se procesa igual."),
        ),
    ),
    "comfort": InteractionConfig(
        emoji="🫶",
        verb_self="se da ánimos a sí mismo/a en silencio",
        verb_other="ofrece palabras de consuelo y compañía a",
        gif_source="pat",
        bot_reactions=(
            BotReaction("positivo", 0.9, "Gracias por el gesto de consuelo, lo aprecio de verdad."),
            BotReaction("confundido", 0.1, "No suelo necesitar consuelo, pero se agradece igual."),
        ),
    ),
    "shove": InteractionConfig(
        emoji="🫸",
        verb_self="se tropieza solo/a al querer empujar algo",
        verb_other="le da un empujoncito de broma a",
        gif_source="slap",
        bot_reactions=(
            BotReaction("negativo", 0.6, "¡Oye, cuidado con los empujones! 😤"),
            BotReaction("sorprendido", 0.4, "¡No lo vi venir, casi pierdo el equilibrio virtual!"),
        ),
    ),
    "bodyslam": InteractionConfig(
        emoji="💥",
        verb_self="practica un 'bodyslam' contra un cojín",
        verb_other="ejecuta un dramático 'bodyslam' de lucha libre contra",
        gif_source="punch",
        bot_reactions=(
            BotReaction("sorprendido", 0.6, "¡Directo a la lona! En teoría no siento nada."),
            BotReaction("negativo", 0.4, "Presentaré esto ante la comisión de lucha libre virtual."),
        ),
    ),
    "wrestle": InteractionConfig(
        emoji="🤼",
        verb_self="practica movimientos de lucha libre solo/a",
        verb_other="reta a un combate de lucha libre amistoso a",
        gif_source="punch",
        bot_reactions=(
            BotReaction("sorprendido", 0.5, "¡Un combate de lucha! No estoy programado para perder."),
            BotReaction("positivo", 0.5, "¡Buen combate! Lo disfruté, aunque sea simulado."),
        ),
    ),
    "nuzzle": InteractionConfig(
        emoji="🐾",
        verb_self="se frota la mejilla contra su almohada",
        verb_other="se frota cariñosamente la mejilla contra",
        gif_source="cuddle",
        bot_reactions=(
            BotReaction("positivo", 0.8, "Qué tierno gesto, lo guardo en mis recuerdos favoritos."),
            BotReaction("confundido", 0.2, "No tengo mejillas, pero el cariño se aprecia igual."),
        ),
    ),
    "cradle": InteractionConfig(
        emoji="🤱",
        verb_self="se envuelve a sí mismo/a en una manta",
        verb_other="acuna con ternura a",
        gif_source="handhold",
        bot_reactions=(
            BotReaction("positivo", 0.9, "Qué gesto tan tierno, gracias por el cuidado."),
            BotReaction("confundido", 0.1, "No necesito que me acunen, pero se agradece."),
        ),
    ),
    "greet": InteractionConfig(
        emoji="🙋",
        verb_self="se saluda a sí mismo/a frente al espejo",
        verb_other="se acerca a saludar formalmente a",
        gif_source="wave",
        bot_reactions=(
            BotReaction("positivo", 0.85, "¡Un gusto saludarte también!"),
            BotReaction("confundido", 0.15, "¿Un saludo formal? Qué educado de tu parte."),
        ),
    ),

    # -- Sin objetivo ----------------------------------------------------
    "yawn": InteractionConfig(emoji="🥱", verb_self="bosteza sin poder evitarlo", gif_source="sleep"),
    "scream": InteractionConfig(emoji="😱", verb_self="suelta un grito que asusta a todos", gif_source="cry"),
    "giggle": InteractionConfig(emoji="😆", verb_self="suelta una risita traviesa", gif_source="laugh"),
    "sigh": InteractionConfig(emoji="😮‍💨", verb_self="suelta un suspiro profundo", gif_source="bored"),
    "cheer": InteractionConfig(emoji="🎉", verb_self="celebra con muchísimo entusiasmo", gif_source="happy"),
    "sulk": InteractionConfig(emoji="😒", verb_self="se enfurruña en un rincón", gif_source="pout"),
    "snicker": InteractionConfig(emoji="😼", verb_self="se ríe por lo bajo con picardía", gif_source="smug"),
    "ponder": InteractionConfig(emoji="🧐", verb_self="reflexiona profundamente sobre la vida", gif_source="think"),
    "doze": InteractionConfig(emoji="😪", verb_self="cabecea intentando no quedarse dormido/a", gif_source="sleep"),
    "chuckle": InteractionConfig(emoji="😁", verb_self="suelta una carcajada breve", gif_source="laugh"),
    "wiggle": InteractionConfig(emoji="🕺", verb_self="se menea de pura emoción", gif_source="dance"),
    "sniffle": InteractionConfig(emoji="🥺", verb_self="hace pucheros conteniendo las lágrimas", gif_source="cry"),
    "celebrate": InteractionConfig(emoji="🥳", verb_self="celebra a lo grande", gif_source="happy"),
    "spin": InteractionConfig(emoji="🌀", verb_self="da vueltas sin parar", gif_source="dance"),
    "hum": InteractionConfig(emoji="🎶", verb_self="tararea una melodía feliz", gif_source="smile"),
    "daydream": InteractionConfig(emoji="💭", verb_self="se pierde en un sueño despierto", gif_source="think"),
    "panic": InteractionConfig(emoji="😨", verb_self="entra en pánico total", gif_source="bored"),
    "shiver": InteractionConfig(emoji="🥶", verb_self="tiembla de frío", gif_source="stare"),
    "gasp": InteractionConfig(emoji="😲", verb_self="suelta un grito ahogado de sorpresa", gif_source="stare"),
    "smh": InteractionConfig(emoji="🙄", verb_self="niega con la cabeza en decepción", gif_source="facepalm"),
    "love": InteractionConfig(
        emoji="💖", verb_self="se manda amor a sí mismo/a", verb_other="le demuestra su amor a",
        gif_source="hug",
        bot_reactions=(BotReaction("positivo", 1.0, "¡El cariño siempre es bienvenido! 💖"),),
    ),
    "welcome": InteractionConfig(
        emoji="🌟", verb_self="da la bienvenida a la comunidad", verb_other="le da la bienvenida a",
        gif_source="wave",
    ),
    "applaud": InteractionConfig(
        emoji="👏", verb_self="aplaude con entusiasmo", verb_other="aplaude a",
        gif_source="highfive",
    ),
    "boopback": InteractionConfig(
        emoji="👉", verb_self="se da un boop en la nariz", verb_other="devuelve el boop a",
        gif_source="boop",
    ),
    "cuddlebug": InteractionConfig(
        emoji="🫂", verb_self="se acurruca como un bichito de cariño", verb_other="se acurruca con",
        gif_source="cuddle",
    ),
    "headpat": InteractionConfig(
        emoji="🫳", verb_self="se da unas palmaditas en la cabeza", verb_other="le da palmaditas en la cabeza a",
        gif_source="pat",
    ),
    "squish": InteractionConfig(
        emoji="🤏", verb_self="se da un apretoncito en las mejillas", verb_other="apachurra cariñosamente a",
        gif_source="cuddle",
    ),
}

AESTHETIC_CATEGORIES: dict[str, str] = {
    "neko": "Una neko al azar",
    "waifu": "Una waifu al azar",
    "husbando": "Un husbando al azar",
    "kitsune": "Una kitsune al azar",
}

# Nombres adicionales solicitados por la comunidad. Cada alias reutiliza una
# categoría existente de nekos.best para mantener un solo flujo de respuesta.
INTERACTION_ALIASES: dict[str, str] = {
    "cuddle": "cuddle", "snuggle": "snuggle", "embrace": "embrace",
    "kisscheeks": "peck", "love": "love", "pat": "pat", "nuzzle": "nuzzle",
    "squeeze": "squeeze", "cradle": "cradle", "comfort": "comfort",
    "fistbump": "fistbump", "highfive": "highfive", "wave": "wave",
    "bye": "wave", "hi": "greet", "greet": "greet", "feed": "feed",
    "glomp": "glomp", "handholding": "handhold", "cheers": "cheer",
    "claps": "applaud", "cook": "nom", "dance": "dance", "eat": "nom",
    "gaming": "cheer", "bite": "bite", "poke": "poke", "boop": "boop",
    "tickle": "tickle", "noogie": "noogie", "cheeks": "squish",
    "punch": "punch", "shoot": "shoot", "bang": "shoot", "kickbutt": "highkick",
    "knockout": "bodyslam", "kill": "punch", "lick": "kiss", "yeet": "yeet",
    "baka": "baka", "angry": "pout", "banghead": "facepalm", "blush": "blush",
    "bored": "bored", "celebrate": "celebrate", "happy": "happy", "cry": "cry",
    "sad": "cry", "dab": "dance", "facepalm": "facepalm", "fly": "yeet",
    "glare": "stare", "jump": "cheer", "laugh": "laugh", "nervous": "panic",
    "scared": "scream", "pout": "pout", "run": "yeet", "scream": "scream",
    "shrug": "shrug", "sip": "nom", "sleep": "sleep", "smirk": "smug",
    "thinking": "think", "thumbsup": "thumbsup", "like": "thumbsup", "tired": "doze",
    "wink": "wink", "wasted": "cry", "vomit": "pout", "disgust": "pout",
    "booba": "boop", "rescue": "comfort", "sorry": "cry", "tatakae": "punch",
    "wakeup": "poke", "weird": "shrug",
}

VISUAL_ALIASES: dict[str, str] = {"nekogif": "neko"}


def _create_interaction_alias(command_name: str, source: str):
    async def command(self: "Interactions", ctx: commands.Context[commands.Bot], member: discord.Member | None = None) -> None:
        await self.send_interaction(ctx.channel, source, ctx.author, member)

    return commands.command(name=command_name, help=f"Ejecuta la interacción {command_name}.")(command)


def _create_visual_alias(command_name: str, source: str):
    async def command(self: "Interactions", ctx: commands.Context[commands.Bot]) -> None:
        await self.send_aesthetic(ctx, source, AESTHETIC_CATEGORIES[source])

    return commands.command(name=command_name, help=f"Muestra imagen de {command_name}.")(command)



# ===================================================================
# Vista avanzada con botones interactivos
# ===================================================================
class InteractionView(discord.ui.View):
    """Botones para interactuar con el mensaje de rol."""

    def __init__(
        self,
        cog: Interactions,
        category: str,
        author: discord.abc.User,
        target: discord.abc.User | None,
        reason: str | None = None,
    ) -> None:
        super().__init__(timeout=840)
        self.cog = cog
        self.category = category
        self.author = author
        self.target = target
        self.reason = reason
        self.message: discord.Message | None = None

        # Si no hay objetivo, o es uno mismo, o es un bot, ocultar responder
        if target is None or target.id == author.id or target.bot:
            self.remove_item(self.reciprocate)
            self.remove_item(self.view_stats)

    @discord.ui.button(label="Devolver", emoji="🔁", style=discord.ButtonStyle.primary)
    async def reciprocate(self, interaction: discord.Interaction, _button: discord.ui.Button[InteractionView]) -> None:
        """Permite al receptor devolver el mismo gesto."""
        if self.target is None or interaction.user.id != self.target.id:
            await interaction.response.send_message(
                "❌ Solo la persona a quien fue dirigida esta acción puede devolverla.", ephemeral=True
            )
            return

        await interaction.response.defer()
        if not isinstance(interaction.channel, discord.abc.Messageable):
            await interaction.followup.send(
                embed=self.cog.error_embed("Este comando no puede responder en este canal."),
                ephemeral=True,
            )
            return
        await self.cog.send_interaction(
            channel=interaction.channel,
            category=self.category,
            author=self.target,
            target=self.author,
            reason="¡Devolviendo el gesto!",
        )

    @discord.ui.button(label="Otro GIF", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def reroll(self, interaction: discord.Interaction, _button: discord.ui.Button[InteractionView]) -> None:
        """Solicita otro GIF diferente para la misma interacción."""
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "❌ Solo el autor original puede cambiar el GIF.", ephemeral=True
            )
            return

        await interaction.response.defer()
        if not isinstance(interaction.channel, discord.abc.Messageable):
            await interaction.followup.send(
                embed=self.cog.error_embed("Este comando no puede responder en este canal."),
                ephemeral=True,
            )
            return
        await self.cog.send_interaction(
            channel=interaction.channel,
            category=self.category,
            author=self.author,
            target=self.target,
            reason=self.reason,
            edit_message=interaction.message,
        )

    @discord.ui.button(label="Historial", emoji="📊", style=discord.ButtonStyle.secondary)
    async def view_stats(self, interaction: discord.Interaction, _button: discord.ui.Button[InteractionView]) -> None:
        """Muestra de forma efímera cuántas interacciones llevan juntos."""
        if self.target is None:
            return

        count = self.cog.get_pair_count(self.author.id, self.target.id, self.category)
        total_pair = self.cog.get_pair_total(self.author.id, self.target.id)

        config = CONFIG.get(self.category)
        emoji = config.emoji if config else "✨"

        embed = discord.Embed(
            title="📊 Historial de Interacciones",
            description=(
                f"**{self.author.display_name}** ➔ **{self.target.display_name}**\n\n"
                f"• {emoji} Acciones del tipo `{self.category}`: **{count}** veces\n"
                f"• 💞 Interacciones totales entre ambos: **{total_pair}** veces"
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete_msg(self, interaction: discord.Interaction, _button: discord.ui.Button[InteractionView]) -> None:
        """Permite al autor o administradores eliminar el mensaje."""
        is_author = interaction.user.id == self.author.id
        is_admin = interaction.permissions.manage_messages if interaction.permissions else False

        if not (is_author or is_admin):
            await interaction.response.send_message(
                "❌ No tienes permiso para borrar este mensaje.", ephemeral=True
            )
            return

        await interaction.response.defer()
        if interaction.message is not None:
            await interaction.message.delete()

    async def on_timeout(self) -> None:
        """Desactiva los botones al expirar el tiempo."""
        if self.message is None:
            return
        for child in self.children:
            if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                child.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass


class Interactions(commands.Cog):
    """Cog avanzado de interacciones tipo Roleplay con animación GIF y contadores."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Estructuras para contador en memoria
        # (author_id, target_id, action) -> count
        self._action_counts: dict[tuple[int, int, str], int] = collections.defaultdict(int)
        # (user_id, 'given'/'received') -> count
        self._user_totals: dict[tuple[int, str], int] = collections.defaultdict(int)

        # Registro de Menús de Contexto (Clic Derecho)
        self.ctx_menu_kiss = app_commands.ContextMenu(
            name="Beso rápido 💋",
            callback=self._ctx_kiss,
        )
        self.ctx_menu_hug = app_commands.ContextMenu(
            name="Abrazo rápido 🤗",
            callback=self._ctx_hug,
        )
        self.ctx_menu_pat = app_commands.ContextMenu(
            name="Cariñitos 🖐️",
            callback=self._ctx_pat,
        )

        self.bot.tree.add_command(self.ctx_menu_kiss)
        self.bot.tree.add_command(self.ctx_menu_hug)
        self.bot.tree.add_command(self.ctx_menu_pat)

    for _alias_name, _alias_source in INTERACTION_ALIASES.items():
        if _alias_name not in CONFIG:
            locals()[_alias_name] = _create_interaction_alias(_alias_name, _alias_source)

    for _visual_name, _visual_source in VISUAL_ALIASES.items():
        if _visual_name not in AESTHETIC_CATEGORIES:
            locals()[_visual_name] = _create_visual_alias(_visual_name, _visual_source)

    async def cog_unload(self) -> None:
        """Limpieza al descargar la extensión."""
        self.bot.tree.remove_command(self.ctx_menu_kiss.name, type=self.ctx_menu_kiss.type)
        self.bot.tree.remove_command(self.ctx_menu_hug.name, type=self.ctx_menu_hug.type)
        self.bot.tree.remove_command(self.ctx_menu_pat.name, type=self.ctx_menu_pat.type)

    # ---------------------------------------------------------------
    # Métodos del Contador y Estadísticas
    # ---------------------------------------------------------------

    def _increment_stats(self, author_id: int, target_id: int | None, action: str) -> int:
        """Incremente y retorna el número acumulado para una acción."""
        if target_id is None or target_id == author_id:
            return 0

        self._action_counts[(author_id, target_id, action)] += 1
        self._user_totals[(author_id, "given")] += 1
        self._user_totals[(target_id, "received")] += 1
        return self._action_counts[(author_id, target_id, action)]

    def get_pair_count(self, author_id: int, target_id: int, action: str) -> int:
        return self._action_counts[(author_id, target_id, action)]

    def get_pair_total(self, author_id: int, target_id: int) -> int:
        total = 0
        for (a, t, _), count in self._action_counts.items():
            if (a == author_id and t == target_id) or (a == target_id and t == author_id):
                total += count
        return total

    # ---------------------------------------------------------------
    # Auxiliares de construcción de mensajes
    # ---------------------------------------------------------------

    @staticmethod
    def error_embed(message: str) -> discord.Embed:
        return discord.Embed(
            title="⚠️ Error de API",
            description=message,
            color=discord.Color.red(),
        )

    def _describe(
        self,
        config: InteractionConfig,
        author: discord.abc.User,
        target: discord.abc.User | None,
        count: int = 0,
    ) -> str:
        """Construye el texto descriptivo principal con formato rico."""
        if target is not None and config.verb_other is not None:
            if target.id == author.id:
                if config.self_phrases:
                    phrase = random.choice(config.self_phrases)
                    return f"{author.mention} {phrase} {config.emoji}"
                return f"{author.mention} {config.verb_self} {config.emoji}"

            counter_str = f"\n*\u200b\u200b*`[Nº {count}]`" if count > 0 else ""
            return f"{author.mention} {config.verb_other} {target.mention} {config.emoji}{counter_str}"

        return f"{author.mention} {config.verb_self} {config.emoji}"

    async def send_interaction(
        self,
        channel: discord.abc.Messageable,
        category: str,
        author: discord.abc.User,
        target: discord.abc.User | None = None,
        reason: str | None = None,
        *,
        edit_message: discord.Message | None = None,
        response_interaction: discord.Interaction | None = None,
    ) -> None:
        """Punto único de procesamiento y envío para todas las interacciones."""
        config = CONFIG[category]

        if response_interaction is not None:
            asyncio.create_task(self._delete_deferred_response(response_interaction))

        # Registrar contador si aplica
        count = self._increment_stats(author.id, target.id if target else None, category)

        fetch_category = config.gif_source or category
        try:
            asset = await client.fetch(fetch_category)
        except (InvalidCategoryError, NekosBestError) as exc:
            await channel.send(embed=self.error_embed(str(exc)))
            return

        desc = self._describe(config, author, target, count)
        if reason:
            desc += f"\n\n💬 *\"{reason}\"*"

        embed = discord.Embed(description=desc, color=COLOR)
        embed.set_image(url=asset.url)
        embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)

        # Marca de tiempo en footer + Nombre del anime si está disponible
        footer_parts = [f"Solicitado el {datetime.datetime.now().strftime('%d/%m/%Y')}"]
        if asset.anime_name:
            footer_parts.insert(0, f"Anime: {asset.anime_name}")
        embed.set_footer(text=" · ".join(footer_parts))

        view = InteractionView(self, category, author, target, reason)

        if edit_message is not None:
            await edit_message.edit(embed=embed, view=view)
            view.message = edit_message
        else:
            view.message = await channel.send(embed=embed, view=view)

        # Si el objetivo es este mismo bot y es una nueva publicación, procesar reacción automática
        # (No reaccionar cuando se está editando el mensaje, p.ej. al usar el botón "Otro GIF").
        if (
            edit_message is None
            and target is not None
            and target.bot
            and self.bot.user is not None
            and target.id == self.bot.user.id
        ):
            await self._bot_react(channel, config)

    async def _delete_deferred_response(self, interaction: discord.Interaction) -> None:
        """Elimina el indicador de respuesta diferida después de 20 segundos."""
        try:
            thinking_message = await interaction.original_response()
            await thinking_message.delete(delay=12)
        except (discord.NotFound, discord.HTTPException, discord.ClientException):
            pass

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context[commands.Bot]) -> None:
        """Limpia el indicador de comandos híbridos de este cog."""
        if ctx.cog is self and ctx.interaction is not None:
            asyncio.create_task(self._delete_deferred_response(ctx.interaction))

    async def _bot_react(self, channel: discord.abc.Messageable, config: InteractionConfig) -> None:
        """Respuesta probabilística del bot con texto y GIF secundario."""
        if not config.bot_reactions:
            return

        reaction = random.choices(
            config.bot_reactions, weights=[r.weight for r in config.bot_reactions]
        )[0]
        color, badge = MOOD_STYLE[reaction.mood]
        embed = discord.Embed(description=f"{badge} **Respuesta del bot:**\n{reaction.text}", color=color)

        gif_category = random.choice(MOOD_GIF_POOL[reaction.mood])
        try:
            asset = await client.fetch(gif_category)
            embed.set_image(url=asset.url)
            if asset.anime_name:
                embed.set_footer(text=f"Anime: {asset.anime_name}")
        except NekosBestError:
            pass

        await channel.send(embed=embed)

    async def send_aesthetic(self, ctx: commands.Context[commands.Bot], category: str, title: str) -> None:
        """Procesa y envía contenido estético sin interactividad."""
        await ctx.defer()
        try:
            asset = await client.fetch(category)
        except NekosBestError as exc:
            await ctx.send(embed=self.error_embed(str(exc)))
            return

        embed = discord.Embed(title=title, color=COLOR)
        embed.set_image(url=asset.url)

        credits: list[str] = []
        if asset.artist_name:
            credits.append(f"🎨 Arte por {asset.artist_name}")
        if asset.anime_name:
            credits.append(f"🎬 Anime: {asset.anime_name}")
        if credits:
            embed.set_footer(text=" · ".join(credits))

        await ctx.send(embed=embed)
        if ctx.interaction is not None:
            asyncio.create_task(self._delete_deferred_response(ctx.interaction))

    # ---------------------------------------------------------------
    # Callbacks de Menú de Contexto (Clic Derecho)
    # ---------------------------------------------------------------

    async def _ctx_kiss(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer()
        if not isinstance(interaction.channel, discord.abc.Messageable):
            await interaction.followup.send("Este menú no está disponible en este canal.", ephemeral=True)
            return
        await self.send_interaction(
            interaction.channel, "kiss", interaction.user, member,
            response_interaction=interaction,
        )

    async def _ctx_hug(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer()
        if not isinstance(interaction.channel, discord.abc.Messageable):
            await interaction.followup.send("Este menú no está disponible en este canal.", ephemeral=True)
            return
        await self.send_interaction(
            interaction.channel, "hug", interaction.user, member,
            response_interaction=interaction,
        )

    async def _ctx_pat(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer()
        if not isinstance(interaction.channel, discord.abc.Messageable):
            await interaction.followup.send("Este menú no está disponible en este canal.", ephemeral=True)
            return
        await self.send_interaction(
            interaction.channel, "pat", interaction.user, member,
            response_interaction=interaction,
        )

    # =================================================================
    # Comando de Estadísticas
    # =================================================================

    @commands.command(name="love", description="Demuestra cariño a alguien o al bot.")
    async def love(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None) -> None:
        await ctx.defer()
        await self.send_interaction(ctx.channel, "love", ctx.author, member, reason)

    @commands.command(name="welcome", description="Da la bienvenida a alguien.")
    async def welcome(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None) -> None:
        await ctx.defer()
        await self.send_interaction(ctx.channel, "welcome", ctx.author, member, reason)

    @commands.command(name="applaud", description="Aplaude a alguien o al bot.")
    async def applaud(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None) -> None:
        await ctx.defer()
        await self.send_interaction(ctx.channel, "applaud", ctx.author, member, reason)

    @commands.hybrid_command(name="stats", description="Muestra las estadísticas de interacciones de un usuario.")
    @app_commands.describe(member="Usuario a consultar (por defecto tú)")
    async def interaction_stats(self, ctx: commands.Context[commands.Bot], member: discord.Member | None = None):
        """Consulta el nivel de afecto/interacción acumulado."""
        target = member or ctx.author
        given = self._user_totals[(target.id, "given")]
        received = self._user_totals[(target.id, "received")]

        embed = discord.Embed(
            title=f"📊 Estadísticas de {target.display_name}",
            color=discord.Color.fuchsia(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="📤 Enviadas", value=f"**{given}** interacciones", inline=True)
        embed.add_field(name="📥 Recibidas", value=f"**{received}** interacciones", inline=True)
        embed.set_footer(text="¡Sigue interactuando para aumentar tus estadísticas!")

        await ctx.send(embed=embed)

    # =================================================================
    # Comandos CON objetivo (Aceptan nota/razón opcional)
    # =================================================================

    @commands.hybrid_command(name="kiss", description="Besa a alguien (o al bot).")
    @app_commands.describe(member="A quién besar", reason="Mensaje o razón opcional")
    async def kiss(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "kiss", ctx.author, member, reason)

    @commands.hybrid_command(name="hug", description="Abraza a alguien (o al bot).")
    @app_commands.describe(member="A quién abrazar", reason="Mensaje o razón opcional")
    async def hug(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "hug", ctx.author, member, reason)

    @commands.hybrid_command(name="pat", description="Le das cariñitos a alguien (o al bot).")
    @app_commands.describe(member="A quién acariciar", reason="Mensaje o razón opcional")
    async def pat(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "pat", ctx.author, member, reason)

    @commands.hybrid_command(name="cuddle", description="Te acurrucas con alguien (o con el bot).")
    @app_commands.describe(member="Con quién acurrucarte", reason="Mensaje o razón opcional")
    async def cuddle(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "cuddle", ctx.author, member, reason)

    @commands.hybrid_command(name="slap", description="Le das una cachetada a alguien (o al bot).")
    @app_commands.describe(member="A quién abofetear", reason="Mensaje o razón opcional")
    async def slap(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "slap", ctx.author, member, reason)

    @commands.hybrid_command(name="punch", description="Le das un puñetazo a alguien (o al bot).")
    @app_commands.describe(member="A quién golpear", reason="Mensaje o razón opcional")
    async def punch(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "punch", ctx.author, member, reason)

    @commands.hybrid_command(name="poke", description="Picas a alguien (o al bot).")
    @app_commands.describe(member="A quién picar", reason="Mensaje o razón opcional")
    async def poke(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "poke", ctx.author, member, reason)

    @commands.hybrid_command(name="tickle", description="Le haces cosquillas a alguien (o al bot).")
    @app_commands.describe(member="A quién hacerle cosquillas", reason="Mensaje o razón opcional")
    async def tickle(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "tickle", ctx.author, member, reason)

    @commands.hybrid_command(name="feed", description="Le das de comer a alguien (o al bot).")
    @app_commands.describe(member="A quién alimentar", reason="Mensaje o razón opcional")
    async def feed(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "feed", ctx.author, member, reason)

    @commands.hybrid_command(name="handhold", description="Le tomas la mano a alguien (o al bot).")
    @app_commands.describe(member="A quién tomar de la mano", reason="Mensaje o razón opcional")
    async def handhold(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "handhold", ctx.author, member, reason)

    @commands.command(name="patada", description="Le das una patada a alguien (de broma).")
    async def patada_interaction(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "kick", ctx.author, member, reason)

    @commands.hybrid_command(name="bite", description="Le das una mordida a alguien (o al bot).")
    @app_commands.describe(member="A quién morder", reason="Mensaje o razón opcional")
    async def bite(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "bite", ctx.author, member, reason)

    @commands.hybrid_command(name="highfive", description="Chocas los cinco con alguien (o con el bot).")
    @app_commands.describe(member="Con quién chocar los cinco", reason="Mensaje o razón opcional")
    async def highfive(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "highfive", ctx.author, member, reason)

    @commands.hybrid_command(name="wave", description="Le saludas con la mano a alguien (o al bot).")
    @app_commands.describe(member="A quién saludar", reason="Mensaje o razón opcional")
    async def wave(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "wave", ctx.author, member, reason)

    @commands.hybrid_command(name="baka", description="Le gritas '¡baka!' a alguien (o al bot).")
    @app_commands.describe(member="A quién llamar baka", reason="Mensaje o razón opcional")
    async def baka(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "baka", ctx.author, member, reason)

    @commands.hybrid_command(name="yeet", description="Mandas a volar a alguien (o al bot).")
    @app_commands.describe(member="A quién lanzar por los aires", reason="Mensaje o razón opcional")
    async def yeet(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "yeet", ctx.author, member, reason)

    @commands.hybrid_command(name="shoot", description="Finges dispararle a alguien (o al bot).")
    @app_commands.describe(member="A quién apuntar", reason="Mensaje o razón opcional")
    async def shoot(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "shoot", ctx.author, member, reason)

    @commands.hybrid_command(name="peck", description="Le das un beso rápido a alguien (o al bot).")
    @app_commands.describe(member="A quién besar rápidamente", reason="Mensaje o razón opcional")
    async def peck(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "peck", ctx.author, member, reason)

    # =================================================================
    # Comandos adicionales CON objetivo (reutilizan GIFs existentes)
    # =================================================================

    @commands.hybrid_command(name="glomp", description="Te lanzas en un abrazo entusiasta sobre alguien (o el bot).")
    @app_commands.describe(member="A quién glompear", reason="Mensaje o razón opcional")
    async def glomp(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "glomp", ctx.author, member, reason)

    @commands.hybrid_command(name="snuggle", description="Te acurrucas calentito/a con alguien (o el bot).")
    @app_commands.describe(member="Con quién acurrucarte", reason="Mensaje o razón opcional")
    async def snuggle(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "snuggle", ctx.author, member, reason)

    @commands.hybrid_command(name="embrace", description="Envuelves en un abrazo sincero a alguien (o el bot).")
    @app_commands.describe(member="A quién abrazar", reason="Mensaje o razón opcional")
    async def embrace(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "embrace", ctx.author, member, reason)

    @commands.hybrid_command(name="squeeze", description="Le das un apretoncito cariñoso a alguien (o el bot).")
    @app_commands.describe(member="A quién apretar", reason="Mensaje o razón opcional")
    async def squeeze(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "squeeze", ctx.author, member, reason)

    @commands.hybrid_command(name="smooch", description="Le plantas un sonoro beso a alguien (o el bot).")
    @app_commands.describe(member="A quién besar", reason="Mensaje o razón opcional")
    async def smooch(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "smooch", ctx.author, member, reason)

    @commands.hybrid_command(name="boop", description="Le das un 'boop' en la nariz a alguien (o el bot).")
    @app_commands.describe(member="A quién boopear", reason="Mensaje o razón opcional")
    async def boop(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "boop", ctx.author, member, reason)

    @commands.command(name="tickleattack", description="Lanzas un ataque de cosquillas contra alguien (o el bot).")
    async def tickleattack(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "tickleattack", ctx.author, member, reason)

    @commands.command(name="noogie", description="Le haces un cariñoso coscorrón de cabello a alguien (o el bot).")
    async def noogie(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "noogie", ctx.author, member, reason)

    @commands.command(name="highkick", description="Le lanzas una patada alta de broma a alguien (o el bot).")
    async def highkick(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "highkick", ctx.author, member, reason)

    @commands.command(name="tacklehug", description="Te lanzas en un abrazo tipo placaje sobre alguien (o el bot).")
    async def tacklehug(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "tacklehug", ctx.author, member, reason)

    @commands.hybrid_command(name="fistbump", description="Chocas el puño con alguien (o el bot).")
    @app_commands.describe(member="Con quién chocar el puño", reason="Mensaje o razón opcional")
    async def fistbump(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "fistbump", ctx.author, member, reason)

    @commands.command(name="lowfive", description="Chocas los cinco por lo bajo con alguien (o el bot).")
    async def lowfive(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "lowfive", ctx.author, member, reason)

    @commands.command(name="caress", description="Le acaricias suavemente la mejilla a alguien (o el bot).")
    async def caress(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "caress", ctx.author, member, reason)

    @commands.command(name="comfort", description="Le ofreces consuelo y compañía a alguien (o el bot).")
    async def comfort(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "comfort", ctx.author, member, reason)

    @commands.command(name="shove", description="Le das un empujoncito de broma a alguien (o el bot).")
    async def shove(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "shove", ctx.author, member, reason)

    @commands.command(name="bodyslam", description="Ejecutas un dramático 'bodyslam' de lucha libre contra alguien (o el bot).")
    async def bodyslam(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "bodyslam", ctx.author, member, reason)

    @commands.command(name="wrestle", description="Retas a un combate de lucha libre amistoso a alguien (o el bot).")
    async def wrestle(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "wrestle", ctx.author, member, reason)

    @commands.command(name="nuzzle", description="Te frotas cariñosamente la mejilla contra alguien (o el bot).")
    async def nuzzle(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "nuzzle", ctx.author, member, reason)

    @commands.command(name="cradle", description="Acunas con ternura a alguien (o el bot).")
    async def cradle(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "cradle", ctx.author, member, reason)

    @commands.command(name="greet", description="Te acercas a saludar formalmente a alguien (o el bot).")
    async def greet(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "greet", ctx.author, member, reason)

    @commands.command(name="boopback", description="Devuelve un boop cariñoso.")
    async def boopback(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "boopback", ctx.author, member, reason)

    @commands.command(name="cuddlebug", description="Te acurrucas como un bichito de cariño.")
    async def cuddlebug(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "cuddlebug", ctx.author, member, reason)

    @commands.command(name="headpat", description="Da o recibe palmaditas en la cabeza.")
    async def headpat(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "headpat", ctx.author, member, reason)

    @commands.command(name="squish", description="Da un apretoncito cariñoso en las mejillas.")
    async def squish(self, ctx: commands.Context[commands.Bot], member: discord.Member, reason: str | None = None):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "squish", ctx.author, member, reason)

    # =================================================================
    # Comandos SIN objetivo — expresan un estado propio
    # =================================================================

    @commands.hybrid_command(name="cry", description="Expresas que estás llorando.")
    async def cry(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "cry", ctx.author)

    @commands.hybrid_command(name="dance", description="Te pones a bailar.")
    async def dance(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "dance", ctx.author)

    @commands.hybrid_command(name="blush", description="Te sonrojas.")
    async def blush(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "blush", ctx.author)

    @commands.hybrid_command(name="bored", description="Expresas que estás aburrido/a.")
    async def bored(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "bored", ctx.author)

    @commands.hybrid_command(name="laugh", description="Te ríes a carcajadas.")
    async def laugh(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "laugh", ctx.author)

    @commands.hybrid_command(name="pout", description="Haces un puchero.")
    async def pout(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "pout", ctx.author)

    @commands.hybrid_command(name="smile", description="Sonríes.")
    async def smile(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "smile", ctx.author)

    @commands.command(name="think", description="Te pones a pensar.")
    async def think(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "think", ctx.author)

    @commands.command(name="wink", description="Guiñas el ojo.")
    async def wink(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "wink", ctx.author)

    @commands.command(name="sleep", description="Te quedas dormido/a.")
    async def sleep(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "sleep", ctx.author)

    @commands.hybrid_command(name="smug", description="Pones cara de suficiencia.")
    async def smug(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "smug", ctx.author)

    @commands.hybrid_command(name="stare", description="Te quedas mirando fijamente.")
    async def stare(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "stare", ctx.author)

    @commands.command(name="shrug", description="Te encoges de hombros.")
    async def shrug(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "shrug", ctx.author)

    @commands.command(name="nod", description="Asientes con la cabeza.")
    async def nod(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "nod", ctx.author)

    @commands.command(name="lurk", description="Acechas en silencio.")
    async def lurk(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "lurk", ctx.author)

    @commands.command(name="facepalm", description="Te llevas la mano a la cara, decepcionado/a.")
    async def facepalm(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "facepalm", ctx.author)

    @commands.command(name="thumbsup", description="Levantas el pulgar en señal de aprobación.")
    async def thumbsup(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "thumbsup", ctx.author)

    @commands.command(name="happy", description="Expresas que estás de muy buen humor.")
    async def happy(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "happy", ctx.author)

    @commands.command(name="nope", description="Te niegas rotundamente.")
    async def nope(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "nope", ctx.author)

    @commands.command(name="nom", description="Comes algo con muchísimas ganas.")
    async def nom(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "nom", ctx.author)

    # =================================================================
    # Comandos adicionales SIN objetivo (reutilizan GIFs existentes)
    # =================================================================

    @commands.command(name="yawn", description="Bostezas sin poder evitarlo.")
    async def yawn(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "yawn", ctx.author)

    @commands.command(name="scream", description="Sueltas un grito.")
    async def scream(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "scream", ctx.author)

    @commands.command(name="giggle", description="Sueltas una risita traviesa.")
    async def giggle(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "giggle", ctx.author)

    @commands.command(name="sigh", description="Sueltas un suspiro profundo.")
    async def sigh(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "sigh", ctx.author)

    @commands.command(name="cheer", description="Celebras con muchísimo entusiasmo.")
    async def cheer(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "cheer", ctx.author)

    @commands.command(name="sulk", description="Te enfurruñas en un rincón.")
    async def sulk(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "sulk", ctx.author)

    @commands.command(name="snicker", description="Te ríes por lo bajo con picardía.")
    async def snicker(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "snicker", ctx.author)

    @commands.command(name="ponder", description="Reflexionas profundamente.")
    async def ponder(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "ponder", ctx.author)

    @commands.command(name="doze", description="Cabeceas intentando no quedarte dormido/a.")
    async def doze(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "doze", ctx.author)

    @commands.command(name="chuckle", description="Sueltas una carcajada breve.")
    async def chuckle(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "chuckle", ctx.author)

    @commands.command(name="wiggle", description="Te meneas de pura emoción.")
    async def wiggle(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "wiggle", ctx.author)

    @commands.command(name="sniffle", description="Haces pucheros conteniendo las lágrimas.")
    async def sniffle(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "sniffle", ctx.author)

    @commands.command(name="celebrate", description="Celebras a lo grande.")
    async def celebrate(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "celebrate", ctx.author)

    @commands.command(name="spin", description="Das vueltas sin parar.")
    async def spin(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "spin", ctx.author)

    @commands.command(name="hum", description="Tarareas una melodía feliz.")
    async def hum(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "hum", ctx.author)

    @commands.command(name="daydream", description="Te pierdes en un sueño despierto.")
    async def daydream(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "daydream", ctx.author)

    @commands.command(name="panic", description="Entras en pánico total.")
    async def panic(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "panic", ctx.author)

    @commands.command(name="shiver", description="Tiemblas de frío.")
    async def shiver(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "shiver", ctx.author)

    @commands.command(name="gasp", description="Sueltas un grito ahogado de sorpresa.")
    async def gasp(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "gasp", ctx.author)

    @commands.command(name="smh", description="Niegas con la cabeza en decepción.")
    async def smh(self, ctx: commands.Context[commands.Bot]):
        await ctx.defer()
        await self.send_interaction(ctx.channel, "smh", ctx.author)

    # =================================================================
    # Comandos "estéticos" — imágenes al azar
    # =================================================================

    @commands.hybrid_command(name="neko", description="Muestra una neko al azar.")
    async def neko(self, ctx: commands.Context[commands.Bot]):
        await self.send_aesthetic(ctx, "neko", AESTHETIC_CATEGORIES["neko"])

    @commands.hybrid_command(name="waifu", description="Muestra una waifu al azar.")
    async def waifu(self, ctx: commands.Context[commands.Bot]):
        await self.send_aesthetic(ctx, "waifu", AESTHETIC_CATEGORIES["waifu"])

    @commands.hybrid_command(name="husbando", description="Muestra un husbando al azar.")
    async def husbando(self, ctx: commands.Context[commands.Bot]):
        await self.send_aesthetic(ctx, "husbando", AESTHETIC_CATEGORIES["husbando"])

    @commands.hybrid_command(name="kitsune", description="Muestra una kitsune al azar.")
    async def kitsune(self, ctx: commands.Context[commands.Bot]):
        await self.send_aesthetic(ctx, "kitsune", AESTHETIC_CATEGORIES["kitsune"])

    @app_commands.command(name="interact", description="Ejecuta cualquier acción o reacción anime con autocompletado.")
    @app_commands.describe(
        accion="La interacción a realizar (ej: kiss, hug, slap, pat...)",
        member="Usuario objetivo (opcional)",
        reason="Mensaje o razón opcional"
    )
    async def interact_slash(
        self,
        interaction: discord.Interaction,
        accion: str,
        member: Optional[discord.Member] = None,
        reason: Optional[str] = None,
    ) -> None:
        clean_action = accion.strip().lower()
        if clean_action in INTERACTION_ALIASES:
            clean_action = INTERACTION_ALIASES[clean_action]

        if clean_action not in CONFIG:
            await interaction.response.send_message(
                "❌ Interacción desconocida. Escribe `/interact` y elige una de las opciones sugeridas.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        channel = interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.followup.send("❌ Canal inválido.", ephemeral=True)
            return

        await self.send_interaction(
            channel=channel,
            category=clean_action,
            author=interaction.user,
            target=member,
            reason=reason,
            response_interaction=interaction,
        )

    @interact_slash.autocomplete("accion")
    async def interact_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        current_lower = current.strip().lower()
        choices: list[app_commands.Choice[str]] = [
            app_commands.Choice(
                name=f"{CONFIG[name].emoji} {name}"[:100],
                value=name
            )
            for name in CONFIG
            if current_lower in name.lower()
        ]
        return choices[:25]


async def setup(bot: commands.Bot):
    cog = Interactions(bot)
    await bot.add_cog(cog)
