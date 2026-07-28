from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import generate_temp_password, hash_password
from app.models.solicitud import Solicitud
from app.models.sucursal import Sucursal
from app.models.usuario import Rol, Usuario
from app.modules.auth.service import revoke_all_user_tokens
from app.modules.reasignaciones.service import (
    ESTADOS_ABIERTOS,
    ESTADOS_TERMINALES,
    reasignar_comprador_masivo,
    reasignar_vendedor_masivo,
)
from app.modules.sucursales.service import titularidades_de, transferir_titularidades
from app.modules.usuarios.schemas import DesactivarIn, UsuarioCreate, UsuarioUpdate

# Matriz de GESTIÓN v2 (F8c), codificada como DATO: quién crea/edita/resetea/
# activa-desactiva a quién. gerente_sucursal además está acotado a SU sucursal
# (se valida aparte). Solo admin gestiona gerente_compras, director_ventas y
# otros admin.
MATRIZ_GESTION: dict[Rol, frozenset[Rol]] = {
    Rol.ADMIN: frozenset(Rol),
    Rol.DIRECTOR_VENTAS: frozenset({Rol.VENDEDOR, Rol.GERENTE_SUCURSAL}),
    Rol.GERENTE_SUCURSAL: frozenset({Rol.VENDEDOR}),
    Rol.GERENTE_COMPRAS: frozenset({Rol.COMPRADOR}),
}


def autorizar_gestion(gestor: Usuario, rol_objetivo: Rol, sucursal_objetivo: int | None) -> None:
    """403 exacto si el gestor no puede tocar cuentas de ese rol/alcance."""
    permitidos = MATRIZ_GESTION.get(gestor.rol, frozenset())
    if rol_objetivo not in permitidos:
        raise AppError(
            403,
            f"Tu rol no gestiona cuentas de {rol_objetivo.value}",
            "gestion_no_permitida",
        )
    if gestor.rol == Rol.GERENTE_SUCURSAL and (
        gestor.sucursal_id is None or sucursal_objetivo != gestor.sucursal_id
    ):
        raise AppError(
            403,
            "Un gerente de sucursal solo gestiona vendedores de SU sucursal",
            "gestion_no_permitida",
        )


def _validar_rol_sucursal(db: Session, rol: Rol, sucursal_id: int | None) -> int | None:
    """Reglas de consistencia rol ↔ sucursal. Vendedor y gerente EXIGEN
    sucursal (el gerente es siempre de sucursal desde F5); comprador y admin
    no llevan (los territorios del comprador viven en comprador_sucursal)."""
    if rol in (Rol.VENDEDOR, Rol.GERENTE_SUCURSAL):
        if sucursal_id is None:
            raise AppError(422, f"Un {rol.value} requiere sucursal_id", "sucursal_requerida")
    else:
        sucursal_id = None
    if sucursal_id is not None and db.get(Sucursal, sucursal_id) is None:
        raise AppError(422, "La sucursal indicada no existe", "sucursal_invalida")
    return sucursal_id


def _get_usuario(db: Session, usuario_id: int) -> Usuario:
    user = db.get(Usuario, usuario_id)
    if user is None:
        raise AppError(404, "Usuario no encontrado", "usuario_no_encontrado")
    return user


def _check_email_libre(db: Session, email: str, excluir_id: int | None = None) -> None:
    stmt = select(Usuario.id).where(func.lower(Usuario.email) == email)
    if excluir_id is not None:
        stmt = stmt.where(Usuario.id != excluir_id)
    if db.scalar(stmt) is not None:
        raise AppError(409, "Ya existe un usuario con ese email", "email_duplicado")


