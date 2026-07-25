"""Seed idempotente con los datos reales de arranque (F1 + festivos F2 +
solicitudes demo F3 + cotizaciones demo F4).

Emails provisionales `nombre.apellido@herinox.demo` (primer nombre + último
apellido, sin acentos). Contraseña `Herinox2026!` con must_change_password=true.
"""

import unicodedata
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.catalogos import DiaFestivo, FamiliaMotivo, MotivoRechazo
from app.models.cotizacion import Letra, Moneda
from app.models.solicitud import (
    Estado,
    MotivoNoConfirmada,
    Prioridad,
    Solicitud,
    SolicitudPartida,
)
from app.models.sucursal import CompradorSucursal, FolioCounter, Sucursal
from app.models.usuario import Rol, Usuario

PASSWORD_DEFAULT = "Herinox2026!"

# nombre · prefijo_folio provisional · timezone IANA (contador inicial 0;
# prefijos y contadores los edita el admin con los valores reales).
SUCURSALES = [
    ("Matriz", "MTZ", "America/Chihuahua"),
    ("Norte", "CCN", "America/Chihuahua"),
    ("Manufactura", "MFA", "America/Chihuahua"),
    ("TIK", "TIK", "America/Chihuahua"),
    ("Cd. Juárez", "JRZ", "America/Ciudad_Juarez"),
    ("Hermosillo", "HMO", "America/Hermosillo"),
    ("Obregón", "OBR", "America/Hermosillo"),
    ("Culiacán", "CUL", "America/Mazatlan"),
    ("Mexicali", "MXL", "America/Tijuana"),
    ("Monterrey", "MTY", "America/Monterrey"),
    ("León", "LEO", "America/Mexico_City"),
]

# comprador → sucursales de su territorio (titular en todas).
COMPRADORES = [
    ("Nadia Victor", ["Cd. Juárez", "Hermosillo"]),
    ("Oscar López", ["León"]),
    ("Michelle Monarrez", ["Matriz", "Manufactura"]),
    ("Heidy Ruelas", ["Mexicali", "Culiacán", "Obregón"]),
    ("Itzayana Mata", ["TIK", "Norte"]),
    ("Fabián Flores", ["Monterrey"]),
]

# gerente → su sucursal (siempre de sucursal desde F5).
GERENTES = [
    ("Oscar Loya", "Matriz"),
    ("Eugenio Barreras", "Hermosillo"),
    ("Edgar Ramirez", "Mexicali"),
    ("Veronica Navarro", "Obregón"),
    ("Carlos Saenz", "Cd. Juárez"),
    ("Abraham Maytorena", "Culiacán"),
    ("Fernando Valenzuela", "Norte"),
    ("Alonso Muñoz", "León"),
    ("Yesica Garza", "Monterrey"),
]

VENDEDORES = {
    "Matriz": [
        "Erika Palomares",
        "Jorge Hinojos",
        "Angelica Balderrama Cruz",
        "Abraham Arturo Prado Hernandez",
    ],
    "Hermosillo": [
        "Mirna Salas",
        "Juan Manuel Arvayo",
        "Irais Valenzuela",
        "Enrique Macias Vazquez",
        "Alfredo Herrera",
    ],
    "Mexicali": [
        "Juan Flores",
        "Joaquin Alonso Rivera Quintero",
        "Jaime Rodriguez Quevedo",
        "Luis Enrique Victor Garcia",
    ],
    "Obregón": ["Abraham Cervantes", "Paula Lugo", "Carlos Acosta"],
    "Cd. Juárez": [
        "Maribel Rocha",
        "Brenda Elizabeth Polanco Garcia",
        "Edgar Torres Baylon",
        "Luz Maria Molina Gonzalez",
        "Karina Angelica Carlos Lara",
    ],
    "Culiacán": ["Sergio Medina", "Alejandro Gaxiola"],
    "Norte": ["Alejandro Franco", "Efren Prado", "Alba Avitia"],
    "León": [
        "Moises Nava",
        "Arlette Paloma Resendiz",
        "Enrique Resendiz",
        "Gloria de la Luz Murillo",
    ],
    "Monterrey": ["Marisela Matamoros", "Diana Ortiz", "Octavio Pecina Valdez", "Norma Perez"],
    "TIK": ["Joel Salcido"],
}

