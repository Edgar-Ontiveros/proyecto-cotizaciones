"""HanaFuenteOC — lectura real de SAP B1 sobre HANA con hdbcli (F16a §1).

Solo SELECT parametrizados ("?"); jamás DDL/DML. Conexión ÚNICA reutilizada
bajo candado (pool mínimo: la app hace pocas consultas y HANA cobra por
sesión), timeouts cortos, reconexión ante falla y `distribution=OFF` para que
el cliente JAMÁS intente reconectarse al nombre interno "hana-db" que HANA
anuncia (riesgo conocido: desde la red de la app ese nombre no resuelve).

Columnas reales verificadas el 2026-09-22 contra la OC 31000103 (DocEntry
27475): OPOR.DocEntry/DocNum/Series/CardCode/CardName/DocStatus/CANCELED/
CreateDate/DocDate/DocDueDate/DocCur/DocRate/DocTotal/DocTotalFC/Comments/
SlpCode · NNM1.Series/SeriesName · OSLP.SlpCode/SlpName · POR1.LineNum/
ItemCode/Dscription/Quantity/OpenQty/WhsCode/LineStatus/ShipDate/Price/
LineTotal/Currency · OWHS.WhsCode/WhsName · OPDN.DocEntry/DocNum/DocDate/
CANCELED · PDN1.DocEntry/BaseType/BaseEntry/BaseLine/ItemCode/Quantity/
WhsCode · OPCH.DocEntry/DocNum/DocDate/CANCELED/DocTotal/DocTotalFC/DocCur ·
PCH1.DocEntry/BaseType/BaseEntry · OADM.MainCurncy.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.logging import logger
from app.integrations.sap.base import (
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

# Tipos de objeto SAP B1: 22 = orden de compra, 20 = entrada de mercancías.
_OBJ_ORDEN_COMPRA = 22
_OBJ_ENTRADA = 20

_SQL_ENCABEZADO = """
SELECT T0."DocEntry", T0."DocNum", T1."SeriesName", T0."CardCode", T0."CardName",
       T0."DocStatus", T0."CANCELED", T0."CreateDate", T0."DocDate", T0."DocDueDate",
       T0."DocCur", T0."DocRate", T0."DocTotal", T0."DocTotalFC", T0."Comments", T2."SlpName"
FROM OPOR T0
LEFT JOIN NNM1 T1 ON T1."Series" = T0."Series"
LEFT JOIN OSLP T2 ON T2."SlpCode" = T0."SlpCode"
WHERE T0."DocNum" = ?
"""

_SQL_LINEAS = """
SELECT T0."LineNum", T0."ItemCode", T0."Dscription", T0."Quantity", T0."OpenQty",
       T0."WhsCode", T1."WhsName", T0."LineStatus", T0."ShipDate", T0."Price",
       T0."LineTotal", T0."Currency"
FROM POR1 T0
LEFT JOIN OWHS T1 ON T1."WhsCode" = T0."WhsCode"
WHERE T0."DocEntry" = ?
ORDER BY T0."LineNum"
"""

_SQL_ENTRADAS = """
SELECT T1."DocEntry", T1."DocNum", T1."DocDate", T1."CANCELED",
       T0."BaseLine", T0."ItemCode", T0."Quantity", T0."WhsCode", T2."WhsName"
FROM PDN1 T0
JOIN OPDN T1 ON T1."DocEntry" = T0."DocEntry"
LEFT JOIN OWHS T2 ON T2."WhsCode" = T0."WhsCode"
WHERE T0."BaseType" = ? AND T0."BaseEntry" = ?
ORDER BY T1."DocEntry", T0."LineNum"
"""

_SQL_FACTURAS_BASE = """
SELECT DISTINCT T1."DocEntry", T1."DocNum", T1."DocDate", T1."CANCELED",
       T1."DocTotal", T1."DocTotalFC", T1."DocCur", T0."BaseType", T0."BaseEntry"
