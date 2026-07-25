# Especificación Cerrada del Proyecto — Sistema de Cotizaciones Herinox
## Lógica de negocio + Stack técnico integrados — v1.1

**Fuentes:** cuestionario respondido en junta (RESPUESTA.docx) + requerimientos de Edgar + formato real de solicitud (CCN3036_DINCO.xlsx) + plantilla comercial y territorios + `stack_definitivo_e_infraestructura_aws` v1.1.
**Dueño del proceso:** Francisco Muñoz. **Razón social:** Comercializadora de Inoxidables Hernández S.A. de C.V.
**Cambios v1.0 → v1.1:** campos de solicitud tomados del formato real (aparece `codigo_sap` opcional, desaparece `acabado`); folio real `{PREFIJO}-{CONSECUTIVO}` sin año; **tiempo de entrega por partida** (columna del formato) en lugar de por opción.
**Pendientes de entrada (no bloquean):** prefijos de folio y consecutivo actual de cada sucursal; calendario de festivos; columnas del export a Excel; correos reales de usuarios.

---

## 1. Qué es el sistema (una frase)

Plataforma interna donde ~35 vendedores solicitan cotizaciones de pedido especial a 6 compradores (≈250 por semana, 11 sucursales), con medición objetiva de tiempos de respuesta —hoy compras es "juez y parte" con un Excel manual— y análisis por dinero: cuánto se cotiza y cuánto se confirma, por sucursal, comprador, vendedor y cliente.

## 2. Roles y vistas (3 interfaces, 4 roles — confirmado por Edgar)

| Rol | Vista que usa | Alcance de datos | Puede |
|---|---|---|---|
| **Vendedor** | Vista Vendedor | Solo SUS solicitudes | Crear, editar (§4.3), enviar, reenviar rechazadas, seleccionar opción, marcar no confirmada, cancelar |
| **Comprador** | Vista Comprador | Solo las asignadas a él | Tomar, capturar opciones, marcar cotizada, rechazar con motivo, corregir cotizadas |
| **Administrador** (Gerencia de Compras administra el día a día — resp. 51; también los directores) | Vista CRM/Admin | Todo | Todo: CUALQUIER transición o edición sobre cualquier solicitud + administración completa (§6) |
| **Gerente** (siempre de SU sucursal — gerente de ventas, resp. 45–46; el alcance "global" desapareció en F5: los directores se dan de alta como admin) | Vista CRM/Admin acotada a su sucursal | Su sucursal, sin BORRADOR ajenos | Acciones de LADO VENTAS sobre solicitudes de su sucursal: reenviar, cancelar, editar (PATCH), seleccionar/confirmar, no-confirmar y comentar. NO toma/captura/cotiza/rechaza (compras) ni administra. No ve el campo proveedor |

**Cuentas: SOLO el rol admin crea, edita, activa y desactiva usuarios de TODOS los niveles — vendedores, compradores, gerentes y otros administradores** (requerimiento de Edgar; alta rotación en ventas y compras). Sin registro público. Un admin no puede desactivarse a sí mismo.

## 3. Estados y ciclo de vida (definitivo)

```
BORRADOR ──enviar──▶ ENVIADA ──comprador abre──▶ EN_PROCESO ──captura completa──▶ COTIZADA ──vendedor selecciona opción──▶ CONFIRMADA ✔
                        │                            │                                │
                        │                            └──rechazar con motivo──▶ RECHAZADA ──vendedor corrige y reenvía──▶ ENVIADA (nuevo ciclo)
                        └────────────── CANCELADA ✖ (vendedor, desde cualquier estado no terminal)
                                                                                  COTIZADA ──vendedor marca──▶ NO_CONFIRMADA ✖ (con motivo)
```