# Festivos de ley federal (LFT art. 74) 2026–2027. Administrables: el admin
# agregará los que la empresa sume (p. ej. 12-dic o 24/31-dic si aplica).
DIAS_FESTIVOS = [
    (date(2026, 1, 1), "Año Nuevo"),
    (date(2026, 2, 2), "Día de la Constitución (primer lunes de febrero)"),
    (date(2026, 3, 16), "Natalicio de Benito Juárez (tercer lunes de marzo)"),
    (date(2026, 5, 1), "Día del Trabajo"),
    (date(2026, 9, 16), "Día de la Independencia"),
    (date(2026, 11, 16), "Aniversario de la Revolución (tercer lunes de noviembre)"),
    (date(2026, 12, 25), "Navidad"),
    (date(2027, 1, 1), "Año Nuevo"),
    (date(2027, 2, 1), "Día de la Constitución (primer lunes de febrero)"),
    (date(2027, 3, 15), "Natalicio de Benito Juárez (tercer lunes de marzo)"),
    (date(2027, 5, 1), "Día del Trabajo"),
    (date(2027, 9, 16), "Día de la Independencia"),
    (date(2027, 11, 15), "Aniversario de la Revolución (tercer lunes de noviembre)"),
    (date(2027, 12, 25), "Navidad"),
]

MOTIVOS_RECHAZO = [
    (FamiliaMotivo.FALTA_INFORMACION, "Faltan medidas"),
    (FamiliaMotivo.FALTA_INFORMACION, "Falta tipo de acero"),
    (FamiliaMotivo.FALTA_INFORMACION, "Falta información del material"),
    (FamiliaMotivo.NO_PROCEDE, "Material fuera de línea"),
    (FamiliaMotivo.NO_PROCEDE, "No cumple requisitos de pedido especial"),
]


