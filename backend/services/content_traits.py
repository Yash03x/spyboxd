"""Inspectable catalogue categories shared by film and anime insights.

These are metadata combinations, independent of Nanocrowd's audience-reaction
dataset. A category never implies a mood, a review sentiment, or a prediction.
"""

THEME_EXCLUSIONS = {
    "aftercreditsstinger", "duringcreditsstinger", "woman director", "women directors",
    "female director", "based on novel or book", "based on true story", "based on comic",
    "based on young adult novel", "live action remake", "remake", "sequel", "prequel",
    "imax", "3d", "silent film",
    "2d animation", "3d animation", "computer animation", "cgi", "short film",
}


def catalogue_labels(values):
    if not isinstance(values, list):
        return []
    labels = {}
    for value in values[:128]:
        name = value.get("name") if isinstance(value, dict) else value
        if isinstance(name, str) and name.strip() and len(name) <= 100:
            label = " ".join(name.split())
            labels.setdefault(label.casefold(), label)
    return sorted(labels.values(), key=str.casefold)


def film_themes(keywords):
    return [label for label in catalogue_labels(keywords)
            if label.casefold() not in THEME_EXCLUSIONS and not label.casefold().startswith('based on ')]


def microgenres(genres, themes):
    return [f"{genre} · {theme}" for genre in catalogue_labels(genres)
            for theme in catalogue_labels(themes) if genre.casefold() != theme.casefold()]
