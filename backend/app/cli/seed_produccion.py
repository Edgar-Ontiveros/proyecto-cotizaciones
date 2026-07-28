"""Seed de PRODUCCIÓN (F9-prep) — separado del seed demo, que no se toca.

Puebla SOLO el arranque real: las 11 sucursales (prefijos editables desde el
CRM) con contadores de folio EN CERO, festivos de ley 2026–27, catálogo de
motivos de rechazo y los 4 usuarios reales con contraseña temporal
AUTOGENERADA (se muestra UNA sola vez en la salida del comando; cambio
forzado al primer uso).

CERO usuarios demo, CERO solicitudes, CERO titularidades: compradores,
vendedores y gerentes reales se dan de alta desde el CRM, donde el maestro
asigna titulares por sucursal. Hasta entonces, enviar en una sucursal sin
titular responde el 409 esperado — comportamiento correcto, no bug.

Idempotente por email: correrlo dos veces no duplica ni pisa contraseñas ya
cambiadas (un usuario existente se deja INTACTO).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cli.seed import DIAS_FESTIVOS, MOTIVOS_RECHAZO, SUCURSALES
from app.core.security import generate_temp_password, hash_password
from app.models.catalogos import DiaFestivo, MotivoRechazo
from app.models.sucursal import FolioCounter, Sucursal
from app.models.usuario import Rol, Usuario

USUARIOS_REALES = [
    ("Edgar Ontiveros", "eontiveros@herinox.com.mx", Rol.ADMIN),
    ("Francisco Muñoz", "fmunoz@herinox.com.mx", Rol.ADMIN),
    ("Francisco Perez", "fperez@herinox.com.mx", Rol.DIRECTOR_VENTAS),
    ("Luis Jimenez", "ljimenez@herinox.com.mx", Rol.GERENTE_COMPRAS),
]


def run(db: Session) -> tuple[dict[str, int], dict[str, str]]:
    """Devuelve (conteos, temporales) — temporales SOLO de los usuarios recién
    creados en esta corrida; el llamador las imprime una única vez."""
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

    temporales: dict[str, str] = {}
    for nombre, email, rol in USUARIOS_REALES:
        existente = db.scalar(select(Usuario).where(func.lower(Usuario.email) == email.lower()))
        if existente is not None:
            continue  # idempotencia: jamás se pisa una contraseña ya cambiada
        password = generate_temp_password()
        db.add(
            Usuario(
                nombre=nombre,
                email=email,
                password_hash=hash_password(password),
                rol=rol,
                activo=True,
                must_change_password=True,
            )
        )
        temporales[email] = password

    db.commit()
    conteos = {
        "sucursales": len(SUCURSALES),
        "motivos_rechazo": len(MOTIVOS_RECHAZO),
        "dias_festivos": len(DIAS_FESTIVOS),
        "usuarios_reales": len(USUARIOS_REALES),
        "usuarios_creados": len(temporales),
    }
    return conteos, temporales
