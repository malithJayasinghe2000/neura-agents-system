"""evidence immutability is the database's job

[ADR-0034] §4 said evidence rows are immutable and §3 said they live on the
shadow turn's lifecycle. Both were true of the *code* and of neither the schema
nor the grants — so a second connection, a psql session, or a future repository
method could have updated a row or orphaned one, and nothing would have said so.

**A separate migration rather than an edit to `20260906_1200`**, because that one
has already been applied. Migration history is a record of what ran; rewriting it
means a database that has run the old version and a database built from the new
one silently differ.

Two changes:

* **`UPDATE` is revoked from the app role.** An immutable row is one the database
  will not let you change, not one nobody happens to change. `INSERT`, `SELECT`
  and `DELETE` remain: capture writes, promotion reads, and retention deletes.
* **A composite foreign key to `shadow_turns` with `ON DELETE CASCADE`.** This
  table exists only to make one shadow turn reproducible, and it holds a
  merchant's catalogue. When that turn is deleted under the merchant's retention
  policy its evidence must go with it — a retention sweep that has to *remember*
  a second table is a retention sweep that eventually forgets, which is open
  question **S10**'s shape.

The key is `(tenant_id, shadow_turn_id)` rather than `shadow_turn_id` alone,
because `shadow_turns` is keyed `(tenant_id, id)` — a single-column reference
could not be declared and, if it could, would let one tenant's evidence hang off
another tenant's turn.

Revision ID: 5b7e2c1904af
Revises: 8c31d4a70f52
Created: 2026-09-06 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "5b7e2c1904af"
down_revision: str | None = "8c31d4a70f52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rows written before the constraint existed cannot be checked against a
    # turn that may already be gone. There are none in any environment this has
    # run in, and deleting them is the only correct answer if there were: an
    # evidence row whose turn cannot be found is not promotable and not
    # deletable by the cascade that is about to become its lifecycle.
    op.execute(
        """
        DELETE FROM shadow_evidence e
        WHERE NOT EXISTS (
            SELECT 1 FROM shadow_turns t
            WHERE t.tenant_id = e.tenant_id AND t.id = e.shadow_turn_id
        )
        """
    )

    op.create_foreign_key(
        "fk_shadow_evidence_turn",
        "shadow_evidence",
        "shadow_turns",
        ["tenant_id", "shadow_turn_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )

    # The grant, not a trigger. A trigger raising on UPDATE would be a rule the
    # superuser bypasses and the app role obeys; a missing privilege is refused
    # for everyone the privilege was withheld from, which is the direction an
    # access control should fail in.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'neura_app') THEN
                REVOKE UPDATE ON shadow_evidence FROM neura_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'neura_app') THEN
                GRANT UPDATE ON shadow_evidence TO neura_app;
            END IF;
        END
        $$
        """
    )
    op.drop_constraint("fk_shadow_evidence_turn", "shadow_evidence", type_="foreignkey")
