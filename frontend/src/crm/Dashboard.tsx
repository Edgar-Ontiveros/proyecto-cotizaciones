/** Dashboard del CRM (F8d): cards de /metricas/resumen + gráficas, con
 * filtros por preset de fechas y catálogos acotados por rol
 * (/metricas/filtros). Variantes por perfil: carga por comprador y % no
 * encontrados SOLO para compras global y admin. */

import { Card, Group, SimpleGrid, Stack, Text, Tooltip } from "@mantine/core";
import { useState } from "react";

import {
  useFiltrosCatalogo,
  useNoEncontrados,
  useResumen,
  useSerie,
  useTabla,
  useTiemposEtapa,
} from "../api/crmHooks";
import { useAuth } from "../auth/AuthContext";
import { type FiltrosDashboard, type PresetFechas, queryFiltrosDashboard } from "../lib/crm";
import { dinero, horas, pct } from "../lib/format";
import type { ResumenOut } from "../lib/types";
import { FiltrosDashboardBarra } from "./FiltrosDashboard";
import {
  GraficaBandas,
  GraficaBarrasH,
  GraficaEmbudo,
  GraficaNoEncontrados,
  GraficaSerie,
  GraficaTiemposEtapa,
} from "./graficas";

function Indicador({
  titulo,
  valor,
  sub,
  tooltip,
}: {
  titulo: string;
  valor: string;
  sub?: string;
  tooltip?: string;
}) {
  const carta = (
    <Card withBorder p="sm">
      <Text size="xs" c="dimmed">
        {titulo}
      </Text>
      <Text size="xl" fw={700}>
        {valor}
      </Text>
      {sub && (
        <Text size="xs" c="dimmed">
          {sub}
        </Text>
      )}
    </Card>
  );
  if (!tooltip) return carta;
  return (
    <Tooltip label={tooltip} multiline w={320} withArrow>
      {carta}
    </Tooltip>
  );
}

// F14 p.1: fórmula exacta del KPI, visible al pasar el cursor.
const FORMULA_CONVERSION =
  "Conversión = (confirmadas ÷ cotizadas) × 100, por ciclos del periodo: " +
  "el denominador son las solicitudes efectivamente COTIZADAS en el periodo " +
  "(una recotizada cuenta UNA vez); excluye canceladas antes de cotizar, " +
  "cotizaciones con todo no encontrado y solicitudes eliminadas. El " +
  "numerador son, de esas, las hoy CONFIRMADAS.";

function dineroPorMoneda(mapa: Record<string, string>): string {
  const partes = Object.entries(mapa)
    .filter(([, v]) => Number(v) !== 0)
    .map(([m, v]) => dinero(v, m as "MXN" | "USD"));
  return partes.length > 0 ? partes.join(" + ") : "—";
}

function Cards({ resumen }: { resumen: ResumenOut }) {
  // F14 §0b: claves opcionales — para el vendedor NO EXISTEN en el JSON.
  const confirmadoMXN = resumen.dinero_confirmado?.["MXN"];
  const desglose = dineroPorMoneda(resumen.dinero_confirmado_desglose ?? {});
  const conv = resumen.conversion;
  return (
    <SimpleGrid cols={{ base: 2, sm: 3, lg: 6 }}>
      <Indicador titulo="Solicitudes del periodo" valor={String(resumen.solicitudes_periodo)} />
      <Indicador
        titulo="% banda esperada"
        valor={pct(resumen.pct_banda_esperada)}
        sub={`${resumen.ciclos_cerrados} ciclos cerrados`}
      />
      <Indicador titulo="Mediana (h hábiles)" valor={horas(resumen.mediana_horas_habiles)} />
      <Indicador titulo="Rojas AHORA" valor={String(resumen.rojas_ahora)} sub="foto del momento" />
      {/* F14 p.1: "62.5% — 25 de 40 cotizadas"; denominador 0 → "—". */}
      <Indicador
        titulo="Conversión"
        valor={pct(conv.tasa)}
        sub={
          conv.cotizadas > 0
            ? `${conv.confirmadas} de ${conv.cotizadas} cotizadas`
            : "sin cotizadas en el periodo"
        }
        tooltip={FORMULA_CONVERSION}
      />
      <Indicador
        titulo="Confirmado (MXN)"
        valor={confirmadoMXN !== undefined ? dinero(confirmadoMXN, "MXN") : "—"}
        sub={desglose !== "—" ? `origen: ${desglose}` : undefined}
      />
    </SimpleGrid>
  );
}

