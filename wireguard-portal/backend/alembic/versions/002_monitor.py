from alembic import op

revision = "002"
down_revision = "001"


def upgrade():
    op.execute("ALTER TABLE vpn_servers ADD COLUMN checked INTEGER")
    op.execute(
        "ALTER TABLE vpn_servers ADD COLUMN health TEXT NOT NULL DEFAULT '未采样'"
    )
