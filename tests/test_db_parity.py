"""
test_db_parity.py
=================
Drift guard for the dual database layer.

database_sqlite.py monkey-patches its public functions into database.py's
namespace when Postgres is unreachable (see _activate_sqlite_fallback). Any
public function that exists only in database.py therefore keeps its Postgres
implementation in fallback mode — and Postgres-only SQL (NOW(), CONCAT(),
ANY(%s), DISTINCT ON, ::casts) crashes at call time on SQLite. This has
happened twice already: user-management functions drifted one way, the
review-queue functions the other. These tests turn that silent drift into a
red test.

Parsed with ast rather than imported, so the tests run without a database.
"""

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "intent_engine" / "src"

# Public functions that intentionally exist in only one backend. Every entry
# needs a reason — an empty set is the goal state.
KNOWN_PG_ONLY: set[str] = set()
KNOWN_SQLITE_ONLY: set[str] = set()


def _public_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }


def test_every_postgres_function_has_a_sqlite_mirror():
    """A function only in database.py runs Postgres SQL through the SQLite
    shim in fallback mode and crashes at call time."""
    pg = _public_functions(SRC / "database.py")
    sq = _public_functions(SRC / "database_sqlite.py")
    drifted = pg - sq - KNOWN_PG_ONLY
    assert not drifted, (
        f"Public functions in database.py missing from database_sqlite.py: "
        f"{sorted(drifted)} — mirror them (or add to KNOWN_PG_ONLY with a reason)."
    )


def test_no_orphan_sqlite_functions():
    """A function only in database_sqlite.py is dead code — nothing imports
    that module directly, so an unmatched name is never reachable and tends
    to drift from the real implementation (user-management did exactly this)."""
    pg = _public_functions(SRC / "database.py")
    sq = _public_functions(SRC / "database_sqlite.py")
    orphans = sq - pg - KNOWN_SQLITE_ONLY
    assert not orphans, (
        f"Public functions in database_sqlite.py with no database.py counterpart: "
        f"{sorted(orphans)} — dead code, delete them (or add to KNOWN_SQLITE_ONLY "
        f"with a reason)."
    )
