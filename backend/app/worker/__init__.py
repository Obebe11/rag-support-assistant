"""Background jobs on PostgreSQL.

- `queue`: enqueue, claim, complete, fail and requeue jobs.
- `registry`: job handlers by job type.
- `runner`: the worker loop.
- `handlers`: the handler modules for indexing and delivery.

Run the worker with `python -m app.worker`.
"""
