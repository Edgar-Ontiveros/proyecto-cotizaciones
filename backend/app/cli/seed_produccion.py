"""Seed de PRODUCCIÓN (mini-fase v2) — separado del seed demo, que no se toca.

Puebla el arranque real COMPLETO: las 11 sucursales (prefijos editables desde
el CRM) con contadores de folio EN CERO, festivos de ley 2026–27, catálogo de
motivos de rechazo y la PLANTILLA REAL: los 4 directivos + 9 gerentes de
sucursal + 35 vendedores + 6 compradores con sus titularidades reales
(fuente: el roster del seed demo, que es la plantilla real). CERO cuentas
demo bajo ninguna condición y CERO solicitudes.

Correos por regla, dominio @herinox.com.mx: primera letra del nombre +
PRIMER apellido, minúsculas, sin acentos y ñ→n (Maribel Rocha →
mrocha@herinox.com.mx). En colisión, el segundo usa las DOS primeras letras
del nombre; una doble colisión detiene el seed (se reporta, no se inventa).

Contraseña temporal FIJA Herinox2026! con cambio forzado al primer uso.
Idempotente por email: NUNCA pisa una contraseña ya cambiada. Los gerentes
corrigen altas/bajas/cambios de su gente desde el CRM.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cli.seed import (
    COMPRADORES,
    DIAS_FESTIVOS,
    GERENTES,
    MOTIVOS_RECHAZO,
    PASSWORD_DEFAULT,
    SUCURSALES,
    VENDEDORES,
    _sin_acentos,
)
from app.core.security import hash_password
from app.models.catalogos import DiaFestivo, MotivoRechazo
from app.models.sucursal import CompradorSucursal, FolioCounter, Sucursal
from app.models.usuario import Rol, Usuario

USUARIOS_REALES = [
    ("Edgar Ontiveros", "eontiveros@herinox.com.mx", Rol.ADMIN),
    ("Francisco Muñoz", "fmunoz@herinox.com.mx", Rol.ADMIN),
    ("Francisco Perez", "fperez@herinox.com.mx", Rol.DIRECTOR_VENTAS),
    ("Luis Jimenez", "ljimenez@herinox.com.mx", Rol.GERENTE_COMPRAS),
]

# Nombres con más de dos palabras: el PRIMER apellido no se puede deducir por
# posición (¿segundo nombre o primer apellido?). Se fija aquí como dato; un
# nombre largo SIN entrada truena el seed (se pregunta, no se inventa).
PRIMER_APELLIDO = {
    "Angelica Balderrama Cruz": "Balderrama",
    "Abraham Arturo Prado Hernandez": "Prado",
    "Juan Manuel Arvayo": "Arvayo",
    "Enrique Macias Vazquez": "Macias",
    "Joaquin Alonso Rivera Quintero": "Rivera",
    "Jaime Rodriguez Quevedo": "Rodriguez",
    "Luis Enrique Victor Garcia": "Victor",
    "Brenda Elizabeth Polanco Garcia": "Polanco",
    "Edgar Torres Baylon": "Torres",
    "Luz Maria Molina Gonzalez": "Molina",
    "Karina Angelica Carlos Lara": "Carlos",
    "Gloria de la Luz Murillo": "Murillo",
    "Arlette Paloma Resendiz": "Resendiz",
    "Octavio Pecina Valdez": "Pecina",
}


def _normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y ñ→n (NFD quita la virgulilla)."""
    return _sin_acentos(texto).lower()


def _partes_de(nombre_completo: str) -> tuple[str, str]:
    """(primer nombre, primer apellido). Dos palabras = nombre + apellido;
    más palabras exigen entrada en PRIMER_APELLIDO."""
    tokens = nombre_completo.split()
    if len(tokens) == 2:
        return tokens[0], tokens[1]
    primer_apellido = PRIMER_APELLIDO.get(nombre_completo)
    if primer_apellido is None:
        raise RuntimeError(
            f"Nombre ambiguo sin regla de apellido: {nombre_completo!r} — "
            "agregarlo a PRIMER_APELLIDO (no se inventa)"
        )
    return tokens[0], primer_apellido


