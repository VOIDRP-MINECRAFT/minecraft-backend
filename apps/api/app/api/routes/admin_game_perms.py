"""Admin panel → «Права в игре»: LuckPerms groups of the chosen server, who is in them and
why, editing groups, handing groups out. Everything goes to the server through the
VoidRpPerms plugin's queue; who may do what is in core/game_perms.py."""
from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.app.api.routes.admin_moderators import get_authority
from apps.api.app.core import game_perms as gp
from apps.api.app.core.audit import record_audit
from apps.api.app.core.staff_authority import Authority
from apps.api.app.db import get_db_session
from apps.api.app.dependencies.admin import require_permission, require_reauth
from apps.api.app.dependencies.server_context import resolve_server
from apps.api.app.models.game_perm import GamePermApplied, GamePermCatalog, GamePermDirect, GamePermFlag, GamePermOp
from apps.api.app.models.game_server import GameServer
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.models.staff_role import StaffRole, StaffRoleMember

router = APIRouter(prefix="/admin/game-perms", tags=["admin", "game-perms"],
                   dependencies=[Depends(require_permission("game.view"))])

_Server = Annotated[GameServer, Depends(resolve_server)]
_Db = Annotated[Session, Depends(get_db_session)]
_Auth = Annotated[Authority, Depends(get_authority)]
_GROUP = re.compile(r"^[a-z0-9_\-]{1,36}$")
_META = ("weight.", "prefix.", "suffix.", "displayname.", "group.")


def _audit(session: Session, authority: Authority, server: GameServer, action: str, target: str, **meta) -> None:
    record_audit(session, actor=authority.actor, category="game_perms", action=action, target_type="group",
                 target_label=target, server_id=server.id, meta=meta or None)


def _meta_of(nodes: list[dict]) -> dict:
    out: dict[str, Any] = {"prefix": None, "suffix": None, "parents": []}
    best = {"prefix": -1, "suffix": -1}
    for n in nodes:
        k = n.get("key", "")
        if not n.get("value", True):
            continue
        for kind in ("prefix", "suffix"):
            if k.startswith(kind + "."):
                _, prio, text = k.split(".", 2)
                if int(prio) > best[kind]:
                    best[kind], out[kind] = int(prio), text
                    out[kind + "_priority"] = int(prio)
        if k.startswith("group."):
            out["parents"].append(k[6:])
    return out


@router.get("")
def overview(server: _Server, session: _Db, authority: _Auth) -> dict:
    row = session.get(GamePermCatalog, server.id)
    if row is None:
        return {"available": False, "server": server.slug}
    data = row.data
    applied = {(u, g) for (u, g) in session.execute(select(GamePermApplied.user_id, GamePermApplied.group_name)
                                                     .where(GamePermApplied.server_id == server.id)).all()}
    direct = {(u, g) for (u, g) in session.execute(select(GamePermDirect.user_id, GamePermDirect.group_name)
                                                    .where(GamePermDirect.server_id == server.id)).all()}
    sid = str(server.id)
    role_groups: dict[str, list[dict]] = {}
    for r in session.scalars(select(StaffRole).where(StaffRole.is_badge.is_(False))).all():
        for g in (r.game_groups or {}).get(sid) or []:
            role_groups.setdefault(g, []).append({"id": str(r.id), "name": r.name, "color": r.color})
    via_role: dict[tuple, list[str]] = {}
    role_by_id = {r.id: r for r in session.scalars(select(StaffRole)).all()}
    for role_id, user_id in session.execute(select(StaffRoleMember.role_id, StaffRoleMember.user_id)).all():
        for g in (role_by_id[role_id].game_groups or {}).get(sid) or []:
            via_role.setdefault((user_id, g), []).append(role_by_id[role_id].name)
    nick_to_user = {n.lower(): u for (u, n) in session.execute(select(PlayerAccount.user_id, PlayerAccount.minecraft_nickname)).all()}
    owner_only = gp.owner_only_groups(session, server.id)
    pending = session.scalars(select(GamePermOp).where(GamePermOp.server_id == server.id, GamePermOp.status == "pending")).all()
    groups = []
    for g in sorted(data.get("groups", []), key=lambda x: (-gp.weight(x), x["name"])):
        name = g["name"]
        members = []
        for m in g.get("members", []):
            uid = nick_to_user.get((m.get("name") or "").lower())
            members.append({**m, "managed": (uid, name) in applied, "direct": (uid, name) in direct,
                            "roles": via_role.get((uid, name), [])})
        groups.append({
            "name": name, "display": g.get("display"), "weight": g.get("weight"), **_meta_of(g.get("nodes", [])),
            "nodes": [n for n in g.get("nodes", []) if not n.get("key", "").startswith(_META)],
            "members": members, "roles": role_groups.get(name, []),
            "owner_only": name in owner_only,
            "may_give": gp.may_give(session, authority, server.id, name),
            "may_edit": gp.may_edit_groups(session, authority, server.id, name),
        })
    return {
        "available": True, "server": server.slug, "updated_at": row.updated_at.isoformat(),
        "plugin_version": row.plugin_version, "groups": groups, "permissions": data.get("permissions", []),
        "pending": len(pending),
        "me": {"owner": authority.owner, "may_create": gp.may_edit_groups(session, authority, server.id)},
    }


