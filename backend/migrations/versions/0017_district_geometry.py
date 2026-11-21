"""Границы районов Уфы (OpenStreetMap, ODbL) и район у обращений с координатами."""
import json
import os

from alembic import op
from sqlalchemy import text

revision = "0017_district_geometry"
down_revision = "0016_drop_empty_clusters"
branch_labels = None
depends_on = None

GEOJSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ufa_districts.geojson")


def upgrade():
    bind = op.get_bind()
    with open(GEOJSON, encoding="utf-8") as f:
        features = json.load(f)["features"]
    for ft in features:
        bind.execute(
            text(
                "UPDATE districts SET geom = ST_Multi(ST_CollectionExtract("
                "ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)), 3)) "
                "WHERE name = :n AND geom IS NULL"
            ),
            {"g": json.dumps(ft["geometry"]), "n": ft["properties"]["name"]},
        )
    op.execute("CREATE INDEX IF NOT EXISTS districts_geom_gix ON districts USING gist (geom)")
    # район у обращений, поданных с точкой, но без выбранного района
    op.execute(
        "UPDATE appeals a SET district_id = d.id FROM districts d "
        "WHERE a.district_id IS NULL AND a.lat IS NOT NULL AND a.lon IS NOT NULL AND d.geom IS NOT NULL "
        "AND ST_Covers(d.geom, ST_SetSRID(ST_MakePoint(a.lon, a.lat), 4326))"
    )
    op.execute(
        "UPDATE clusters c SET district_id = (SELECT a.district_id FROM appeals a "
        "WHERE a.cluster_id = c.id AND a.district_id IS NOT NULL ORDER BY a.id LIMIT 1) "
        "WHERE c.district_id IS NULL"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS districts_geom_gix")
