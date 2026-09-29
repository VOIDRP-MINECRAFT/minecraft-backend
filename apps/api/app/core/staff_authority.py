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

from apps.api.app.core.permissions import SERVER_ADMIN_KEYS, SERVER_KEYS, Access, access_of


def top_position(user) -> int | None:
    # Badges carry no rights and no seniority.
    positions = [r.position for r in (getattr(user, "staff_roles", None) or []) if not getattr(r, "is_badge", False)]
    return max(positions) if positions else None


def rank(user) -> int:
    """Seniority for things like the audit log: owner > platform admins > admins of
    servers > people by their highest role > the rest."""
    if user is None:
        return -1
    if getattr(user, "is_owner", False):
        return 1_000_000
    if getattr(user, "is_admin", False):
        return 900_000
    if getattr(user, "admin_server_ids", None):
        return 800_000
    top = top_position(user)
    return min(top, 700_000) if top is not None else -1


class Authority:
    def __init__(self, actor) -> None:
        self.actor = actor
        self.access: Access = access_of(actor)
        self.owner = bool(getattr(actor, "is_owner", False))
        self.platform = self.access.platform_admin
        self.admin_servers = self.access.admin_servers
        self.top = top_position(actor)
        self.can_manage_roles = self.platform or self._somewhere("roles.manage")
        self.can_assign_roles = self.platform or self._somewhere("roles.assign")
        # The «Сотрудники» tab (personal grants); appointing admins stays with the owner and
        # platform admins.
        self.can_staff = self.platform or self.access.holds_everywhere("staff.manage")
        self.can_manage_badges = self.platform or self._somewhere("badges.manage")
        # Set by the page dependency: the actor's role owns badges (members hand them out).
        self.owns_badges = False
        self.can_assign_badges = self.platform or self._somewhere("badges.assign")

    def _somewhere(self, key: str) -> bool:
        return self.access.holds_everywhere(key) or any(key in keys for keys in self.access.per_server.values()) \
            or (key in SERVER_ADMIN_KEYS and bool(self.admin_servers))

    def _holds_on(self, key: str, server_ids) -> bool:
        """``key`` on every server of a scope (None = everywhere)."""
        if server_ids is None:
            return self.access.holds_everywhere(key)
        return len(server_ids) > 0 and all(key in self.access.on(sid) for sid in server_ids)

    @property
    def opens_staff_pages(self) -> bool:
        return (self.can_manage_roles or self.can_assign_roles or self.can_manage_badges
                or self.can_assign_badges or self.can_staff or self.owns_badges)

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
        """``key`` (roles.manage / roles.assign) on every server of the role (everywhere for
        a role of all servers), every permission of the role held by the actor there, and
        the role below the actor's own — admins of all the role's servers stand above any
        role of theirs."""
        if self.platform:
            return True
        if not self._holds_on(key, server_ids) or not self._covers(permissions, server_ids):
            return False
        return self._within_admin_servers(server_ids) or self._below(position)

    def is_member(self, role) -> bool:
        return role is not None and any(r.id == role.id for r in (getattr(self.actor, "staff_roles", None) or []))

    def may_assign_role(self, role) -> bool:
        if getattr(role, "is_badge", False):
            # A badge grants nothing: badges.assign on its servers (everywhere for a common
            # one), or membership of the role that owns it; the person still has to be
            # below the giver.
            return (self.platform or self._holds_on("badges.assign", role.scope_ids)
                    or self.is_member(role.owner_role))
        return self.may_edit_role(role.position, role.server_ids, role.permissions, key="roles.assign")

    def may_edit_badge(self, server_ids, owner_role=None) -> bool:
        if self.platform:
            return True
        if owner_role is not None:
            return (self.is_member(owner_role) or self._holds_on("badges.manage", owner_role.server_ids)
                    or self.may_edit_role(owner_role.position, owner_role.server_ids, owner_role.permissions))
        return self._holds_on("badges.manage", server_ids)

    def may_own_badge(self, owner_role) -> bool:
        """A badge may be tied to a role the actor has, or one they manage."""
        return self.platform or self.is_member(owner_role) or self.may_edit_role(
            owner_role.position, owner_role.server_ids, owner_role.permissions)

    def sees_role(self, role) -> bool:
        """What the roles page lists: what the actor may change or hand out, and their own."""
        if self.platform or self.is_member(role):
            return True
        if role.is_badge:
            return (self.may_edit_badge(role.server_ids, role.owner_role) or self.may_assign_role(role)
                    or self.is_member(role.owner_role))
        return (self.may_edit_role(role.position, role.server_ids, role.permissions)
                or self.may_assign_role(role))

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
        # Admins of servers answer only to platform admins — never to one another, even
        # two admins of the same server (equals cannot strip each other's roles or rights).
        if target.admin_server_ids:
            return False
        if self.admin_servers:
            return True
        target_top = top_position(target)
        return self.top is not None and (target_top is None or target_top < self.top)

    def may_grant(self, key: str, server_id=None) -> bool:
        """A personal grant the actor may give or take away: a platform admin any; anyone
        else only what they hold themselves (everywhere, or on that server)."""
        if self.platform:
            return True
        if server_id is None:
            return key in self.access.everywhere
        return key in self.access.on(server_id)

    @staticmethod
    def server_keys_only(keys) -> list[str]:
        return [k for k in keys if k in SERVER_KEYS]