FROM PCH1 T0
JOIN OPCH T1 ON T1."DocEntry" = T0."DocEntry"
WHERE {condicion}
ORDER BY T1."DocEntry"
"""

_SQL_MONEDA_LOCAL = 'SELECT "MainCurncy" FROM OADM'


def _fecha(valor: Any) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return None


def _dec(valor: Any) -> Decimal | None:
    if valor is None:
        return None
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


class HanaFuenteOC(FuenteOC):
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        schema: str,
        timeout_ms: int = 5000,
    ) -> None:
        self._kw: dict[str, Any] = {
            "address": host,
            "port": port,
            "user": user,
            "password": password,
            "currentSchema": schema,
            # Nunca redistribuir/reconectar al host que HANA anuncia ("hana-db").
            "distribution": "OFF",
            "connectTimeout": timeout_ms,
            "communicationTimeout": max(timeout_ms, 2000) * 3,
            "reconnect": "FALSE",
        }
        self._lock = threading.Lock()
        self._conn: Any = None
        self._moneda_local: str | None = None

    # ------------------------------------------------------------ conexión

    def _conectar(self) -> Any:
        from hdbcli import dbapi

        return dbapi.connect(**self._kw)

    def _query(
        self, sql: str, params: Sequence[Any] = (), intentos: int = 2
    ) -> list[tuple[Any, ...]]:
        """Ejecuta UN SELECT; ante cualquier falla del driver cierra la conexión,
        reintenta una vez con conexión nueva y, si vuelve a fallar, levanta
        SapNoDisponible (la app sigue viva; el caller responde 503)."""
        with self._lock:
            ultimo: Exception | None = None
            for intento in range(1, intentos + 1):
                try:
                    if self._conn is None:
                        self._conn = self._conectar()
                    cursor = self._conn.cursor()
                    try:
                        cursor.execute(sql, list(params))
                        return [tuple(fila) for fila in cursor.fetchall()]
                    finally:
                        cursor.close()
                except Exception as exc:  # hdbcli.dbapi.Error, OSError, timeouts...
                    ultimo = exc
                    logger.warning("sap_query_fallo", intento=intento, error=str(exc)[:200])
                    self._cerrar()
            raise SapNoDisponible(str(ultimo))

    def _cerrar(self) -> None:
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.close()
            self._conn = None

    def ping(self) -> bool:
        """Ping barato para /health: UN intento, sin reintento (acota la espera
        al connectTimeout cuando HANA está caído)."""
        try:
            return self._query("SELECT 1 FROM DUMMY", intentos=1) == [(1,)]
        except SapNoDisponible:
            return False

    def _moneda_local_de(self) -> str:
        if self._moneda_local is None:
            filas = self._query(_SQL_MONEDA_LOCAL)
            self._moneda_local = str(filas[0][0]) if filas and filas[0][0] else "MXN"
        return self._moneda_local

    # ------------------------------------------------------------ consultas

    def buscar_oc(self, doc_num: int) -> EncabezadoOC | None:
        filas = self._query(_SQL_ENCABEZADO, (int(doc_num),))
        if not filas:
            return None
        (
            doc_entry,
            num,
            serie,
            card_code,
            card_name,
            doc_status,
            canceled,
            create_date,
            doc_date,
            due_date,
            doc_cur,
            doc_rate,
            doc_total,
            doc_total_fc,
            comments,
            slp_name,
        ) = filas[0]
        moneda = (doc_cur or "").strip() or None
        local = self._moneda_local_de()
        total = _dec(doc_total_fc) if moneda and moneda != local else _dec(doc_total)
        return EncabezadoOC(
            doc_entry=int(doc_entry),
            doc_num=int(num),
            serie=serie,
            sucursal_sap=normalizar_sucursal_sap(serie),
            proveedor_codigo=card_code,
            proveedor_nombre=card_name,
            doc_status=(doc_status or "O").strip().upper(),
            cancelada=(canceled or "N").strip().upper() == "Y",
            fecha_creacion=_fecha(create_date),
            fecha_contabilizacion=_fecha(doc_date),
            fecha_entrega=_fecha(due_date),
            moneda=moneda,
            tipo_cambio=_dec(doc_rate),
            total=total,
            total_mxn=_dec(doc_total),
            comentarios=(comments or "").replace("\r", " · ").strip() or None,
            encargado_compras=slp_name,
        )

    def lineas_oc(self, doc_entry: int) -> list[LineaOC]:
        lineas = []
        for fila in self._query(_SQL_LINEAS, (int(doc_entry),)):
            (num, item, desc, qty, open_qty, whs, whs_name, status, ship, price, total, cur) = fila
            lineas.append(
                LineaOC(
                    num_linea=int(num),
                    articulo=item,
                    descripcion=desc,
                    cantidad=_dec(qty) or Decimal("0"),
                    cantidad_abierta=_dec(open_qty) or Decimal("0"),
                    almacen_codigo=whs,
                    almacen_nombre=whs_name,
                    estatus_linea=(status or "").strip().upper() or None,
                    fecha_entrega=_fecha(ship),
                    precio=_dec(price),
                    importe=_dec(total),
                    moneda=(cur or "").strip() or None,
                )
            )
        return lineas

    def cadena_oc(self, doc_entry: int) -> CadenaOC:
        entradas: dict[int, EntradaOC] = {}
        lineas_por_entrada: dict[int, list[LineaEntrada]] = {}
        for fila in self._query(_SQL_ENTRADAS, (_OBJ_ORDEN_COMPRA, int(doc_entry))):
            (e_entry, e_num, e_date, canceled, base_line, item, qty, whs, whs_name) = fila
            e_entry = int(e_entry)
            lineas_por_entrada.setdefault(e_entry, []).append(
                LineaEntrada(
                    linea_base=int(base_line) if base_line is not None else None,
                    articulo=item,
                    cantidad=_dec(qty) or Decimal("0"),
                    almacen_codigo=whs,
                    almacen_nombre=whs_name,
                )
            )
            if e_entry not in entradas:
                entradas[e_entry] = EntradaOC(
                    doc_entry=e_entry,
                    doc_num=int(e_num),
                    fecha=_fecha(e_date),
                    cancelada=(canceled or "N").strip().upper() == "Y",
                    lineas=lineas_por_entrada[e_entry],
                )
        ids_entradas = sorted(entradas)
        condicion = '(T0."BaseType" = ? AND T0."BaseEntry" = ?)'
        params: list[Any] = [_OBJ_ORDEN_COMPRA, int(doc_entry)]
        if ids_entradas:
            marcas = ", ".join("?" for _ in ids_entradas)
            condicion += f' OR (T0."BaseType" = ? AND T0."BaseEntry" IN ({marcas}))'
            params += [_OBJ_ENTRADA, *ids_entradas]
        local = self._moneda_local_de()
        facturas = []
        for fila in self._query(_SQL_FACTURAS_BASE.format(condicion=condicion), params):
            (f_entry, f_num, f_date, canceled, total, total_fc, cur, base_type, base_entry) = fila
            moneda = (cur or "").strip() or None
            facturas.append(
                FacturaOC(
                    doc_entry=int(f_entry),
                    doc_num=int(f_num),
                    fecha=_fecha(f_date),
                    cancelada=(canceled or "N").strip().upper() == "Y",
                    total=_dec(total_fc) if moneda and moneda != local else _dec(total),
                    moneda=moneda,
                    ligada_a="entrada" if int(base_type) == _OBJ_ENTRADA else "oc",
                    base_doc_entry=int(base_entry) if base_entry is not None else None,
                )
            )
        return CadenaOC(entradas=[entradas[i] for i in ids_entradas], facturas=facturas)
