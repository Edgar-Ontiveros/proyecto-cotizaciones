from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import generate_temp_password, hash_password
from app.models.sucursal import Sucursal
from app.models.usuario import AlcanceGerente, Rol, Usuario
from app.modules.auth.service import revoke_all_user_tokens
from app.modules.usuarios.schemas import UsuarioCreate, UsuarioUpdate


def _validar_rol_sucursal(
    db: Session,
    rol: Rol,
    sucursal_id: int | None,
    alcance_gerente: AlcanceGerente | None,
) -> tuple[int | None, AlcanceGerente | None]:
    """Reglas de consistencia rol ↔ sucursal ↔ alcance. Devuelve los valores
    normalizados (los roles que no usan un campo lo dejan en NULL)."""
    if rol == Rol.VENDEDOR:
        if sucursal_id is None:
            raise AppError(422, "Un vendedor requiere sucursal_id", "sucursal_requerida")
        alcance_gerente = None
    elif rol == Rol.GERENTE:
        if alcance_gerente is None:
            raise AppError(422, "Un gerente requiere alcance_gerente", "alcance_requerido")
        if alcance_gerente == AlcanceGerente.SUCURSAL and sucursal_id is None:
            raise AppError(
                422, "Un gerente de alcance sucursal requiere sucursal_id", "sucursal_requerida"
            )
        if alcance_gerente == AlcanceGerente.GLOBAL:
            sucursal_id = None
    else:  # comprador (territorios en F5) y admin no llevan sucursal ni alcance
        sucursal_id = None
        alcance_gerente = None

    if sucursal_id is not None and db.get(Sucursal, sucursal_id) is None:
        raise AppError(422, "La sucursal indicada no existe", "sucursal_invalida")
    return sucursal_id, alcance_gerente


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
    rol: Rol | None,
    sucursal_id: int | None,
    activo: bool | None,
    q: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Usuario], int]:
    stmt = select(Usuario)
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


def crear(db: Session, data: UsuarioCreate) -> tuple[Usuario, str | None]:
    email = data.email.strip().lower()
    _check_email_libre(db, email)
    sucursal_id, alcance = _validar_rol_sucursal(
        db, data.rol, data.sucursal_id, data.alcance_gerente
    )
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
        alcance_gerente=alcance,
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    return user, password_temporal


def actualizar(db: Session, usuario_id: int, data: UsuarioUpdate) -> Usuario:
    user = _get_usuario(db, usuario_id)
    cambios = data.model_dump(exclude_unset=True)
    if "email" in cambios:
        cambios["email"] = cambios["email"].strip().lower()
        _check_email_libre(db, cambios["email"], excluir_id=user.id)
    rol = cambios.get("rol", user.rol)
    sucursal_id = cambios.get("sucursal_id", user.sucursal_id)
    alcance = cambios.get("alcance_gerente", user.alcance_gerente)
    sucursal_id, alcance = _validar_rol_sucursal(db, rol, sucursal_id, alcance)
    for campo in ("nombre", "email"):
        if campo in cambios:
            setattr(user, campo, cambios[campo])
    user.rol = rol
    user.sucursal_id = sucursal_id
    user.alcance_gerente = alcance
    db.commit()
    return user


def reset_password(db: Session, usuario_id: int) -> str:
    user = _get_usuario(db, usuario_id)
    temporal = generate_temp_password()
    user.password_hash = hash_password(temporal)
    user.must_change_password = True
    revoke_all_user_tokens(db, user.id)
    db.commit()
    return temporal


def desactivar(db: Session, usuario_id: int, admin: Usuario) -> Usuario:
    if usuario_id == admin.id:
        raise AppError(400, "Un admin no puede desactivarse a sí mismo", "no_auto_desactivacion")
    user = _get_usuario(db, usuario_id)
    user.activo = False
    revoke_all_user_tokens(db, user.id)
    db.commit()
    return user


def activar(db: Session, usuario_id: int) -> Usuario:
    user = _get_usuario(db, usuario_id)
    user.activo = True
    db.commit()
    return user
