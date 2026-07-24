"""Suite del módulo core/horario_habil.py — todos los valores esperados están
calculados a mano en nombres/docstrings.

Calendario 2026 usado (verificado): lun 20-jul … sáb 25-jul … lun 27-jul;
DST EUA/frontera: inicia dom 8-mar-2026 y termina dom 1-nov-2026. Festivos
del seed: lun 16-nov-2026 (Revolución), entre otros.
"""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.cli.seed import DIAS_FESTIVOS
from app.core.horario_habil import (
    Banda,
    banda_de,
    dia_habil_efectivo,
    dias_habiles_transcurridos,
    es_dia_habil,
    horas_habiles_entre,
    inicio_de_dia_t,
    jornada_de,
)

FESTIVOS = frozenset(fecha for fecha, _ in DIAS_FESTIVOS)
SIN_FESTIVOS: frozenset[date] = frozenset()

CHIH = "America/Chihuahua"  # UTC-6 fijo (sin DST desde 2022)
JRZ = "America/Ciudad_Juarez"  # DST de EUA: -7 invierno / -6 verano
TIJ = "America/Tijuana"  # DST de EUA: -8 invierno / -7 verano
HMO = "America/Hermosillo"  # UTC-7 fijo (sin DST)


def utc(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


def local(tz: str, y: int, m: int, d: int, h: int, mi: int = 0) -> datetime:
    """Instante UTC construido desde hora local de la zona dada."""
    return datetime(y, m, d, h, mi, tzinfo=ZoneInfo(tz)).astimezone(UTC)


# ---------------------------------------------------------------- es_dia_habil


def test_es_dia_habil_semana_y_sabado():
    assert es_dia_habil(date(2026, 7, 20), FESTIVOS)  # lunes
    assert es_dia_habil(date(2026, 7, 24), FESTIVOS)  # viernes
    assert es_dia_habil(date(2026, 7, 25), FESTIVOS)  # sábado SÍ es hábil
    assert not es_dia_habil(date(2026, 7, 26), FESTIVOS)  # domingo no
    assert not es_dia_habil(date(2026, 11, 16), FESTIVOS)  # lunes festivo no


def test_jornada_de_lv_sabado_domingo_festivo():
    lunes = jornada_de(date(2026, 7, 20), FESTIVOS)
    assert lunes == (
        datetime.combine(date(2026, 7, 20), time(8, 0)),
        datetime.combine(date(2026, 7, 20), time(18, 0)),
    )
    sabado = jornada_de(date(2026, 7, 25), FESTIVOS)
    assert sabado is not None and sabado[1].time() == time(13, 0)
    assert jornada_de(date(2026, 7, 26), FESTIVOS) is None  # domingo
    assert jornada_de(date(2026, 11, 16), FESTIVOS) is None  # festivo


# ----------------------------------------------------------------------- HORAS


def test_horas_lunes_9_a_13_son_4():
    assert horas_habiles_entre(
        local(CHIH, 2026, 7, 20, 9), local(CHIH, 2026, 7, 20, 13), CHIH, FESTIVOS
    ) == pytest.approx(4.0)


def test_horas_lun_1730_a_mar_0830_es_1():
    """0.5 del lunes (17:30–18:00) + 0.5 del martes (08:00–08:30)."""
    assert horas_habiles_entre(
        local(CHIH, 2026, 7, 20, 17, 30), local(CHIH, 2026, 7, 21, 8, 30), CHIH, FESTIVOS
    ) == pytest.approx(1.0)


def test_horas_vie_17_a_lun_9_son_7():
    """1 del viernes (17–18) + 5 del sábado (8–13) + 0 domingo + 1 del lunes."""
    assert horas_habiles_entre(
        local(CHIH, 2026, 7, 24, 17), local(CHIH, 2026, 7, 27, 9), CHIH, FESTIVOS
    ) == pytest.approx(7.0)


def test_horas_sabado_10_a_14_son_3():
    """La jornada sabatina termina 13:00 → 10:00–13:00 = 3.0."""
    assert horas_habiles_entre(
        local(CHIH, 2026, 7, 25, 10), local(CHIH, 2026, 7, 25, 14), CHIH, FESTIVOS
    ) == pytest.approx(3.0)


def test_horas_envio_domingo_a_lunes_10_son_2():
    assert horas_habiles_entre(
        local(CHIH, 2026, 7, 26, 12), local(CHIH, 2026, 7, 27, 10), CHIH, FESTIVOS
    ) == pytest.approx(2.0)


def test_horas_festivo_entre_medio_suma_0():
    """vie 13-nov 17:00 → lun 16-nov (festivo: Revolución) 23:00 = 1 + 5 + 0 = 6."""
    assert horas_habiles_entre(
        local(CHIH, 2026, 11, 13, 17), local(CHIH, 2026, 11, 16, 23), CHIH, FESTIVOS
    ) == pytest.approx(6.0)
    # …y siguiendo hasta el martes 09:00 solo agrega 1 h del martes.
    assert horas_habiles_entre(
        local(CHIH, 2026, 11, 13, 17), local(CHIH, 2026, 11, 17, 9), CHIH, FESTIVOS
    ) == pytest.approx(7.0)


def test_horas_fin_menor_o_igual_a_inicio_es_0():
    t1 = local(CHIH, 2026, 7, 20, 12)
    assert horas_habiles_entre(t1, t1, CHIH, FESTIVOS) == 0.0
    assert horas_habiles_entre(t1, local(CHIH, 2026, 7, 20, 9), CHIH, FESTIVOS) == 0.0


def test_horas_datetime_naive_lanza_valueerror():
    naive = datetime(2026, 7, 20, 12)
    aware = local(CHIH, 2026, 7, 20, 13)
    with pytest.raises(ValueError):
        horas_habiles_entre(naive, aware, CHIH, FESTIVOS)
    with pytest.raises(ValueError):
        horas_habiles_entre(aware, naive, CHIH, FESTIVOS)


def test_horas_fraccion_15_minutos_es_025():
    assert horas_habiles_entre(
        local(CHIH, 2026, 7, 20, 8), local(CHIH, 2026, 7, 20, 8, 15), CHIH, FESTIVOS
    ) == pytest.approx(0.25)


def test_horas_antes_de_jornada_recorta_a_las_8():
    """Frontera documentada: lun 06:00→09:00 solo cuenta 08:00–09:00 = 1.0."""
    assert horas_habiles_entre(
        local(CHIH, 2026, 7, 20, 6), local(CHIH, 2026, 7, 20, 9), CHIH, FESTIVOS
    ) == pytest.approx(1.0)


# -------------------------------------------------------------- ZONAS HORARIAS


@pytest.mark.parametrize("tz", [JRZ, TIJ])
def test_horas_cruzando_inicio_dst_por_reloj_local(tz):
    """vie 6-mar-2026 17:00 → lun 9-mar 09:00 local: el DST inicia el domingo
    8-mar (no hábil) → 1 + 5 + 0 + 1 = 7.0 por reloj local, aunque el lapso
    UTC sea 63 h (y no 64) por el salto de primavera."""
    inicio = local(tz, 2026, 3, 6, 17)
    fin = local(tz, 2026, 3, 9, 9)
    assert (fin - inicio).total_seconds() / 3600 == pytest.approx(63.0)
    assert horas_habiles_entre(inicio, fin, tz, FESTIVOS) == pytest.approx(7.0)


@pytest.mark.parametrize("tz", [JRZ, TIJ])
def test_horas_cruzando_fin_dst_por_reloj_local(tz):
    """vie 30-oct-2026 17:00 → lun 2-nov 09:00 local: el DST termina el domingo
    1-nov (no hábil) → 7.0 por reloj local, con lapso UTC de 65 h (y no 64)."""
    inicio = local(tz, 2026, 10, 30, 17)
    fin = local(tz, 2026, 11, 2, 9)
    assert (fin - inicio).total_seconds() / 3600 == pytest.approx(65.0)
    assert horas_habiles_entre(inicio, fin, tz, FESTIVOS) == pytest.approx(7.0)


def test_horas_hermosillo_sin_dst_semana_completa_50():
    """Control sin DST: lun 20-jul 08:00 → vie 24-jul 18:00 = 5 × 10 = 50.0."""
    assert horas_habiles_entre(
        local(HMO, 2026, 7, 20, 8), local(HMO, 2026, 7, 24, 18), HMO, FESTIVOS
    ) == pytest.approx(50.0)


def test_mismo_instante_utc_da_t_distinto_por_zona():
    """Envío 2026-07-21T00:30Z: en Chihuahua ya es lun 20-jul 18:30 (después
    del fin de jornada → T0 = mar 21); en Tijuana aún es lun 17:30 (dentro →
    T0 = lun 20). Al evaluar el mié 22 (16:00Z): T=1 (ESPERADA) vs T=2
    (NORMAL)."""
    envio = utc(2026, 7, 21, 0, 30)
    assert dia_habil_efectivo(envio, CHIH, FESTIVOS) == date(2026, 7, 21)
    assert dia_habil_efectivo(envio, TIJ, FESTIVOS) == date(2026, 7, 20)

    hasta = utc(2026, 7, 22, 16)
    t_chih = dias_habiles_transcurridos(envio, hasta, CHIH, FESTIVOS)
    t_tij = dias_habiles_transcurridos(envio, hasta, TIJ, FESTIVOS)
    assert (t_chih, t_tij) == (1, 2)
    assert (banda_de(t_chih), banda_de(t_tij)) == (Banda.ESPERADA, Banda.NORMAL)


# ------------------------------------------------------------------ T Y BANDAS

ENVIO_LUN_10 = local(CHIH, 2026, 7, 20, 10)  # lunes hábil, 10:00 locales


@pytest.mark.parametrize(
    ("hasta", "t_esperado", "banda_esperada"),
    [
        (local(CHIH, 2026, 7, 20, 16), 0, Banda.ESPERADA),  # lun 16:00
        (local(CHIH, 2026, 7, 21, 9), 1, Banda.ESPERADA),  # mar 09:00
        (local(CHIH, 2026, 7, 22, 9), 2, Banda.NORMAL),  # mié 09:00
        (local(CHIH, 2026, 7, 23, 9), 3, Banda.LENTA),  # jue 09:00
    ],
)
def test_t_y_banda_desde_envio_lunes_10(hasta, t_esperado, banda_esperada):
    t = dias_habiles_transcurridos(ENVIO_LUN_10, hasta, CHIH, FESTIVOS)
    assert t == t_esperado
    assert banda_de(t) == banda_esperada


def test_envio_viernes_17_sabado_cuenta_como_dia():
    """T0=vie 24-jul; sáb→T=1, lun→T=2, mar→T=3."""
    envio = local(CHIH, 2026, 7, 24, 17)
    assert dia_habil_efectivo(envio, CHIH, FESTIVOS) == date(2026, 7, 24)
    casos = [
        (local(CHIH, 2026, 7, 25, 10), 1),  # sábado
        (local(CHIH, 2026, 7, 27, 10), 2),  # lunes
        (local(CHIH, 2026, 7, 28, 10), 3),  # martes
    ]
    for hasta, t in casos:
        assert dias_habiles_transcurridos(envio, hasta, CHIH, FESTIVOS) == t


def test_envio_sabado_fuera_de_jornada_t0_lunes():
    """sáb 25-jul 14:00 (la jornada sabatina terminó 13:00) → T0 = lun 27."""
    envio = local(CHIH, 2026, 7, 25, 14)
    assert dia_habil_efectivo(envio, CHIH, FESTIVOS) == date(2026, 7, 27)


def test_envio_sabado_dentro_de_jornada_t0_sabado():
    envio = local(CHIH, 2026, 7, 25, 11)
    assert dia_habil_efectivo(envio, CHIH, FESTIVOS) == date(2026, 7, 25)


def test_envio_lunes_19_t0_martes():
    envio = local(CHIH, 2026, 7, 20, 19)
    assert dia_habil_efectivo(envio, CHIH, FESTIVOS) == date(2026, 7, 21)


def test_envio_en_festivo_t0_siguiente_habil():
    """lun 16-nov-2026 (Revolución) 10:00 → T0 = mar 17-nov."""
    envio = local(CHIH, 2026, 11, 16, 10)
    assert dia_habil_efectivo(envio, CHIH, FESTIVOS) == date(2026, 11, 17)


def test_envio_antes_de_las_8_t0_mismo_dia():
    """Frontera documentada: envío lun 06:00 (antes de jornada pero antes del
    FIN de jornada) → T0 = ese mismo lunes."""
    envio = local(CHIH, 2026, 7, 20, 6)
    assert dia_habil_efectivo(envio, CHIH, FESTIVOS) == date(2026, 7, 20)


def test_banda_de_tabla():
    assert banda_de(0) == Banda.ESPERADA
    assert banda_de(1) == Banda.ESPERADA
    assert banda_de(2) == Banda.NORMAL
    assert banda_de(3) == Banda.LENTA
    assert banda_de(10) == Banda.LENTA


# -------------------------------------------------------------- inicio_de_dia_t


def test_inicio_de_dia_t_envio_viernes():
    """Envío vie 24-jul 17:00 (Chihuahua, UTC-6): t=2 → lun 27-jul 08:00
    local = 14:00Z; t=3 → mar 28-jul 08:00 local = 14:00Z."""
    envio = local(CHIH, 2026, 7, 24, 17)
    assert inicio_de_dia_t(envio, 2, CHIH, FESTIVOS) == utc(2026, 7, 27, 14)
    assert inicio_de_dia_t(envio, 3, CHIH, FESTIVOS) == utc(2026, 7, 28, 14)


def test_inicio_de_dia_t_cruza_cambio_de_offset_en_juarez():
    """Envío vie 6-mar-2026 (Juárez en UTC-7); su día T=2 es el lun 9-mar, ya
    en horario de verano (UTC-6): 08:00 local = 14:00Z (el sábado previo, aún
    en UTC-7, da 15:00Z)."""
    envio = local(JRZ, 2026, 3, 6, 17)  # = 2026-03-07T00:00Z (offset -7)
    assert envio == utc(2026, 3, 7, 0)
    assert inicio_de_dia_t(envio, 1, JRZ, FESTIVOS) == utc(2026, 3, 7, 15)  # sáb (aún -7)
    assert inicio_de_dia_t(envio, 2, JRZ, FESTIVOS) == utc(2026, 3, 9, 14)  # lun (ya -6)


def test_inicio_de_dia_t_salta_festivos():
    """Envío vie 13-nov 10:00: T=1 sáb 14, T=2 salta el lun 16 (festivo) →
    mar 17-nov 08:00 local."""
    envio = local(CHIH, 2026, 11, 13, 10)
    assert inicio_de_dia_t(envio, 2, CHIH, FESTIVOS) == local(CHIH, 2026, 11, 17, 8)


def test_inicio_de_dia_t_invalido():
    with pytest.raises(ValueError):
        inicio_de_dia_t(ENVIO_LUN_10, -1, CHIH, FESTIVOS)
    with pytest.raises(ValueError):
        inicio_de_dia_t(datetime(2026, 7, 20, 10), 2, CHIH, FESTIVOS)  # naive
