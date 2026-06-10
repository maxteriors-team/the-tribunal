"""ad advertisers and creatives

Revision ID: c5f19e53d001
Revises: 7bafc8edd369
Create Date: 2026-06-08 17:35:51.897589

Tracks advertisers + their ads pulled from public ad libraries (Meta Ad Library,
Google Ads Transparency) so the signal engine can detect long-running,
low-iteration advertisers as outbound prospects. Only the two new tables are
created here; unrelated autogenerate drift against the existing schema was
intentionally dropped from this revision.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c5f19e53d001'
down_revision: Union[str, None] = '7bafc8edd369'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ad_advertisers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('discovery_job_id', sa.UUID(), nullable=True),
        sa.Column('prospect_id', sa.UUID(), nullable=True),
        sa.Column(
            'platform',
            sa.Enum('meta', 'google', name='adplatform', native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column('advertiser_key', sa.String(length=255), nullable=False),
        sa.Column('page_id', sa.String(length=255), nullable=True),
        sa.Column('advertiser_name', sa.String(length=512), nullable=True),
        sa.Column('page_url', sa.String(length=1024), nullable=True),
        sa.Column('website_url', sa.String(length=1024), nullable=True),
        sa.Column('website_host', sa.String(length=255), nullable=True),
        sa.Column('country_code', sa.String(length=2), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_scanned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('signal_window_days', sa.Integer(), nullable=False),
        sa.Column('total_ad_count', sa.Integer(), nullable=False),
        sa.Column('active_ad_count', sa.Integer(), nullable=False),
        sa.Column('distinct_creative_count', sa.Integer(), nullable=False),
        sa.Column('active_creative_count', sa.Integer(), nullable=False),
        sa.Column('longest_running_active_days', sa.Integer(), nullable=False),
        sa.Column('creative_refresh_rate', sa.Float(), nullable=False),
        sa.Column('continuity_score', sa.Float(), nullable=False),
        sa.Column('opportunity_score', sa.Integer(), nullable=False),
        sa.Column('platform_spread', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('media_mix', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('signals', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('example_creative', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('contact_traced', sa.Boolean(), nullable=False),
        sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['discovery_job_id'],
            ['lead_discovery_jobs.id'],
            name=op.f('fk_ad_advertisers_discovery_job_id_lead_discovery_jobs'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['prospect_id'],
            ['lead_prospects.id'],
            name=op.f('fk_ad_advertisers_prospect_id_lead_prospects'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces.id'],
            name=op.f('fk_ad_advertisers_workspace_id_workspaces'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ad_advertisers')),
        sa.UniqueConstraint(
            'workspace_id',
            'platform',
            'advertiser_key',
            name='uq_ad_advertisers_workspace_platform_key',
        ),
    )
    op.create_index(
        op.f('ix_ad_advertisers_discovery_job_id'),
        'ad_advertisers',
        ['discovery_job_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_ad_advertisers_prospect_id'),
        'ad_advertisers',
        ['prospect_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_ad_advertisers_workspace_id'),
        'ad_advertisers',
        ['workspace_id'],
        unique=False,
    )
    op.create_index(
        'ix_ad_advertisers_workspace_last_scanned',
        'ad_advertisers',
        ['workspace_id', 'last_scanned_at'],
        unique=False,
    )
    op.create_index(
        'ix_ad_advertisers_workspace_platform',
        'ad_advertisers',
        ['workspace_id', 'platform'],
        unique=False,
    )
    op.create_index(
        'ix_ad_advertisers_workspace_score',
        'ad_advertisers',
        ['workspace_id', 'opportunity_score'],
        unique=False,
        postgresql_ops={'opportunity_score': 'DESC'},
    )
    op.create_table(
        'ad_creatives',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('advertiser_id', sa.UUID(), nullable=False),
        sa.Column('ad_external_id', sa.String(length=255), nullable=False),
        sa.Column('creative_hash', sa.String(length=64), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('link_caption', sa.String(length=1024), nullable=True),
        sa.Column('link_url', sa.String(length=2048), nullable=True),
        sa.Column('link_host', sa.String(length=255), nullable=True),
        sa.Column('cta_type', sa.String(length=100), nullable=True),
        sa.Column('snapshot_url', sa.String(length=2048), nullable=True),
        sa.Column(
            'media_type',
            sa.Enum(
                'image', 'video', 'carousel', 'text', 'unknown',
                name='admediatype', native_enum=False, length=20,
            ),
            nullable=False,
        ),
        sa.Column('platforms', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('ad_delivery_start_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ad_delivery_stop_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['advertiser_id'],
            ['ad_advertisers.id'],
            name=op.f('fk_ad_creatives_advertiser_id_ad_advertisers'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces.id'],
            name=op.f('fk_ad_creatives_workspace_id_workspaces'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ad_creatives')),
        sa.UniqueConstraint(
            'advertiser_id',
            'ad_external_id',
            name='uq_ad_creatives_advertiser_ad_external_id',
        ),
    )
    op.create_index(
        'ix_ad_creatives_advertiser_active',
        'ad_creatives',
        ['advertiser_id', 'is_active'],
        unique=False,
    )
    op.create_index(
        'ix_ad_creatives_advertiser_hash',
        'ad_creatives',
        ['advertiser_id', 'creative_hash'],
        unique=False,
    )
    op.create_index(
        op.f('ix_ad_creatives_advertiser_id'),
        'ad_creatives',
        ['advertiser_id'],
        unique=False,
    )
    op.create_index(
        'ix_ad_creatives_workspace_created_at',
        'ad_creatives',
        ['workspace_id', 'created_at'],
        unique=False,
        postgresql_ops={'created_at': 'DESC'},
    )
    op.create_index(
        op.f('ix_ad_creatives_workspace_id'),
        'ad_creatives',
        ['workspace_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_ad_creatives_workspace_id'), table_name='ad_creatives')
    op.drop_index(
        'ix_ad_creatives_workspace_created_at',
        table_name='ad_creatives',
        postgresql_ops={'created_at': 'DESC'},
    )
    op.drop_index(op.f('ix_ad_creatives_advertiser_id'), table_name='ad_creatives')
    op.drop_index('ix_ad_creatives_advertiser_hash', table_name='ad_creatives')
    op.drop_index('ix_ad_creatives_advertiser_active', table_name='ad_creatives')
    op.drop_table('ad_creatives')
    op.drop_index(
        'ix_ad_advertisers_workspace_score',
        table_name='ad_advertisers',
        postgresql_ops={'opportunity_score': 'DESC'},
    )
    op.drop_index('ix_ad_advertisers_workspace_platform', table_name='ad_advertisers')
    op.drop_index('ix_ad_advertisers_workspace_last_scanned', table_name='ad_advertisers')
    op.drop_index(op.f('ix_ad_advertisers_workspace_id'), table_name='ad_advertisers')
    op.drop_index(op.f('ix_ad_advertisers_prospect_id'), table_name='ad_advertisers')
    op.drop_index(op.f('ix_ad_advertisers_discovery_job_id'), table_name='ad_advertisers')
    op.drop_table('ad_advertisers')