export function Dashboard() {
  const { usuario } = useAuth();
  const { data: catalogos } = useFiltrosCatalogo();
  const [preset, setPreset] = useState<PresetFechas>("mes");
  const [sucursalId, setSucursalId] = useState<number | undefined>();
  const [compradorId, setCompradorId] = useState<number | undefined>();
  const [vendedorId, setVendedorId] = useState<number | undefined>();

  const rol = usuario?.rol;
  const esCompras = rol === "admin" || rol === "gerente_compras";
  // El gerente de sucursal tiene la sucursal FIJA (control deshabilitado): el
  // backend la fuerza igual (con_scoping) — aquí solo se refleja.
  const sucursalFija = rol === "gerente_sucursal" ? (usuario?.sucursal_id ?? undefined) : undefined;

  const filtros: FiltrosDashboard = {
    preset,
    sucursal_id: sucursalFija ?? sucursalId,
    comprador_id: compradorId,
    vendedor_id: vendedorId,
  };
  const params = queryFiltrosDashboard(filtros);

  const resumen = useResumen(params);
  const serie = useSerie(params);
  const carga = useTabla("comprador", params, esCompras);
  const noEncontrados = useNoEncontrados(params, esCompras);
  // Addendum F8g: tiempos por etapa con LOS MISMOS filtros del dashboard.
  const tiemposEtapa = useTiemposEtapa(params);

  const filasCarga = (carga.data ?? [])
    .filter((g) => (g.carga_abierta ?? 0) > 0)
    .map((g) => ({ nombre: g.nombre, valor: g.carga_abierta ?? 0 }));

  return (
    <Stack>
      <FiltrosDashboardBarra
        preset={preset}
        setPreset={setPreset}
        catalogos={catalogos}
        sucursalId={sucursalFija ?? sucursalId}
        setSucursalId={setSucursalId}
        sucursalDeshabilitada={sucursalFija !== undefined}
        compradorId={compradorId}
        setCompradorId={setCompradorId}
        vendedorId={vendedorId}
        setVendedorId={setVendedorId}
      />
      {resumen.data && <Cards resumen={resumen.data} />}
      {resumen.data && (
        <Group gap="xs">
          <Text size="sm" c="dimmed">
            Referencia (cotizadas hoy): {dineroPorMoneda(resumen.data.dinero_referencia)}
          </Text>
        </Group>
      )}
      {tiemposEtapa.data && (
        <SimpleGrid cols={{ base: 2, lg: 4 }}>
          <Indicador
            titulo="Tiempo de compras (mediana h háb.)"
            valor={horas(tiemposEtapa.data.compras.mediana_horas_habiles)}
            sub={
              tiemposEtapa.data.compras.promedio_horas_habiles !== null
                ? `promedio ${horas(tiemposEtapa.data.compras.promedio_horas_habiles)} · n=${tiemposEtapa.data.compras.n}`
                : undefined
            }
          />
          <Indicador
            titulo="Tiempo de ventas (mediana h háb.)"
            valor={horas(tiemposEtapa.data.ventas.mediana_horas_habiles)}
            sub={
              tiemposEtapa.data.ventas.promedio_horas_habiles !== null
                ? `promedio ${horas(tiemposEtapa.data.ventas.promedio_horas_habiles)} · n=${tiemposEtapa.data.ventas.n}`
                : undefined
            }
          />
        </SimpleGrid>
      )}
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        {serie.data && <GraficaSerie semanas={serie.data.semanas} />}
        {tiemposEtapa.data && <GraficaTiemposEtapa data={tiemposEtapa.data} />}
        {resumen.data && <GraficaEmbudo embudo={resumen.data.embudo} />}
        {resumen.data && <GraficaBandas distribucion={resumen.data.distribucion_bandas} />}
        {esCompras && (
          <GraficaBarrasH
            titulo="Carga abierta por comprador (ahora)"
            filas={filasCarga}
            nombreSerie="Abiertas"
          />
        )}
        {esCompras && noEncontrados.data && <GraficaNoEncontrados data={noEncontrados.data} />}
      </SimpleGrid>
    </Stack>
  );
}