def listar(
    db: Session,
    gestor: Usuario,
    rol: Rol | None,
    sucursal_id: int | None,
    activo: bool | None,
    q: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Usuario], int]:
    stmt = select(Usuario)
    # Alcance de la matriz EN el query (CLAUDE.md #7): cada gestor lista solo
    # los roles que puede gestionar; el gerente de sucursal, solo su sucursal.
    if gestor.rol != Rol.ADMIN:
        stmt = stmt.where(Usuario.rol.in_(MATRIZ_GESTION.get(gestor.rol, frozenset())))
    if gestor.rol == Rol.GERENTE_SUCURSAL:
        propia = gestor.sucursal_id if gestor.sucursal_id is not None else -1
        stmt = stmt.where(Usuario.sucursal_id == propia)
    if rol is not None:
        stmt = stmt.where(Usuario.rol == rol)
    if sucursal_id is not None:
        stmt = stmt.where(Usuario.sucursal_id == sucursal_id)
    if activo is not None:
        stmt = stmt.where(Usuario.activo == activo)
    if q:
        stmt = stmt.where(Usuario.nombre.ilike(f"%{q.strip()}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(db.scalars(stmt.order_by(Usuario.nombre).limit(limit).offset(offset)))
    return items, total


def crear(db: Session, data: UsuarioCreate, gestor: Usuario) -> tuple[Usuario, str | None]:
    email = data.email.strip().lower()
    _check_email_libre(db, email)
    sucursal_id = _validar_rol_sucursal(db, data.rol, data.sucursal_id)
    autorizar_gestion(gestor, data.rol, sucursal_id)
    password_temporal = None
    password = data.password
    if password is None:
        password = password_temporal = generate_temp_password()
    user = Usuario(
        nombre=data.nombre.strip(),
        email=email,
        password_hash=hash_password(password),
        rol=data.rol,
        sucursal_id=sucursal_id,
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    return user, password_temporal


def actualizar(db: Session, usuario_id: int, data: UsuarioUpdate, gestor: Usuario) -> Usuario:
    user = _get_usuario(db, usuario_id)
    cambios = data.model_dump(exclude_unset=True)
    rol = cambios.get("rol", user.rol)
    if usuario_id == gestor.id and rol != gestor.rol:
        # Regla generalizada (F8c): NADIE se cambia a sí mismo el rol — sin
        # esto el último admin podría dejarse fuera para siempre.
        raise AppError(422, "No puedes cambiarte a ti mismo el rol", "no_auto_degradacion")
    # La matriz aplica sobre lo que el usuario ES y sobre lo que QUEDARÍA.
    autorizar_gestion(gestor, user.rol, user.sucursal_id)
    if "email" in cambios:
        cambios["email"] = cambios["email"].strip().lower()
        _check_email_libre(db, cambios["email"], excluir_id=user.id)
    sucursal_id = _validar_rol_sucursal(db, rol, cambios.get("sucursal_id", user.sucursal_id))
    autorizar_gestion(gestor, rol, sucursal_id)
    for campo in ("nombre", "email"):
        if campo in cambios:
            setattr(user, campo, cambios[campo])
    user.rol = rol
    user.sucursal_id = sucursal_id
    db.commit()
    return user


def reset_password(db: Session, usuario_id: int, gestor: Usuario) -> str:
    user = _get_usuario(db, usuario_id)
    autorizar_gestion(gestor, user.rol, user.sucursal_id)
    temporal = generate_temp_password()
    user.password_hash = hash_password(temporal)
    user.must_change_password = True
    revoke_all_user_tokens(db, user.id)
    db.commit()
    return temporal


def _baja_segura_comprador(db: Session, user: Usuario, data: DesactivarIn, admin: Usuario) -> None:
    titularidades = titularidades_de(db, user.id)
    abiertas = (
        db.scalar(
            select(func.count())
            .select_from(Solicitud)
            .where(Solicitud.comprador_id == user.id, Solicitud.estado.in_(ESTADOS_ABIERTOS))
        )
        or 0
    )
    pendientes = []
    if titularidades and data.titularidades_a is None:
        pendientes.append(f"es titular de: {', '.join(titularidades)} (envía titularidades_a)")
    if abiertas and data.solicitudes_a is None:
        pendientes.append(f"tiene {abiertas} solicitud(es) abiertas (envía solicitudes_a)")
    if pendientes:
        raise AppError(
            409,
            "No se puede desactivar al comprador sin reasignar: " + "; ".join(pendientes),
            "baja_requiere_reasignacion",
        )
    if titularidades:
        assert data.titularidades_a is not None
        transferir_titularidades(db, user.id, data.titularidades_a, commit=False)
    if abiertas:
        assert data.solicitudes_a is not None
        reasignar_comprador_masivo(db, user.id, data.solicitudes_a, admin, commit=False)


def _baja_segura_vendedor(db: Session, user: Usuario, data: DesactivarIn, admin: Usuario) -> None:
    no_terminales = (
        db.scalar(
            select(func.count())
            .select_from(Solicitud)
            .where(Solicitud.vendedor_id == user.id, Solicitud.estado.not_in(ESTADOS_TERMINALES))
        )
        or 0
    )
    if not no_terminales:
        return
    if data.solicitudes_a is None:
        raise AppError(
            409,
            f"No se puede desactivar al vendedor: tiene {no_terminales} solicitud(es) "
            "no terminales (envía solicitudes_a)",
            "baja_requiere_reasignacion",
        )
    reasignar_vendedor_masivo(db, user.id, data.solicitudes_a, admin, commit=False)


def desactivar(
    db: Session, usuario_id: int, admin: Usuario, data: DesactivarIn | None = None
) -> Usuario:
    """Baja segura (F5): con pendientes y sin destinos → 409 detallado; con
    destinos, transfiere titularidades y reasigna abiertas (con eventos) y
    desactiva — todo en un acto (una sola transacción)."""
    if usuario_id == admin.id:
        # Regla generalizada (F8c): NADIE se desactiva a sí mismo.
        raise AppError(400, "No puedes desactivarte a ti mismo", "no_auto_desactivacion")
    user = _get_usuario(db, usuario_id)
    autorizar_gestion(admin, user.rol, user.sucursal_id)
    data = data or DesactivarIn()
    if usuario_id in (data.titularidades_a, data.solicitudes_a):
        raise AppError(
            422,
            "El destino de la reasignación no puede ser el usuario dado de baja",
            "destino_invalido",
        )
    if user.rol == Rol.COMPRADOR:
        _baja_segura_comprador(db, user, data, admin)
    elif user.rol == Rol.VENDEDOR:
        _baja_segura_vendedor(db, user, data, admin)
    user.activo = False
    revoke_all_user_tokens(db, user.id)
    db.commit()
    return user


def activar(db: Session, usuario_id: int, gestor: Usuario) -> Usuario:
    user = _get_usuario(db, usuario_id)
    autorizar_gestion(gestor, user.rol, user.sucursal_id)
    user.activo = True
    db.commit()
    return user
