/** Gráficas Recharts del dashboard (F8d). Reglas dataviz aplicadas:
 * - Un solo eje por gráfica; una serie = un solo matiz (sin arcoíris).
 * - Pareja categórica FIJA azul #2059A6 / naranja #F08215 (validada CVD);
 *   el naranja va SIEMPRE acompañado de leyenda/etiquetas (contraste).
 * - Los colores de ESTATUS (semáforo de bandas) son reservados y llevan
 *   etiqueta + conteo, nunca color solo. Texto en tintas de texto, no en el
 *   color de la serie. */

import { Card, Group, Text, Title } from "@mantine/core";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { dinero } from "../lib/format";
import type { NoEncontradosOut, SemanaOut, TiemposEtapaOut } from "../lib/types";

export const AZUL = "#2059A6";
export const NARANJA = "#F08215";
const REJILLA = "var(--mantine-color-gray-3)";
const TINTA = "var(--mantine-color-gray-7)";

const BANDA_COLOR: Record<string, string> = {
  ESPERADA: "var(--mantine-color-green-6)",
  NORMAL: "var(--mantine-color-yellow-6)",
  LENTA: "var(--mantine-color-red-6)",
};
const BANDA_TEXTO: Record<string, string> = {
  ESPERADA: "Esperada (verde)",
  NORMAL: "Normal (amarillo)",
  LENTA: "Lenta (rojo)",
};

function Carta({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <Card withBorder p="md" h="100%">
      <Title order={6} c="gray.7" mb="xs">
        {titulo}
      </Title>
      {children}
    </Card>
  );
}

const mesCorto = (iso: string) => {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
};

export function GraficaSerie({ semanas }: { semanas: SemanaOut[] }) {
  const datos = semanas.map((s) => ({ ...s, etiqueta: mesCorto(s.semana) }));
  return (
    <Carta titulo="Tendencia semanal (semana del lunes)">
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={datos} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
          <CartesianGrid stroke={REJILLA} vertical={false} />
          <XAxis dataKey="etiqueta" tick={{ fontSize: 11, fill: TINTA }} tickLine={false} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: TINTA }} tickLine={false} />
          <Tooltip
            formatter={(valor, nombre) => [String(valor), nombre]}
            labelFormatter={(_, punto) => {
              const p = punto[0]?.payload as SemanaOut | undefined;
              return p
                ? `Semana del ${p.semana} · confirmado ${dinero(p.dinero_confirmado_mxn, "MXN")}`
                : "";
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line
            name="Creadas"
            dataKey="creadas"
            stroke={AZUL}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
          <Line
            name="Confirmadas"
            dataKey="confirmadas"
            stroke={NARANJA}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </Carta>
  );
}

const ORDEN_EMBUDO = [
  "BORRADOR",
  "ENVIADA",
  "EN_PROCESO",
  "COTIZADA",
  "CONFIRMADA",
  "NO_CONFIRMADA",
  "RECHAZADA",
  "CANCELADA",
];

export function GraficaEmbudo({ embudo }: { embudo: Record<string, number> }) {
  const datos = ORDEN_EMBUDO.filter((e) => (embudo[e] ?? 0) > 0).map((estado) => ({
    estado,
    conteo: embudo[estado] ?? 0,
  }));
  return (
    <Carta titulo="Embudo por estado (creadas en el periodo)">
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={datos} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <CartesianGrid stroke={REJILLA} vertical={false} />
          <XAxis
            dataKey="estado"
            tick={{ fontSize: 10, fill: TINTA }}
            tickLine={false}
            interval={0}
          />
          <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: TINTA }} tickLine={false} />
          <Tooltip />
          <Bar dataKey="conteo" name="Solicitudes" fill={AZUL} radius={[4, 4, 0, 0]} maxBarSize={40} />
        </BarChart>
      </ResponsiveContainer>
    </Carta>
  );
}

export function GraficaBandas({ distribucion }: { distribucion: Record<string, number> }) {
  const datos = ["ESPERADA", "NORMAL", "LENTA"]
    .map((banda) => ({ banda, conteo: distribucion[banda] ?? 0 }))
    .filter((d) => d.conteo > 0);
  const total = datos.reduce((suma, d) => suma + d.conteo, 0);
  return (
    <Carta titulo="Distribución de bandas (ciclos del periodo)">
      {total === 0 ? (
        <Text c="dimmed" size="sm">
          Sin ciclos en el periodo
        </Text>
      ) : (
        <Group wrap="nowrap" align="center" gap="md">
          <ResponsiveContainer width={180} height={200}>
            <PieChart>
              <Pie
                data={datos}
                dataKey="conteo"
                nameKey="banda"
                innerRadius={50}
                outerRadius={80}
                paddingAngle={2}
                stroke="var(--mantine-color-body)"
                strokeWidth={2}
              >
                {datos.map((d) => (
                  <Cell key={d.banda} fill={BANDA_COLOR[d.banda]} />
                ))}
              </Pie>
              <Tooltip formatter={(v, n) => [String(v), BANDA_TEXTO[String(n)] ?? String(n)]} />
            </PieChart>
          </ResponsiveContainer>
          <div>
            {datos.map((d) => (
              <Group key={d.banda} gap={6} mb={4} wrap="nowrap">
                <span
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 3,
                    background: BANDA_COLOR[d.banda],
                    display: "inline-block",
                  }}
                />
                <Text size="sm">
                  {BANDA_TEXTO[d.banda]}: <b>{d.conteo}</b> ({Math.round((d.conteo / total) * 100)}%)
                </Text>
              </Group>
            ))}
          </div>
        </Group>
      )}
    </Carta>
  );
}

