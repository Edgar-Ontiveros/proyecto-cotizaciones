"""Seed de PRODUCCIÓN (F9-prep) — separado del seed demo, que no se toca.

Puebla SOLO el arranque real: las 11 sucursales (prefijos editables desde el
CRM) con contadores de folio EN CERO, festivos de ley 2026–27, catálogo de
motivos de rechazo y los 4 usuarios reales con la contraseña temporal FIJA
Herinox2026! y cambio forzado al primer uso (decisión de Edgar, mini-fase
demo: sin autogeneración ni impresión de contraseñas).

CERO usuarios demo, CERO solicitudes, CERO titularidades: compradores,
vendedores y gerentes reales se dan de alta desde el CRM, donde el maestro
asigna titulares por sucursal. Hasta entonces, enviar en una sucursal sin
titular responde el 409 esperado — comportamiento correcto, no bug.

Idempotente por email: correrlo dos veces no duplica ni pisa contraseñas ya
cambiadas (un usuario existente se deja INTACTO).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cli.seed import DIAS_FESTIVOS, MOTIVOS_RECHAZO, PASSWORD_DEFAULT, SUCURSALES
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

# --con-demo (mini-fase): cuentas de SIMULACIÓN con contraseña fija conocida
# (Herinox2026!, cambio forzado al primer uso), marcadas como demo.
USUARIOS_DEMO = [
    ("Vendedor Demo", "vendedor.demo@herinox.demo", Rol.VENDEDOR),
    ("Comprador Demo", "comprador.demo@herinox.demo", Rol.COMPRADOR),
]
SUCURSAL_DEMO = "Matriz"


def _agregar_demo(db: Session) -> int:
    """Cuentas demo + titularidad de Matriz para el comprador demo (solo si
    Matriz no tiene ya titular). Idempotente. Devuelve usuarios creados."""
    matriz = db.scalar(select(Sucursal).where(Sucursal.nombre == SUCURSAL_DEMO))
    if matriz is None:  # las sucursales se sembraron justo antes
        raise RuntimeError(f"Sucursal {SUCURSAL_DEMO} inexistente en el seed")
    password_hash = hash_password(PASSWORD_DEFAULT)
    creados = 0
    demo_por_email: dict[str, Usuario] = {}
    for nombre, email, rol in USUARIOS_DEMO:
        usuario = db.scalar(select(Usuario).where(func.lower(Usuario.email) == email))
        if usuario is None:
            usuario = Usuario(
                nombre=nombre,
                email=email,
                password_hash=password_hash,
                rol=rol,
                activo=True,
                must_change_password=True,
                sucursal_id=matriz.id if rol == Rol.VENDEDOR else None,
            )
            db.add(usuario)
            db.flush()
            creados += 1
        demo_por_email[email] = usuario

    comprador_demo = demo_por_email["comprador.demo@herinox.demo"]
    titular = db.scalar(
        select(CompradorSucursal).where(
            CompradorSucursal.sucursal_id == matriz.id, CompradorSucursal.titular
        )
    )
    if titular is None:
        # Sin esto, enviar en Matriz daría el 409 de sucursal sin titular.
        db.add(
            CompradorSucursal(comprador_id=comprador_demo.id, sucursal_id=matriz.id, titular=True)
        )
    return creados


def run(db: Session, con_demo: bool = False) -> dict[str, int]:
    """Devuelve los conteos. TODOS los usuarios que crea (reales y demo)
    entran con la temporal fija Herinox2026! y cambio forzado."""
    for nombre, prefijo, tz in SUCURSALES:
        sucursal = db.scalar(select(Sucursal).where(Sucursal.nombre == nombre))
        if sucursal is None:
            sucursal = Sucursal(nombre=nombre, prefijo_folio=prefijo, timezone=tz)
            db.add(sucursal)
            db.flush()
        if db.get(FolioCounter, sucursal.id) is None:
            # Decisión de Edgar (F9-prep): la numeración arranca LIMPIA.
            db.add(FolioCounter(sucursal_id=sucursal.id, ultimo=0))

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
    creados = 0
    for nombre, email, rol in USUARIOS_REALES:
        existente = db.scalar(select(Usuario).where(func.lower(Usuario.email) == email.lower()))
        if existente is not None:
            continue  # idempotencia: jamás se pisa una contraseña ya cambiada
        db.add(
            Usuario(
                nombre=nombre,
                email=email,
                password_hash=password_hash,
                rol=rol,
                activo=True,
                must_change_password=True,
            )
        )
        creados += 1

    conteos = {
        "sucursales": len(SUCURSALES),
        "motivos_rechazo": len(MOTIVOS_RECHAZO),
        "dias_festivos": len(DIAS_FESTIVOS),
        "usuarios_reales": len(USUARIOS_REALES),
        "usuarios_creados": creados,
    }
    if con_demo:
        # Sin el flag, el comando queda EXACTAMENTE igual (ni la clave existe).
        conteos["usuarios_demo_creados"] = _agregar_demo(db)
    db.commit()
    return conteos
