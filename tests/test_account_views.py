from types import SimpleNamespace

from flask_security.models import fsqla_v3 as fsqla

from nuevo_fonotarot.extensions import db

original_set_db_info = fsqla.FsModels.set_db_info


def safe_set_db_info(*args, **kwargs):
    try:
        return original_set_db_info(*args, **kwargs)
    except Exception as exc:
        if "already defined for this MetaData instance" in str(exc):
            return None
        raise


fsqla.FsModels.set_db_info = safe_set_db_info
fsqla.FsModels.set_db_info(db, user_table_name="users", role_table_name="roles")

from nuevo_fonotarot.account import views as account_views


def test_firenze_profile_update_payload_includes_editable_profile_fields():
    user = SimpleNamespace(
        full_name="Nombre Nuevo",
        email="user@example.com",
        phone="56999998888",
    )

    payload = account_views._firenze_profile_update_payload(
        user,
        full_name_changed=True,
        phone_changed=True,
    )

    assert payload == {
        "full_name": "Nombre Nuevo",
        "email": "user@example.com",
        "phone": "56999998888",
    }


def test_firenze_profile_update_payload_omits_unneeded_fields():
    user = SimpleNamespace(
        full_name="Nombre",
        email="user@example.com",
        phone="56911112222",
    )

    payload = account_views._firenze_profile_update_payload(
        user,
        full_name_changed=False,
        phone_changed=False,
    )

    assert payload == {
        "email": "user@example.com",
    }
