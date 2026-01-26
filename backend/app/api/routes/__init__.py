from app.api.routes.domains import router as domains_router
from app.api.routes.mailboxes import router as mailboxes_router
from app.api.routes.tenants import router as tenants_router
from app.api.routes.wizard import router as wizard_router
from app.api.routes.stats import router as stats_router

__all__ = [
    "domains_router",
    "mailboxes_router",
    "tenants_router",
    "wizard_router",
    "stats_router",
]