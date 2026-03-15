"""
ApiService v2.2 - Estable
FishTrace - Interconectividad API
"""

import threading
import sqlite3
import logging
import time
import requests
from datetime import datetime
from functools import wraps
from flask import Flask, jsonify
from flask_cors import CORS
from pyngrok import ngrok, conf

from Config.Config import Config
from Herramientas.SensorService import SensorService


# ================= CONFIG LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
logging.getLogger("werkzeug").setLevel(logging.WARNING)


class ApiService:

    # ================= INIT =================
    def __init__(self, port=5001):

        self.port = port
        self.ngrok_token = Config.NGROK_AUTHTOKEN.strip() if Config.NGROK_AUTHTOKEN else None

        self.app = Flask(__name__)
        CORS(self.app, resources={r"/api/*": {"origins": "*"}})
        self.app.config["JSON_SORT_KEYS"] = False

        self.running = False
        self.public_url = None

        self.server_thread = None
        self.monitor_thread = None
        self.keepalive_thread = None
        self.sensor_thread = None

        self._cache = {}
        self._live_sensors = {}          # ← Variables ambientales en vivo
        self._live_sensors_lock = threading.Lock()

        if self.ngrok_token:
            ngrok.set_auth_token(self.ngrok_token)

        self._setup_routes()

    def iniciar_ngrok(self):
        tunnel = ngrok.connect(5001)
        self.public_url = tunnel.public_url
        logger.info(f"Ngrok activo en {self.public_url}")

    def get_public_url(self):
        return self.public_url


    # ================= SENSOR POLLING =================
    def _poll_sensors(self):
        """Actualiza variables ambientales desde el WOC cada 1 segundo."""
        while self.running:
            try:
                data = SensorService.get_water_quality_data()
                if data:
                    with self._live_sensors_lock:
                        self._live_sensors = data
            except Exception as e:
                logger.warning(f"Error polling sensores: {e}")
            time.sleep(1)


    # ================= ROUTES =================
    def _setup_routes(self):

        def cached(timeout=60):
            def decorator(f):
                @wraps(f)
                def wrapper(*args, **kwargs):
                    now = time.time()
                    key = f.__name__

                    if key in self._cache:
                        data, ts = self._cache[key]
                        if now - ts < timeout:
                            return data

                    result = f(*args, **kwargs)
                    self._cache[key] = (result, now)
                    return result
                return wrapper
            return decorator


        @self.app.route('/api/health', methods=['GET'])
        def health_check():
            try:
                with sqlite3.connect(Config.DB_NAME) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM measurements")
                    count = cursor.fetchone()[0]

                with self._live_sensors_lock:
                    sensores_activos = bool(self._live_sensors)

                return jsonify({
                    "status": "healthy",
                    "service": "FishTrace API",
                    "version": "2.2",
                    "database": "connected",
                    "total_measurements": count,
                    "sensores_en_vivo": sensores_activos,
                    "timestamp": datetime.now().isoformat()
                }), 200

            except Exception as e:
                return jsonify({
                    "status": "unhealthy",
                    "error": str(e)
                }), 500


        @self.app.route('/api/last_report', methods=['GET'])
        def get_last_report():
            try:
                with sqlite3.connect(Config.DB_NAME) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()

                    cursor.execute("""
                        SELECT substr(timestamp, 1, 10) as f
                        FROM measurements
                        WHERE length_cm > 0 OR manual_length_cm > 0
                        ORDER BY timestamp DESC LIMIT 1
                    """)
                    res = cursor.fetchone()

                    if not res:
                        return jsonify({
                            "success": False,
                            "error": "No hay mediciones registradas",
                            "data": None
                        }), 404

                    ultima_fecha = res['f']

                    query = """
                    SELECT 
                        substr(timestamp, 1, 10) as fecha,
                        COUNT(*) as total_muestras,

                        ROUND(AVG(CASE WHEN manual_length_cm > 0 THEN manual_length_cm ELSE length_cm END), 2) as longitud_cm,
                        ROUND(AVG(CASE WHEN manual_weight_g > 0 THEN manual_weight_g ELSE weight_g END), 2) as peso_g,
                        ROUND(AVG(CASE WHEN manual_height_cm > 0 THEN manual_height_cm ELSE height_cm END), 2) as alto_cm,
                        ROUND(AVG(CASE WHEN manual_width_cm > 0 THEN manual_width_cm ELSE width_cm END), 2) as ancho_cm,

                        ROUND(AVG(lat_area_cm2), 2) as area_lateral_cm2,
                        ROUND(AVG(top_area_cm2), 2) as area_cenital_cm2,
                        ROUND(AVG(volume_cm3), 2) as volumen_cm3,

                        ROUND(AVG(CASE WHEN api_air_temp_c > 0 THEN api_air_temp_c ELSE NULL END), 1) as temp_aire_c,
                        ROUND(AVG(CASE WHEN api_water_temp_c > 0 THEN api_water_temp_c ELSE NULL END), 1) as temp_agua_c,
                        ROUND(AVG(CASE WHEN api_ph > 0 THEN api_ph ELSE NULL END), 1) as ph,
                        ROUND(AVG(CASE WHEN api_do_mg_l > 0 THEN api_do_mg_l ELSE NULL END), 1) as oxigeno_mg_l,
                        ROUND(AVG(CASE WHEN api_rel_humidity > 0 THEN api_rel_humidity ELSE NULL END), 1) as humedad_rel,
                        ROUND(AVG(CASE WHEN api_turbidity_ntu > 0 THEN api_turbidity_ntu ELSE NULL END), 1) as turbidez_ntu,
                        ROUND(AVG(CASE WHEN api_cond_us_cm > 0 THEN api_cond_us_cm ELSE NULL END), 1) as conductividad_us

                    FROM measurements 
                    WHERE substr(timestamp, 1, 10) = ?
                    """

                    cursor.execute(query, (ultima_fecha,))
                    reporte = cursor.fetchone()

                # ← Snapshot seguro de los sensores en vivo
                with self._live_sensors_lock:
                    live = dict(self._live_sensors)

                data = {
                    "fecha": reporte["fecha"],
                    "total_muestras": reporte["total_muestras"],

                    "biometria": {
                        "longitud_cm": reporte["longitud_cm"],
                        "peso_g": reporte["peso_g"],
                        "alto_cm": reporte["alto_cm"],
                        "ancho_cm": reporte["ancho_cm"]
                    },

                    "geometria": {
                        "area_lateral_cm2": reporte["area_lateral_cm2"],
                        "area_cenital_cm2": reporte["area_cenital_cm2"],
                        "volumen_cm3": reporte["volumen_cm3"]
                    },

                    # Prioridad: valor en vivo del WOC → fallback a promedio DB
                    "sensores": {
                        "temperatura": {
                            "aire_c":  live.get("api_air_temp_c",   reporte["temp_aire_c"]),
                            "agua_c":  live.get("api_water_temp_c", reporte["temp_agua_c"])
                        },
                        "calidad_agua": {
                            "ph":               live.get("api_ph",            reporte["ph"]),
                            "oxigeno_mg_l":     live.get("api_do_mg_l",       reporte["oxigeno_mg_l"]),
                            "turbidez_ntu":     live.get("api_turbidity_ntu", reporte["turbidez_ntu"]),
                            "conductividad_us": live.get("api_cond_us_cm",    reporte["conductividad_us"])
                        },
                        "ambiente": {
                            "humedad_rel": live.get("api_rel_humidity", reporte["humedad_rel"])
                        }
                    },

                    "sensores_en_vivo": bool(live)   # ← indica si los datos son frescos
                }

                return jsonify({
                    "success": True,
                    "timestamp": datetime.now().isoformat(),
                    "data": data
                }), 200

            except Exception as e:
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500
            
        @self.app.route('/api/stats', methods=['GET'])
        def get_statistics():
            try:
                with sqlite3.connect(Config.DB_NAME) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()

                    cursor.execute("""
                        SELECT 
                            COUNT(*) as total_mediciones,
                            COUNT(DISTINCT substr(timestamp, 1, 10)) as dias_activos,
                            MIN(substr(timestamp, 1, 10)) as primera_medicion,
                            MAX(substr(timestamp, 1, 10)) as ultima_medicion,
                            ROUND(AVG(CASE WHEN manual_length_cm > 0 THEN manual_length_cm ELSE length_cm END), 2) as longitud_promedio,
                            ROUND(AVG(CASE WHEN manual_weight_g > 0 THEN manual_weight_g ELSE weight_g END), 2) as peso_promedio
                        FROM measurements
                        WHERE length_cm > 0 OR manual_length_cm > 0
                    """)

                    stats = cursor.fetchone()

                    return jsonify({
                        "success": True,
                        "data": {
                            "total_mediciones": stats["total_mediciones"],
                            "dias_activos": stats["dias_activos"],
                            "primera_medicion": stats["primera_medicion"],
                            "ultima_medicion": stats["ultima_medicion"],
                            "promedios_historicos": {
                                "longitud_cm": stats["longitud_promedio"],
                                "peso_g": stats["peso_promedio"]
                            }
                        }
                    }), 200

            except Exception as e:
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500
            
        @self.app.errorhandler(404)
        def not_found(error):
            return jsonify({
                "success": False,
                "error": "Endpoint no encontrado",
                "available_endpoints": [
                    "/api/health",
                    "/api/last_report",
                    "/api/stats"
                ]
            }), 404


    # ================= SERVER =================
    def _run_server(self):
        try:
            self.app.run(
                host="0.0.0.0",
                port=self.port,
                use_reloader=False,
                threaded=True
            )
        except Exception as e:
            logger.error(f"Flask error: {e}")
            self.running = False


    # ================= TUNNEL =================
    def _start_tunnel(self):
        try:
            ngrok.kill()
            conf.get_default().request_timeout = 30

            tunnel = ngrok.connect(
                addr=self.port,
                proto="http",
                domain="keitha-groveless-tari.ngrok-free.dev",
                bind_tls=True
            )

            self.public_url = tunnel.public_url
            logger.info(f"Ngrok activo en {self.public_url}")

        except Exception as e:
            logger.error(f"Error túnel: {e}")
            self.public_url = None


    # ================= MONITOR =================
    def _monitor(self):
        while self.running:
            time.sleep(120)

            try:
                tunnels = ngrok.get_tunnels()
                if not tunnels:
                    logger.warning("Túnel caído. Reconectando...")
                    self._start_tunnel()

            except Exception:
                self._start_tunnel()


    # ================= KEEP ALIVE =================
    def _keep_alive(self):
        while self.running:
            time.sleep(300)
            try:
                if self.public_url:
                    requests.get(self.public_url + "/api/health", timeout=10)
            except:
                pass


    # ================= START =================
    def start(self):

        if self.running:
            return

        self.running = True

        # Flask
        self.server_thread = threading.Thread(
            target=self._run_server,
            daemon=True
        )
        self.server_thread.start()

        time.sleep(2)

        # Túnel
        self._start_tunnel()

        # Monitor
        self.monitor_thread = threading.Thread(
            target=self._monitor,
            daemon=True
        )
        self.monitor_thread.start()

        # KeepAlive
        self.keepalive_thread = threading.Thread(
            target=self._keep_alive,
            daemon=True
        )
        self.keepalive_thread.start()

        # Sensor Polling (cada 1 segundo)
        self.sensor_thread = threading.Thread(
            target=self._poll_sensors,
            daemon=True
        )
        self.sensor_thread.start()
        logger.info("Polling de sensores IoT iniciado (intervalo: 1s)")


    # ================= STOP =================
    def stop(self):
        self.running = False
        try:
            ngrok.kill()
        except:
            pass


    # ================= STATUS =================
    def get_status_info(self):
        if self.running and self.public_url:
            return "API Online", "Online", self.public_url

        elif self.running:
            return "API Local", "Local", f"http://localhost:{self.port}"

        else:
            return "API Offline", "Offline", None

    def get_live_sensors(self):
        """Retorna una copia thread-safe del último snapshot de sensores IoT."""
        try:
            with self._live_sensors_lock:
                return dict(self._live_sensors)
        except Exception as e:
            logger.warning(f"No se pudo obtener snapshot de sensores: {e}")
            return {}
        
    # ================= ENTRY POINT =================
    def main():
        api_service = ApiService()
        api_service.start()

        time.sleep(3)

        status, url = api_service.get_status_info()
        logger.info(f"Servicio API iniciado | Estado: {status} | URL: {url}")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            api_service.stop()
            logger.info("Servicio detenido.")


    if __name__ == "__main__":
        main()