# Solicitudes demo (F3/F4): (vendedor_email, cliente, prioridad, flujo,
# partidas); la sucursal sale del vendedor. Flujos: borrador | enviada |
# en_proceso | rechazada | reenviada (2 ciclos) | cancelada | cotizada_mxn |
# cotizada_usd | confirmada | no_confirmada. Partidas tomadas del formato
# real: (codigo_sap, cantidad, unidad, tipo_acero, descripcion, medidas).
_Partida = tuple[str | None, str, str, str | None, str, str | None]
SOLICITUDES_DEMO: list[tuple[str, str, Prioridad, str, list[_Partida]]] = [
    (
        "erika.palomares@herinox.demo",
        "DINCO",
        Prioridad.NORMAL,
        "borrador",
        [
            ("205494", "40", "PZA", "A-36", 'ANGULO 2" X 1/4"', "6.10 MTS"),
            ("205712", "24", "PZA", "A-36", 'CANAL CPS 4" ESTANDAR', "6.10 MTS"),
        ],
    ),
    (
        "jorge.hinojos@herinox.demo",
        "CONSTRUCCIONES DEL PARQUE",
        Prioridad.NORMAL,
        "enviada",
        [
            ("208115", "18", "PZA", None, "LAMINA LISA CAL.14", "3X10 PIES"),
            ("SERVICIO", "1", "LOTE", None, "CORTE A MEDIDA DE LAMINA", None),
        ],
    ),
    (
        "angelica.cruz@herinox.demo",
        "DINCO",
        Prioridad.URGENTE,
        "en_proceso",
        [
            ("209301", "6", "PZA", "A-36", 'PLACA 1/2" A-36', "4X10 PIES"),
            ("209015", "12", "PZA", None, "PTR 2X2 CAL.11", "6.10 MTS"),
        ],
    ),
    (
        "erika.palomares@herinox.demo",
        "TALLERES GARCIA",
        Prioridad.NORMAL,
        "rechazada",
        [(None, "874", "PZA", "304", "SOLERA 1/8 X 1", "12.20 MTS")],
    ),
    (
        "abraham.hernandez@herinox.demo",
        "MAQUINADOS INDUSTRIALES CUU",
        Prioridad.URGENTE,
        "reenviada",
        [
            ("210007", "4", "PZA", None, "VIGA IPR 6X4", "40 PIES"),
            ("205494", "16", "PZA", "A-36", 'ANGULO 3" X 1/4"', "6.10 MTS"),
        ],
    ),
    (
        "jorge.hinojos@herinox.demo",
        "DINCO",
        Prioridad.NORMAL,
        "cancelada",
        [("208221", "30", "PZA", None, "LAMINA GALVANIZADA CAL.12", "3X10 PIES")],
    ),
    (
        "alejandro.franco@herinox.demo",
        "CONSTRUCTORA DEL NORTE",
        Prioridad.NORMAL,
        "enviada",
        [
            ("209301", "8", "PZA", "A-36", 'PLACA 3/8" A-36', "4X10 PIES"),
            ("SERVICIO", "1", "LOTE", None, "BISELADO DE PLACA", None),
        ],
    ),
    (
        "efren.prado@herinox.demo",
        "HERRERIA AVILA",
        Prioridad.URGENTE,
        "en_proceso",
        [("209015", "20", "PZA", None, "PTR 1 1/2 X 1 1/2 CAL.14", "6.10 MTS")],
    ),
    (
        "alba.avitia@herinox.demo",
        "INDUSTRIAL PONIENTE",
        Prioridad.NORMAL,
        "borrador",
        [("208115", "10", "PZA", None, "LAMINA ANTIDERRAPANTE CAL.10", "4X10 PIES")],
    ),
    (
        "maribel.rocha@herinox.demo",
        "MAQUILADOS JRZ",
        Prioridad.URGENTE,
        "enviada",
        [
            ("205712", "36", "PZA", "A-36", 'CANAL CPS 6"', "6.10 MTS"),
            ("209301", "2", "PZA", "A-36", 'PLACA 1" A-36', "4X8 PIES"),
        ],
    ),
    (
        "brenda.garcia@herinox.demo",
        "ARNESES FRONTERIZOS",
        Prioridad.NORMAL,
        "en_proceso",
        [("SERVICIO", "1", "LOTE", "304", "CORTE LASER DE LAMINA INOX CAL.16", "60X60 CM")],
    ),
    (
        "edgar.baylon@herinox.demo",
        "DINCO",
        Prioridad.NORMAL,
        "rechazada",
        [(None, "15", "PZA", None, "VIGA IPR 8X4", None)],
    ),
    (
        "mirna.salas@herinox.demo",
        "PAILERIA DEL YAQUI",
        Prioridad.NORMAL,
        "cotizada_mxn",
        [
            (None, "120", "KG", "304", "SOLERA INOX 1/4 X 2", "6.10 MTS"),
            ("209301", "4", "PZA", "A-36", 'PLACA 5/8" A-36', "4X10 PIES"),
        ],
    ),
    (
        "juan.flores@herinox.demo",
        "AEROESPACIAL DE MEXICALI",
        Prioridad.URGENTE,
        "cotizada_usd",
        [(None, "60", "KG", "316L", 'BARRA REDONDA INOX 316L 2"', "3.66 MTS")],
    ),
    (
        "sergio.medina@herinox.demo",
        "EMPACADORA DEL HUMAYA",
        Prioridad.NORMAL,
        "confirmada",
        [
            (None, "250", "KG", "304", "LAMINA INOX CAL.18 ACABADO 2B", "4X10 PIES"),
            ("SERVICIO", "1", "LOTE", None, "CORTE A MEDIDA DE LAMINA", None),
        ],
    ),
    (
        "moises.nava@herinox.demo",
        "CALDERAS DEL BAJIO",
        Prioridad.NORMAL,
        "no_confirmada",
        [("205931", "18", "PZA", "304", 'TUBO INOX 2" CAL.16', "6.10 MTS")],
    ),
]

# Opciones demo (F4): flujo → [(letra, moneda, proveedor, [(precio_unitario,
# tiempo_entrega) por partida, en orden])]. Precios realistas de acero por
# KG/PZA. La vigencia es fija para que el seed sea determinista.
VIGENCIA_DEMO = date(2026, 8, 31)
_Opcion = tuple[Letra, Moneda, str | None, list[tuple[str, str]]]
OPCIONES_DEMO: dict[str, list[_Opcion]] = {
    "cotizada_mxn": [
        (
            Letra.A,
            Moneda.MXN,
            "Aceros y Metales del Norte",
            [("98.50", "5 días hábiles"), ("18450.00", "1 semana")],
        ),
        (
            Letra.B,
            Moneda.MXN,
            "Inoxidables GV",
            [("94.80", "2 semanas"), ("17980.00", "2 semanas")],
        ),
    ],
    "cotizada_usd": [(Letra.A, Moneda.USD, "Rolled Alloys", [("5.85", "3 semanas")])],
    "confirmada": [
        (
            Letra.A,
            Moneda.MXN,
            "Aceros Camesa",
            [("112.00", "1 semana"), ("1500.00", "1 semana")],
        ),
        (
            Letra.B,
            Moneda.MXN,
            "Metales de Sinaloa",
            [("108.50", "10 días hábiles"), ("1200.00", "10 días hábiles")],
        ),
    ],
    "no_confirmada": [(Letra.A, Moneda.MXN, None, [("1450.00", "4 semanas")])],
}


