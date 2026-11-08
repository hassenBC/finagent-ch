"""Empty the mock e-mail outbox (demo data only) so a recording starts clean."""
from finagent.db import pool
with pool().connection() as c:
    c.execute("TRUNCATE outbox")
print("outbox cleared")
