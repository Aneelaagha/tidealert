"""initial schema

Revision ID: 110369599447
Revises:
Create Date: 2026-09-14 20:23:56.407159

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '110369599447'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Postgres enum types created by this migration, dropped explicitly on downgrade
# (drop_table does not drop the enum types its columns use).
ENUM_TYPES = [
    'risk_level', 'age_bracket', 'signal_source', 'household_status', 'item_type', 'need_status',
    'signal_type', 'case_status', 'confidence_word', 'engine', 'task_status', 'responder_status',
    'probe_channel', 'depth_reported',
]


def upgrade() -> None:
    op.create_geospatial_table('zones',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('boundary', Geometry(geometry_type='POLYGON', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.Column('region', sa.String(), nullable=False),
    sa.Column('silence_score', sa.Float(), nullable=False),
    sa.Column('isolation_minutes', sa.Integer(), nullable=True),
    sa.Column('risk_level', sa.Enum('safe', 'elevated', 'extreme', name='risk_level'), nullable=False),
    sa.Column('population_count', sa.Integer(), nullable=False),
    sa.Column('registered_count', sa.Integer(), nullable=False),
    sa.Column('current_water_depth', sa.Float(), nullable=True),
    sa.Column('flood_extent_confirmed', sa.Boolean(), nullable=False),
    sa.Column('data_confidence', sa.Integer(), nullable=False),
    sa.Column('coverage_gaps', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('typical_resolution_minutes', sa.Integer(), nullable=True),
    sa.Column('last_updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_index('idx_zones_boundary', 'zones', ['boundary'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_table('households',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('zone_id', sa.UUID(), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('age_bracket', sa.Enum('under_18', 'age_18_64', 'age_65_plus', name='age_bracket'), nullable=False),
    sa.Column('has_disability', sa.Boolean(), nullable=False),
    sa.Column('primary_language', sa.String(), nullable=False),
    sa.Column('income_bracket', sa.String(), nullable=True),
    sa.Column('is_registered', sa.Boolean(), nullable=False),
    sa.Column('contact_phone', sa.String(), nullable=True),
    sa.Column('registered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_signal_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_signal_source', sa.Enum('social', 'sms', 'mesh', 'radio', 'none', name='signal_source'), nullable=False),
    sa.Column('current_silence_score', sa.Float(), nullable=False),
    sa.Column('status', sa.Enum('unknown', 'safe', 'needs_help', 'isolated', 'rescued', name='household_status'), nullable=False),
    sa.Column('nominee_household_id', sa.UUID(), nullable=True),
    sa.Column('median_response_seconds', sa.Float(), nullable=True),
    sa.Column('response_variance_seconds', sa.Float(), nullable=True),
    sa.Column('probe_count', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['zone_id'], ['zones.id'], ),
    sa.ForeignKeyConstraint(['nominee_household_id'], ['households.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_households_zone_id', 'households', ['zone_id'], unique=False)
    op.create_table('zone_needs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('zone_id', sa.UUID(), nullable=False),
    sa.Column('item_type', sa.Enum('blankets', 'food', 'water', 'medical', 'shelter', 'boat', 'vehicle', 'other', name='item_type'), nullable=False),
    sa.Column('quantity_needed', sa.Integer(), nullable=False),
    sa.Column('quantity_fulfilled', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('open', 'partially_fulfilled', 'fulfilled', name='need_status'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['zone_id'], ['zones.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('data_sources',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('cadence_seconds', sa.Integer(), nullable=False),
    sa.Column('stale_after_seconds', sa.Integer(), nullable=False),
    sa.Column('type_default', sa.Enum('measured', 'reported', 'inferred', 'predicted', name='signal_type'), nullable=False),
    sa.Column('url', sa.String(), nullable=False),
    sa.Column('license', sa.String(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_table('signals',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('source_id', sa.UUID(), nullable=False),
    # signal_type enum was already created with data_sources.
    sa.Column('signal_type', postgresql.ENUM('measured', 'reported', 'inferred', 'predicted', name='signal_type', create_type=False), nullable=False),
    sa.Column('variable', sa.String(), nullable=False),
    sa.Column('value_num', sa.Float(), nullable=True),
    sa.Column('value_text', sa.String(), nullable=True),
    sa.Column('geometry', Geometry(geometry_type='GEOMETRY', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('corroborates_signal_id', sa.UUID(), nullable=True),
    sa.Column('conflicts_with_signal_id', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], ),
    sa.ForeignKeyConstraint(['corroborates_signal_id'], ['signals.id'], ),
    sa.ForeignKeyConstraint(['conflicts_with_signal_id'], ['signals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_index('idx_signals_geometry', 'signals', ['geometry'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_index('ix_signals_observed_at', 'signals', ['observed_at'], unique=False)
    op.create_table('gauge_readings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('signal_id', sa.UUID(), nullable=False),
    sa.Column('usgs_site_id', sa.String(), nullable=False),
    sa.Column('stage_ft', sa.Float(), nullable=False),
    sa.Column('discharge_cfs', sa.Float(), nullable=True),
    sa.Column('datum', sa.String(), nullable=True),
    sa.Column('flood_stage_ft', sa.Float(), nullable=True),
    sa.Column('moderate_stage_ft', sa.Float(), nullable=True),
    sa.Column('major_stage_ft', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['signal_id'], ['signals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_table('road_segments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('osm_way_id', sa.BigInteger(), nullable=False),
    sa.Column('geometry', Geometry(geometry_type='LINESTRING', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.Column('highway_class', sa.String(), nullable=False),
    sa.Column('is_bridge', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('is_tunnel', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('graph_edge_id', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_index('idx_road_segments_geometry', 'road_segments', ['geometry'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_index('ix_road_segments_graph_edge_id', 'road_segments', ['graph_edge_id'], unique=False)
    op.create_geospatial_table('responders',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('role', sa.String(), nullable=False),
    sa.Column('team_id', sa.String(), nullable=True),
    sa.Column('phone', sa.String(), nullable=True),
    sa.Column('last_ping_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_ping_geometry', Geometry(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('status', sa.Enum('available', 'assigned', 'off_duty', name='responder_status'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_index('idx_responders_last_ping_geometry', 'responders', ['last_ping_geometry'], unique=False, postgresql_using='gist', postgresql_ops={})

    # cases.task_id -> tasks.id is added after tasks exists (the two tables reference each other).
    op.create_table('cases',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('zone_id', sa.UUID(), nullable=False),
    sa.Column('household_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.Enum('open', 'in_progress', 'resolved', 'false_alarm', name='case_status'), nullable=False),
    sa.Column('inference_sentence', sa.Text(), nullable=False),
    sa.Column('confidence_word', sa.Enum('corroborated', 'single_source', 'stale_verify', name='confidence_word'), nullable=False),
    sa.Column('task_id', sa.UUID(), nullable=True),
    sa.Column('outcome', sa.Text(), nullable=True),
    sa.Column('validated', sa.Boolean(), nullable=True),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_contribution_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('escalated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['zone_id'], ['zones.id'], ),
    sa.ForeignKeyConstraint(['household_id'], ['households.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_cases_zone_id', 'cases', ['zone_id'], unique=False)
    op.create_index('ix_cases_status', 'cases', ['status'], unique=False)
    op.create_table('case_engine_contributions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('case_id', sa.UUID(), nullable=False),
    sa.Column('engine', sa.Enum('silence', 'isolation', 'listening', name='engine'), nullable=False),
    sa.Column('rule_fragment', sa.Text(), nullable=False),
    sa.Column('engine_confidence', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_table('tasks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('case_id', sa.UUID(), nullable=False),
    sa.Column('assigned_responder_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.Enum('pending', 'assigned', 'en_route', 'complete', name='task_status'), nullable=False),
    sa.Column('route_geometry', Geometry(geometry_type='LINESTRING', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('outcome', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['assigned_responder_id'], ['responders.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_geospatial_index('idx_tasks_route_geometry', 'tasks', ['route_geometry'], unique=False, postgresql_using='gist', postgresql_ops={})
    op.create_foreign_key('fk_cases_task_id_tasks', 'cases', 'tasks', ['task_id'], ['id'])

    op.create_table('probe_responses',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('signal_id', sa.UUID(), nullable=True),
    sa.Column('household_id', sa.UUID(), nullable=False),
    sa.Column('channel', sa.Enum('sms', 'voice', 'neighbor', name='probe_channel'), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('response_code', sa.String(), nullable=True),
    sa.Column('response_text', sa.Text(), nullable=True),
    sa.Column('depth_reported', sa.Enum('ankle', 'knee', 'waist', name='depth_reported'), nullable=True),
    sa.Column('is_corroborating', sa.Boolean(), server_default='false', nullable=False),
    sa.ForeignKeyConstraint(['signal_id'], ['signals.id'], ),
    sa.ForeignKeyConstraint(['household_id'], ['households.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('nfip_claims',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('community_id_number', sa.String(), nullable=False),
    sa.Column('county_fips', sa.String(), nullable=False),
    sa.Column('date_of_loss', sa.Date(), nullable=False),
    sa.Column('flood_zone', sa.String(), nullable=True),
    sa.Column('amount_paid_building', sa.Float(), nullable=True),
    sa.Column('amount_paid_contents', sa.Float(), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_nfip_claims_county_fips_date_of_loss', 'nfip_claims', ['county_fips', 'date_of_loss'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_nfip_claims_county_fips_date_of_loss', table_name='nfip_claims')
    op.drop_table('nfip_claims')
    op.drop_table('probe_responses')
    op.drop_constraint('fk_cases_task_id_tasks', 'cases', type_='foreignkey')
    op.drop_geospatial_index('idx_tasks_route_geometry', table_name='tasks', postgresql_using='gist', column_name='route_geometry')
    op.drop_geospatial_table('tasks')
    op.drop_table('case_engine_contributions')
    op.drop_index('ix_cases_status', table_name='cases')
    op.drop_index('ix_cases_zone_id', table_name='cases')
    op.drop_table('cases')
    op.drop_geospatial_index('idx_responders_last_ping_geometry', table_name='responders', postgresql_using='gist', column_name='last_ping_geometry')
    op.drop_geospatial_table('responders')
    op.drop_index('ix_road_segments_graph_edge_id', table_name='road_segments')
    op.drop_geospatial_index('idx_road_segments_geometry', table_name='road_segments', postgresql_using='gist', column_name='geometry')
    op.drop_geospatial_table('road_segments')
    op.drop_table('gauge_readings')
    op.drop_index('ix_signals_observed_at', table_name='signals')
    op.drop_geospatial_index('idx_signals_geometry', table_name='signals', postgresql_using='gist', column_name='geometry')
    op.drop_geospatial_table('signals')
    op.drop_table('data_sources')
    op.drop_table('zone_needs')
    op.drop_index('ix_households_zone_id', table_name='households')
    op.drop_table('households')
    op.drop_geospatial_index('idx_zones_boundary', table_name='zones', postgresql_using='gist', column_name='boundary')
    op.drop_geospatial_table('zones')

    for enum_name in ENUM_TYPES:
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