def _sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def email_provisional(nombre: str) -> str:
    """`nombre.apellido@herinox.demo`: primer nombre + último apellido."""
    partes = _sin_acentos(nombre).lower().split()
    return f"{partes[0]}.{partes[-1]}@herinox.demo"


def _demo_solicitudes(db: Session) -> int:
    """Crea las solicitudes demo usando los services y transiciones REALES.
    Guard de idempotencia: solo corre si no existe ninguna solicitud."""
    if db.scalar(select(func.count()).select_from(Solicitud)):
        return 0
    # Imports locales para evitar acoplar el seed base a los módulos de F3/F4.
    from app.modules.cotizaciones.schemas import OpcionIn, RenglonIn
    from app.modules.cotizaciones.service import (
        cotizar,
        guardar_opcion,
        no_confirmar,
        seleccionar,
    )
    from app.modules.solicitudes.schemas import PartidaIn, SolicitudCreate
    from app.modules.solicitudes.service import crear
    from app.modules.solicitudes.state_machine import ejecutar_transicion

    def _usuario(email: str) -> Usuario:
        return db.execute(select(Usuario).where(Usuario.email == email)).scalar_one()

    def _motivo(texto: str) -> MotivoRechazo:
        return db.execute(select(MotivoRechazo).where(MotivoRechazo.texto == texto)).scalar_one()

    motivo_medidas = _motivo("Faltan medidas")
    motivo_info = _motivo("Falta información del material")

    for email, cliente, prioridad, flujo, partidas in SOLICITUDES_DEMO:
        vendedor = _usuario(email)
        data = SolicitudCreate(
            cliente=cliente,
            prioridad=prioridad,
            notas=None,
            partidas=[
                PartidaIn(
                    codigo_sap=codigo,
                    cantidad=Decimal(cantidad),
                    unidad=unidad,
                    tipo_acero=tipo,
                    descripcion=descripcion,
                    medidas=medidas,
                )
                for codigo, cantidad, unidad, tipo, descripcion, medidas in partidas
            ],
        )
        solicitud = crear(db, data, vendedor)
        if flujo == "borrador":
            continue
        ejecutar_transicion(db, solicitud.id, Estado.ENVIADA, vendedor)
        if flujo in ("en_proceso", "rechazada", "reenviada"):
            assert solicitud.comprador_id is not None
            comprador = db.get(Usuario, solicitud.comprador_id)
            assert comprador is not None
            ejecutar_transicion(db, solicitud.id, Estado.EN_PROCESO, comprador)
            if flujo in ("rechazada", "reenviada"):
                motivo = motivo_medidas if flujo == "reenviada" else motivo_info
                ejecutar_transicion(
                    db,
                    solicitud.id,
                    Estado.RECHAZADA,
                    comprador,
                    motivo_id=motivo.id,
                    comentario="Favor de completar la información del material",
                )
            if flujo == "reenviada":
                ejecutar_transicion(db, solicitud.id, Estado.ENVIADA, vendedor)
        elif flujo == "cancelada":
            ejecutar_transicion(db, solicitud.id, Estado.CANCELADA, vendedor)
        elif flujo in OPCIONES_DEMO:
            assert solicitud.comprador_id is not None
            comprador = db.get(Usuario, solicitud.comprador_id)
            assert comprador is not None
            partida_ids = db.scalars(
                select(SolicitudPartida.id)
                .where(SolicitudPartida.solicitud_id == solicitud.id)
                .order_by(SolicitudPartida.num_partida)
            ).all()
            # El primer guardar_opcion sobre ENVIADA ejecuta la auto-toma real.
            for letra, moneda, proveedor, renglones in OPCIONES_DEMO[flujo]:
                guardar_opcion(
                    db,
                    solicitud.id,
                    letra,
                    OpcionIn(
                        moneda=moneda,
                        vigencia=VIGENCIA_DEMO,
                        proveedor=proveedor,
                        renglones=[
                            RenglonIn(
                                partida_id=pid,
                                precio_unitario=Decimal(precio),
                                tiempo_entrega=tiempo,
                            )
                            for pid, (precio, tiempo) in zip(partida_ids, renglones, strict=True)
                        ],
                    ),
                    comprador,
                )
            cotizar(db, solicitud.id, comprador)
            if flujo == "confirmada":
                seleccionar(db, solicitud.id, Letra.B, vendedor)
            elif flujo == "no_confirmada":
                no_confirmar(
                    db,
                    solicitud.id,
                    MotivoNoConfirmada.PRECIO,
                    "El cliente consiguió mejor precio con otro proveedor",
                    vendedor,
                )
    return len(SOLICITUDES_DEMO)


