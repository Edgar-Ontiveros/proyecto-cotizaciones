from decimal import Decimal

from sqlalchemy import func, select

from app.cli.seed import PASSWORD_DEFAULT, email_provisional, run
from app.core.security import verify_password
from app.models.catalogos import DiaFestivo, MotivoRechazo
from app.models.cotizacion import CotizacionOpcion, Letra, Moneda, OpcionPartida
from app.models.historial import HistorialEstado
from app.models.solicitud import UNIDADES, Estado, Solicitud
from app.models.sucursal import CompradorSucursal, FolioCounter, Sucursal
from app.models.usuario import Rol, Usuario


def _conteo_por_rol(db, rol: Rol) -> int:
    return db.scalar(select(func.count()).where(Usuario.rol == rol).select_from(Usuario))


def test_seed_idempotente_y_conteos_exactos(db):
    run(db)
    run(db)  # correr dos veces no duplica

    assert db.scalar(select(func.count()).select_from(Sucursal)) == 11
    assert _conteo_por_rol(db, Rol.COMPRADOR) == 6
    assert _conteo_por_rol(db, Rol.GERENTE) == 9
    assert _conteo_por_rol(db, Rol.VENDEDOR) == 35
    assert _conteo_por_rol(db, Rol.ADMIN) == 1
    assert db.scalar(select(func.count()).select_from(MotivoRechazo)) == 5
    assert db.scalar(select(func.count()).select_from(FolioCounter)) == 11
    assert db.scalar(select(func.count()).select_from(DiaFestivo)) == 14

    # Solicitudes demo (F3/F4): 16, sin duplicar en la segunda corrida, con
    # estados variados producidos por transiciones reales.
    assert db.scalar(select(func.count()).select_from(Solicitud)) == 16
    estados = dict(
        db.execute(select(Solicitud.estado, func.count()).group_by(Solicitud.estado)).all()
    )
    assert estados == {
        Estado.BORRADOR: 2,
        Estado.ENVIADA: 4,  # 3 enviadas + 1 reenviada (2 ciclos)
        Estado.EN_PROCESO: 3,
        Estado.RECHAZADA: 2,
        Estado.CANCELADA: 1,
        Estado.COTIZADA: 2,  # una con A y B en MXN, otra con A en USD
        Estado.CONFIRMADA: 1,
        Estado.NO_CONFIRMADA: 1,
    }
    # 33 de F3 (12 nacimientos + 21 transiciones) + 18 de F4: los 4 flujos
    # nuevos aportan nacimiento + ENVIADA + EN_PROCESO (auto-toma) + COTIZADA,
    # y confirmada/no_confirmada un desenlace más cada una.
    assert db.scalar(select(func.count()).select_from(HistorialEstado)) == 51
    enviadas = db.scalar(
        select(func.count()).select_from(HistorialEstado).where(HistorialEstado.a == Estado.ENVIADA)
    )
    assert enviadas == 15  # 14 solicitudes enviadas (16 - 2 borradores) + 1 reenvío

    # Cotizaciones (F4): 6 opciones (2+1+2+1) con 10 renglones, capturadas
    # vía los services reales (totales calculados en backend).
    assert db.scalar(select(func.count()).select_from(CotizacionOpcion)) == 6
    assert db.scalar(select(func.count()).select_from(OpcionPartida)) == 10

    # La CONFIRMADA fija monto y moneda desnormalizados == total de la opción
    # B seleccionada: 250 KG × 108.50 + 1 PZ × 1200.00 = 28,325.00 MXN.
    confirmada = db.execute(
        select(Solicitud).where(Solicitud.estado == Estado.CONFIRMADA)
    ).scalar_one()
    opcion_b = db.execute(
        select(CotizacionOpcion).where(
            CotizacionOpcion.solicitud_id == confirmada.id, CotizacionOpcion.letra == Letra.B
        )
    ).scalar_one()
    assert confirmada.opcion_seleccionada_id == opcion_b.id
    assert confirmada.monto_confirmado == Decimal("28325.00") == opcion_b.total
    assert confirmada.moneda_confirmada == Moneda.MXN
    assert confirmada.confirmado_en is not None

    # Renglón rico (F8b): la cotizada MXN trae UN renglón alternativa (con
    # descripción y precio) y UN no-encontrado; proveedor POR RENGLÓN; el
    # total de esa opción excluye al no-encontrado (120 KG × 94.80).
    renglones = list(db.scalars(select(OpcionPartida)))
    assert all(r.cantidad is not None and r.unidad in UNIDADES for r in renglones)
    no_encontrados = [r for r in renglones if r.no_encontrada]
    alternativas = [r for r in renglones if r.es_alternativa]
    assert len(no_encontrados) == 1 and no_encontrados[0].precio_unitario is None
    assert len(alternativas) == 1
    assert alternativas[0].alternativa_descripcion and alternativas[0].precio_unitario
    assert alternativas[0].opcion.total == Decimal("11376.00")
    assert no_encontrados[0].opcion_id == alternativas[0].opcion_id
    assert {r.proveedor for r in renglones} >= {"Aceros y Metales del Norte", "Rolled Alloys"}

    # La NO_CONFIRMADA conserva el motivo del catálogo fijo.
    no_confirmada = db.execute(
        select(Solicitud).where(Solicitud.estado == Estado.NO_CONFIRMADA)
    ).scalar_one()
    assert no_confirmada.motivo_no_confirmada == "PRECIO"

    # La COTIZADA en USD nunca mezcla monedas.
    usd = db.scalars(select(CotizacionOpcion).where(CotizacionOpcion.moneda == Moneda.USD)).all()
    assert len(usd) == 1 and usd[0].total == Decimal("351.00")

    # Territorios completos: los 6 compradores son titulares y cubren las 11
    # sucursales (una titularidad por sucursal).
    territorios = db.scalars(select(CompradorSucursal)).all()
    assert len(territorios) == 11
    assert all(t.titular for t in territorios)
    assert len({t.sucursal_id for t in territorios}) == 11

    # Todos entran con la contraseña por defecto y deben cambiarla.
    usuarios = db.scalars(select(Usuario)).all()
    assert len(usuarios) == 51
    assert all(u.must_change_password for u in usuarios)
    admin = db.scalar(select(Usuario).where(Usuario.email == "edgar@herinox.demo"))
    assert admin is not None and admin.rol == Rol.ADMIN
    assert verify_password(PASSWORD_DEFAULT, admin.password_hash)


def test_emails_provisionales_sin_acentos():
    assert email_provisional("Fabián Flores") == "fabian.flores@herinox.demo"
    assert email_provisional("Alonso Muñoz") == "alonso.munoz@herinox.demo"
    assert email_provisional("Gloria de la Luz Murillo") == "gloria.murillo@herinox.demo"
