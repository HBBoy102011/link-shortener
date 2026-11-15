"""ORM models package.

Importing this module registers every table on ``Base.metadata`` so that
Alembic and ``create_all`` see the full schema.
"""

from app.core.database import Base
from app.models.click import Click
from app.models.link import Link
from app.models.user import User

__all__ = ["Base", "Click", "Link", "User"]
