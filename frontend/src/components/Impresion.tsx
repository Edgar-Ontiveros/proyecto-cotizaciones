/** Impresión (F10 p.5 + F14 p.2) — sin dependencias nuevas.
 *
 * Dos capas:
 * - Hoja de la SOLICITUD (F10): la tabla de partidas sin dinero, para el área
 *   compras (trabajar la captura en papel). Se conserva tal cual.
 * - Documentos por ESTATUS (F14 p.2): COTIZADA → "Cotización"; CONFIRMADA →
 *   "Pedido confirmado" (+ control secundario para REIMPRIMIR la cotización
 *   original). El botón vive SIEMPRE visible; antes de COTIZADA queda
 *   inactivo con tooltip. Cada impresión se registra en la bitácora
 *   (POST /solicitudes/{id}/impresiones) al invocarla.
 *
 * La hoja activa es lo ÚNICO visible en @media print (impresion.css); solo
 * una hoja existe en el DOM a la vez (estado `activo`). El contenido es el
 * que el ROL ya recibió en su JSON — aquí no se inventa ni se filtra nada:
 * el vendedor no tiene TC/consolidado/proveedor porque sus claves no llegan.
 */

import { Button, Tooltip } from "@mantine/core";
import { useEffect, useState } from "react";

import { useAuth } from "../auth/AuthContext";
import { api } from "../lib/api";
import { type DocumentoImpresion, documentoPorEstado } from "../lib/crm";
import { dinero, fecha, folioCliente } from "../lib/format";
import type { OpcionOut, PartidaOut, SolicitudDetailOut } from "../lib/types";

export const ROLES_IMPRIMEN = ["comprador", "gerente_compras", "admin"];

const TITULO_DOCUMENTO: Record<DocumentoImpresion, string> = {
  COTIZACION: "Cotización",
  PEDIDO_CONFIRMADO: "Pedido confirmado",
};

type HojaActiva = DocumentoImpresion | "SOLICITUD";

/** Controles + hojas de impresión del detalle (ambas vistas). Reemplaza al
 * par BotonImprimir/HojaImpresion de F10 integrando los documentos F14. */
export function ControlesImpresion({ solicitud }: { solicitud: SolicitudDetailOut }) {
  const { usuario } = useAuth();
  const [activo, setActivo] = useState<HojaActiva | null>(null);

  // La hoja debe estar en el DOM antes de window.print(): se activa por
  // estado y el efecto imprime ya con el render aplicado.
  useEffect(() => {
    if (activo === null) return;
    window.print();
    setActivo(null);
  }, [activo]);

  if (usuario === null) return null;
  const documento = documentoPorEstado(solicitud.estado);

  const imprimirDocumento = (doc: DocumentoImpresion) => {
    // Bitácora (F14 p.2): se dispara AL INVOCAR la impresión; un fallo del
    // registro no bloquea el papel (el error lo muestra el handler global).
    void api(`/solicitudes/${solicitud.id}/impresiones`, {
      method: "POST",
      body: { documento: doc },
    }).catch(() => undefined);
    setActivo(doc);
  };

  return (
    <>
      {/* F10 p.5: la hoja de la solicitud sigue para el área compras. */}
      {ROLES_IMPRIMEN.includes(usuario.rol) && (
        <Button variant="default" onClick={() => setActivo("SOLICITUD")}>
          Imprimir solicitud
        </Button>
      )}
      <Tooltip
        label="Disponible cuando la solicitud esté cotizada"
        disabled={documento !== null}
        withArrow
      >
        {/* span: un botón disabled no dispara eventos y el tooltip lo necesita */}
        <span>
          <Button
            variant="default"
            disabled={documento === null}
            onClick={() => documento !== null && imprimirDocumento(documento)}
          >
            {documento === "PEDIDO_CONFIRMADO" ? "Imprimir pedido" : "Imprimir cotización"}
          </Button>
        </span>
      </Tooltip>
      {solicitud.estado === "CONFIRMADA" && (
        <Button variant="subtle" onClick={() => imprimirDocumento("COTIZACION")}>
          Reimprimir cotización
        </Button>
      )}
      {activo === "SOLICITUD" && <HojaImpresion solicitud={solicitud} />}
      {activo !== null && activo !== "SOLICITUD" && (
        <HojaDocumento solicitud={solicitud} documento={activo} />
      )}
    </>
  );
}

