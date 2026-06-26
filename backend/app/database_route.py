import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.config import DATA_DIR, DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_cursor() -> Iterator[sqlite3.Cursor]:
    conn = _connect()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn.cursor()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                flight_width REAL NOT NULL,
                protection_width REAL NOT NULL,
                bottom_height REAL NOT NULL,
                top_height REAL NOT NULL,
                min_turn_radius REAL NOT NULL DEFAULT 0,
                turn_mode TEXT NOT NULL DEFAULT 'angle',
                altitude_reference_mode TEXT NOT NULL DEFAULT 'asl',
                altitude_change_min REAL NOT NULL DEFAULT 10,
                enable_layering INTEGER NOT NULL DEFAULT 1,
                layer_step REAL NOT NULL DEFAULT 50,
                layer_scheme TEXT NOT NULL DEFAULT '60-90,90-120,120-180,180-240,240-300',
                is_complete INTEGER NOT NULL DEFAULT 0,
                last_generated_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS route_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                point_type TEXT NOT NULL DEFAULT 'waypoint',
                longitude REAL NOT NULL,
                latitude REAL NOT NULL,
                altitude REAL NOT NULL DEFAULT 0,
                order_index INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(route_id) REFERENCES routes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS landing_sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                longitude REAL NOT NULL,
                latitude REAL NOT NULL,
                altitude REAL NOT NULL DEFAULT 0,
                altitude_source TEXT NOT NULL DEFAULT 'manual',
                altitude_confirmed INTEGER NOT NULL DEFAULT 0,
                altitude_confirmed_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(route_id) REFERENCES routes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS route_full_state (
                route_id INTEGER PRIMARY KEY,
                snapshot_json TEXT NOT NULL,
                has_protection_zone INTEGER NOT NULL DEFAULT 0,
                has_altitude_layers INTEGER NOT NULL DEFAULT 0,
                is_complete INTEGER NOT NULL DEFAULT 0,
                generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(route_id) REFERENCES routes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS route_geo_extractions (
                route_id INTEGER PRIMARY KEY,
                route_name TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'osm_overpass',
                module_status_json TEXT,
                building_count INTEGER NOT NULL DEFAULT 0,
                terrain_sample_count INTEGER NOT NULL DEFAULT 0,
                terrain_record_count INTEGER NOT NULL DEFAULT 0,
                protection_zone_json TEXT,
                centerline_json TEXT,
                extracted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(route_id) REFERENCES routes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS route_geo_buildings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id INTEGER NOT NULL,
                osm_type TEXT,
                osm_id TEXT,
                name TEXT,
                longitude REAL,
                latitude REAL,
                distance_to_route_m REAL,
                height_m REAL,
                ground_elevation_m REAL,
                levels TEXT,
                building_type TEXT,
                raw_tags_json TEXT,
                FOREIGN KEY(route_id) REFERENCES routes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS route_geo_terrain (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id INTEGER NOT NULL,
                sample_index INTEGER NOT NULL,
                distance_m REAL,
                longitude REAL,
                latitude REAL,
                elevation_m REAL,
                source_ref TEXT,
                source_distance_m REAL,
                FOREIGN KEY(route_id) REFERENCES routes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS route_geo_terrain_cloud (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id INTEGER NOT NULL,
                sample_index INTEGER NOT NULL,
                distance_m REAL,
                cross_offset_m REAL DEFAULT 0,
                longitude REAL,
                latitude REAL,
                elevation_m REAL,
                source_ref TEXT,
                source_distance_m REAL,
                FOREIGN KEY(route_id) REFERENCES routes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS route_analysis_factor_inputs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id INTEGER NOT NULL,
                factor_id TEXT NOT NULL,
                input_mode TEXT NOT NULL DEFAULT 'auto',
                manual_value_json TEXT,
                param_json TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(route_id) REFERENCES routes(id) ON DELETE CASCADE,
                UNIQUE(route_id, factor_id)
            );

            CREATE TABLE IF NOT EXISTS route_analysis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id INTEGER NOT NULL,
                run_id TEXT NOT NULL,
                aircraft_type TEXT NOT NULL DEFAULT 'micro',
                status TEXT NOT NULL DEFAULT 'completed',
                total_factors INTEGER NOT NULL DEFAULT 0,
                pass_count INTEGER NOT NULL DEFAULT 0,
                fail_count INTEGER NOT NULL DEFAULT 0,
                unknown_count INTEGER NOT NULL DEFAULT 0,
                summary_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(route_id) REFERENCES routes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS route_analysis_factor_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id INTEGER NOT NULL,
                factor_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                aircraft_type TEXT NOT NULL DEFAULT 'micro',
                data_status TEXT NOT NULL DEFAULT 'unknown',
                compliance TEXT NOT NULL DEFAULT 'unknown',
                source_mode TEXT,
                evidence_json TEXT,
                next_action TEXT,
                auto_value_json TEXT,
                selected_value_json TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(route_id) REFERENCES routes(id) ON DELETE CASCADE,
                UNIQUE(route_id, factor_id)
            );

            CREATE TABLE IF NOT EXISTS route_analysis_authoritative_layers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factor_id TEXT NOT NULL,
                name TEXT NOT NULL,
                version TEXT,
                source TEXT,
                priority INTEGER NOT NULL DEFAULT 100,
                enabled INTEGER NOT NULL DEFAULT 1,
                geojson_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS import_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                import_type TEXT NOT NULL DEFAULT 'vector',
                source_format TEXT NOT NULL DEFAULT 'geojson',
                file_name TEXT NOT NULL DEFAULT '',
                source_crs TEXT,
                target_crs TEXT NOT NULL DEFAULT 'EPSG:4326',
                feature_count INTEGER NOT NULL DEFAULT 0,
                item_count INTEGER NOT NULL DEFAULT 0,
                geometry_types_json TEXT,
                bounds_json TEXT,
                metadata_json TEXT,
                is_visible INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS import_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                item_type TEXT NOT NULL DEFAULT 'generic',
                airspace_level TEXT NOT NULL DEFAULT 'suitable',
                feature_count INTEGER NOT NULL DEFAULT 0,
                geometry_types_json TEXT,
                bounds_json TEXT,
                metadata_json TEXT,
                is_visible INTEGER NOT NULL DEFAULT 1,
                is_locked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES import_projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS import_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                feature_index INTEGER NOT NULL DEFAULT 0,
                geojson_json TEXT NOT NULL,
                bounds_json TEXT,
                FOREIGN KEY(item_id) REFERENCES import_items(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS import_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                phase TEXT NOT NULL DEFAULT 'queued',
                progress REAL NOT NULL DEFAULT 0,
                message TEXT DEFAULT '',
                error TEXT,
                total_count INTEGER,
                processed_count INTEGER NOT NULL DEFAULT 0,
                result_project_id INTEGER,
                result_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS import_project_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                FOREIGN KEY(project_id) REFERENCES import_projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS imported_datasets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                import_type TEXT NOT NULL DEFAULT 'vector',
                source_format TEXT NOT NULL DEFAULT 'geojson',
                file_name TEXT NOT NULL DEFAULT '',
                source_crs TEXT,
                target_crs TEXT NOT NULL DEFAULT 'EPSG:4326',
                feature_count INTEGER NOT NULL DEFAULT 0,
                geometry_types_json TEXT,
                bounds_json TEXT,
                feature_collection_json TEXT,
                import_summary_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS takeoff_flight_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id INTEGER NOT NULL,
                landing_id INTEGER NOT NULL,
                aircraft_platform TEXT NOT NULL DEFAULT 'vtol',
                aircraft_preset TEXT NOT NULL DEFAULT 'micro',
                aircraft_params_json TEXT,
                target_layer_sequence INTEGER,
                entry_attach_point_json TEXT,
                exit_attach_point_json TEXT,
                plan_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(route_id) REFERENCES routes(id) ON DELETE CASCADE,
                FOREIGN KEY(landing_id) REFERENCES landing_sites(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                hashed_password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
