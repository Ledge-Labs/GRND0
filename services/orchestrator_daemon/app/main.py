# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import create_router
from app.config import Settings
from app.connectors.registry import ConnectorRegistry
from app.cognitive_loop.loop import CognitiveLoop
from app.cognitive_loop.routing import LaneRouter
from app.harness_registry import HarnessRegistry
from app.store import RuntimeStore


settings = Settings.from_env()
registry = HarnessRegistry(settings.harness_path)
store = RuntimeStore(settings.database_path, settings.authorized_read_roots)
router = LaneRouter(settings.lanes_path)
connectors = ConnectorRegistry(settings, store)
loop = CognitiveLoop(settings, registry, store, router, connectors)

app = FastAPI(title="GRND0", version="0.0.1", docs_url=None, redoc_url=None)
app.include_router(create_router(settings, loop, store, connectors))