| Estado | Lo pone | Significado |
|---|---|---|
| BORRADOR | Vendedor | Guardada a medias; solo él la ve (resp. 10). |
| ENVIADA | Sistema (al enviar/reenviar) | Asigna comprador titular de la sucursal, genera folio (si no existía), **arranca el reloj**. |
| EN_PROCESO | Sistema, cuando el comprador abre/empieza a capturar (resp. 18) | También es el estado de una respuesta parcial (resp. 20). |
| COTIZADA | Sistema, cuando el comprador marca captura completa (resp. 18) | **Detiene el reloj.** Publica las opciones al vendedor. |
| CONFIRMADA | Sistema, cuando el vendedor selecciona una opción (= hacer el pedido, resp. 36) | Terminal exitoso. Fija opción ganadora y **monto oficial**. |
| RECHAZADA | Comprador, con motivo de catálogo (resp. 17, 31) | **Detiene el reloj.** El vendedor puede corregir y **reenviar** → ENVIADA, ciclo nuevo (resp. 31). |
| CANCELADA | Vendedor | Error de envío o cliente desistió (resp. 17). Terminal. |
| NO_CONFIRMADA | Vendedor, con motivo (precio / tiempo de entrega / cliente desistió / otro) | Terminal. Decisión derivada (§11): da el "porqué no se cierran" (resp. 4, 57) sin el estado "Cerrada" que la junta rechazó (resp. 19). Admin puede revertirla a COTIZADA. |

**Motivos de rechazo en dos familias** (administrables): *falta_informacion* (se espera reenvío) y *no_procede* (resp. 17). Los reportes las distinguen.
**Reglas:** reenviar solo aplica a RECHAZADA (mismo folio, historia conservada). Una COTIZADA no se reabre: ajustes de precio/cantidad los corrige el comprador sobre las opciones y quedan en historial (resp. 21). Toda transición valida matriz + rol, en transacción con `SELECT ... FOR UPDATE`.

## 4. Reglas de negocio

### 4.1 La solicitud — campos EXACTOS del formato real (CCN3036_DINCO.xlsx)

**Encabezado** (el sistema los pone solo): Folio · Fecha · Cliente (captura §4.4) · Vendedor · Sucursal · + Prioridad (§4.6) y Notas del sistema.

**Partidas** (ilimitadas — resp. 8), columnas del formato:

| Columna del formato | Campo | Obligatorio |
|---|---|---|
| No. | `num_partida` (automático) | — |
| Codigo SAP | `codigo_sap` (texto; en el formato usan "SERVICIO" cuando no hay código) | No |
| Cantidad | `cantidad` | **Sí** |
| Unidad de medida | `unidad` (KG, PZA, …) | **Sí** |
| Tipo de acero | `tipo_acero` | No (viene vacío en el formato real; suele ir en la descripción) |
| Descripción | `descripcion` | **Sí** |
| Medidas | `medidas` (texto libre: "874 PZA A 12.20 MTS") | No — *candidato a obligatorio: es lo que más falta hoy (resp. 9); decide Francisco* |

**No existe columna "Acabado"** en el formato real (la junta la mencionó, el formato no la trae; se escribe dentro de la descripción). **Las columnas "Precio" y "Tiempo de entrega" del formato son la RESPUESTA de compras** → viven en las opciones (§4.8), no en la solicitud.
**Sin archivos adjuntos** en todo el sistema (resp. 38 + Edgar).

### 4.2 Folios — convención real observada
`{PREFIJO_SUCURSAL}-{CONSECUTIVO}` **sin año** (observado: `CCN-3036`, sucursal Norte), consecutivo corrido por sucursal. En el asunto/nombre actual anexan el cliente (`CCN-3036 DINCO`); el sistema muestra folio y cliente juntos en listados. El **prefijo y el contador inicial de cada sucursal son editables por el admin** (para continuar la numeración actual sin saltos). Generación race-safe: `folio_counters(sucursal_id, ultimo)` con `FOR UPDATE` en la transacción del envío. *Pendiente: lista real de prefijos y número actual por sucursal.*

### 4.3 Edición del vendedor
Editable en ENVIADA y EN_PROCESO — mientras el comprador no haya respondido (resp. 11). Toda edición notifica al comprador y queda en historial. Cambio de cliente o proyecto → nueva solicitud (resp. 11). De COTIZADA en adelante, el vendedor no edita.

