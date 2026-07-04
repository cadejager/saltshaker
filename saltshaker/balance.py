"""Host-balance helpers for the objectives solver: the wasted-seats cap, the
availability-proportional fair-share target, and the coarse penalty table.
Pure (no clingo). See 2026-06-29-clingo-objectives-design.md."""


def hostable(families):
    """Families that can host on at least one night."""
    return [f for f in families if any(f.host_nights)]


def flexible_hosts(families):
    """Hostable families with no host_target (their hosting ratio is balanced)."""
    return [f for f in families if any(f.host_nights) and f.host_target is None]


def compute_cap(families):
    """Wasted-seats cap = (max space among hostable families) - 1.

    Only families that can actually host count, so a large-space family that
    never hosts cannot inflate the cap.
    """
    return max(f.space for f in hostable(families)) - 1


def fairshare_targets(families, T):
    """email -> round(10 * T * attend(F) / A) over flexible hosts (integer tenths),
    A = sum of attend-night counts over flexible hosts. Empty if no flexible hosts."""
    flex = flexible_hosts(families)
    total_attend = sum(sum(f.attend_nights) for f in flex)
    targets = {}
    for f in flex:
        att = sum(f.attend_nights)
        targets[f.email] = round(10 * T * att / total_attend) if total_attend else 0
    return targets


def pentab_facts(families, T):
    """ASP facts pentab("email",C,P) for each flexible host and each count
    C in 0..nights, P = |10*C - fairshare|. Empty string if no flexible hosts."""
    flex = flexible_hosts(families)
    if not flex:
        return ""
    nights = len(families[0].attend_nights)
    targets = fairshare_targets(families, T)
    lines = []
    for f in flex:
        s10 = targets[f.email]
        for c in range(nights + 1):
            lines.append('pentab("%s",%d,%d).' % (f.email, c, abs(10 * c - s10)))
    return "\n".join(lines) + "\n"
