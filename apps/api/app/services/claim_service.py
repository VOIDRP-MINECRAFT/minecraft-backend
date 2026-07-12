from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from apps.api.app.models.claim import Claim, ClaimTrusted
from apps.api.app.models.player_account import PlayerAccount
from apps.api.app.schemas.claim import (
    ClaimActionResponse,
    ClaimCreateRequest,
    ClaimGameRead,
    ClaimSiteRead,
)
from apps.api.app.utils.normalization import normalize_minecraft_nickname

# Core cube (level 1) + up to 30 upgrades.
MAX_LEVEL = 31
# Cubes are 16-block cells whose (0,0,0) cell is centred on the core.
HALF = 8
SIZE = 16


def cube_of(block_coord: int) -> int:
    return block_coord // 16


def _cube_box(core: tuple[int, int, int], cube: tuple[int, int, int]) -> tuple[int, int, int, int, int, int]:
    minx = core[0] - HALF + cube[0] * SIZE
    miny = core[1] - HALF + cube[1] * SIZE
    minz = core[2] - HALF + cube[2] * SIZE
    return (minx, miny, minz, minx + SIZE, miny + SIZE, minz + SIZE)


def _boxes_intersect(a: tuple, b: tuple) -> bool:
    return not (
        a[3] <= b[0] or a[0] >= b[3]
        or a[4] <= b[1] or a[1] >= b[4]
        or a[5] <= b[2] or a[2] >= b[5]
    )


def _as_tuples(cubes: list) -> set[tuple[int, int, int]]:
    out: set[tuple[int, int, int]] = set()
    for c in cubes or []:
        if isinstance(c, (list, tuple)) and len(c) == 3:
            out.add((int(c[0]), int(c[1]), int(c[2])))
    return out


def _adjacent(a: tuple[int, int, int], b: tuple[int, int, int]) -> bool:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2]) == 1