@router.get("/ops")
def recent_ops(server: _Server, session: _Db) -> dict:
    rows = session.scalars(select(GamePermOp).where(GamePermOp.server_id == server.id)
                           .order_by(GamePermOp.created_at.desc()).limit(60)).all()
    return {"items": [{"id": str(r.id), "op": r.op, "status": r.status, "result": r.result, "by": r.created_by,
                       "at": r.created_at.isoformat()} for r in rows]}


def _known(session: Session, server: GameServer, name: str) -> dict:
    g = gp.groups_by_name(gp.catalog(session, server.id)).get(name)
    if g is None:
        raise HTTPException(status_code=404, detail="Нет такой группы на сервере")
    return g


def _need_edit(session: Session, authority: Authority, server: GameServer, name: str | None) -> None:
    if not gp.may_edit_groups(session, authority, server.id, name):
        raise HTTPException(status_code=403, detail="Менять группы можно с правом «Права в игре: менять состав групп»"
                            + (" — эту группу только владелец" if name and name in gp.owner_only_groups(session, server.id) else ""))


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=36)


@router.post("/groups")
def create_group(body: GroupCreate, server: _Server, session: _Db, authority: _Auth) -> dict:
    _need_edit(session, authority, server, None)
    name = body.name.strip().lower()
    if not _GROUP.match(name):
        raise HTTPException(status_code=400, detail="Имя группы: латиница в нижнем регистре, цифры, _ и -")
    gp.enqueue(session, server.id, {"op": "group.create", "group": name}, authority.actor.site_login)
    _audit(session, authority, server, "group_create", name)
    session.commit()
    return {"queued": True}


@router.delete("/groups/{name}", dependencies=[Depends(require_reauth)])
def delete_group(name: str, server: _Server, session: _Db, authority: _Auth) -> dict:
    _known(session, server, name)
    _need_edit(session, authority, server, name)
    if name == "default":
        raise HTTPException(status_code=400, detail="Группу default удалить нельзя — она у всех игроков")
    gp.enqueue(session, server.id, {"op": "group.delete", "group": name}, authority.actor.site_login)
    session.execute(delete(GamePermDirect).where(GamePermDirect.server_id == server.id, GamePermDirect.group_name == name))
    session.execute(delete(GamePermApplied).where(GamePermApplied.server_id == server.id, GamePermApplied.group_name == name))
    session.execute(delete(GamePermFlag).where(GamePermFlag.server_id == server.id, GamePermFlag.group_name == name))
    sid = str(server.id)
    for r in session.scalars(select(StaffRole)).all():
        if name in ((r.game_groups or {}).get(sid) or []):
            gg = dict(r.game_groups)
            gg[sid] = [g for g in gg[sid] if g != name]
            r.game_groups = gg
    _audit(session, authority, server, "group_delete", name)
    session.commit()
    return {"queued": True}


class NodeBody(BaseModel):
    key: str = Field(..., min_length=1, max_length=200)
    value: bool = True
    contexts: dict[str, list[str]] | None = None
    expiry: int | None = None
    remove: bool = False


@router.post("/groups/{name}/nodes")
def change_node(name: str, body: NodeBody, server: _Server, session: _Db, authority: _Auth) -> dict:
    _known(session, server, name)
    _need_edit(session, authority, server, name)
    key = body.key.strip()
    if key.startswith(_META):
        raise HTTPException(status_code=400, detail="Вес, префикс, суффикс и наследование меняются отдельными полями")
    op = {"op": "group.node", "group": name, "key": key, "value": body.value, "remove": body.remove}
    if body.contexts:
        op["contexts"] = body.contexts
    if body.expiry:
        op["expiry"] = body.expiry
    gp.enqueue(session, server.id, op, authority.actor.site_login)
    _audit(session, authority, server, "node_remove" if body.remove else "node_add", name, node=key, value=body.value)
    session.commit()
    return {"queued": True}


class MetaBody(BaseModel):
    weight: int | None = Field(default=None, ge=0, le=100000)
    prefix: str | None = Field(default=None, max_length=64)
    suffix: str | None = Field(default=None, max_length=64)
    display: str | None = Field(default=None, max_length=64)