### 4.4 Clientes y materiales (sin SAP)
Sin acceso a la BD de SAP (resp. 13): **catálogo interno de clientes con alta al vuelo** — el vendedor teclea, el sistema autocompleta contra los ya usados y crea el nuevo si no existe (normalizado: mayúsculas, espacios colapsados). Necesario para el KPI "por cliente" (resp. 47). Materiales: texto libre + `codigo_sap` opcional cuando lo conocen (§4.1); análisis de "artículos frecuentes" (resp. 57) sobre descripción/código, normalización fina en v2.

### 4.5 Asignación y territorios (datos reales cargados)
- Territorios comprador↔sucursal administrables; **titular único por sucursal**; asignación automática al enviar (resp. 22–24).
- Mapa real: Nadia Victor → Cd. Juárez, Hermosillo · Oscar López → León · Michelle Monarrez → Matriz, Manufactura · Heidy Ruelas → Mexicali, Culiacán, Obregón · Itzayana Mata → TIK, Norte · Fabián Flores → Monterrey.
- 11 sucursales: Matriz, Norte, Manufactura, TIK (no estaba en la junta — zona horaria asumida Chihuahua, confirmar), Cd. Juárez, Hermosillo, Obregón, Culiacán, Mexicali, Monterrey, León.
- Ausencias/vacaciones y bajas: **el admin reasigna** — titularidad de sucursal (para nuevas) y reasignación individual o masiva de solicitudes abiertas (por comprador o por vendedor) (resp. 25–26, 52). Nunca cuentas compartidas.
- Vendedores y gerentes pertenecen a una sucursal; el admin los da de alta, de baja y los mueve (requerimiento de Edgar: altamente modificable).

### 4.6 Prioridad
`NORMAL | URGENTE`, la pone el vendedor (resp. 30). No afecta relojes: ordena la cola del comprador y es visible en dashboards; el CRM muestra % de urgentes por vendedor como antídoto al abuso.

### 4.7 Medición de tiempos: bandas en horas hábiles
Sin tiempos máximos (resp. 28) pero con evaluación (resp. 49) y alerta al 3er día (resp. 33) → **bandas** calibradas a la escala real (resp. 3):

| Banda | Respuesta (horas hábiles) | Semáforo |
|---|---|---|
| Esperada | ≤ 1 día hábil | Verde (hoy 97%) |
| Normal | ≤ 2 días hábiles | Amarillo |
| Lenta | > 2 días hábiles | Rojo + alerta a administración al iniciar el 3er día hábil |

- Reloj por ciclo: ENVIADA (o reenvío) → COTIZADA | RECHAZADA (resp. 32). Tiempo en RECHAZADA no cuenta (resp. 31); el reenvío inicia ciclo nuevo.
- Horario hábil: L–V 08:00–18:00, sábado 08:00–13:00, menos `dias_festivos` administrables (resp. 29).
- El reloj corre en la **zona horaria de la sucursal** — con Juárez, Hermosillo, Mexicali, Culiacán, Monterrey y León hay 5+ zonas IANA. Toda la aritmética vive en `core/horario_habil.py` (el módulo más testeado del sistema).
- KPIs de comprador: mediana de horas hábiles, % en banda esperada, distribución; reglas conocidas por los compradores antes de arrancar (resp. 49).

### 4.8 Opciones de cotización A–E y selección
- De **1 a 5 opciones** por solicitud, letras **A–E** (resp. 36 pedía mínimo 2 posibles; Edgar fija máximo 5).
- **Por opción:** moneda (MXN|USD, una por opción — resp. 16), vigencia de la cotización, comentarios (opcional), proveedor (opcional, **visible SOLO para comprador y admin** — resp. 35; nunca vendedor ni gerente).
- **Por partida dentro de cada opción** (columnas del formato real): `precio_unitario` y `tiempo_entrega` → `importe = cantidad × precio_unitario` → `total` de la opción.
- Obligatorios al completar: por opción moneda y vigencia; por partida precio y tiempo de entrega (resp. 34 + formato).
- **Respuesta parcial** (resp. 20): guardar avances deja EN_PROCESO; "marcar cotización completa" exige toda opción capturada con sus obligatorios en todas las partidas → COTIZADA.
- **Selección:** el vendedor compara A–E lado a lado y elige UNA al confirmar el pedido → CONFIRMADA; la elegida "se queda", las demás en historial.

