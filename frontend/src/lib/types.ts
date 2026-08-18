// Tipos espejo de los schemas Pydantic del backend (fuente de verdad).
// Los Decimal del backend viajan como string en JSON.

export type Rol =
  | "vendedor"
  | "comprador"
  | "gerente_sucursal"
  | "gerente_compras"
  | "director_ventas"
  | "admin";

export type Estado =
  | "BORRADOR"
  | "ENVIADA"
  | "EN_PROCESO"
  | "COTIZADA"
  | "CONFIRMADA"
  | "NO_CONFIRMADA"
  | "RECHAZADA"
  | "CANCELADA";

export type Prioridad = "NORMAL" | "URGENTE";
export type Moneda = "MXN" | "USD";
export type Banda = "ESPERADA" | "NORMAL" | "LENTA";
export type Letra = "A" | "B" | "C" | "D" | "E";
export type MotivoNoConfirmada = "PRECIO" | "TIEMPO_ENTREGA" | "CLIENTE_DESISTIO" | "OTRO";

export interface UsuarioMe {
  id: number;
  nombre: string;
  email: string;
  rol: Rol;
  sucursal_id: number | null;
  activo: boolean;
  must_change_password: boolean;
}

export interface AccessTokenResponse {
  access_token: string;
  token_type: string;
  must_change_password: boolean;
}

export interface PartidaOut {
  id: number;
  num_partida: number;
  codigo_sap: string | null;
  cantidad: string;
  unidad: Unidad;
  tipo_acero: string | null;
  descripcion: string;
  medidas: string | null;
}

export interface SolicitudOut {
  id: number;
  folio: string | null;
  estado: Estado;
  prioridad: Prioridad;
  // F8f: solicitud de PROYECTO — badge en listados/cola/detalle/CRM.
  es_proyecto: boolean;
  // F8h: cambio de cantidad/unidad pendiente de aprobación (bloquea
  // confirmar/corregir/editar).
  cambio_pendiente: boolean;
  // F10.1 p.2b: el ÚLTIMO cambio quedó APROBADO y la solicitud sigue en
  // COTIZADA (derivado por el backend; muere solo al cambiar de estado).
  cambio_aprobado: boolean;
  cliente_id: number | null;
  cliente_nombre: string | null;
  vendedor_id: number;
  comprador_id: number | null;
  sucursal_id: number;
  notas: string | null;
  opcion_seleccionada_id: number | null;
  // F8e: para el rol VENDEDOR estas claves NO llegan (el backend las excluye
  // del schema); para el resto sí. Por eso son opcionales.
  monto_confirmado?: string | null;
  moneda_confirmada?: Moneda | null;
  motivo_no_confirmada: string | null;
  creado_en: string;
  enviado_en: string | null;
  cotizado_en: string | null;
  confirmado_en: string | null;
  banda: Banda | null;
  dias_transcurridos: number | null;
  horas_habiles: number | null;
  // Referencia: SUBTOTALES por moneda — opción A en COTIZADA; para el
  // vendedor también la GANADORA en CONFIRMADA (F8e).
  referencia_mxn: string | null;
  referencia_usd: string | null;
  // TC capturado por el COMPRADOR al cotizar (F8e); ausente para vendedor.
  tipo_cambio?: string | null;
  // F12 p.5: fincado interno del área compras — las claves SOLO llegan a
  // comprador, gerente_compras y admin (el lado ventas ni las recibe).
  fincada?: boolean;
  fincada_por?: number | null;
  fincada_en?: string | null;
}

export type Unidad = "PZ" | "KG" | "TON" | "MTS" | "M2";

export interface RenglonOut {
  id: number;
  partida_id: number;
  num_partida: number;
  // Cantidad/unidad COTIZADAS (pueden diferir de lo pedido).
  cantidad: string;
  unidad: Unidad;
  // Moneda POR RENGLÓN (F8c).
  moneda: Moneda | null;
  precio_unitario: string | null;
  importe: string | null;
  tiempo_entrega: string | null;
  no_encontrada: boolean;
  es_alternativa: boolean;
  alternativa_descripcion: string | null;
  // F11: cotizado normal + comentario de la partida para el vendedor.
  con_observacion: boolean;
  observacion: string | null;
  // SOLO llega para comprador/admin; el backend la excluye para vendedor y
  // gerente (jamás inventarla en UI).
  proveedor?: string | null;
}

export interface OpcionOut {
  id: number;
  letra: Letra;
  vigencia: string | null;
  comentarios: string | null;
  // Subtotales POR MONEDA (F8c): jamás se suman sin tipo de cambio.
  total_mxn: string;
  total_usd: string;
  completa: boolean;
  // Consolidado MXN por opción (F8e): SOLO para roles autorizados; para el
  // vendedor la clave no llega.
  consolidado_mxn?: string | null;
  renglones: RenglonOut[];
}

