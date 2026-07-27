// Tipos espejo de los schemas Pydantic del backend (fuente de verdad).
// Los Decimal del backend viajan como string en JSON.

export type Rol = "vendedor" | "comprador" | "gerente" | "admin";

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
  cliente_id: number | null;
  cliente_nombre: string | null;
  vendedor_id: number;
  comprador_id: number | null;
  sucursal_id: number;
  notas: string | null;
  opcion_seleccionada_id: number | null;
  monto_confirmado: string | null;
  moneda_confirmada: Moneda | null;
  motivo_no_confirmada: string | null;
  creado_en: string;
  enviado_en: string | null;
  cotizado_en: string | null;
  confirmado_en: string | null;
  banda: Banda | null;
  dias_transcurridos: number | null;
  horas_habiles: number | null;
  // Monto de REFERENCIA (F8b): total/moneda de la opción A, solo COTIZADA.
  monto_referencia: string | null;
  moneda_referencia: Moneda | null;
}

export type Unidad = "PZ" | "KG" | "TON" | "MTS" | "M2";

export interface RenglonOut {
  id: number;
  partida_id: number;
  num_partida: number;
  // Cantidad/unidad COTIZADAS (pueden diferir de lo pedido).
  cantidad: string;
  unidad: Unidad;
  precio_unitario: string | null;
  importe: string | null;
  tiempo_entrega: string | null;
  no_encontrada: boolean;
  es_alternativa: boolean;
  alternativa_descripcion: string | null;
  // SOLO llega para comprador/admin; el backend la excluye para vendedor y
  // gerente (jamás inventarla en UI).
  proveedor?: string | null;
}

export interface OpcionOut {
  id: number;
  letra: Letra;
  moneda: Moneda | null;
  vigencia: string | null;
  comentarios: string | null;
  total: string;
  completa: boolean;
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

export interface SolicitudDetailOut extends SolicitudOut {
  partidas: PartidaOut[];
  opciones: OpcionOut[];
  historial: HistorialOut[];
  comentarios: ComentarioOut[];
  ciclos: CicloOut[];
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
