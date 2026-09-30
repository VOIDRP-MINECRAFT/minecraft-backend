"""In-game permissions (LuckPerms) managed from the admin panel.

The VoidRpPerms plugin on each server reports a catalog (groups, their nodes and members,
the plugins' permissions) and applies queued operations. Who should be in which group
comes from roles (``staff_roles.game_groups``) and direct grants; ``reconcile`` compares
that with what the panel has already put on people (``game_perm_applied``) and queues
the difference — so only the panel's own grants are ever taken away.

Hierarchy (like Discord roles, by LuckPerms group weight): a group can be handed out or
put in a role only if it is lighter than the giver's own heaviest group on that server;
groups flagged «только владелец» only by the owner; admins of a server hand out any other
group of theirs; editing groups needs ``game.groups.manage`` (granted by the owner).
"""
from __future__ import annotations

import math
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.app.core.security import utc_now
from apps.api.app.models.game_perm import (
    GamePermApplied,
    GamePermCatalog,
    GamePermDirect,
    GamePermFlag,
    GamePermOp,
)
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.staff_role import StaffRole, StaffRoleMember
from apps.api.app.models.user import User


def catalog(session: Session, server_id) -> dict:
    row = session.get(GamePermCatalog, server_id)
    return row.data if row else {}


def groups_by_name(data: dict) -> dict[str, dict]:
    return {g["name"]: g for g in data.get("groups", [])}


def weight(group: dict | None) -> int:
    return int((group or {}).get("weight") or 0)


def owner_only_groups(session: Session, server_id) -> set[str]:
    return {name for (name,) in session.execute(select(GamePermFlag.group_name).where(
        GamePermFlag.server_id == server_id, GamePermFlag.owner_only.is_(True))).all()}


# ── who should have what ─────────────────────────────────────────────────────

def desired(session: Session, server_id) -> set[tuple[UUID, str]]:
    sid = str(server_id)
    out: set[tuple[UUID, str]] = set()
    roles = session.scalars(select(StaffRole).where(StaffRole.is_badge.is_(False))).all()
    by_role = {}
    for r in roles:
        groups = (r.game_groups or {}).get(sid) or []
        if groups and (r.server_ids is None or sid in [str(x) for x in r.server_ids]):
            by_role[r.id] = groups
    if by_role:
        for role_id, user_id in session.execute(select(StaffRoleMember.role_id, StaffRoleMember.user_id).where(
                StaffRoleMember.role_id.in_(list(by_role)))).all():
            for g in by_role[role_id]:
                out.add((user_id, g))
    for user_id, g in session.execute(select(GamePermDirect.user_id, GamePermDirect.group_name).where(
            GamePermDirect.server_id == server_id)).all():
        out.add((user_id, g))
    return out


def groups_of(session: Session, server_id, user_id) -> set[str]:
    return {g for (u, g) in desired(session, server_id) if u == user_id}


def enqueue(session: Session, server_id, op: dict, actor: str | None) -> GamePermOp:
    row = GamePermOp(server_id=server_id, op=op, created_by=actor)
    session.add(row)
    session.flush()
    return row


def reconcile(session: Session, server_id, actor: str | None = "система") -> int:
    """Queues LuckPerms changes so people have exactly the panel's groups: adds what is
    missing, takes away what the panel gave earlier and nobody should have now. Groups
    the plugin has not reported (typo, deleted) are skipped. Returns how many were queued."""
    known = groups_by_name(catalog(session, server_id))
    if not known:
        return 0
    want = {(u, g) for (u, g) in desired(session, server_id) if g in known}
    have = {(u, g) for (u, g) in session.execute(select(GamePermApplied.user_id, GamePermApplied.group_name).where(
        GamePermApplied.server_id == server_id)).all()}
    pending = session.scalars(select(GamePermOp).where(GamePermOp.server_id == server_id,
                                                       GamePermOp.status == "pending")).all()
    queued = {(p.op.get("user_id"), p.op.get("group"), bool(p.op.get("remove")))
              for p in pending if p.op.get("op") == "user.parent"}
    names = dict(session.execute(select(PlayerAccount.user_id, PlayerAccount.minecraft_nickname).where(
        PlayerAccount.user_id.in_({u for (u, _) in want | have} or {None}))).all())
    n = 0
    for (u, g) in sorted(want - have, key=str):
        if (str(u), g, False) in queued or not names.get(u):
            continue
        enqueue(session, server_id, {"op": "user.parent", "user_id": str(u), "name": names[u], "group": g}, actor)
        n += 1
    for (u, g) in sorted(have - want, key=str):
        if (str(u), g, True) in queued or not names.get(u):
            continue
        enqueue(session, server_id, {"op": "user.parent", "user_id": str(u), "name": names[u], "group": g, "remove": True}, actor)
        n += 1
    return n


def record_result(session: Session, op: GamePermOp, ok: bool, result: str | None) -> None:
    op.status = "done" if ok else "failed"
    op.result = (result or "")[:1000]
    op.done_at = utc_now()
    data = op.op
    if ok and data.get("op") == "user.parent" and data.get("user_id"):
        uid = UUID(data["user_id"])
        if data.get("remove"):
            session.execute(delete(GamePermApplied).where(GamePermApplied.server_id == op.server_id,
                                                          GamePermApplied.user_id == uid,
                                                          GamePermApplied.group_name == data["group"]))
        elif session.get(GamePermApplied, (op.server_id, uid, data["group"])) is None:
            session.add(GamePermApplied(server_id=op.server_id, user_id=uid, group_name=data["group"],
                                        created_by=op.created_by))


# ── hierarchy ────────────────────────────────────────────────────────────────

def power(session: Session, authority, server_id) -> float:
    """How heavy a group the actor may hand out on this server (strictly lighter)."""
    if authority.platform:
        return math.inf
    if str(server_id) in authority.admin_servers:
        return math.inf
    if "game.assign" not in authority.access.on(server_id):
        return -math.inf
    known = groups_by_name(catalog(session, server_id))
    mine = groups_of(session, server_id, authority.actor.id)
    return max((weight(known.get(g)) for g in mine), default=-math.inf)


def may_give(session: Session, authority, server_id, group: str) -> bool:
    if group == "default":  # everyone has it already
        return False
    if group in owner_only_groups(session, server_id):
        return bool(authority.owner)
    known = groups_by_name(catalog(session, server_id))
    if group not in known:
        return False
    return weight(known[group]) < power(session, authority, server_id)


def may_edit_groups(session: Session, authority, server_id, group: str | None = None) -> bool:
    if group and group in owner_only_groups(session, server_id):
        return bool(authority.owner)
    return authority.platform or "game.groups.manage" in authority.access.on(server_id)


def user_by_name(session: Session, name: str) -> User | None:
    from apps.api.app.utils.normalization import normalize_minecraft_nickname

    try:
        _, norm = normalize_minecraft_nickname(name)
    except ValueError:
        return None
    return session.scalar(select(User).join(PlayerAccount, PlayerAccount.user_id == User.id)
                          .where(PlayerAccount.minecraft_nickname_normalized == norm))


def reconcile_all(session: Session, actor: str | None = "система") -> None:
    """After roles or their members change: every server that has a catalog."""
    for (server_id,) in session.execute(select(GamePermCatalog.server_id)).all():
        reconcile(session, server_id, actor)