export interface HistorialOut {
  id: number;
  de: Estado | null;
  a: Estado;
  usuario_id: number;
  usuario_nombre: string;
  motivo_id: number | null;
  motivo_texto: string | null;
  comentario: string | null;
  timestamp: string;
}

export interface ComentarioOut {
  id: number;
  usuario_id: number;
  usuario_nombre: string;
  texto: string;
  creado_en: string;
}

export interface CicloOut {
  numero: number;
  apertura: string;
  cierre: string | null;
  horas_habiles: number;
  dias_transcurridos: number;
  banda: Banda;
}

// F8f: estancia continua en un estado (las transiciones reales cortan, los
// eventos de==a no); fin=null = segmento vigente.
export interface SegmentoOut {
  estado: Estado;
  inicio: string;
  fin: string | null;
  horas_habiles: number;
  horas_naturales: number;
}

export interface TiemposOut {
  segmentos: SegmentoOut[];
  general_horas_habiles: number;
  general_horas_naturales: number;
  compras_horas_habiles: number;
  ventas_horas_habiles: number;
  detenido: boolean;
}

// F8g: metadatos del comprobante de pedido (el archivo se descarga por
// endpoint autenticado, jamás por URL estática).
export interface ComprobanteOut {
  id: string;
  nombre_original: string;
  mime: string;
  tamano_bytes: number;
  subido_por: number;
  subido_por_nombre: string;
  creado_en: string;
}

// F8h/F13: cambios de partidas post-cotización.
export type EstadoCambio = "PENDIENTE" | "APROBADO" | "RECHAZADO" | "RETIRADO";

// F13: qué le hace el renglón a la partida.
export type TipoRenglonCambio = "MODIFICACION" | "ALTA" | "BAJA";

export interface CambioPartidaOut {
  // id del renglón de cambio; referencia un ALTA al capturar su precio (F13).
  id: number;
  tipo: TipoRenglonCambio;
  partida_id: number | null;
  num_partida: number | null;
  descripcion: string;
  descripcion_nueva: string | null;
  cantidad_anterior: string | null;
  cantidad_nueva: string | null;
  unidad_anterior: string | null;
  unidad_nueva: string | null;
}

export interface CambioOut {
  id: number;
  estado_cambio: EstadoCambio;
  solicitado_por: number;
  solicitado_por_nombre: string;
  resuelto_por: number | null;
  resuelto_por_nombre: string | null;
  comentario_solicitante: string | null;
  comentario_resolucion: string | null;
  creado_en: string;
  resuelto_en: string | null;
  partidas: CambioPartidaOut[];
}

export interface SolicitudDetailOut extends SolicitudOut {
  // F10 p.5: identidad para la hoja de impresión (todo rol con acceso).
  vendedor_nombre: string | null;
  sucursal_nombre: string | null;
  partidas: PartidaOut[];
  opciones: OpcionOut[];
  historial: HistorialOut[];
  comentarios: ComentarioOut[];
  ciclos: CicloOut[];
  tiempos: TiemposOut | null;
  // F10 p.6: pueden ser varios; confirmar exige al menos uno.
  comprobantes: ComprobanteOut[];
  cambios: CambioOut[];
  // F12 p.5: para el rótulo "Fincada por X el DD/MM" (solo área compras).
  fincada_por_nombre?: string | null;
}

// F12 p.4: fila de la bitácora de eliminaciones (solo admin, solo lectura).
export interface EliminacionOut {
  id: number;
  solicitud_id: number;
  folio: string | null;
  cliente: string | null;
  sucursal: string;
  estado_final: string;
  monto_confirmado: string | null;
  vendedor: string;
  comprador: string | null;
  num_partidas: number;
  num_opciones: number;
  num_comprobantes: number;
  motivo: string;
  eliminado_por_id: number;
  eliminado_por: string;
  eliminado_en: string;
}

export interface EliminacionListOut {
  items: EliminacionOut[];
  total: number;
  limit: number;
  offset: number;
}

export interface SolicitudListOut {
  items: SolicitudOut[];
  total: number;
  limit: number;
  offset: number;
}

export interface ClienteOut {
  id: number;
  nombre_normalizado: string;
}

export type FamiliaMotivo = "falta_informacion" | "no_procede";

export interface MotivoOut {
  id: number;
  familia: FamiliaMotivo;
  texto: string;
  activo: boolean;
}

export interface RojaOut {
  solicitud_id: number;
  folio: string | null;
  dias_transcurridos: number;
  horas_habiles: number;
}

