"""baseline schema

Revision ID: 20260225_0001
Revises:
Create Date: 2026-02-25 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

from app.core.database import Base
from app.models import ApprovalStatus, CIStatus, CollisionStatus, SyncJobStatus  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = "20260225_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
