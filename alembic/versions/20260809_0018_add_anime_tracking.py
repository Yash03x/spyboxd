"""Anime as a second library, alongside films.

Spyboxd's argument is about overlap: the same title, close in time, across
several people. Nothing about that is specific to film, and the group this
instance tracks watches anime the same way -- but MyAnimeList is a separate
service with its own identities, its own catalogue and its own idea of what a
"list entry" is, so it gets its own tables rather than being forced into
`movies` and `profile_films`.

Three additions:

- `profiles.mal_username` links a tracked person to their MyAnimeList account.
  Nullable and expected to stay null for most: having a Letterboxd profile
  implies nothing about having a MAL one, and an absent link is "we do not
  know of one" rather than "they have none".
- `anime` is the catalogue, keyed by MAL's own id. Its titles, episode count
  and airing dates come from the official API rather than being derived.
- `profile_anime` is one row per person per title: their status, score,
  episode progress and the dates MAL records. Scores are 1-10 integers on MAL,
  not the half-star 0.5-5 scale films use, and are stored as MAL gives them --
  converting at write time would bake one interpretation into the store.

Nothing here is deleted on a later import: `removed_at` marks a row that has
stopped appearing, the same append-only contract the film side keeps, so a
list entry a member drops moves to lost-and-found rather than vanishing.

Revision ID: 20260809_0018
Revises: 20260802_0017
Create Date: 2026-08-09 20:40:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260809_0018"
down_revision: Union[str, None] = "20260802_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("mal_username", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_profiles_mal_username", "profiles", ["mal_username"], unique=False
    )

    op.create_table(
        "anime",
        sa.Column("id", sa.Integer(), primary_key=True),
        # MAL's own id is the identity. Titles are not: they are romanised
        # inconsistently and change, which is exactly how a catalogue ends up
        # with the same show twice.
        sa.Column("mal_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("title_english", sa.String(length=500), nullable=True),
        sa.Column("title_japanese", sa.String(length=500), nullable=True),
        sa.Column("media_type", sa.String(length=32), nullable=True),
        sa.Column("episodes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("mean_score", sa.Float(), nullable=True),
        sa.Column("poster_url", sa.String(length=1000), nullable=True),
        sa.Column("synopsis", sa.Text(), nullable=True),
        sa.Column("genres", sa.JSON(), nullable=True),
        sa.Column("studios", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_anime_mal_id", "anime", ["mal_id"], unique=True)
    op.create_index("ix_anime_title", "anime", ["title"], unique=False)

    op.create_table(
        "profile_anime",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "anime_id",
            sa.Integer(),
            sa.ForeignKey("anime.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # MAL's own vocabulary, unmapped: watching, completed, on_hold,
        # dropped, plan_to_watch. Translating it into the film side's
        # vocabulary would lose "on hold", which has no equivalent.
        sa.Column("status", sa.String(length=32), nullable=False),
        # 1-10 as MAL stores it. A 0 means unscored on MAL, so it is written
        # as NULL here -- a zero standing in for an absence is the mistake
        # this product has made before.
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("episodes_watched", sa.Integer(), nullable=True),
        sa.Column("is_rewatching", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("times_rewatched", sa.Integer(), nullable=True),
        sa.Column("started_date", sa.Date(), nullable=True),
        sa.Column("finished_date", sa.Date(), nullable=True),
        # When MAL says the entry last changed. The only timing signal the
        # list API gives, and the one an overlap has to be built from.
        sa.Column("updated_at_source", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        # Append-only, as everywhere else: an entry that stops appearing is
        # marked, never deleted.
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("profile_id", "anime_id", name="uq_profile_anime"),
    )
    op.create_index(
        "ix_profile_anime_profile_id", "profile_anime", ["profile_id"], unique=False
    )
    op.create_index(
        "ix_profile_anime_anime_id", "profile_anime", ["anime_id"], unique=False
    )
    # The overlap query's shape: everybody who finished a given title, ordered
    # by when. Without it that is a sequential scan per pair.
    op.create_index(
        "ix_profile_anime_finished",
        "profile_anime",
        ["anime_id", "finished_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_profile_anime_finished", table_name="profile_anime")
    op.drop_index("ix_profile_anime_anime_id", table_name="profile_anime")
    op.drop_index("ix_profile_anime_profile_id", table_name="profile_anime")
    op.drop_table("profile_anime")
    op.drop_index("ix_anime_title", table_name="anime")
    op.drop_index("ix_anime_mal_id", table_name="anime")
    op.drop_table("anime")
    op.drop_index("ix_profiles_mal_username", table_name="profiles")
    op.drop_column("profiles", "mal_username")