export interface MiPanelOut {
  mes: string;
  ciclos_cerrados: number;
  mediana_horas_habiles: number | null;
  pct_banda_esperada: number | null;
  distribucion_bandas: Record<string, number>;
  carga_abierta: number;
  rojas: RojaOut[];
}

export interface NotificacionOut {
  id: number;
  solicitud_id: number | null;
  tipo: string;
  mensaje: string;
  leida: boolean;
  creado_en: string;
}

export interface NotificacionListOut {
  items: NotificacionOut[];
  total: number;
  no_leidas: number;
  limit: number;
  offset: number;
}

// ------------------------------------------------------------- CRM (F8d)

export interface UsuarioOut {
  id: number;
  nombre: string;
  email: string;
  rol: Rol;
  sucursal_id: number | null;
  activo: boolean;
  must_change_password: boolean;
}

export interface UsuarioCreadoOut extends UsuarioOut {
  // SOLO en la respuesta de creación cuando el sistema generó la temporal.
  password_temporal: string | null;
}

export interface UsuarioListOut {
  items: UsuarioOut[];
  total: number;
  limit: number;
  offset: number;
}

export interface ResetPasswordOut {
  password_temporal: string;
}

export interface SucursalOut {
  id: number;
  nombre: string;
  prefijo_folio: string;
  timezone: string;
  activa: boolean;
}

export interface FolioCounterOut {
  sucursal_id: number;
  ultimo: number;
}

export interface TerritorioSucursal {
  sucursal_id: number;
  sucursal_nombre: string;
  titular: boolean;
}

export interface TerritorioComprador {
  comprador_id: number;
  comprador_nombre: string;
  comprador_activo: boolean;
  sucursales: TerritorioSucursal[];
}

export interface TerritoriosOut {
  items: TerritorioComprador[];
}

export interface ReasignacionMasivaOut {
  reasignadas: number;
}

export interface FestivoOut {
  id: number;
  fecha: string;
  descripcion: string | null;
}

// Métricas (los Decimal viajan como string).

export interface SinDesenlaceOut {
  total: number;
  antiguedad_promedio_dias: number | null;
  antiguedad_maxima_dias: number | null;
}

export interface ConversionOut {
  confirmadas: number;
  no_confirmadas: number;
  tasa: number | null;
  sin_desenlace: SinDesenlaceOut;
}

export interface ResumenOut {
  solicitudes_periodo: number;
  ciclos_cerrados: number;
  mediana_horas_habiles: number | null;
  pct_banda_esperada: number | null;
  distribucion_bandas: Record<string, number>;
  rojas_ahora: number;
  embudo: Record<string, number>;
  dinero_confirmado: Record<string, string>;
  dinero_confirmado_desglose: Record<string, string>;
  dinero_referencia: Record<string, string>;
  conversion: ConversionOut;
}

export interface GrupoOut {
  id: number;
  nombre: string;
  volumen: number;
  ciclos_cerrados: number;
  mediana_horas_habiles: number | null;
  pct_banda_esperada: number | null;
  distribucion_bandas: Record<string, number>;
  dinero_confirmado: Record<string, string>;
  carga_abierta: number | null;
  cotizadas: number | null;
  confirmadas: number | null;
  no_confirmadas: number | null;
  sin_desenlace: number | null;
  ratio_confirmacion: number | null;
}

export interface SemanaOut {
  semana: string; // lunes de la semana (YYYY-MM-DD)
  creadas: number;
  confirmadas: number;
  dinero_confirmado_mxn: string;
}

export interface SerieOut {
  semanas: SemanaOut[];
}

export interface MaterialOut {
  valor: string;
  conteo: number;
}

export interface MaterialesOut {
  por_descripcion: MaterialOut[];
  por_codigo_sap: MaterialOut[];
}

export interface NoEncontradosGrupoOut {
  id: number;
  nombre: string;
  total_renglones: number;
  no_encontrados: number;
  pct: number | null;
}

export interface NoEncontradosOut {
  total_renglones: number;
  no_encontrados: number;
  pct: number | null;
  por_comprador: NoEncontradosGrupoOut[];
  top_materiales: MaterialOut[];
}

// F8f/F8g: /metricas/tiempos-etapa — estadística sobre segmentos CERRADOS.
export interface EstadisticaTiempoOut {
  n: number;
  promedio_horas_habiles: number | null;
  mediana_horas_habiles: number | null;
}

export interface TiemposEtapaOut {
  por_estado: Record<string, EstadisticaTiempoOut>;
  compras: EstadisticaTiempoOut;
  ventas: EstadisticaTiempoOut;
}

export interface OpcionFiltroOut {
  id: number;
  nombre: string;
}

export interface FiltrosCatalogoOut {
  sucursales: OpcionFiltroOut[];
  compradores: OpcionFiltroOut[] | null;
  vendedores: OpcionFiltroOut[] | null;
}
