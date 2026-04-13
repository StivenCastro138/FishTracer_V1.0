"""
PROYECTO: FishTrace - Trazabilidad de Crecimiento de Peces
MÓDULO: Gestión de Persistencia (DatabaseManager.py)
DESCRIPCIÓN: Administra la base de datos SQLite, manejando el ciclo de vida de los datos,
            migraciones de esquema, índices de rendimiento y consultas biométricas.
"""

import sqlite3
import os
import csv
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# ESQUEMA DE DATOS Y DEFINICIÓN DE COLUMNAS
# ============================================================================
MEASUREMENT_COLUMNS = (
    'id', 'timestamp', 'fish_id', 
    'length_cm', 'height_cm', 'width_cm', 'weight_g',
    'manual_length_cm', 'manual_height_cm', 'manual_width_cm', 'manual_weight_g',
    'lat_area_cm2', 'top_area_cm2', 'volume_cm3',
    'confidence_score', 'notes', 'image_path', 
    'measurement_type', 'validation_errors',

    'api_air_temp_c', 'api_water_temp_c', 
    'api_rel_humidity', 'api_abs_humidity_g_m3',
    'api_ph', 'api_cond_us_cm', 'api_do_mg_l', 'api_turbidity_ntu',
    'batch_id'
)

MEASUREMENT_COLUMNS_STR = ', '.join(MEASUREMENT_COLUMNS)

