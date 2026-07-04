"""Build the ASP program for the feasibility solver and parse clingo models back
into the in-memory schedule.

Emails and allergy/allergen/repel tokens are emitted as double-quoted ASP string
constants. The static rules encode hard constraints H1-H8 plus a top-priority
minimize-unfed objective (see 2026-06-27-clingo-feasibility-design.md, section 6).
"""

# Static ASP rules (everything that is not per-instance facts). See spec 6.2.
RULES = """
{ host(F,N) } :- canhost(F,N).
seat(F,F,N) :- host(F,N).
{ seat(G,H,N) : host(H,N) } 1 :- canattend(G,N), not host(G,N).

:- host(H,N), space(H,Sp), #sum { S,G : seat(G,H,N), size(G,S) } > Sp.
:- seat(G,H,N), G != H, allergy(G,T), allergen(H,T).
:- seat(A,H,N), seat(B,H,N), A < B, repel(A,T), repel(B,T).
:- htarget(F,T), #count { N : host(F,N) } > T.

unfed(G,N) :- canattend(G,N), not host(G,N), not seat(G,_,N).
:~ unfed(G,N). [1@3, G, N]

#show host/2.
#show seat/3.
"""


def _q(s):
    """Quote a string as an ASP double-quoted constant (emails/tokens contain @ and .)."""
    return '"%s"' % s


def build_facts(families):
    """Return the ASP facts (one per line) for a list of Family objects."""
    nights = len(families[0].attend_nights)
    lines = ["night(0..%d)." % (nights - 1)]
    for f in families:
        e = _q(f.email)
        lines.append("family(%s)." % e)
        lines.append("size(%s,%d)." % (e, f.size))
        lines.append("space(%s,%d)." % (e, f.space))
        if f.host_target is not None:
            lines.append("htarget(%s,%d)." % (e, f.host_target))
        for n in range(nights):
            if f.host_nights[n]:
                lines.append("canhost(%s,%d)." % (e, n))
            if f.attend_nights[n]:
                lines.append("canattend(%s,%d)." % (e, n))
        for t in f.allergies:
            lines.append("allergy(%s,%s)." % (e, _q(t)))
        for t in f.allergens:
            lines.append("allergen(%s,%s)." % (e, _q(t)))
        for t in f.repel:
            lines.append("repel(%s,%s)." % (e, _q(t)))
        for t in f.knows:
            lines.append("knows(%s,%s)." % (e, _q(t)))
    return "\n".join(lines) + "\n"


def build_program(families):
    """Return the full ASP program (facts + static rules) for the families."""
    return build_facts(families) + RULES


def model_to_schedule(symbols, families):
    """Reconstruct the in-memory schedule from a model's shown host/2 and seat/3 symbols.

    Returns a list indexed by night; each entry a dict mapping a host Family to a
    set of attendee Family objects (host included).
    """
    by_email = {f.email: f for f in families}
    nights = len(families[0].attend_nights)
    schedule = [{} for _ in range(nights)]
    for sym in symbols:
        if sym.name == "host" and len(sym.arguments) == 2:
            host = by_email[sym.arguments[0].string]
            night = sym.arguments[1].number
            schedule[night].setdefault(host, set())
    for sym in symbols:
        if sym.name == "seat" and len(sym.arguments) == 3:
            guest = by_email[sym.arguments[0].string]
            host = by_email[sym.arguments[1].string]
            night = sym.arguments[2].number
            schedule[night].setdefault(host, set()).add(guest)
    return schedule


# --- Phase 2a: one-stage objectives program parts ---
# Hard constraints H1-H8, with feed-everyone HARD (a direct integrity constraint).
HARD_CORE = """
{ host(F,N) } :- canhost(F,N).
seat(F,F,N) :- host(F,N).
{ seat(G,H,N) : host(H,N) } 1 :- canattend(G,N), not host(G,N).

:- host(H,N), space(H,Sp), #sum { S,G : seat(G,H,N), size(G,S) } > Sp.
:- seat(G,H,N), G != H, allergy(G,T), allergen(H,T).
:- seat(A,H,N), seat(B,H,N), A < B, repel(A,T), repel(B,T).
:- htarget(F,T), #count { N : host(F,N) } > T.

:- canattend(G,N), not host(G,N), not seat(G,_,N).
"""

# Hard wasted-seats cap: total empty seats per night <= Cap.
CAP_RULE = """
:- night(N), cap(Cap),
   #sum { Sp,H : host(H,N), space(H,Sp) ; -S,G : seat(G,H,N), size(G,S) } > Cap.
"""

# Coarse host-balance (@3). pentab facts are emitted from Python.
BALANCE_RULES = """
flexible(F) :- canhost(F,_), not htarget(F,_).
hostcnt(F,C) :- flexible(F), C = #count { N : host(F,N) }.
balpen(F,P)  :- hostcnt(F,C), pentab(F,C,P).
:~ balpen(F,P). [P@3, F]
"""

# Mixing (@2, = metric M5) and back-to-back (@1). Grounded for Pass 2 only.
MIXING_B2B_RULES = """
sharedknows(A,B) :- knows(A,T), knows(B,T), A < B.
meet(A,B) :- seat(A,H,N), seat(B,H,N), A < B, not sharedknows(A,B).
:~ meet(A,B). [-1@2, A, B]
b2b(F,N) :- host(F,N), host(F,N-1).
:~ b2b(F,N). [1@1, F, N]
"""

SHOW = """
#show host/2.
#show seat/3.
"""

# Balance-cost lock body for `#program lock(cb).` (grounded after Pass 1).
LOCK_PROGRAM = ":- #sum { P,F : balpen(F,P) } > cb."


def aux_program(families, cap):
    """Min-dinners program (to anchor the fair-share target T): hard core + cap +
    minimize total dinners. No balance/mixing."""
    return (asp_join(build_facts(families), "cap(%d)." % cap, HARD_CORE, CAP_RULE,
                     ":~ host(F,N). [1@1, F, N]", "#show host/2."))


def base_program(families, cap, pentab):
    """Pass-1 base: hard core + cap + coarse balance. Mixing/b2b are added later."""
    return asp_join(build_facts(families), "cap(%d)." % cap, pentab,
                    HARD_CORE, CAP_RULE, BALANCE_RULES, SHOW)


def asp_join(*parts):
    """Join non-empty program fragments with newlines."""
    return "\n".join(p for p in parts if p) + "\n"
