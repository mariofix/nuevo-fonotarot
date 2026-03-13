"""add product_categories table and migrate Product.category to FK

Revision ID: e1f2a3b4c5d6
Revises: 7b79db108ac7
Create Date: 2026-03-13 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e1f2a3b4c5d6'
down_revision = '7b79db108ac7'
branch_labels = None
depends_on = None

# Initial category seed data (previously hardcoded in Product.CATEGORY_CHOICES)
_INITIAL_CATEGORIES = [
    {"slug": "mazos", "name": "Mazos de Tarot"},
    {"slug": "velas", "name": "Velas"},
    {"slug": "inciensos", "name": "Inciensos"},
    {"slug": "cristales", "name": "Cristales"},
    {"slug": "otros", "name": "Otros"},
]


def upgrade():
    # 1. Create product_categories table
    op.create_table(
        'product_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('product_categories', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_product_categories_slug'), ['slug'], unique=True)

    # 2. Seed the initial categories
    product_categories = sa.table(
        'product_categories',
        sa.column('slug', sa.String),
        sa.column('name', sa.String),
    )
    op.bulk_insert(product_categories, _INITIAL_CATEGORIES)

    # 3. Add category_id FK column to products (nullable to allow data migration)
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_products_category_id',
            'product_categories',
            ['category_id'],
            ['id'],
        )

    # 4. Migrate existing category string values to FK references
    connection = op.get_bind()
    for cat in _INITIAL_CATEGORIES:
        result = connection.execute(
            sa.text("SELECT id FROM product_categories WHERE slug = :slug"),
            {"slug": cat["slug"]},
        )
        row = result.fetchone()
        if row:
            connection.execute(
                sa.text("UPDATE products SET category_id = :cat_id WHERE category = :slug"),
                {"cat_id": row[0], "slug": cat["slug"]},
            )

    # 5. Drop the old category string column
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_column('category')


def downgrade():
    # 1. Re-add the old category string column
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category', sa.String(length=50), nullable=True))

    # 2. Populate category string from FK reference
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE products SET category = ("
            "SELECT slug FROM product_categories WHERE product_categories.id = products.category_id"
            ")"
        )
    )

    # 3. Set default 'otros' for any NULL values
    connection.execute(
        sa.text("UPDATE products SET category = 'otros' WHERE category IS NULL")
    )

    # 4. Remove FK column
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_constraint('fk_products_category_id', type_='foreignkey')
        batch_op.drop_column('category_id')

    # 5. Drop product_categories table
    with op.batch_alter_table('product_categories', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_product_categories_slug'))
    op.drop_table('product_categories')