/** Tabla de renglones de UNA opción: descripción (la de la partida, o la
 * alternativa cotizada), cantidad, unidad, precio unitario e importe. El
 * proveedor solo se muestra si el JSON del rol lo trae (área compras). */
function TablaOpcion({
  opcion,
  partidas,
  conProveedor,
}: {
  opcion: OpcionOut;
  partidas: Map<number, PartidaOut>;
  conProveedor: boolean;
}) {
  return (
    <table className="hoja-partidas">
      <thead>
        <tr>
          <th>No.</th>
          <th>Descripción</th>
          <th>Cantidad</th>
          <th>Unidad</th>
          <th>Precio unitario</th>
          <th>Importe</th>
          {conProveedor && <th>Proveedor</th>}
        </tr>
      </thead>
      <tbody>
        {opcion.renglones.map((r) => {
          const partida = partidas.get(r.partida_id);
          const descripcion = r.es_alternativa
            ? `${r.alternativa_descripcion ?? ""} (alternativa)`
            : (partida?.descripcion ?? "—");
          return (
            <tr key={r.id}>
              <td>{r.num_partida}</td>
              <td>{r.no_encontrada ? `${descripcion} — NO ENCONTRADO` : descripcion}</td>
              <td>{r.cantidad}</td>
              <td>{r.unidad}</td>
              <td>
                {r.precio_unitario !== null && r.moneda !== null
                  ? dinero(r.precio_unitario, r.moneda)
                  : "—"}
              </td>
              <td>{r.importe !== null && r.moneda !== null ? dinero(r.importe, r.moneda) : "—"}</td>
              {conProveedor && <td>{r.proveedor ?? "—"}</td>}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** Totales de una opción: subtotales por moneda SIEMPRE; el TOTAL (MXN)
 * consolidado solo cuando la clave llega (roles autorizados, F8e). */
function TotalesOpcion({ opcion }: { opcion: OpcionOut }) {
  const subtotales = [
    Number(opcion.total_mxn) !== 0 ? `Subtotal MXN: ${dinero(opcion.total_mxn, "MXN")}` : null,
    Number(opcion.total_usd) !== 0 ? `Subtotal USD: ${dinero(opcion.total_usd, "USD")}` : null,
  ].filter(Boolean);
  return (
    <p className="hoja-totales">
      {subtotales.join(" · ") || "Sin importes"}
      {opcion.consolidado_mxn != null && (
        <b> — TOTAL (MXN): {dinero(opcion.consolidado_mxn, "MXN")}</b>
      )}
    </p>
  );
}

/** Documento imprimible (F14 p.2): Cotización (todas las opciones A–E) o
 * Pedido confirmado (solo la ganadora, con el monto oficial si el rol lo
 * recibe; el vendedor ve los subtotales por moneda de siempre). */
export function HojaDocumento({
  solicitud,
  documento,
}: {
  solicitud: SolicitudDetailOut;
  documento: DocumentoImpresion;
}) {
  const partidas = new Map(solicitud.partidas.map((p) => [p.id, p]));
  const conProveedor = solicitud.opciones.some((o) => o.renglones.some((r) => "proveedor" in r));
  const opciones =
    documento === "PEDIDO_CONFIRMADO"
      ? solicitud.opciones.filter((o) => o.id === solicitud.opcion_seleccionada_id)
      : [...solicitud.opciones].sort((a, b) => a.letra.localeCompare(b.letra));
  const hoyISO = new Date().toISOString();
  return (
    <div className="hoja-impresion">
      <p className="hoja-empresa">
        <b>Comercializadora de Inoxidables Hernández S.A. de C.V.</b> · Herinox
      </p>
      <h1>
        {TITULO_DOCUMENTO[documento]} — {folioCliente(solicitud.folio, solicitud.cliente_nombre)}
      </h1>
      <table className="hoja-generales">
        <tbody>
          <tr>
            <th>Folio</th>
            <td>{solicitud.folio ?? "—"}</td>
            <th>Fecha de emisión</th>
            <td>{fecha(hoyISO)}</td>
          </tr>
          <tr>
            <th>Cliente</th>
            <td>{solicitud.cliente_nombre ?? "—"}</td>
            <th>Sucursal</th>
            <td>{solicitud.sucursal_nombre ?? "—"}</td>
          </tr>
          <tr>
            <th>Vendedor</th>
            <td>{solicitud.vendedor_nombre ?? "—"}</td>
            <th>Comprador</th>
            <td>{solicitud.comprador_nombre ?? "—"}</td>
          </tr>
        </tbody>
      </table>
      {opciones.map((opcion) => (
        <div key={opcion.id}>
          <h2>
            Opción {opcion.letra}
            {opcion.vigencia !== null ? ` · vigencia ${fecha(opcion.vigencia)}` : ""}
            {documento === "PEDIDO_CONFIRMADO" ? " (seleccionada)" : ""}
          </h2>
          <TablaOpcion opcion={opcion} partidas={partidas} conProveedor={conProveedor} />
          <TotalesOpcion opcion={opcion} />
          {opcion.comentarios !== null && (
            <p className="hoja-notas">Comentarios: {opcion.comentarios}</p>
          )}
        </div>
      ))}
      {documento === "PEDIDO_CONFIRMADO" && solicitud.monto_confirmado != null && (
        <p className="hoja-totales">
          <b>MONTO OFICIAL (consolidado MXN): {dinero(solicitud.monto_confirmado, "MXN")}</b>
          {solicitud.tipo_cambio != null && ` · tipo de cambio ${solicitud.tipo_cambio}`}
        </p>
      )}
      {solicitud.notas !== null && <p className="hoja-notas">Notas: {solicitud.notas}</p>}
    </div>
  );
}

export function HojaImpresion({ solicitud }: { solicitud: SolicitudDetailOut }) {
  return (
    <div className="hoja-impresion">
      <h1>Solicitud de cotización — {folioCliente(solicitud.folio, solicitud.cliente_nombre)}</h1>
      <table className="hoja-generales">
        <tbody>
          <tr>
            <th>Folio</th>
            <td>{solicitud.folio ?? "(borrador)"}</td>
            <th>Sucursal</th>
            <td>{solicitud.sucursal_nombre}</td>
          </tr>
          <tr>
            <th>Fecha</th>
            <td>{fecha(solicitud.creado_en)}</td>
            <th>Estado</th>
            <td>{solicitud.estado}</td>
          </tr>
          <tr>
            <th>Vendedor</th>
            <td>{solicitud.vendedor_nombre}</td>
            <th>Cliente</th>
            <td>{solicitud.cliente_nombre ?? "—"}</td>
          </tr>
          <tr>
            <th>Prioridad</th>
            <td>{solicitud.prioridad}</td>
            <th>Banda</th>
            <td>{solicitud.banda ?? "—"}</td>
          </tr>
          <tr>
            <th>Tipo</th>
            <td colSpan={3}>{solicitud.es_proyecto ? "PROYECTO" : "Pedido especial"}</td>
          </tr>
        </tbody>
      </table>
      <table className="hoja-partidas">
        <thead>
          <tr>
            <th>No.</th>
            <th>Código SAP</th>
            <th>Cantidad</th>
            <th>Unidad</th>
            <th>Tipo de acero</th>
            <th>Descripción</th>
            <th>Medidas</th>
          </tr>
        </thead>
        <tbody>
          {solicitud.partidas.map((p) => (
            <tr key={p.id}>
              <td>{p.num_partida}</td>
              <td>{p.codigo_sap ?? "SERVICIO"}</td>
              <td>{p.cantidad}</td>
              <td>{p.unidad}</td>
              <td>{p.tipo_acero ?? "—"}</td>
              <td>{p.descripcion}</td>
              <td>{p.medidas ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {solicitud.notas && <p className="hoja-notas">Notas: {solicitud.notas}</p>}
    </div>
  );
}
