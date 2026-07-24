"""Aritmética de horas y días hábiles multi-zona.

ÚNICO lugar del sistema donde vive esta lógica (CLAUDE.md #1). Funciones
puras: sin BD, sin FastAPI; los festivos llegan como frozenset[date] y la
zona de la sucursal como nombre IANA (zoneinfo, stdlib).

Reglas (especificación §4.7):
- Jornada hábil: L–V 08:00–18:00, sábado 08:00–13:00, hora LOCAL de la
  sucursal. Domingos y festivos no son hábiles.
- Todo instante de entrada/salida es datetime aware en UTC; la conversión a
  hora local ocurre solo aquí adentro.
- T0 (día hábil efectivo del envío): el día local del envío si es hábil y el
  envío ocurre ANTES del fin de su jornada (un envío antes de las 08:00 de un
  día hábil también cuenta como ese día); si cae fuera, el siguiente hábil.
- T: cada día hábil posterior a T0 (el sábado cuenta) suma 1, evaluado con el
  día local del instante final.
- Bandas: T∈{0,1} ESPERADA · T==2 NORMAL · T>=3 LENTA.

Nota DST: la intersección con jornadas se hace por reloj de pared local. Los
cambios de horario en las zonas con DST (Juárez, Tijuana) ocurren en domingo
de madrugada — fuera de jornada — así que no distorsionan los totales.
"""

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

_HORA_INICIO = time(8, 0)
_FIN_LUNES_VIERNES = time(18, 0)
_FIN_SABADO = time(13, 0)
_SABADO = 5
_DOMINGO = 6


class Banda(StrEnum):
    ESPERADA = "ESPERADA"
    NORMAL = "NORMAL"
    LENTA = "LENTA"


def es_dia_habil(fecha_local: date, festivos: frozenset[date]) -> bool:
    return fecha_local.weekday() != _DOMINGO and fecha_local not in festivos


def jornada_de(fecha_local: date, festivos: frozenset[date]) -> tuple[datetime, datetime] | None:
    """(inicio, fin) de la jornada de ese día en hora LOCAL naive; None si no
    es día hábil."""
    if not es_dia_habil(fecha_local, festivos):
        return None
    fin = _FIN_SABADO if fecha_local.weekday() == _SABADO else _FIN_LUNES_VIERNES
    return (
        datetime.combine(fecha_local, _HORA_INICIO),
        datetime.combine(fecha_local, fin),
    )


def _a_local_naive(instante_utc: datetime, tz: str) -> datetime:
    """Reloj de pared local (naive) del instante. ValueError si es naive."""
    if instante_utc.tzinfo is None:
        raise ValueError("se requiere un datetime aware (UTC), no naive")
    return instante_utc.astimezone(ZoneInfo(tz)).replace(tzinfo=None)


def _siguiente_habil(fecha_local: date, festivos: frozenset[date]) -> date:
    d = fecha_local + timedelta(days=1)
    while not es_dia_habil(d, festivos):
        d += timedelta(days=1)
    return d


def horas_habiles_entre(
    inicio_utc: datetime, fin_utc: datetime, tz: str, festivos: frozenset[date]
) -> float:
    """Horas hábiles (float, con fracciones) entre dos instantes UTC.

    Suma la intersección del intervalo con las jornadas hábiles, medida en
    reloj local de la sucursal. 0.0 si fin <= inicio.
    """
    inicio_local = _a_local_naive(inicio_utc, tz)
    fin_local = _a_local_naive(fin_utc, tz)
    if fin_utc <= inicio_utc:
        return 0.0
    total = 0.0
    d = inicio_local.date()
    while d <= fin_local.date():
        jornada = jornada_de(d, festivos)
        if jornada is not None:
            lo = max(jornada[0], inicio_local)
            hi = min(jornada[1], fin_local)
            if hi > lo:
                total += (hi - lo).total_seconds() / 3600.0
        d += timedelta(days=1)
    return total


def dia_habil_efectivo(instante_utc: datetime, tz: str, festivos: frozenset[date]) -> date:
    """T0: día local del instante si es hábil y ocurre antes del fin de su
    jornada; si no, el siguiente día hábil."""
    local = _a_local_naive(instante_utc, tz)
    jornada = jornada_de(local.date(), festivos)
    if jornada is not None and local < jornada[1]:
        return local.date()
    return _siguiente_habil(local.date(), festivos)


def dias_habiles_transcurridos(
    enviado_utc: datetime, hasta_utc: datetime, tz: str, festivos: frozenset[date]
) -> int:
    """T: días hábiles posteriores a T0 hasta el día local de `hasta_utc`
    inclusive (el sábado cuenta; domingos y festivos no). 0 si el día final
    no pasa de T0."""
    t0 = dia_habil_efectivo(enviado_utc, tz, festivos)
    dia_final = _a_local_naive(hasta_utc, tz).date()
    t = 0
    d = t0
    while d < dia_final:
        d += timedelta(days=1)
        if es_dia_habil(d, festivos):
            t += 1
    return t


def banda_de(t: int) -> Banda:
    if t <= 1:
        return Banda.ESPERADA
    if t == 2:
        return Banda.NORMAL
    return Banda.LENTA


def inicio_de_dia_t(enviado_utc: datetime, t: int, tz: str, festivos: frozenset[date]) -> datetime:
    """Instante UTC en que inicia (08:00 locales) el día T=t de un envío.

    F7 lo usará para programar la entrada a NORMAL (t=2) y LENTA (t=3).
    """
    if t < 0:
        raise ValueError("t debe ser >= 0")
    d = dia_habil_efectivo(enviado_utc, tz, festivos)
    for _ in range(t):
        d = _siguiente_habil(d, festivos)
    inicio_local = datetime.combine(d, _HORA_INICIO, tzinfo=ZoneInfo(tz))
    return inicio_local.astimezone(UTC)
