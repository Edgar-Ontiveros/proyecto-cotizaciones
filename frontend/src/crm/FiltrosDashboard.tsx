/** Barra de filtros del dashboard (F8d): presets de fecha + selects según lo
 * que /metricas/filtros da al rol (compradores/vendedores llegan null si el
 * rol no los ve). */

import { Group, SegmentedControl, Select } from "@mantine/core";

import type { PresetFechas } from "../lib/crm";
import type { FiltrosCatalogoOut, OpcionFiltroOut } from "../lib/types";

export function opcionesSelect(opciones: OpcionFiltroOut[] | null | undefined) {
  return (opciones ?? []).map((o) => ({ value: String(o.id), label: o.nombre }));
}

const PRESETS: { value: PresetFechas; label: string }[] = [
  { value: "mes", label: "Mes actual" },
  { value: "30d", label: "30 días" },
  { value: "trimestre", label: "Trimestre" },
];

interface Props {
  preset: PresetFechas;
  setPreset: (p: PresetFechas) => void;
  catalogos: FiltrosCatalogoOut | undefined;
  sucursalId: number | undefined;
  setSucursalId: (v: number | undefined) => void;
  sucursalDeshabilitada: boolean;
  compradorId: number | undefined;
  setCompradorId: (v: number | undefined) => void;
  vendedorId: number | undefined;
  setVendedorId: (v: number | undefined) => void;
}

export function FiltrosDashboardBarra(p: Props) {
  return (
    <Group gap="sm">
      <SegmentedControl
        value={p.preset}
        onChange={(v) => p.setPreset(v as PresetFechas)}
        data={PRESETS}
        size="xs"
      />
      <Select
        placeholder="Sucursal"
        data={opcionesSelect(p.catalogos?.sucursales)}
        value={p.sucursalId !== undefined ? String(p.sucursalId) : null}
        onChange={(v) => p.setSucursalId(v === null ? undefined : Number(v))}
        disabled={p.sucursalDeshabilitada}
        clearable={!p.sucursalDeshabilitada}
        searchable
        w={200}
      />
      {p.catalogos?.compradores && (
        <Select
          placeholder="Comprador"
          data={opcionesSelect(p.catalogos.compradores)}
          value={p.compradorId !== undefined ? String(p.compradorId) : null}
          onChange={(v) => p.setCompradorId(v === null ? undefined : Number(v))}
          clearable
          searchable
          w={200}
        />
      )}
      {p.catalogos?.vendedores && (
        <Select
          placeholder="Vendedor"
          data={opcionesSelect(p.catalogos.vendedores)}
          value={p.vendedorId !== undefined ? String(p.vendedorId) : null}
          onChange={(v) => p.setVendedorId(v === null ? undefined : Number(v))}
          clearable
          searchable
          w={200}
        />
      )}
    </Group>
  );
}
