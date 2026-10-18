"""The only store Auryn uses. One pooled client; one graph per tenant.

Isolation is the graph boundary, never a WHERE clause. A query names one graph
and cannot reach another.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from falkordb import FalkorDB
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError, ResponseError

from .models import StoreUnavailable, validate_tenant

DEFAULT_URL = "falkor://localhost:6379"


def _parse(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    return host, port


class Store:
    """Holds one FalkorDB client and selects a graph per operation.

    A connection is never opened per operation. `select_graph` is a cheap
    handle over the shared connection.
    """

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.environ.get("FALKORDB_URL", DEFAULT_URL)
        host, port = _parse(self.url)
        self.host, self.port = host, port
        try:
            self._db = FalkorDB(host=host, port=port)
            self._db.connection.ping()
        except (RedisConnectionError, OSError) as exc:
            raise StoreUnavailable(
                f"FalkorDB is not reachable at {host}:{port}. "
                f"Auryn has no other store and cannot continue. ({exc})"
            ) from exc

    @property
    def connection(self):
        """The underlying client, for the instrument reads in metrics.py."""
        return self._db.connection

    def graph(self, tenant: str):
        """Return a handle to one tenant's graph. Validates before any query."""
        return self._db.select_graph(validate_tenant(tenant))

    def query(
        self, tenant: str, cypher: str, params: dict[str, Any] | None = None, *, read_only: bool = False
    ):
        """Run one parameterized query against one tenant's graph.

        Every value passes as a parameter. No query is built by joining text.
        """
        g = self.graph(tenant)
        try:
            if read_only:
                return g.ro_query(cypher, params=params or {})
            return g.query(cypher, params=params or {})
        except (RedisConnectionError, OSError) as exc:
            raise StoreUnavailable(
                f"FalkorDB became unreachable at {self.host}:{self.port}. ({exc})"
            ) from exc
        except ResponseError as exc:
            # A real query error. Let it surface; do not disguise it as unavailability.
            raise
        except RedisError as exc:
            raise StoreUnavailable(f"FalkorDB error at {self.host}:{self.port}. ({exc})") from exc

    def list_graphs(self) -> list[str]:
        """Tenant count comes from FalkorDB's own listing, not a count we kept."""
        try:
            return list(self._db.list_graphs())
        except (RedisConnectionError, OSError) as exc:
            raise StoreUnavailable(f"FalkorDB is not reachable. ({exc})") from exc

    def drop(self, tenant: str) -> None:
        """Remove one tenant's whole memory. Other tenants are unaffected."""
        try:
            self.graph(tenant).delete()
        except ResponseError:
            pass  # the graph does not exist; removing nothing is success

    def close(self) -> None:
        self._db.close()
