from enum import StrEnum
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from growth_os.db.base import Base, UUIDTimestampMixin


class MembershipRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ConnectorStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"


class Tenant(UUIDTimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)


class Workspace(UUIDTimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_workspaces_id_tenant_id"),
        UniqueConstraint("tenant_id", "name", name="uq_workspaces_tenant_id_name"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class Membership(UUIDTimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["workspaces.id", "workspaces.tenant_id"],
            ondelete="RESTRICT",
            name="fk_memberships_workspace_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "user_id",
            name="uq_memberships_workspace_user",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    role: Mapped[MembershipRole] = mapped_column(
        Enum(MembershipRole, native_enum=False, length=20),
        default=MembershipRole.MEMBER,
        nullable=False,
    )


class Site(UUIDTimestampMixin, Base):
    __tablename__ = "sites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["workspaces.id", "workspaces.tenant_id"],
            ondelete="RESTRICT",
            name="fk_sites_workspace_tenant",
        ),
        UniqueConstraint(
            "id",
            "workspace_id",
            "tenant_id",
            name="uq_sites_id_workspace_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "url",
            name="uq_sites_workspace_url",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)


class Connector(UUIDTimestampMixin, Base):
    """Persistence placeholder for future connector implementations."""

    __tablename__ = "connectors"
    __table_args__ = (
        ForeignKeyConstraint(
            ["site_id", "workspace_id", "tenant_id"],
            ["sites.id", "sites.workspace_id", "sites.tenant_id"],
            ondelete="RESTRICT",
            name="fk_connectors_site_workspace_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "site_id",
            "kind",
            name="uq_connectors_site_kind",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    site_id: Mapped[UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[ConnectorStatus] = mapped_column(
        Enum(ConnectorStatus, native_enum=False, length=30),
        default=ConnectorStatus.NOT_CONFIGURED,
        nullable=False,
    )
