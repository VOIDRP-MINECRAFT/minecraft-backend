"""Who may change whose access in the admin panel.

Ranks, most senior first:
* the owner — appoints and removes platform admins;
* platform admins (``is_admin``) — everything else, including admins of single servers;
* admins of a server (``admin_server_ids``) — on their servers: roles bound to those
  servers only, and people's personal grants there;
* people with ``roles.manage`` / ``roles.assign`` — roles below their own highest role,
  and only roles whose every permission they hold themselves (on the same servers).

A role is "below" someone when its position is lower than their highest role's. Nobody
changes a person ranked at or above themselves.
"""
from __future__ import annotations

from apps.api.app.core.permissions import SERVER_KEYS, Access, access_of


def top_position(user) -> int | None:
    positions = [r.position for r in (getattr(user, "staff_roles", None) or [])]
    return max(positions) if positions else None


class Authority:
    def __init__(self, actor) -> None:
        self.actor = actor
        self.access: Access = access_of(actor)
        self.owner = bool(getattr(actor, "is_owner", False))
        self.platform = self.access.platform_admin
        self.admin_servers = self.access.admin_servers
        self.top = top_position(actor)
        self.can_manage_roles = self.platform or bool(self.admin_servers) or self.access.holds_everywhere("roles.manage")
        self.can_assign_roles = self.platform or bool(self.admin_servers) or self.access.holds_everywhere("roles.assign")

    @property
    def opens_staff_pages(self) -> bool:
        return self.can_manage_roles or self.can_assign_roles

    # ── roles ────────────────────────────────────────────────────────────────

    def _within_admin_servers(self, server_ids) -> bool:
        return server_ids is not None and len(server_ids) > 0 and {str(s) for s in server_ids} <= self.admin_servers

    def _covers(self, permissions, server_ids) -> bool:
        """The actor holds every key of a role on every server the role covers."""
        keys = set(permissions or [])
        if server_ids is None:
            return keys <= self.access.everywhere
        return all(keys <= self.access.on(sid) for sid in server_ids)

    def _below(self, position: int) -> bool:
        return self.top is not None and position < self.top

    def may_edit_role(self, position: int, server_ids, permissions, key: str = "roles.manage") -> bool:
        if self.platform or self._within_admin_servers(server_ids):
            return True
        return (self.access.holds_everywhere(key) and self._below(position)
                and self._covers(permissions, server_ids))

    def may_assign_role(self, role) -> bool:
        return self.may_edit_role(role.position, role.server_ids, role.permissions, key="roles.assign")

    # ── people ───────────────────────────────────────────────────────────────

    def outranks(self, target) -> bool:
        """The actor may change this person at all."""
        if target.id == self.actor.id:
            return False
        if target.is_owner:
            return False
        if target.is_admin:
            return self.owner
        if self.platform:
            return True
        target_admin = {str(s) for s in (target.admin_server_ids or [])}
        if target_admin and not target_admin <= self.admin_servers:
            # An admin of a server the actor does not run is not the actor's to change.
            return False
        if self.admin_servers:
            return True
        target_top = top_position(target)
        return self.top is not None and (target_top is None or target_top < self.top) and not target_admin

    def personal_servers(self) -> set[str] | None:
        """Servers whose personal grants the actor may edit (None: all, and the global list)."""
        if self.platform:
            return None
        return set(self.admin_servers)

    @staticmethod
    def server_keys_only(keys) -> list[str]:
        return [k for k in keys if k in SERVER_KEYS]