class ClaimService:
    def __init__(self, session: Session, server_id: UUID) -> None:
        self.session = session
        self.server_id = server_id

    # ── nick ↔ user helpers ──────────────────────────────────────────────
    def _user_id_by_nick(self, nick: str) -> UUID | None:
        _, normalized = normalize_minecraft_nickname(nick)
        account = self.session.execute(
            select(PlayerAccount).where(
                PlayerAccount.minecraft_nickname_normalized == normalized
            )
        ).scalar_one_or_none()
        return account.user_id if account else None

    def _nicks_by_user_ids(self, user_ids: list[UUID]) -> dict[UUID, str]:
        if not user_ids:
            return {}
        rows = self.session.execute(
            select(PlayerAccount.user_id, PlayerAccount.minecraft_nickname).where(
                PlayerAccount.user_id.in_(user_ids)
            )
        ).all()
        return {uid: nick for uid, nick in rows}

    # ── reads ────────────────────────────────────────────────────────────
    def _all_claims(self) -> list[Claim]:
        return list(
            self.session.execute(
                select(Claim)
                .where(Claim.server_id == self.server_id)
                .options(selectinload(Claim.trusted))
            ).scalars()
        )

    def _other_boxes(self, dimension: str, exclude_id: UUID | None = None) -> list[tuple]:
        boxes: list[tuple] = []
        for c in self._all_claims():
            if c.dimension != dimension or c.id == exclude_id:
                continue
            core = (c.core_x, c.core_y, c.core_z)
            for cube in _as_tuples(c.cubes):
                boxes.append(_cube_box(core, cube))
        return boxes

    def _to_game_read(self, claim: Claim, nick_map: dict[UUID, str]) -> ClaimGameRead:
        trusted_nicks = [nick_map[t.user_id] for t in claim.trusted if t.user_id in nick_map]
        return ClaimGameRead(
            id=claim.id,
            owner_nick=nick_map.get(claim.owner_user_id, ""),
            dimension=claim.dimension,
            core_x=claim.core_x,
            core_y=claim.core_y,
            core_z=claim.core_z,
            level=claim.level,
            cubes=[list(c) for c in _as_tuples(claim.cubes)],
            trusted_nicks=trusted_nicks,
        )

    def list_game(self) -> list[ClaimGameRead]:
        claims = self._all_claims()
        ids: set[UUID] = set()
        for c in claims:
            ids.add(c.owner_user_id)
            ids.update(t.user_id for t in c.trusted)
        nick_map = self._nicks_by_user_ids(list(ids))
        return [self._to_game_read(c, nick_map) for c in claims]

    def list_site_for_user(self, user_id: UUID) -> list[ClaimSiteRead]:
        claims = list(
            self.session.execute(
                select(Claim)
                .where(Claim.server_id == self.server_id, Claim.owner_user_id == user_id)
                .options(selectinload(Claim.trusted))
            ).scalars()
        )
        trusted_ids: set[UUID] = set()
        for c in claims:
            trusted_ids.update(t.user_id for t in c.trusted)
        nick_map = self._nicks_by_user_ids(list(trusted_ids))
        out: list[ClaimSiteRead] = []
        for c in claims:
            cubes = [list(x) for x in _as_tuples(c.cubes)]
            out.append(
                ClaimSiteRead(
                    id=c.id,
                    dimension=c.dimension,
                    core_x=c.core_x,
                    core_y=c.core_y,
                    core_z=c.core_z,
                    level=c.level,
                    size_cubes=len(cubes),
                    cubes=cubes,
                    trusted_nicks=[nick_map[t.user_id] for t in c.trusted if t.user_id in nick_map],
                    created_at=c.created_at,
                )
            )
        return out

    def _game_read_single(self, claim: Claim) -> ClaimGameRead:
        ids = [claim.owner_user_id, *[t.user_id for t in claim.trusted]]
        return self._to_game_read(claim, self._nicks_by_user_ids(ids))

    # ── writes ───────────────────────────────────────────────────────────
    def create(self, req: ClaimCreateRequest) -> ClaimActionResponse:
        owner_id = self._user_id_by_nick(req.owner_nick)
        if owner_id is None:
            return ClaimActionResponse(ok=False, error="owner account not found")

        core = (req.core_x, req.core_y, req.core_z)
        new_box = _cube_box(core, (0, 0, 0))
        if any(_boxes_intersect(new_box, b) for b in self._other_boxes(req.dimension)):
            return ClaimActionResponse(ok=False, error="cube overlaps an existing claim")

        claim = Claim(
            server_id=self.server_id,
            owner_user_id=owner_id,
            dimension=req.dimension,
            core_x=req.core_x,
            core_y=req.core_y,
            core_z=req.core_z,
            core_chunk_x=cube_of(req.core_x),
            core_chunk_z=cube_of(req.core_z),
            level=1,
            cubes=[[0, 0, 0]],
        )
        self.session.add(claim)
        self.session.flush()
        return ClaimActionResponse(ok=True, claim=self._game_read_single(claim))

    def _get(self, claim_id: UUID) -> Claim | None:
        return self.session.execute(
            select(Claim)
            .where(Claim.id == claim_id, Claim.server_id == self.server_id)
            .options(selectinload(Claim.trusted))
        ).scalar_one_or_none()

    def add_cube(self, claim_id: UUID, cube: list[int]) -> ClaimActionResponse:
        claim = self._get(claim_id)
        if claim is None:
            return ClaimActionResponse(ok=False, error="claim not found")
        if not cube or len(cube) != 3:
            return ClaimActionResponse(ok=False, error="invalid cube")

        c = (int(cube[0]), int(cube[1]), int(cube[2]))
        existing = _as_tuples(claim.cubes)

        if len(existing) >= MAX_LEVEL:
            return ClaimActionResponse(ok=False, error="max level reached")
        if c in existing:
            return ClaimActionResponse(ok=False, error="cube already claimed")
        core = (claim.core_x, claim.core_y, claim.core_z)
        new_box = _cube_box(core, c)
        if any(_boxes_intersect(new_box, b) for b in self._other_boxes(claim.dimension, exclude_id=claim.id)):
            return ClaimActionResponse(ok=False, error="cube overlaps an existing claim")
        if not any(_adjacent(c, e) for e in existing):
            return ClaimActionResponse(ok=False, error="cube is not adjacent to the claim")

        claim.cubes = [*claim.cubes, list(c)]
        claim.level = len(claim.cubes)
        self.session.flush()
        return ClaimActionResponse(ok=True, claim=self._game_read_single(claim))

    def fill(self, claim_id: UUID) -> ClaimActionResponse:
        """Fill the bounding box of the claim's cubes, adding every free cell inside
        it (skipping ones that would overlap another claim), up to MAX_LEVEL. This
        turns an L/plus-shaped claim into a solid rectangular box."""
        claim = self._get(claim_id)
        if claim is None:
            return ClaimActionResponse(ok=False, error="claim not found")

        cubes = _as_tuples(claim.cubes)
        if not cubes:
            return ClaimActionResponse(ok=False, error="claim has no cubes")

        xs = [c[0] for c in cubes]
        ys = [c[1] for c in cubes]
        zs = [c[2] for c in cubes]
        core = (claim.core_x, claim.core_y, claim.core_z)
        others = self._other_boxes(claim.dimension, exclude_id=claim.id)

        added = 0
        for x in range(min(xs), max(xs) + 1):
            for y in range(min(ys), max(ys) + 1):
                for z in range(min(zs), max(zs) + 1):
                    c = (x, y, z)
                    if c in cubes:
                        continue
                    if len(cubes) >= MAX_LEVEL:
                        break
                    if any(_boxes_intersect(_cube_box(core, c), b) for b in others):
                        continue
                    cubes.add(c)
                    added += 1

        if added == 0:
            return ClaimActionResponse(ok=False, error="nothing to fill")

        claim.cubes = [list(c) for c in cubes]
        claim.level = len(claim.cubes)
        self.session.flush()
        return ClaimActionResponse(ok=True, claim=self._game_read_single(claim))

    def delete(self, claim_id: UUID) -> ClaimActionResponse:
        claim = self._get(claim_id)
        if claim is None:
            return ClaimActionResponse(ok=False, error="claim not found")
        self.session.delete(claim)
        self.session.flush()
        return ClaimActionResponse(ok=True)

    def trust(self, claim_id: UUID, nick: str, action: str) -> ClaimActionResponse:
        claim = self._get(claim_id)
        if claim is None:
            return ClaimActionResponse(ok=False, error="claim not found")

        user_id = self._user_id_by_nick(nick)
        if user_id is None:
            return ClaimActionResponse(ok=False, error="player account not found")

        if action == "add":
            if user_id != claim.owner_user_id and not any(
                t.user_id == user_id for t in claim.trusted
            ):
                self.session.add(ClaimTrusted(claim_id=claim.id, user_id=user_id))
        elif action == "remove":
            for t in list(claim.trusted):
                if t.user_id == user_id:
                    self.session.delete(t)
        else:
            return ClaimActionResponse(ok=False, error="invalid action")

        self.session.flush()
        self.session.refresh(claim)
        return ClaimActionResponse(ok=True, claim=self._game_read_single(claim))