class DatabaseManager:
    """
    Controlador central para operaciones CRUD y administración de SQLite.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Inicializa el gestor y asegura la existencia del archivo de base de datos.
        """
        if db_path is None:
            folder = "BasedeDatos"
            os.makedirs(folder, exist_ok=True)
            db_path = os.path.join(folder, "database.db")
        
        self.db_path = db_path
        self._column_cache: Optional[Dict[str, int]] = None
        self.init_database()
    
    # ========================================================================
    # INICIALIZACIÓN Y MIGRACIONES
    # ========================================================================
    def init_database(self) -> None:
        """Crea la estructura relacional (tablas e índices) si no existe en el sistema.
        Define tablas para: Mediciones, Calibraciones y Perfiles de Especies."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Tabla de mediciones biométricas y ambientales
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                fish_id TEXT,
                
                length_cm REAL,
                height_cm REAL,
                width_cm REAL,
                weight_g REAL,
                
                manual_length_cm REAL,
                manual_height_cm REAL,
                manual_width_cm REAL,
                manual_weight_g REAL,
                
                lat_area_cm2 REAL,
                top_area_cm2 REAL,
                volume_cm3 REAL,
                
                confidence_score REAL,
                notes TEXT,
                image_path TEXT,
                measurement_type TEXT DEFAULT 'manual',
                validation_errors TEXT,

                api_air_temp_c REAL,
                api_water_temp_c REAL,
                api_rel_humidity REAL,
                api_abs_humidity_g_m3 REAL,
                api_ph REAL,
                api_cond_us_cm REAL,
                api_do_mg_l REAL, 
                api_turbidity_ntu REAL,
                batch_id TEXT
            )
        ''')
        
        # Tabla de histórico de calibraciones de cámaras y visión
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS calibrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                
                scale_lat_front REAL NOT NULL,
                scale_lat_back REAL NOT NULL,
                scale_top_front REAL NOT NULL,
                scale_top_back REAL NOT NULL,
                
                hsv_left_h_min INTEGER, hsv_left_h_max INTEGER,
                hsv_left_s_min INTEGER, hsv_left_s_max INTEGER,
                hsv_left_v_min INTEGER, hsv_left_v_max INTEGER,
                
                hsv_top_h_min INTEGER, hsv_top_h_max INTEGER,
                hsv_top_s_min INTEGER, hsv_top_s_max INTEGER,
                hsv_top_v_min INTEGER, hsv_top_v_max INTEGER,
                
                notes TEXT
            )
        ''')
        
        # Tabla de perfiles de especies
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS species_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                weight_k REAL,
                weight_exp REAL,
                shape_factor REAL,
                notes TEXT
            )
        ''')
        
        conn.commit()
        
        # Ejecutar migraciones
        self.migrate_database(cursor, conn)
        
        # Crear índices
        self._create_indexes(cursor, conn)
        
        conn.close()
        logger.info("Base de datos inicializada correctamente.")
    
    def migrate_database(self, cursor: sqlite3.Cursor, conn: sqlite3.Connection) -> None:
        """
        Gestiona la evolución del esquema de datos. Agrega nuevas columnas
        a bases de datos existentes sin afectar la integridad de registros previos.
        """
        new_columns_meas = {
            'height_cm': 'REAL',
            'width_cm': 'REAL',
            'manual_length_cm': 'REAL',
            'manual_height_cm': 'REAL', 
            'manual_width_cm': 'REAL',
            'manual_weight_g': 'REAL',
            'lat_area_cm2': 'REAL',
            'top_area_cm2': 'REAL',
            'measurement_type': "TEXT DEFAULT 'manual'",
            'validation_errors': 'TEXT',
            
            'api_air_temp_c': 'REAL',
            'api_water_temp_c': 'REAL',
            'api_rel_humidity': 'REAL',
            'api_abs_humidity_g_m3': 'REAL',
            'api_ph': 'REAL',
            'api_cond_us_cm': 'REAL',
            'api_do_mg_l': 'REAL',
            'api_turbidity_ntu': 'REAL',
            'batch_id': 'TEXT'
        }
        
        cursor.execute("PRAGMA table_info(measurements)")
        existing_cols_meas = {col[1] for col in cursor.fetchall()}
        
        for col_name, col_type in new_columns_meas.items():
            if col_name not in existing_cols_meas:
                try:
                    cursor.execute(f'ALTER TABLE measurements ADD COLUMN {col_name} {col_type}')
                    logger.info(f"Columna '{col_name}' agregada a measurements.")
                except sqlite3.OperationalError as e:
                    logger.error(f"Error migrando measurements ({col_name}): {e}.")

        # Compatibilidad: todo registro histórico sin tanda pasa a TANDA_1.
        try:
            cursor.execute(
                """
                UPDATE measurements
                SET batch_id = 'TANDA_1'
                WHERE batch_id IS NULL OR trim(batch_id) = ''
                """
            )
        except sqlite3.OperationalError as e:
            logger.error(f"Error aplicando backfill de tanda historica: {e}")

        conn.commit()
        self._column_cache = None

    def _create_indexes(self, cursor: sqlite3.Cursor, conn: sqlite3.Connection) -> None:
        """Optimiza la velocidad de respuesta para consultas de filtrado y ordenamiento."""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_timestamp ON measurements(timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_fish_id ON measurements(fish_id)",
            "CREATE INDEX IF NOT EXISTS idx_measurement_type ON measurements(measurement_type)",
            "CREATE INDEX IF NOT EXISTS idx_batch_id ON measurements(batch_id)"
        ]
        for idx_query in indexes:
            try:
                cursor.execute(idx_query)
            except sqlite3.OperationalError:
                pass
        conn.commit()
    
    # ========================================================================
    # OPERACIONES DE PERSISTENCIA (CRUD)
    # ========================================================================
    def save_measurement(self, data: Dict[str, Any]) -> int:
        """Registra una nueva medición biométrica."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        lat_area = data.get('lat_area_cm2', data.get('area_cm2', 0))
        top_area = data.get('top_area_cm2', 0)
        
        cursor.execute('''
            INSERT INTO measurements 
            (timestamp, fish_id, length_cm, height_cm, width_cm, weight_g,
             manual_length_cm, manual_height_cm, manual_width_cm, manual_weight_g,
             lat_area_cm2, top_area_cm2, volume_cm3, 
             confidence_score, notes, image_path, measurement_type, validation_errors,
             api_air_temp_c, api_water_temp_c, api_rel_humidity, 
             api_abs_humidity_g_m3, api_ph, api_cond_us_cm, api_do_mg_l, api_turbidity_ntu, batch_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('timestamp', datetime.now().isoformat()),
            data.get('fish_id', ''), 
            data.get('length_cm', 0),
            data.get('height_cm', 0),
            data.get('width_cm', 0),
            data.get('weight_g', 0),
            
            data.get('manual_length_cm'),
            data.get('manual_height_cm'),
            data.get('manual_width_cm'),
            data.get('manual_weight_g'),
            
            lat_area,
            top_area,
            data.get('volume_cm3', 0),
            
            data.get('confidence_score', 0), 
            data.get('notes', ''), 
            data.get('image_path', ''),
            data.get('measurement_type', 'auto'),
            data.get('validation_errors', ''),
            
            data.get('api_air_temp_c', 0),
            data.get('api_water_temp_c', 0),
            data.get('api_rel_humidity', 0),
            data.get('api_abs_humidity_g_m3', 0),
            data.get('api_ph', 0),
            data.get('api_cond_us_cm', 0),
            data.get('api_do_mg_l', 0),
            data.get('api_turbidity_ntu', 0),
            data.get('batch_id', '')
        ))
        
        conn.commit()
        measurement_id = cursor.lastrowid
        conn.close()
        
        logger.info("Medicion guardada: ID=%s", measurement_id)
            
        return measurement_id
    
    def get_measurement_as_dict(self, m_id):
        """Retorna un registro completo mapeado como diccionario"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row 
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM measurements WHERE id = ?", (m_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error al obtener diccionario de medicion: {e}")
            return None
    
    def get_measurement_by_id(self, measurement_id: int) -> Optional[Tuple]:
        """Recupera UNA medición por su ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            f"SELECT {MEASUREMENT_COLUMNS_STR} FROM measurements WHERE id = ?", 
            (measurement_id,)
        )
        result = cursor.fetchone()
        conn.close()
        return result
    
    def update_measurement(self, measurement_id: int, data: Dict[str, Any]) -> bool:
        """Actualiza una medición existente."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        lat_area = data.get('lat_area_cm2', data.get('area_cm2', 0))
        
        cursor.execute('''
            UPDATE measurements 
            SET timestamp = ?, fish_id = ?, 
                length_cm = ?, height_cm = ?, width_cm = ?, weight_g = ?,
                manual_length_cm = ?, manual_height_cm = ?, manual_width_cm = ?, manual_weight_g = ?,
                lat_area_cm2 = ?, top_area_cm2 = ?, volume_cm3 = ?,
                notes = ?, measurement_type = ?, validation_errors = ?,
                api_air_temp_c = ?, api_water_temp_c = ?, api_rel_humidity = ?,
                api_abs_humidity_g_m3 = ?, api_ph = ?, api_cond_us_cm = ?, api_do_mg_l = ?, api_turbidity_ntu = ?,
                batch_id = ?
            WHERE id = ?
        ''', (
            data.get('timestamp', ''),
            data.get('fish_id', ''),
            data.get('length_cm', 0),
            data.get('height_cm', 0),
            data.get('width_cm', 0),
            data.get('weight_g', 0),
            
            data.get('manual_length_cm'),
            data.get('manual_height_cm'),
            data.get('manual_width_cm'),
            data.get('manual_weight_g'),
            
            lat_area,
            data.get('top_area_cm2', 0),
            data.get('volume_cm3', 0),
            
            data.get('notes', ''),
            data.get('measurement_type', 'manual'),
            data.get('validation_errors', ''),
            
            data.get('api_air_temp_c', 0),
            data.get('api_water_temp_c', 0),
            data.get('api_rel_humidity', 0),
            data.get('api_abs_humidity_g_m3', 0),
            data.get('api_ph', 0),
            data.get('api_cond_us_cm', 0),
            data.get('api_do_mg_l', 0),
            data.get('api_turbidity_ntu', 0),
            data.get('batch_id', ''),
            
            measurement_id
        ))
        
        conn.commit()
        affected_rows = cursor.rowcount
        conn.close()
        return affected_rows > 0
    
    def delete_measurement(self, measurement_id: int) -> bool:
        """Elimina una medición por ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM measurements WHERE id = ?", (measurement_id,))
        conn.commit()
        affected_rows = cursor.rowcount
        conn.close()
        return affected_rows > 0
    
    def execute_query(self, query: str, parameters: tuple = (), fetchone: bool = False, fetchall: bool = False) -> Any:
        """Ejecuta una consulta SQL"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, parameters)
                
                if fetchone:
                    return cursor.fetchone()
                if fetchall:
                    return cursor.fetchall()
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error ejecutando query '{query}': {e}")
            return None if (fetchone or fetchall) else False
        
    def get_image_path(self, measurement_id):
        query = "SELECT image_path FROM measurements WHERE id = ?"
        result = self.execute_query(query, (measurement_id,), fetchone=True)
        return result[0] if result else None
    
    # ========================================================================
    # UTILIDADES DE ACCESO
    # ========================================================================
    def get_filtered_measurements(
        self, 
        limit: Optional[int] = 100, 
        offset: int = 0, 
        search_query: Optional[str] = None, 
        filter_type: Optional[str] = None, 
        batch_id: Optional[str] = None,
        excluded_batch_ids: Optional[List[str]] = None,
        date_start: Optional[str] = None, 
        date_end: Optional[str] = None
    ) -> List[Tuple]:
        """Consulta optimizada con índices y filtros."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            where_clause, params = self._build_measurements_filters(
                search_query=search_query,
                filter_type=filter_type,
                batch_id=batch_id,
                excluded_batch_ids=excluded_batch_ids,
                date_start=date_start,
                date_end=date_end,
            )
            query = f"SELECT {MEASUREMENT_COLUMNS_STR} FROM measurements WHERE {where_clause}"
            
            query += " ORDER BY timestamp DESC"
            
            if limit is not None:
                query += " LIMIT ? OFFSET ?"
                params.extend([limit, offset])
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            conn.close()
            return results
        
        except Exception as e:
            logger.error("Error en get_filtered_measurements", exc_info=True)
            return []

    def get_filtered_measurements_count(
        self,
        search_query: Optional[str] = None,
        filter_type: Optional[str] = None,
        batch_id: Optional[str] = None,
        excluded_batch_ids: Optional[List[str]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> int:
        """Retorna el total de registros para los filtros aplicados."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            where_clause, params = self._build_measurements_filters(
                search_query=search_query,
                filter_type=filter_type,
                batch_id=batch_id,
                excluded_batch_ids=excluded_batch_ids,
                date_start=date_start,
                date_end=date_end,
            )

            cursor.execute(
                f"SELECT COUNT(*) FROM measurements WHERE {where_clause}",
                params,
            )
            result = cursor.fetchone()
            conn.close()
            return int(result[0]) if result else 0
        except Exception:
            logger.error("Error en get_filtered_measurements_count", exc_info=True)
            return 0

    def get_filtered_measurements_quick_totals(
        self,
        search_query: Optional[str] = None,
        filter_type: Optional[str] = None,
        batch_id: Optional[str] = None,
        excluded_batch_ids: Optional[List[str]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Retorna totales rápidos para la vista de historial."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            where_clause, params = self._build_measurements_filters(
                search_query=search_query,
                filter_type=filter_type,
                batch_id=batch_id,
                excluded_batch_ids=excluded_batch_ids,
                date_start=date_start,
                date_end=date_end,
            )

            cursor.execute(
                f'''
                SELECT
                    COUNT(*) AS total,
                    AVG(CASE WHEN length_cm > 0 THEN length_cm END) AS avg_length,
                    AVG(CASE WHEN weight_g > 0 THEN weight_g END) AS avg_weight,
                    SUM(CASE WHEN measurement_type LIKE 'manual%' THEN 1 ELSE 0 END) AS manual_total,
                    SUM(CASE WHEN measurement_type NOT LIKE 'manual%' THEN 1 ELSE 0 END) AS auto_total
                FROM measurements
                WHERE {where_clause}
                ''',
                params,
            )

            row = cursor.fetchone()
            conn.close()

            if not row:
                return {
                    "total": 0,
                    "avg_length": 0.0,
                    "avg_weight": 0.0,
                    "manual_total": 0,
                    "auto_total": 0,
                }

            return {
                "total": int(row[0] or 0),
                "avg_length": float(row[1] or 0.0),
                "avg_weight": float(row[2] or 0.0),
                "manual_total": int(row[3] or 0),
                "auto_total": int(row[4] or 0),
            }
        except Exception:
            logger.error("Error en get_filtered_measurements_quick_totals", exc_info=True)
            return {
                "total": 0,
                "avg_length": 0.0,
                "avg_weight": 0.0,
                "manual_total": 0,
                "auto_total": 0,
            }

    def _build_measurements_filters(
        self,
        search_query: Optional[str] = None,
        filter_type: Optional[str] = None,
        batch_id: Optional[str] = None,
        excluded_batch_ids: Optional[List[str]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> Tuple[str, List[Any]]:
        """Construye la cláusula WHERE y sus parámetros."""
        query = "1=1"
        params: List[Any] = []

        if filter_type and filter_type not in ["Todas", "Todos", None]:
            query += " AND measurement_type = ?"
            params.append(filter_type)

        if batch_id and batch_id not in ["Todas", "Todos", None, ""]:
            query += " AND COALESCE(batch_id, '') = ?"
            params.append(batch_id)

        if excluded_batch_ids:
            cleaned = [b for b in excluded_batch_ids if b and b not in ["Todas", "Todos"]]
            if cleaned:
                placeholders = ", ".join(["?" for _ in cleaned])
                query += f" AND COALESCE(batch_id, '') NOT IN ({placeholders})"
                params.extend(cleaned)

        if date_start:
            query += " AND date(timestamp) >= date(?)"
            params.append(date_start)

        if date_end:
            query += " AND date(timestamp) <= date(?)"
            params.append(date_end)

        if search_query:
            query += " AND (fish_id LIKE ? OR notes LIKE ? OR CAST(id AS TEXT) LIKE ?)"
            wildcard = f"%{search_query}%"
            params.extend([wildcard, wildcard, wildcard])

        return query, params
    
    def get_today_measurements_count(self) -> int:
        """Cuenta mediciones del día actual."""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM measurements WHERE date(timestamp) = ?", (today,))
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0
        
    def save_calibration(self, scale_lat_front: float, scale_lat_back: float, 
                         scale_top_front: float, scale_top_back: float, 
                         hsv_left: Optional[Dict] = None, hsv_top: Optional[Dict] = None, 
                         notes: str = "") -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        default_hsv = {'h_min': 35, 'h_max': 85, 's_min': 40, 's_max': 255, 'v_min': 40, 'v_max': 255}
        hsv_l = hsv_left if hsv_left else default_hsv
        hsv_t = hsv_top if hsv_top else default_hsv
        
        cursor.execute('''
            INSERT INTO calibrations 
            (timestamp, 
             scale_lat_front, scale_lat_back, scale_top_front, scale_top_back,
             hsv_left_h_min, hsv_left_h_max, hsv_left_s_min, hsv_left_s_max, hsv_left_v_min, hsv_left_v_max,
             hsv_top_h_min, hsv_top_h_max, hsv_top_s_min, hsv_top_s_max, hsv_top_v_min, hsv_top_v_max,
             notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            scale_lat_front, scale_lat_back, scale_top_front, scale_top_back,
            hsv_l['h_min'], hsv_l['h_max'], hsv_l['s_min'], hsv_l['s_max'], hsv_l['v_min'], hsv_l['v_max'],
            hsv_t['h_min'], hsv_t['h_max'], hsv_t['s_min'], hsv_t['s_max'], hsv_t['v_min'], hsv_t['v_max'],
            notes
        ))
        
        conn.commit()
        calib_id = cursor.lastrowid
        conn.close()
        return calib_id
    
    def get_latest_calibration(self) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT scale_lat_front, scale_lat_back, scale_top_front, scale_top_back,
                   hsv_left_h_min, hsv_left_h_max, hsv_left_s_min, hsv_left_s_max, hsv_left_v_min, hsv_left_v_max,
                   hsv_top_h_min, hsv_top_h_max, hsv_top_s_min, hsv_top_s_max, hsv_top_v_min, hsv_top_v_max,
                   timestamp
            FROM calibrations ORDER BY timestamp DESC LIMIT 1
        ''')
        
        result = cursor.fetchone()
        conn.close()
        
        if not result: return None
        
        return {
            'scale_lat_front': result[0], 'scale_lat_back': result[1],
            'scale_top_front': result[2], 'scale_top_back': result[3],
            'hsv_left': {'h_min': result[4], 'h_max': result[5], 's_min': result[6], 's_max': result[7], 'v_min': result[8], 'v_max': result[9]},
            'hsv_top': {'h_min': result[10], 'h_max': result[11], 's_min': result[12], 's_max': result[13], 'v_min': result[14], 'v_max': result[15]},
            'timestamp': result[16]
        }
    
   # ========================================================================
    # HELPERS
    # ========================================================================
    def get_field_value(self, measurement_row: Any, field_name: str, default: Any = None) -> Any:
        """Extrae valores de forma robusta."""
        if not measurement_row: return default
        if isinstance(measurement_row, dict): return measurement_row.get(field_name, default)
        
        if self._column_cache is None: self._rebuild_column_cache()
        
        if field_name in self._column_cache:
            idx = self._column_cache[field_name]
            try:
                value = measurement_row[idx]
                return value if value is not None else default
            except (IndexError, KeyError):
                return default
        return default
    
    def _rebuild_column_cache(self) -> None:
        """Mapea los nombres de columnas a sus índices."""
        try:
            self._column_cache = {col: i for i, col in enumerate(MEASUREMENT_COLUMNS)}
        except Exception as e:
            logger.error(f"Error reconstruyendo cache de columnas: {e}")
            self._column_cache = {}
            
    def get_next_fish_number(self, batch_id: Optional[str] = None) -> int:
            """
            Calcula el siguiente número secuencial para el ID del pez 
            basado en los registros del día actual.
            """
            try:
                
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()

                    if batch_id:
                        query = "SELECT COUNT(*) FROM measurements WHERE COALESCE(batch_id, '') = ?"
                        cursor.execute(query, (batch_id,))
                    else:
                        today_str = datetime.now().strftime('%Y-%m-%d')
                        query = "SELECT COUNT(*) FROM measurements WHERE timestamp LIKE ?"
                        cursor.execute(query, (f"{today_str}%",))
                    
                    count = cursor.fetchone()[0]
                    return count + 1
            except Exception as e:
                logger.error(f"Error calculando siguiente ID secuencial: {e}")
                return 1 

    def get_distinct_batches(self) -> List[str]:
        """Retorna las tandas existentes ordenadas por uso reciente."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT COALESCE(batch_id, '') AS batch_id, MAX(timestamp) AS last_ts
                    FROM measurements
                    GROUP BY COALESCE(batch_id, '')
                    HAVING batch_id <> ''
                    ORDER BY last_ts DESC
                    """
                )
                rows = cursor.fetchall()
                return [str(row[0]) for row in rows if row and row[0]]
        except Exception as e:
            logger.error(f"Error obteniendo tandas: {e}")
            return []

    def get_batch_summaries(self) -> List[Dict[str, Any]]:
        """Obtiene resumen por tanda: cantidad y rango temporal."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT
                        COALESCE(batch_id, '') AS batch_id,
                        COUNT(*) AS total,
                        MIN(date(timestamp)) AS first_day,
                        MAX(date(timestamp)) AS last_day,
                        MAX(timestamp) AS last_ts
                    FROM measurements
                    GROUP BY COALESCE(batch_id, '')
                    HAVING batch_id <> ''
                    ORDER BY last_ts DESC
                    """
                )
                rows = cursor.fetchall()
                return [
                    {
                        "batch_id": str(row["batch_id"]),
                        "total": int(row["total"] or 0),
                        "first_day": row["first_day"],
                        "last_day": row["last_day"],
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error obteniendo resumen de tandas: {e}")
            return []

    def rename_batch(self, old_batch_id: str, new_batch_id: str) -> int:
        """Renombra una tanda existente."""
        if not old_batch_id or not new_batch_id or old_batch_id == new_batch_id:
            return 0
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE measurements
                    SET batch_id = ?
                    WHERE COALESCE(batch_id, '') = ?
                    """,
                    (new_batch_id, old_batch_id),
                )
                conn.commit()
                return int(cursor.rowcount or 0)
        except Exception as e:
            logger.error(f"Error renombrando tanda: {e}")
            return 0

    def assign_batch_by_date_range(self, batch_id: str, date_start: str, date_end: str) -> int:
        """Asigna tanda a registros en rango de fechas [date_start, date_end]."""
        if not batch_id or not date_start or not date_end:
            return 0
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE measurements
                    SET batch_id = ?
                    WHERE date(timestamp) >= date(?)
                      AND date(timestamp) <= date(?)
                    """,
                    (batch_id, date_start, date_end),
                )
                conn.commit()
                return int(cursor.rowcount or 0)
        except Exception as e:
            logger.error(f"Error asignando tanda por rango: {e}")
            return 0

    def delete_batch(self, batch_id: str, replacement_batch_id: str = "TANDA_1") -> int:
        """Elimina una tanda reasignando sus registros a otra tanda segura."""
        if not batch_id or batch_id == replacement_batch_id:
            return 0
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE measurements
                    SET batch_id = ?
                    WHERE COALESCE(batch_id, '') = ?
                    """,
                    (replacement_batch_id, batch_id),
                )
                conn.commit()
                return int(cursor.rowcount or 0)
        except Exception as e:
            logger.error(f"Error eliminando tanda: {e}")
            return 0
            
    def invalidate_cache(self) -> None:
        self._column_cache = None

    def reset_measurements_cycle(
        self,
        backup_dir: Optional[str] = None,
        delete_images: bool = False,
    ) -> Dict[str, Any]:
        """
        Reinicia una nueva tanda de mediciones de forma segura.

        - Respalda la tabla `measurements` a CSV (si hay registros).
        - Elimina registros de mediciones.
        - Reinicia el AUTOINCREMENT de `measurements`.
        - Opcionalmente elimina imágenes asociadas.

        No toca calibraciones ni perfiles de especies.
        """
        summary: Dict[str, Any] = {
            "success": False,
            "total_before": 0,
            "deleted_rows": 0,
            "deleted_images": 0,
            "backup_path": None,
            "errors": [],
        }

        if backup_dir is None:
            backup_dir = os.path.join("Resultados", "CSV", "Respaldos")

        os.makedirs(backup_dir, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM measurements ORDER BY timestamp ASC")
            rows = cursor.fetchall()
            summary["total_before"] = len(rows)

            if not rows:
                summary["success"] = True
                return summary

            image_paths: List[str] = []
            if delete_images:
                for row in rows:
                    img = row["image_path"] if "image_path" in row.keys() else None
                    if img:
                        image_paths.append(str(img))

            backup_name = f"backup_mediciones_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            backup_path = os.path.join(backup_dir, backup_name)

            fieldnames = rows[0].keys()
            with open(backup_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([str(name).upper() for name in fieldnames])
                for row in rows:
                    writer.writerow([row[name] for name in fieldnames])

            summary["backup_path"] = backup_path

            cursor.execute("BEGIN")
            cursor.execute("DELETE FROM measurements")
            summary["deleted_rows"] = cursor.rowcount if cursor.rowcount is not None else len(rows)

            try:
                cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'measurements'")
            except sqlite3.OperationalError:
                # Algunos entornos SQLite no exponen sqlite_sequence en ciertas condiciones.
                pass

            conn.commit()

            if delete_images:
                for img_path in image_paths:
                    try:
                        abs_path = os.path.abspath(img_path)
                        if os.path.exists(abs_path):
                            os.remove(abs_path)
                            summary["deleted_images"] += 1
                    except Exception as e:
                        summary["errors"].append(f"No se pudo eliminar imagen '{img_path}': {e}")

            summary["success"] = True
            logger.info(
                "Reinicio de tanda completado | filas=%s | imagenes=%s | backup=%s",
                summary["deleted_rows"],
                summary["deleted_images"],
                summary["backup_path"],
            )
            return summary

        except Exception as e:
            conn.rollback()
            summary["errors"].append(str(e))
            logger.error("Error al reiniciar tanda de mediciones: %s", e, exc_info=True)
            return summary
        finally:
            conn.close()