@router.patch("/groups/{name}/meta")
def change_meta(name: str, body: MetaBody, server: _Server, session: _Db, authority: _Auth) -> dict:
    _known(session, server, name)
    _need_edit(session, authority, server, name)
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return {"queued": False}
    gp.enqueue(session, server.id, {"op": "group.meta", "group": name, **fields}, authority.actor.site_login)
    _audit(session, authority, server, "meta", name, **fields)
    session.commit()
    return {"queued": True}


class ParentBody(BaseModel):
    parent: str
    remove: bool = False


@router.post("/groups/{name}/parents")
def change_parent(name: str, body: ParentBody, server: _Server, session: _Db, authority: _Auth) -> dict:
    _known(session, server, name)
    _known(session, server, body.parent)
    _need_edit(session, authority, server, name)
    _need_edit(session, authority, server, body.parent)  # inheriting an owner-only group is the owner's call
    if body.parent == name:
        raise HTTPException(status_code=400, detail="Группа не может наследовать сама себя")
    gp.enqueue(session, server.id, {"op": "group.parent", "group": name, "parent": body.parent, "remove": body.remove},
               authority.actor.site_login)
    _audit(session, authority, server, "parent_remove" if body.remove else "parent_add", name, parent=body.parent)
    session.commit()
    return {"queued": True}


class FlagBody(BaseModel):
    owner_only: bool


@router.put("/groups/{name}/owner-only")
def set_owner_only(name: str, body: FlagBody, server: _Server, session: _Db, authority: _Auth) -> dict:
    if not authority.owner:
        raise HTTPException(status_code=403, detail="Помечать группы «только владелец» может только владелец")
    _known(session, server, name)
    row = session.get(GamePermFlag, (server.id, name))
    if row is None:
        session.add(GamePermFlag(server_id=server.id, group_name=name, owner_only=body.owner_only))
    else:
        row.owner_only = body.owner_only
    _audit(session, authority, server, "owner_only", name, value=body.owner_only)
    session.commit()
    return {"ok": True}


class MemberBody(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)


def _person(session: Session, authority: Authority, username: str):
    user = gp.user_by_name(session, username)
    if user is None:
        from apps.api.app.api.routes.admin_moderators import _find
        user = _find(session, username)
    if user.player_account is None:
        raise HTTPException(status_code=400, detail="У аккаунта нет игрового ника")
    staff = bool(user.is_admin or user.is_moderator or user.admin_server_ids)
    if staff and user.id != authority.actor.id and not authority.outranks(user):
        raise HTTPException(status_code=403, detail="Этого человека менять может только тот, кто выше")
    return user


@router.post("/groups/{name}/members")
def add_member(name: str, body: MemberBody, server: _Server, session: _Db, authority: _Auth) -> dict:
    _known(session, server, name)
    if not gp.may_give(session, authority, server.id, name):
        raise HTTPException(status_code=403, detail="Эту группу выдать нельзя: она не легче твоей или только для владельца")
    user = _person(session, authority, body.username)
    if session.get(GamePermDirect, (server.id, user.id, name)) is None:
        session.add(GamePermDirect(server_id=server.id, user_id=user.id, group_name=name,
                                   created_by=authority.actor.site_login))
    session.flush()
    gp.reconcile(session, server.id, authority.actor.site_login)
    _audit(session, authority, server, "member_add", name, player=user.player_account.minecraft_nickname)
    session.commit()
    return {"queued": True}


@router.post("/groups/{name}/members/remove")
def remove_member(name: str, body: MemberBody, server: _Server, session: _Db, authority: _Auth) -> dict:
    """Takes the group away: a direct grant is dropped; a group someone was given by hand
    in the game (before the panel) is removed in LuckPerms too. A group that comes from a
    role goes away only with the role."""
    _known(session, server, name)
    if not gp.may_give(session, authority, server.id, name):
        raise HTTPException(status_code=403, detail="Эту группу снимать нельзя: она не легче твоей или только для владельца")
    user = gp.user_by_name(session, body.username)
    nick = body.username
    if user is not None:
        _person(session, authority, body.username)
        session.execute(delete(GamePermDirect).where(GamePermDirect.server_id == server.id,
                                                     GamePermDirect.user_id == user.id, GamePermDirect.group_name == name))
        session.flush()
        if (user.id, name) in gp.desired(session, server.id):
            raise HTTPException(status_code=400, detail="Эта группа выдана ролью — сними роль или убери группу из роли")
        nick = user.player_account.minecraft_nickname
        if session.get(GamePermApplied, (server.id, user.id, name)) is None:
            gp.enqueue(session, server.id, {"op": "user.parent", "name": nick, "group": name, "remove": True},
                       authority.actor.site_login)
    else:
        gp.enqueue(session, server.id, {"op": "user.parent", "name": nick, "group": name, "remove": True},
                   authority.actor.site_login)
    gp.reconcile(session, server.id, authority.actor.site_login)
    _audit(session, authority, server, "member_remove", name, player=nick)
    session.commit()
    return {"queued": True}
