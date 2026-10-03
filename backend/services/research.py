"""Date-bounded, inspectable research over recorded diary events.

Never manufacture event dates from film-state/import timestamps. Summary,
comparison, facets and exported evidence all use the same filters and grain.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean

from services.insights import InsightRequestError, InsightsService, _group_pick_score


DIMENSIONS = {"genre", "director", "language", "country", "decade"}
SORTS = {"newest", "oldest", "title", "rating"}


def summarize(events, profiles, days):
    ratings = [row.rating for row in events if row.rating is not None]
    return {
        "watches": len(events), "films": len({row.movie_id for row in events}),
        "rated": len(ratings), "average_rating": round(mean(ratings), 3) if ratings else None,
        "rewatches": sum(row.rewatch for row in events),
        "members": len(profiles), "active_members": len({row.profile_id for row in events}),
        "watches_per_member_30_days": round(len(events) * 30 / max(len(profiles) * days, 1), 3),
        "low_rating_sample": len(ratings) < 10,
    }


def build_research(service: InsightsService, requested, *, comparison=(), start=None, end=None,
                   basis="watched", dimension="genre", trait="", search="", sort="newest", offset=0, limit=100):
    today = datetime.now(timezone.utc).date()
    end = end or today
    start = start or date(end.year, 1, 1)
    if end < start or (end - start).days > 3652 or end > today or start.year < 1900:
        raise InsightRequestError("Choose an ordered date range from 1900 through today, at most ten years long.")
    if dimension not in DIMENSIONS or sort not in SORTS or basis not in {"watched", "logged"}:
        raise InsightRequestError("Unsupported research dimension, date basis or sort order.")
    if offset < 0 or not 1 <= limit <= 10000:
        raise InsightRequestError("Invalid evidence page.")
    a = service._resolve_profiles(requested, minimum=1, maximum=50)
    b = service._resolve_profiles(comparison, minimum=1, maximum=50) if comparison else []
    profiles = list({p.id: p for p in [*a, *b]}.values())
    if len(profiles) > 50:
        raise InsightRequestError("Compare at most 50 distinct profiles at once.")
    events = service._event_rows(profiles)
    states = service._state_rows(profiles, analytical_enrichment=True)
    lookup = {(row.profile_id, row.movie_id): row for row in states}
    days = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = start - timedelta(days=days)
    query = search.strip().casefold()

    def when(row):
        return row.opinion_date if basis == "logged" else row.watched_date

    def traits(row):
        state = lookup.get((row.profile_id, row.movie_id))
        return list(dict.fromkeys(service._trait_values(state, dimension))) if state else []

    def matches(row):
        return (not query or query in f"{row.movie.title} {row.username}".casefold()) and (
            not trait or trait.casefold() in {value.casefold() for value in traits(row)}
        )

    filtered = [row for row in events if matches(row)]
    cohorts = []
    cohort_events = []
    for label, members in (("A", a), ("B", b)):
        if not members:
            continue
        ids = {p.id for p in members}
        now = [row for row in filtered if row.profile_id in ids and start <= when(row) <= end]
        before = [row for row in filtered if row.profile_id in ids and previous_start <= when(row) <= previous_end]
        current = summarize(now, members, days)
        previous = summarize(before, members, days)
        monthly = defaultdict(list)
        buckets = defaultdict(list)
        for row in now:
            monthly[when(row).strftime("%Y-%m")].append(row)
            for value in traits(row):
                buckets[value].append(row)
        cohorts.append({
            "label": label, "profiles": [p.username for p in members], "current": current, "previous": previous,
            "change": {
                "watches": current["watches"] - previous["watches"],
                "watches_percent": round((current["watches"] / previous["watches"] - 1) * 100, 2) if previous["watches"] else None,
                "rating": round(current["average_rating"] - previous["average_rating"], 3)
                    if current["average_rating"] is not None and previous["average_rating"] is not None else None,
            },
            "per_profile": [{"username": p.username, **summarize([r for r in now if r.profile_id == p.id], [p], days)} for p in members],
            "monthly": [{"month": month, **summarize(rows, members, days)} for month, rows in sorted(monthly.items())],
            "traits": [{"label": label, **summarize(rows, members, days)} for label, rows in sorted(buckets.items(), key=lambda pair: (-len(pair[1]), pair[0]))[:50]],
        })
        cohort_events.append(now)

    # One shared member's event appears once in evidence, with both memberships.
    current_rows = list({row.id: row for rows in cohort_events for row in rows}.values())
    sort_keys = {
        "newest": lambda row: (-when(row).toordinal(), row.username, row.id),
        "oldest": lambda row: (when(row).toordinal(), row.username, row.id),
        "title": lambda row: (row.movie.title.casefold(), when(row), row.username, row.id),
        "rating": lambda row: (row.rating is None, -(row.rating or 0), row.movie.title.casefold(), row.id),
    }
    current_rows.sort(key=sort_keys[sort])
    a_ids, b_ids = {p.id for p in a}, {p.id for p in b}
    evidence = [{
        "event_id": row.id, "movie_id": row.movie_id, "title": row.movie.title,
        "year": row.movie.release_year, "username": row.username,
        "groups": [name for name, ids in (("A", a_ids), ("B", b_ids)) if row.profile_id in ids],
        "date": when(row).isoformat(), "watched_date": row.watched_date.isoformat(),
        "logged_date": row.logged_date.isoformat() if row.logged_date else None,
        "rating": row.rating, "rewatch": row.rewatch, "source_kind": row.source_kind,
        "film_url": row.movie.letterboxd_url,
    } for row in current_rows[offset:offset + limit]]
    coverage = service._feature_coverage(profiles, "taste_timeline", events, states)
    dated_counts = Counter((row.profile_id, row.movie_id) for row in events)
    undated = sum(max(max(row.watch_count, 1) - dated_counts[(row.profile_id, row.movie_id)], 0) for row in states)
    without_trait = sum(not traits(row) for row in current_rows)
    warnings = list(dict.fromkeys([*coverage["blockers"], *coverage["warnings"]]))
    if undated:
        warnings.append(f"{undated} known watches have no diary date; period comparisons cannot include them.")
    if without_trait:
        warnings.append(f"{without_trait} matching watch events have no {dimension} metadata; they remain in overall totals but not trait breakdowns.")
    if a_ids & b_ids:
        warnings.append("Groups share members; their observations are not independent and must not be added together.")
    if any(c["current"]["low_rating_sample"] for c in cohorts):
        warnings.append("At least one group has fewer than 10 rated events; treat its rating average as a small descriptive sample.")
    return {
        "period": {"from": start.isoformat(), "to": end.isoformat(), "days": days,
                   "previous_from": previous_start.isoformat(), "previous_to": previous_end.isoformat(), "basis": basis},
        "filters": {"dimension": dimension, "trait": trait, "search": search, "sort": sort},
        "groups": cohorts, "evidence": {"rows": evidence, "total": len(current_rows), "offset": offset, "limit": limit},
        "facets": sorted({value for row in events if start <= when(row) <= end for value in traits(row)}),
        "coverage": {**coverage, "undated_known_watches": undated, "events_without_trait": without_trait, "warnings": warnings},
        "method": "One watch is one person's recorded diary event. Rewatches remain separate. All summaries and evidence use the same title/profile and trait filters. Prior period has equal calendar length. Per-member 30-day rates adjust for group size and duration, not missing history. Ratings are pooled rated-event means, not population estimates. Monthly buckets without records are omitted, not proven inactive. Log-date mode falls back to watch date when no log date exists.",
    }


def evaluate_recommendations(service: InsightsService, requested, *, top_k=5):
    """Retrospective leave-one-member-out rating-component diagnostic.

    A hidden rating never contributes to its own ranking. This is not a
    temporal backtest or proof that unseen recommendations will work.
    """
    profiles = service._resolve_profiles(requested, minimum=2, maximum=50)
    states = service._state_rows(profiles, lightweight_enrichment=True)
    by_movie = defaultdict(list)
    for row in states:
        if row.rating is not None:
            by_movie[row.movie_id].append(row)
    ids = {p.id for p in profiles}
    results = []
    for person in profiles:
        candidates = []
        for movie_id, rows in by_movie.items():
            held_out = next((row for row in rows if row.profile_id == person.id), None)
            known = [row for row in rows if row.profile_id != person.id]
            if held_out is None or not known:
                continue
            score = _group_pick_score(ids, set(), known)
            candidates.append((score["ratings"] + score["evidence"], movie_id, held_out, mean(r.rating for r in known)))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        baseline = sorted(candidates, key=lambda item: (-item[3], item[1]))
        eligible = len(candidates) >= max(top_k * 2, 10)
        picks = candidates[:top_k] if eligible else []
        base_picks = baseline[:top_k] if eligible else []
        results.append({
            "username": person.username, "eligible_movies": len(candidates), "evaluated": eligible,
            "held_out_mean": round(mean(item[2].rating for item in picks), 3) if picks else None,
            "mean_only_baseline": round(mean(item[2].rating for item in base_picks), 3) if base_picks else None,
            "low_rated_picks": sum(item[2].rating < 3 for item in picks), "picks": len(picks),
            "examples": [{"movie_id": item[1], "title": item[2].movie.title, "held_out_rating": item[2].rating} for item in picks],
        })
    evaluated = [row for row in results if row["evaluated"]]
    return {
        "status": "available" if evaluated else "insufficient_data", "top_k": top_k,
        "members_evaluated": len(evaluated), "members_selected": len(profiles), "per_profile": results,
        "equal_member_mean": round(mean(row["held_out_mean"] for row in evaluated), 3) if evaluated else None,
        "worst_member_mean": min((row["held_out_mean"] for row in evaluated), default=None),
        "baseline_equal_member_mean": round(mean(row["mean_only_baseline"] for row in evaluated), 3) if evaluated else None,
        "method": "Hide one member's ratings, rank films using only the other members' rating evidence, then inspect the hidden ratings of the top five. Each evaluated member has equal weight. At least 10 commonly rated films are required per member. The baseline ranks by the other members' mean rating only. Canonical movie ID breaks ties.",
        "limitations": "Retrospective diagnostic of the rating component only, using films members already rated. It does not test watchlist intent, availability, unseen tastes or future satisfaction. Shared-film selection bias and missing ratings remain. No claim of statistically significant superiority is made.",
    }
