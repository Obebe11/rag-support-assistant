"""Background jobs on PostgreSQL.

- `queue`: enqueue, claim, complete, fail and requeue jobs.
- `registry`: job handlers by job type.
- `runner`: the worker loop.
- `handlers`: handler modules owned by T3 (indexing) and T4 (delivery).

Run the worker with `python -m app.worker`.
"""
