"""migrate users/roles to FsUserMixin/FsRoleMixin without data loss

Revision ID: c19e884a175c
Revises: b54236434b59
Create Date: 2026-05-06 20:51:22.247064
"""

from alembic import op
import sqlalchemy as sa
from flask_security.datastore import AsaList
from sqlalchemy.ext.mutable import MutableList


# revision identifiers, used by Alembic.
revision = "c19e884a175c"
down_revision = "b54236434b59"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("fs_webauthn_user_handle", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "mf_recovery_codes",
                MutableList.as_mutable(AsaList()),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "create_datetime",
                sa.DateTime(),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "update_datetime",
                sa.DateTime(),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            )
        )
        batch_op.create_unique_constraint(
            "uq_users_fs_webauthn_user_handle", ["fs_webauthn_user_handle"]
        )

    op.create_table(
        "webauthn",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(length=1024), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.Integer(), nullable=True),
        sa.Column("transports", MutableList.as_mutable(AsaList()), nullable=True),
        sa.Column("backup_state", sa.Boolean(), nullable=False),
        sa.Column("device_type", sa.String(length=64), nullable=False),
        sa.Column("extensions", sa.String(length=255), nullable=True),
        sa.Column(
            "create_datetime",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("lastuse_datetime", sa.DateTime(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("usage", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("webauthn", schema=None) as batch_op:
        batch_op.create_index("ix_webauthn_credential_id", ["credential_id"], unique=True)


def downgrade():
    with op.batch_alter_table("webauthn", schema=None) as batch_op:
        batch_op.drop_index("ix_webauthn_credential_id")
    op.drop_table("webauthn")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint(
            "uq_users_fs_webauthn_user_handle",
            type_="unique",
        )
        batch_op.drop_column("update_datetime")
        batch_op.drop_column("create_datetime")
        batch_op.drop_column("mf_recovery_codes")
        batch_op.drop_column("fs_webauthn_user_handle")