### 4.9 Dinero (requisito prioritario)
- **Monto confirmado** = total de la opción seleccionada (dato duro, resp. 36). **Monto de referencia** de una COTIZADA sin confirmar = total de la **opción A** (decisión derivada §11).
- Agregados **separados por moneda** (MXN y USD) en v1; conversión con TC configurable en v2.
- Todo dashboard de dinero filtra por sucursal, comprador, vendedor, cliente, fecha, estado y moneda. Dinero en `Numeric(14,2)`, nunca float.

### 4.10 Comentarios, notificaciones, retención
- Comentarios visibles para todos los involucrados (resp. 40).
- Notificaciones in-app v1 (resp. 41): solicitud asignada / edición de una activa → comprador; cotizada o rechazada → vendedor; banda amarilla → comprador; banda roja → comprador + administración.
- Correo v1.5 (SES): resumen diario (compradores/vendedores) + semanal (dirección) (resp. 42). Sin correo por evento.
- Retención: para siempre (resp. 56). ~13,000 solicitudes/año — trivial.

## 5. Modelo de datos final

- **usuarios** — nombre, email único (CI), hash, rol (`vendedor|comprador|admin|gerente`), `sucursal_id` (obligatoria para vendedor y gerente — el gerente es siempre de sucursal desde F5), activo, must_change_password.
- **sucursales** — nombre, `prefijo_folio` único editable, `contador` editable vía folio_counters, `timezone` IANA, activa.
- **comprador_sucursal** — comprador, sucursal, `titular` (índice único parcial: un titular por sucursal).
- **clientes** — nombre_normalizado único, creado_por, creado_en.
- **solicitudes** — folio, vendedor, comprador, sucursal, cliente, estado, prioridad, notas, `opcion_seleccionada_id`, `monto_confirmado` + `moneda_confirmada`, `motivo_no_confirmada`, hitos (creado/enviado/cotizado/confirmado_en).
- **solicitud_partidas** — num_partida, `codigo_sap` (nullable), cantidad `Numeric(14,3)`, unidad, `tipo_acero` (nullable), descripcion, medidas (nullable).
- **cotizacion_opciones** — solicitud, letra A–E (única por solicitud), moneda, vigencia, comentarios, proveedor (restringido), total, completa.
- **opcion_partidas** — opción, partida, `precio_unitario`, `importe`, `tiempo_entrega`.
- **historial_estados** — solicitud, de, a, usuario, motivo/comentario, timestamp (base de toda la medición).
- **comentarios** — solicitud, usuario, texto, creado_en (visibles para todos los involucrados, §4.10).
- **motivos_rechazo** (familia), **dias_festivos**, **notificaciones**, **refresh_tokens**, **folio_counters** (por sucursal, sin año, inicial configurable).

Estructurales v1.1 intactas: historial como eventos, bandas siempre calculadas, transiciones con bloqueo, UTC + `timezone` por sucursal, naming_convention, Alembic.

## 6. Las tres vistas

**Vendedor** — Sus solicitudes: folio, cliente, fecha, estado, banda, comprador, prioridad, monto. Filtros: fecha, cliente, estado. Captura calcada al formato: encabezado automático + tabla de partidas (No., Código SAP, Cantidad, Unidad, Tipo de acero, Descripción, Medidas) con filas dinámicas. Acciones: enviar, editar, cancelar, corregir-y-reenviar rechazadas (viendo motivo), **comparador A–E con "Confirmar pedido con esta opción"**, marcar no confirmada.

**Comprador** — Su cola (solo la suya — resp. 44): urgentes primero, luego antigüedad de ciclo, semáforo visible. Captura por opción (A–E): precio y tiempo de entrega por partida, moneda y vigencia por opción, totales automáticos, guardar parcial, "marcar completa", rechazar con motivo. Panel personal: su mediana, su % esperada, su distribución (los números con los que lo evalúan — resp. 49).

