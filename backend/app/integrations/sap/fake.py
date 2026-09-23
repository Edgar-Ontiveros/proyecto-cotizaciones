"""FakeFuenteOC — fuente en memoria para tests y desarrollo sin VPN (F16a).

Viene precargada con la OC REAL de prueba 31000103 tal como la devolvió HANA
el 2026-09-22 (§0), para que dev y tests hablen del mismo caso. `caida=True`
simula HANA fuera de línea (SapNoDisponible en todo, ping False).

F16a.1: trae tres BORRADORES de OC (serie "CU.", como la 37000054 real) que
NO existen en OPOR: 37000060 aprobado sin añadir, 37000061 pendiente de
autorización y 37000062 rechazado. Ninguno se puede vincular.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.integrations.sap.base import (
    BorradorOC,
    CadenaOC,
    EncabezadoOC,
    EntradaOC,
    FacturaOC,
    FuenteOC,
    LineaEntrada,
    LineaOC,
    SapNoDisponible,
    normalizar_sucursal_sap,
)

# --------------------------------------------------- OC real 31000103 (§0)

OC_31000103 = EncabezadoOC(
    doc_entry=27475,
    doc_num=31000103,
    serie="CH.",
    sucursal_sap="CH",
    proveedor_codigo="20000116",
    proveedor_nombre="ORGANIZACIÓN EN VÁLVULAS. S.A. DE C.V.",
    doc_status="C",
    cancelada=False,
    fecha_creacion=date(2026, 8, 7),
    fecha_contabilizacion=date(2026, 8, 7),
    fecha_entrega=date(2026, 8, 17),
    moneda="USD",
    tipo_cambio=Decimal("17.2317"),
    total=Decimal("26.10"),
    total_mxn=Decimal("449.74"),
    comentarios="PCH-11115-26 · JORGE HINOJOS",
    encargado_compras="JAHNA MICHELLE MONARREZ RASCON",
)
LINEAS_31000103 = [
    LineaOC(
        0,
        "CODSOINOX3044010045",
        'CODO SOLD. INOX. 304 C. 40 DE 1" X 45 G (0.150 KG/PZ)',
        Decimal("3"),
        Decimal("0"),
        "CHMTZ",
        "MATRIZ",
        "C",
        date(2026, 8, 17),
        Decimal("3.5"),
        Decimal("180.93"),
        "USD",
    ),
    LineaOC(
        1,
        "CODSOINOX3041003490",
        'CODO SOLD. INOX. 304 C. 10 DE 3/4" X 90 G (0.140 KG/PZ)',
        Decimal("4"),
        Decimal("0"),
        "CHMTZ",
        "MATRIZ",
        "C",
        date(2026, 8, 17),
        Decimal("3"),
        Decimal("206.78"),
        "USD",
    ),
]
CADENA_31000103 = CadenaOC(
    entradas=[
        EntradaOC(
            doc_entry=25148,
            doc_num=41000196,
            fecha=date(2026, 8, 12),
            cancelada=False,
            lineas=[
                LineaEntrada(0, "CODSOINOX3044010045", Decimal("3"), "MTYCDIS", "MONTERREY CEDIS"),
                LineaEntrada(1, "CODSOINOX3041003490", Decimal("4"), "MTYCDIS", "MONTERREY CEDIS"),
            ],
        )
    ],
    facturas=[
        FacturaOC(
            34310, 41000250, date(2026, 8, 12), False, Decimal("26.10"), "USD", "entrada", 25148
        )
    ],
)


# ------------------------------------------- borradores demo (F16a.1)

BORRADOR_APROBADO_SIN_ANADIR = 37000060
BORRADOR_PENDIENTE = 37000061
BORRADOR_RECHAZADO = 37000062


def _borrador(doc_num: int, abierto: bool, autorizacion: str | None) -> BorradorOC:
    return BorradorOC(
        doc_entry=50000 + (doc_num % 1000),
        doc_num=doc_num,
        serie="CU.",
        sucursal_sap="CU",
        proveedor_nombre="I.N.T. INOXIDABLES, S.A. DE C.V.",
        abierto=abierto,
        autorizacion=autorizacion,
        fecha_creacion=date(2026, 9, 22),
    )


BORRADORES_DEMO = [
    _borrador(BORRADOR_APROBADO_SIN_ANADIR, abierto=True, autorizacion="Y"),
    _borrador(BORRADOR_PENDIENTE, abierto=True, autorizacion="W"),
    _borrador(BORRADOR_RECHAZADO, abierto=True, autorizacion="N"),
]


class FakeFuenteOC(FuenteOC):
    def __init__(self, precargar_real: bool = True) -> None:
        self._ocs: dict[int, tuple[EncabezadoOC, list[LineaOC], CadenaOC]] = {}
        self._borradores: dict[int, BorradorOC] = {}
        self.caida = False
        self.consultas = 0
        if precargar_real:
            self.registrar(OC_31000103, LINEAS_31000103, CADENA_31000103)
            for borrador in BORRADORES_DEMO:
                self.registrar_borrador(borrador)

    # ---------------------------------------------------------- utilidades

    def registrar(
        self, encabezado: EncabezadoOC, lineas: list[LineaOC], cadena: CadenaOC | None = None
    ) -> EncabezadoOC:
        if encabezado.sucursal_sap is None and encabezado.serie is not None:
            encabezado = replace(encabezado, sucursal_sap=normalizar_sucursal_sap(encabezado.serie))
        self._ocs[encabezado.doc_num] = (encabezado, list(lineas), cadena or CadenaOC())
        return encabezado

    def oc_simple(
        self,
        doc_num: int,
        *,
        serie: str = "CH.",
        doc_status: str = "O",
        cancelada: bool = False,
        fecha_entrega: date | None = date(2026, 12, 31),
        cantidad: Decimal = Decimal("10"),
        cantidad_abierta: Decimal | None = None,
        proveedor: str = "PROVEEDOR DEMO S.A. DE C.V.",
        encargado: str | None = "JAHNA MICHELLE MONARREZ RASCON",
        moneda: str = "MXN",
        total: Decimal = Decimal("1000.00"),
        cadena: CadenaOC | None = None,
    ) -> EncabezadoOC:
        """OC de una línea para armar escenarios en tests."""
        enc = EncabezadoOC(
            doc_entry=doc_num * 10,
            doc_num=doc_num,
            serie=serie,
            sucursal_sap=normalizar_sucursal_sap(serie),
            proveedor_codigo="P0001",
            proveedor_nombre=proveedor,
            doc_status=doc_status,
            cancelada=cancelada,
            fecha_creacion=date(2026, 9, 1),
            fecha_contabilizacion=date(2026, 9, 1),
            fecha_entrega=fecha_entrega,
            moneda=moneda,
            tipo_cambio=Decimal("17.5") if moneda == "USD" else None,
            total=total,
            total_mxn=total * Decimal("17.5") if moneda == "USD" else total,
            comentarios=None,
            encargado_compras=encargado,
        )
        abierta = cantidad if cantidad_abierta is None else cantidad_abierta
        linea = LineaOC(
            num_linea=0,
            articulo="ART-1",
            descripcion="ARTÍCULO DEMO",
            cantidad=cantidad,
            cantidad_abierta=abierta,
            almacen_codigo="CHMTZ",
            almacen_nombre="MATRIZ",
            estatus_linea="C" if abierta <= 0 else "O",
            fecha_entrega=fecha_entrega,
            precio=total / cantidad,
            importe=total,
            moneda=moneda,
        )
        return self.registrar(enc, [linea], cadena)

    def registrar_borrador(self, borrador: BorradorOC) -> BorradorOC:
        self._borradores[borrador.doc_num] = borrador
        return borrador

    def borrador_simple(
        self, doc_num: int, *, abierto: bool = True, autorizacion: str | None = "Y"
    ) -> BorradorOC:
        """Borrador de OC para escenarios en tests (nunca entra a `_ocs`)."""
        return self.registrar_borrador(_borrador(doc_num, abierto, autorizacion))

    def actualizar(self, doc_num: int, **cambios: object) -> None:
        """Simula que SAP cambió el encabezado (p. ej. cancelada=True)."""
        enc, lineas, cadena = self._ocs[doc_num]
        self._ocs[doc_num] = (replace(enc, **cambios), lineas, cadena)  # type: ignore[arg-type]

    def poner_cadena(
        self, doc_num: int, cadena: CadenaOC, lineas: list[LineaOC] | None = None
    ) -> None:
        enc, viejas, _ = self._ocs[doc_num]
        self._ocs[doc_num] = (enc, lineas if lineas is not None else viejas, cadena)

    def _check(self) -> None:
        self.consultas += 1
        if self.caida:
            raise SapNoDisponible("fake: HANA fuera de línea")

    # ----------------------------------------------------------- contrato

    def ping(self) -> bool:
        return not self.caida

    def buscar_oc(self, doc_num: int) -> EncabezadoOC | None:
        self._check()
        entrada = self._ocs.get(int(doc_num))
        return entrada[0] if entrada else None

    def buscar_borrador(self, doc_num: int) -> BorradorOC | None:
        self._check()
        return self._borradores.get(int(doc_num))

    def lineas_oc(self, doc_entry: int) -> list[LineaOC]:
        self._check()
        for enc, lineas, _ in self._ocs.values():
            if enc.doc_entry == doc_entry:
                return list(lineas)
        return []

    def cadena_oc(self, doc_entry: int) -> CadenaOC:
        self._check()
        for enc, _, cadena in self._ocs.values():
            if enc.doc_entry == doc_entry:
                return cadena
        return CadenaOC()
