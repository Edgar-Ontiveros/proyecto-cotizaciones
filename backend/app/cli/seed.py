"""Seed idempotente con los datos reales de arranque (F1 + festivos de F2).

Emails provisionales `nombre.apellido@herinox.demo` (primer nombre + último
apellido, sin acentos). Contraseña `Herinox2026!` con must_change_password=true.
Sin solicitudes demo (F3).
"""

import unicodedata
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.catalogos import DiaFestivo, FamiliaMotivo, MotivoRechazo
from app.models.sucursal import CompradorSucursal, FolioCounter, Sucursal
from app.models.usuario import AlcanceGerente, Rol, Usuario

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

# gerente (alcance sucursal) → su sucursal.
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


def _sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def email_provisional(nombre: str) -> str:
    """`nombre.apellido@herinox.demo`: primer nombre + último apellido."""
    partes = _sin_acentos(nombre).lower().split()
    return f"{partes[0]}.{partes[-1]}@herinox.demo"


def _get_or_create_usuario(
    db: Session,
    nombre: str,
    email: str,
    rol: Rol,
    password_hash: str,
    sucursal_id: int | None = None,
    alcance_gerente: AlcanceGerente | None = None,
) -> Usuario:
    user = db.scalar(select(Usuario).where(Usuario.email == email))
    if user is None:
        user = Usuario(
            nombre=nombre,
            email=email,
            password_hash=password_hash,
            rol=rol,
            sucursal_id=sucursal_id,
            alcance_gerente=alcance_gerente,
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
            alcance_gerente=AlcanceGerente.SUCURSAL,
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

    return {
        "sucursales": len(SUCURSALES),
        "compradores": len(COMPRADORES),
        "gerentes": len(GERENTES),
        "vendedores": sum(len(v) for v in VENDEDORES.values()),
        "admins": 1,
        "motivos_rechazo": len(MOTIVOS_RECHAZO),
        "dias_festivos": len(DIAS_FESTIVOS),
    }