**CRM / Admin** (admin con gestión; gerentes acotados a su sucursal, con las acciones de lado ventas de §2) —
- *Dashboard:* solicitudes del periodo, % banda esperada, mediana, distribución, rojas AHORA, carga abierta por comprador, embudo por estado, **dinero cotizado (ref.) y confirmado por moneda**, conversión COTIZADA→CONFIRMADA, comparativos por sucursal/comprador/vendedor/**cliente** (resp. 47), clientes que cotizan mucho y confirman poco, materiales frecuentes (resp. 57).
- *Tabla global:* filtros sucursal, comprador, vendedor, cliente, fecha, estado, prioridad, moneda, banda; **export a Excel** de lo filtrado (columnas: pendiente resp. 48; default todas las visibles).
- *Administración:* usuarios (**alta/baja/edición de vendedores, compradores, gerentes y admins — solo admin**), sucursales (alta/baja, prefijo de folio, contador, zona horaria), territorios y titularidad, reasignación individual/masiva (por comprador o vendedor), motivos de rechazo, festivos, revocar sesiones.

## 7. Alertas — mecánica
El contenedor `scheduler` evalúa cada 15 min los ciclos abiertos contra el calendario hábil de su sucursal; genera notificación de banda amarilla (comprador) y roja (comprador + administración), deduplicadas por solicitud y banda. Digests por correo en v1.5.

## 8. Piloto y éxito
Piloto: **Matriz con 1 comprador (Michelle Monarrez)**, 2 semanas (resp. 55). Canal único: solo lo del sistema cuenta para evaluación; solo dirección puede pedir por fuera (resp. 54). Éxito a 3 meses (resp. 57): 99% por el sistema, tiempos reales conocidos, clientes que cotizan sin confirmar identificados, valor $ por sucursal, artículos frecuentes → candidatos a stock.

## 9. Dimensionamiento
250/semana ≈ 13k solicitudes/año; con ~20 partidas y ~2 opciones promedio ≈ 500k–1M filas/año en `opcion_partidas` — sin problema para t3.small + db.t4g.micro. Índices: `solicitudes(comprador_id, estado)`, `(sucursal_id, creado_en)`, `(vendedor_id, estado)`, `(cliente_id)`; historial por solicitud.

## 10. Registro de cambios al stack (acumulado)
- v1.0: fuera adjuntos/S3-CORS (S3 solo backups); nuevo `horario_habil` multi-TZ; entidades opciones/territorios/motivos/festivos; 4 roles; digests.
- **v1.1 (formato real):** `codigo_sap` opcional en partidas; sin campo `acabado`; `tiempo_entrega` por partida (en `opcion_partidas`); folio `{PREFIJO}-{CONSECUTIVO}` sin año con prefijo y contador editables.
- Sin cambios: FastAPI/React 19/Mantine 9/PostgreSQL 17, monolito modular sync, JWT, EC2 t3.small + RDS db.t4g.micro us-east-1, SSM, OIDC, observabilidad.

## 11. Decisiones derivadas — validar con Francisco
1. Monto de referencia pre-confirmación = opción A. 2. NO_CONFIRMADA opcional con motivo. 3. Motivos de rechazo en dos familias. 4. Titular único por sucursal. 5. Prioridad NORMAL/URGENTE sin efecto en relojes. 6. Banda esperada = ≤1 día hábil. 7. Reloj en TZ de la sucursal. **8. (v1.1) "Medidas" opcional u obligatoria — el formato la deja libre, pero es lo que más falta (resp. 9). 9. (v1.1) TIK: ubicación/zona horaria. 10. (v1.1) Manufactura sin personal en plantilla: ¿cotiza vía Matriz?**

## 12. Construcción con Claude Code
Edgar implementa en terminal. En el repo viven SOLO dos archivos de contexto: `CLAUDE.md` (raíz) y `docs/especificacion.md` (este documento). **Los prompts de fase NO van al repo: se pegan directo en la terminal**, uno por sesión, con validación de Edgar entre fases. Fases: F1 fundación (monorepo, modelos, auth, usuarios, seed real) · F2 horario hábil multi-TZ · F3 solicitudes + estados + historial · F4 opciones A–E + selección + montos · F5 territorios + administración · F6 métricas + CRM + export · F7 notificaciones + scheduler · F8 frontend (3 vistas) · F9 deploy AWS + piloto.