export interface FilaCarga {
  nombre: string;
  valor: number;
}

export function GraficaBarrasH({
  titulo,
  filas,
  nombreSerie,
  formatear = (v: number) => String(v),
}: {
  titulo: string;
  filas: FilaCarga[];
  nombreSerie: string;
  formatear?: (v: number) => string;
}) {
  const alto = Math.max(140, filas.length * 34 + 40);
  return (
    <Carta titulo={titulo}>
      {filas.length === 0 ? (
        <Text c="dimmed" size="sm">
          Sin datos en el periodo
        </Text>
      ) : (
        <ResponsiveContainer width="100%" height={alto}>
          <BarChart data={filas} layout="vertical" margin={{ top: 0, right: 32, bottom: 0, left: 8 }}>
            <CartesianGrid stroke={REJILLA} horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 11, fill: TINTA }} tickLine={false} />
            <YAxis
              type="category"
              dataKey="nombre"
              width={140}
              tick={{ fontSize: 11, fill: TINTA }}
              tickLine={false}
            />
            <Tooltip formatter={(v) => [formatear(Number(v)), nombreSerie]} />
            <Bar
              dataKey="valor"
              name={nombreSerie}
              fill={AZUL}
              radius={[0, 4, 4, 0]}
              maxBarSize={20}
              label={{
                position: "right",
                fontSize: 11,
                fill: TINTA,
                formatter: (v: unknown) => formatear(Number(v)),
              }}
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </Carta>
  );
}

const ORDEN_TIEMPOS = ORDEN_EMBUDO;

/** Tiempos por etapa (F8f/addendum F8g): mediana de horas hábiles por estado
 * sobre segmentos CERRADOS. Pinta SOLO estados con n > 0; el tooltip agrega
 * promedio y n. */
export function GraficaTiemposEtapa({ data }: { data: TiemposEtapaOut }) {
  const filas = ORDEN_TIEMPOS.filter((estado) => (data.por_estado[estado]?.n ?? 0) > 0).map(
    (estado) => {
      const e = data.por_estado[estado];
      return {
        estado,
        mediana: e?.mediana_horas_habiles ?? 0,
        promedio: e?.promedio_horas_habiles ?? 0,
        n: e?.n ?? 0,
      };
    },
  );
  return (
    <Carta titulo="Tiempos por etapa (mediana de horas hábiles, estancias cerradas)">
      {filas.length === 0 ? (
        <Text c="dimmed" size="sm">
          Sin estancias cerradas en el periodo
        </Text>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={filas} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid stroke={REJILLA} vertical={false} />
            <XAxis
              dataKey="estado"
              tick={{ fontSize: 10, fill: TINTA }}
              tickLine={false}
              interval={0}
            />
            <YAxis tick={{ fontSize: 11, fill: TINTA }} tickLine={false} />
            <Tooltip
              formatter={(valor) => [`${Number(valor).toFixed(1)} h`, "Mediana"]}
              labelFormatter={(estado, punto) => {
                const p = punto[0]?.payload as (typeof filas)[number] | undefined;
                return p
                  ? `${String(estado)} · promedio ${p.promedio.toFixed(1)} h · n=${p.n}`
                  : String(estado);
              }}
            />
            <Bar
              dataKey="mediana"
              name="Mediana (h hábiles)"
              fill={AZUL}
              radius={[4, 4, 0, 0]}
              maxBarSize={40}
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </Carta>
  );
}

export function GraficaNoEncontrados({ data }: { data: NoEncontradosOut }) {
  const filas = data.por_comprador
    .filter((g) => g.total_renglones > 0)
    .map((g) => ({ nombre: g.nombre, valor: Math.round((g.pct ?? 0) * 1000) / 10 }));
  return (
    <GraficaBarrasH
      titulo={`% de renglones no encontrados (global ${
        data.pct === null ? "—" : `${(data.pct * 100).toFixed(1)}%`
      })`}
      filas={filas}
      nombreSerie="% no encontrados"
      formatear={(v) => `${v}%`}
    />
  );
}