def generar_emails(nombres: list[str]) -> dict[str, str]:
    """nombre_completo → email real, en orden determinista. Colisión: el
    SEGUNDO usa las dos primeras letras del nombre; doble colisión truena."""
    usados = {email for _, email, _ in USUARIOS_REALES}
    emails: dict[str, str] = {}
    for nombre_completo in nombres:
        nombre, apellido = _partes_de(nombre_completo)
        base = f"{_normalizar(nombre)[0]}{_normalizar(apellido)}@herinox.com.mx"
        if base not in usados:
            email = base
        else:
            email = f"{_normalizar(nombre)[:2]}{_normalizar(apellido)}@herinox.com.mx"
            if email in usados:
                raise RuntimeError(
                    f"Colisión doble de email para {nombre_completo!r} ({base}, {email}) — "
                    "reportar a Edgar (no se inventa)"
                )
        usados.add(email)
        emails[nombre_completo] = email
    return emails


def _plantilla_completa() -> list[str]:
    """Orden determinista para la asignación de emails: gerentes →
    compradores → vendedores por sucursal en el orden del roster."""
    return (
        [nombre for nombre, _ in GERENTES]
        + [nombre for nombre, _ in COMPRADORES]
        + [nombre for lista in VENDEDORES.values() for nombre in lista]
    )


def _get_or_create_usuario(
    db: Session,
    nombre: str,
    email: str,
    rol: Rol,
    password_hash: str,
    sucursal_id: int | None = None,
) -> tuple[Usuario, bool]:
    """Idempotente por email; un usuario existente queda INTACTO (jamás se
    pisa una contraseña ya cambiada)."""
    usuario = db.scalar(select(Usuario).where(func.lower(Usuario.email) == email.lower()))
    if usuario is not None:
        return usuario, False
    usuario = Usuario(
        nombre=nombre,
        email=email,
        password_hash=password_hash,
        rol=rol,
        activo=True,
        must_change_password=True,
        sucursal_id=sucursal_id,
    )
    db.add(usuario)
    db.flush()
    return usuario, True


def run(db: Session) -> dict[str, int]:
    """Devuelve los conteos. TODOS los usuarios entran con la temporal fija
    Herinox2026! y cambio forzado."""
    sucursales: dict[str, Sucursal] = {}
    for nombre, prefijo, tz in SUCURSALES:
        sucursal = db.scalar(select(Sucursal).where(Sucursal.nombre == nombre))
        if sucursal is None:
            sucursal = Sucursal(nombre=nombre, prefijo_folio=prefijo, timezone=tz)
            db.add(sucursal)
            db.flush()
        if db.get(FolioCounter, sucursal.id) is None:
            # Decisión de Edgar (F9-prep): la numeración arranca LIMPIA.
            db.add(FolioCounter(sucursal_id=sucursal.id, ultimo=0))
        sucursales[nombre] = sucursal

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

    password_hash = hash_password(PASSWORD_DEFAULT)
    emails = generar_emails(_plantilla_completa())
    creados = 0

    for nombre, email, rol in USUARIOS_REALES:
        _, creado = _get_or_create_usuario(db, nombre, email, rol, password_hash)
        creados += creado

    for nombre, nombre_sucursal in GERENTES:
        _, creado = _get_or_create_usuario(
            db,
            nombre,
            emails[nombre],
            Rol.GERENTE_SUCURSAL,
            password_hash,
            sucursal_id=sucursales[nombre_sucursal].id,
        )
        creados += creado

    for nombre_sucursal, lista in VENDEDORES.items():
        for nombre in lista:
            _, creado = _get_or_create_usuario(
                db,
                nombre,
                emails[nombre],
                Rol.VENDEDOR,
                password_hash,
                sucursal_id=sucursales[nombre_sucursal].id,
            )
            creados += creado

    titularidades = 0
    for nombre, territorio in COMPRADORES:
        comprador, creado = _get_or_create_usuario(
            db, nombre, emails[nombre], Rol.COMPRADOR, password_hash
        )
        creados += creado
        for nombre_sucursal in territorio:
            sucursal = sucursales[nombre_sucursal]
            titular = db.scalar(
                select(CompradorSucursal).where(
                    CompradorSucursal.sucursal_id == sucursal.id, CompradorSucursal.titular
                )
            )
            if titular is None:
                db.add(
                    CompradorSucursal(
                        comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True
                    )
                )
                titularidades += 1

    db.commit()
    return {
        "sucursales": len(SUCURSALES),
        "motivos_rechazo": len(MOTIVOS_RECHAZO),
        "dias_festivos": len(DIAS_FESTIVOS),
        "directivos": len(USUARIOS_REALES),
        "gerentes_sucursal": len(GERENTES),
        "vendedores": sum(len(v) for v in VENDEDORES.values()),
        "compradores": len(COMPRADORES),
        "usuarios_creados": creados,
        "titularidades_creadas": titularidades,
    }
