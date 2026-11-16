"""Deterministic progress math. The language model NEVER computes final percentages."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

HUNDRED = Decimal(100)


def D(x: Any) -> Decimal:
    return Decimal(str(x))


def q(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), ROUND_HALF_UP)


def validate_weights(weights: list[Any]) -> None:
    if not weights:
        raise ValueError("at least one work package is required")
    if sum((D(w) for w in weights), Decimal(0)) != HUNDRED:
        raise ValueError("work package weights must total exactly 100")


def overall_progress(items: list[dict]) -> Decimal:
    """SUM(weight * approved / 100). Only approved values are used."""
    return q(
        sum(
            (D(i["weight_percentage"]) * D(i["approved_percentage"]) / HUNDRED for i in items),
            Decimal(0),
        )
    )


def assessment_coverage(items: list[dict]) -> Decimal:
    """Share of total project weight that was (re)assessed in this report."""
    total = sum((D(i["weight_percentage"]) for i in items), Decimal(0))
    done = sum((D(i["weight_percentage"]) for i in items if i.get("assessed")), Decimal(0))
    return q(done / total * HUNDRED) if total else Decimal(0)


def current_values(packages: list[dict], last_snapshot: list[dict] | None) -> dict[str, Decimal]:
    """Latest approved value per package: from the last published report, else the initial baseline."""
    from_snap = {
        str(i["work_package_id"]): D(i["approved_percentage"]) for i in (last_snapshot or [])
    }
    return {
        str(p["id"]): from_snap.get(str(p["id"]), D(p["initial_approved_percentage"]))
        for p in packages
    }


def build_draft_items(
    packages: list[dict], current: dict[str, Decimal], assessments: list[dict]
) -> list[dict]:
    """AI proposals become 'pending' decisions; unassessable packages default to RETAIN (never 0)."""
    by_id = {str(a["work_package_id"]): a for a in assessments}
    items = []
    for p in packages:
        pid, prev, ai = str(p["id"]), current[str(p["id"])], by_id.get(str(p["id"]))
        usable = bool(
            ai and ai.get("assessable") and ai.get("proposed_completion_percentage") is not None
        )
        items.append(
            {
                "work_package_id": pid,
                "name": p["name"],
                "weight_percentage": float(p["weight_percentage"]),
                "previous_approved_percentage": float(prev),
                "ai": ai if usable else ({**ai, "assessable": False} if ai else None),
                "decision": "pending" if usable else "retain",
                "approved_percentage": None if usable else float(prev),
                "assessed": False,
            }
        )
    return items


def apply_decisions(items: list[dict], decisions: list[dict]) -> list[dict]:
    by_id = {i["work_package_id"]: i for i in items}
    for d in decisions:
        item = by_id.get(str(d["work_package_id"]))
        if item is None:
            raise ValueError(f"unknown work package {d['work_package_id']}")
        kind = d["decision"]
        if kind == "accept":
            ai = item.get("ai") or {}
            if not ai.get("assessable") or ai.get("proposed_completion_percentage") is None:
                raise ValueError(f"{item['name']}: no AI proposal to accept")
            item.update(
                decision="accept",
                approved_percentage=float(ai["proposed_completion_percentage"]),
                assessed=True,
            )
        elif kind == "edit":
            v = d.get("approved_percentage")
            if v is None or not (0 <= D(v) <= 100):
                raise ValueError(f"{item['name']}: approved_percentage must be between 0 and 100")
            item.update(decision="edit", approved_percentage=float(v), assessed=True)
        elif kind == "retain":
            item.update(
                decision="retain",
                approved_percentage=item["previous_approved_percentage"],
                assessed=False,
            )
        else:
            raise ValueError(f"invalid decision '{kind}'")
    return items


DROP_THRESHOLD = 5.0  # percentage points


def flagged_drops(items: list[dict]) -> list[dict]:
    """Pending AI proposals clearly below the last approved value: usually a model mistake, not
    real regression. They need a human decision before a bulk accept."""
    out = []
    for i in items:
        ai = i.get("ai") or {}
        proposed = ai.get("proposed_completion_percentage")
        if i["decision"] != "pending" or not ai.get("assessable") or proposed is None:
            continue
        if D(i["previous_approved_percentage"]) - D(proposed) > D(DROP_THRESHOLD):
            out.append(i)
    return out


def pending_items(items: list[dict]) -> list[str]:
    return [i["name"] for i in items if i["decision"] == "pending"]


def provisional(items: list[dict]) -> list[dict]:
    """For display only: pending packages count as their previous approved value."""
    return [
        {
            **i,
            "approved_percentage": i["approved_percentage"]
            if i["approved_percentage"] is not None
            else i["previous_approved_percentage"],
        }
        for i in items
    ]
