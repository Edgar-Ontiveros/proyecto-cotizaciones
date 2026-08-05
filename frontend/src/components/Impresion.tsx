/** Impresión de la solicitud (F10 p.5) — sin dependencias nuevas.
 *
 * La hoja vive oculta en el DOM del detalle; `impresion.css` la vuelve lo
 * ÚNICO visible en @media print (sin navegación ni botones). El botón solo
 * dispara window.print(). El contenido es el que el ROL ya recibió en su
 * JSON — aquí no se inventa ni se filtra nada. */

import { Button } from "@mantine/core";

import { fecha, folioCliente } from "../lib/format";
import type { SolicitudDetailOut } from "../lib/types";

export const ROLES_IMPRIMEN = ["comprador", "gerente_compras", "admin"];

export function BotonImprimir() {
  return (
    <Button variant="default" onClick={() => window.print()}>
      Imprimir
    </Button>
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
