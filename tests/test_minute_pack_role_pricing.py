from datetime import datetime, timedelta
from decimal import Decimal

from nuevo_fonotarot.extensions import db


def _make_user(email: str, *roles):
    from nuevo_fonotarot.models import User

    user = User(
        email=email,
        username=email,
        password="test-password",
        fs_uniquifier=f"{email}-uniq",
        active=True,
    )
    for role in roles:
        user.roles.append(role)
    db.session.add(user)
    db.session.flush()
    return user


def test_resolve_minute_pack_price_falls_back_to_base(app):
    with app.app_context():
        from nuevo_fonotarot.models import MinutePack
        from nuevo_fonotarot.tienda.minutos.service import resolve_minute_pack_price

        pack = MinutePack(minutes=20, price=Decimal("10000"), currency="CLP", is_active=True)
        db.session.add(pack)
        user = _make_user("guest-fallback@example.com")
        db.session.commit()

        resolved = resolve_minute_pack_price(pack, user)

        assert resolved.amount == Decimal("10000")
        assert resolved.is_overridden is False


def test_resolve_minute_pack_price_uses_latest_active_schedule_for_role(app):
    with app.app_context():
        from nuevo_fonotarot.models import MinutePack, MinutePackRolePrice, Role
        from nuevo_fonotarot.tienda.minutos.service import resolve_minute_pack_price

        role = Role(name="leales-oro-schedule")
        pack = MinutePack(minutes=30, price=Decimal("15000"), currency="CLP", is_active=True)
        db.session.add_all([role, pack])
        db.session.flush()

        now = datetime.now()
        db.session.add_all(
            [
                MinutePackRolePrice(
                    minute_pack=pack,
                    role=role,
                    price=Decimal("7000"),
                    currency="CLP",
                    starts_at=now - timedelta(days=7),
                    is_active=True,
                ),
                MinutePackRolePrice(
                    minute_pack=pack,
                    role=role,
                    price=Decimal("9000"),
                    currency="CLP",
                    starts_at=now + timedelta(days=7),
                    is_active=True,
                ),
                MinutePackRolePrice(
                    minute_pack=pack,
                    role=role,
                    price=Decimal("8000"),
                    currency="CLP",
                    starts_at=now - timedelta(days=1),
                    is_active=True,
                ),
            ]
        )
        user = _make_user("oro@example.com", role)
        db.session.commit()

        resolved = resolve_minute_pack_price(pack, user, now)

        assert resolved.amount == Decimal("8000")
        assert resolved.applied_role_name == "leales-oro-schedule"


def test_resolve_minute_pack_price_prefers_best_price_across_roles(app):
    with app.app_context():
        from nuevo_fonotarot.models import MinutePack, MinutePackRolePrice, Role
        from nuevo_fonotarot.tienda.minutos.service import resolve_minute_pack_price

        oro = Role(name="leales-oro-best-price")
        plata = Role(name="leales-plata-best-price")
        pack = MinutePack(minutes=60, price=Decimal("30000"), currency="CLP", is_active=True)
        db.session.add_all([oro, plata, pack])
        db.session.flush()

        now = datetime.now()
        db.session.add_all(
            [
                MinutePackRolePrice(
                    minute_pack=pack,
                    role=oro,
                    price=Decimal("18000"),
                    currency="CLP",
                    starts_at=now - timedelta(days=2),
                    is_active=True,
                ),
                MinutePackRolePrice(
                    minute_pack=pack,
                    role=plata,
                    price=Decimal("17000"),
                    currency="CLP",
                    starts_at=now - timedelta(days=1),
                    is_active=True,
                ),
            ]
        )
        user = _make_user("multi-role@example.com", oro, plata)
        db.session.commit()

        resolved = resolve_minute_pack_price(pack, user, now)

        assert resolved.amount == Decimal("17000")
        assert resolved.applied_role_name == "leales-plata-best-price"


def test_default_loyalty_role_names_are_seeded_constants():
    from nuevo_fonotarot.tienda.minutos.service import DEFAULT_LOYALTY_ROLE_NAMES

    assert DEFAULT_LOYALTY_ROLE_NAMES == ("leales-oro", "leales-plata", "leales-bronze")
