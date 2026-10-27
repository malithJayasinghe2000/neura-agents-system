"""memberships.role — one of three roles

ADR-0058 §2. ``role`` existed with one value, ``owner`` (ADR-0026 §5). Now there
are three, and what each may do is code (``neura_core.identity.roles``). This
only stops the database holding a value the code does not know: such a role
would hold no permission, so a typo in a script would make a member who can open
nothing and no error would say why.

**Existing members stay owners.** Every membership made before this is
``owner``, the column's default is unchanged, and the constraint is checked
against the rows already there, so an unexpected value stops the migration
rather than slipping past it.

Revision ID: 5a7c2e9b4d13
Revises: 3c8e5a1d9f42
Create Date: 2026-10-10 12:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "5a7c2e9b4d13"
down_revision: str | None = "3c8e5a1d9f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_memberships_role"),
        "memberships",
        "role IN ('owner', 'support', 'developer')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_memberships_role"), "memberships", type_="check")
