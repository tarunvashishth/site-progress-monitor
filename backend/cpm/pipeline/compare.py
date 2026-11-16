"""Pair frames of the current video with comparable frames of an earlier capture (perceptual hash)."""

from cpm.pipeline.frames import hamming


def _dist(a: str, b: str) -> int:
    try:
        return hamming(a, b)
    except (TypeError, ValueError):
        return 10**6  # unreadable hash: never comparable


def pair_frames(
    current: list[dict], earlier: list[dict], max_pairs: int, max_distance: int
) -> list[dict]:
    """Greedy one-to-one matching by dHash distance. Only views that look alike are paired, so the
    model is never asked to compare unrelated angles. Returns [] when nothing is comparable."""
    by_e = {e["frame_index"]: e for e in earlier}
    cands = sorted(
        (_dist(c["image_hash"], e["image_hash"]), c["frame_index"], e["frame_index"])
        for c in current
        for e in earlier
    )
    used_c: set[int] = set()
    used_e: set[int] = set()
    out: list[dict] = []
    for dist, ci, ei in cands:
        if dist > max_distance or len(out) >= max_pairs:
            break
        if ci in used_c or ei in used_e:
            continue
        used_c.add(ci)
        used_e.add(ei)
        out.append({"current_index": ci, "earlier": by_e[ei], "distance": dist})
    return sorted(out, key=lambda p: p["current_index"])