def _get_or_create_usuario(
    db: Session,
    nombre: str,
    email: str,
    rol: Rol,
    password_hash: str,
    sucursal_id: int | None = None,
) -> Usuario:
    user = db.scalar(select(Usuario).where(Usuario.email == email))
    if user is None:
        user = Usuario(
            nombre=nombre,
            email=email,
            password_hash=password_hash,
            rol=rol,
            sucursal_id=sucursal_id,
            must_change_password=True,
        )
        db.add(user)
        db.flush()
    return user


def run(db: Session) -> dict[str, int]:
    """Puebla los datos de arranque. Correrlo dos veces no duplica nada."""
    password_hash = hash_password(PASSWORD_DEFAULT)

    sucursales: dict[str, Sucursal] = {}
    for nombre, prefijo, tz in SUCURSALES:
        sucursal = db.scalar(select(Sucursal).where(Sucursal.nombre == nombre))
        if sucursal is None:
            sucursal = Sucursal(nombre=nombre, prefijo_folio=prefijo, timezone=tz)
            db.add(sucursal)
            db.flush()
        if db.get(FolioCounter, sucursal.id) is None:
            db.add(FolioCounter(sucursal_id=sucursal.id, ultimo=0))
        sucursales[nombre] = sucursal

    _get_or_create_usuario(db, "Edgar", "edgar@herinox.demo", Rol.ADMIN, password_hash)

    for nombre, territorio in COMPRADORES:
        comprador = _get_or_create_usuario(
            db, nombre, email_provisional(nombre), Rol.COMPRADOR, password_hash
        )
        for nombre_sucursal in territorio:
            sucursal = sucursales[nombre_sucursal]
            existe = db.scalar(
                select(CompradorSucursal).where(
                    CompradorSucursal.comprador_id == comprador.id,
                    CompradorSucursal.sucursal_id == sucursal.id,
                )
            )
            if existe is None:
                db.add(
                    CompradorSucursal(
                        comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True
                    )
                )

    for nombre, nombre_sucursal in GERENTES:
        _get_or_create_usuario(
            db,
            nombre,
            email_provisional(nombre),
            Rol.GERENTE,
            password_hash,
            sucursal_id=sucursales[nombre_sucursal].id,
        )

    for nombre_sucursal, nombres in VENDEDORES.items():
        for nombre in nombres:
            _get_or_create_usuario(
                db,
                nombre,
                email_provisional(nombre),
                Rol.VENDEDOR,
                password_hash,
                sucursal_id=sucursales[nombre_sucursal].id,
            )

    for familia, texto in MOTIVOS_RECHAZO:
        motivo = db.scalar(
            select(MotivoRechazo).where(
                MotivoRechazo.familia == familia, MotivoRechazo.texto == texto
            )
        )
        if motivo is None:
            db.add(MotivoRechazo(familia=familia, texto=texto))

    for fecha, descripcion in DIAS_FESTIVOS:
        festivo = db.scalar(select(DiaFestivo).where(DiaFestivo.fecha == fecha))
        if festivo is None:
            db.add(DiaFestivo(fecha=fecha, descripcion=descripcion))

    db.commit()

    solicitudes_demo = _demo_solicitudes(db)

    return {
        "sucursales": len(SUCURSALES),
        "compradores": len(COMPRADORES),
        "gerentes": len(GERENTES),
        "vendedores": sum(len(v) for v in VENDEDORES.values()),
        "admins": 1,
        "motivos_rechazo": len(MOTIVOS_RECHAZO),
        "dias_festivos": len(DIAS_FESTIVOS),
        "solicitudes_demo": solicitudes_demo,
    }
