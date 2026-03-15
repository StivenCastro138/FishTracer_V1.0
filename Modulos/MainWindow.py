
"""
PROYECTO: FishTrace - Trazabilidad de Crecimiento de Peces
MÓDULO: Ventana Principal de Control (MainWindow.py)
DESCRIPCIÓN: Núcleo de la Interfaz Gráfica de Usuario (GUI).
             Esta clase actúa como el 'Controlador Maestro' de la aplicación, integrando:
             1. Visualización de video en tiempo real (Soporte para Cámaras Estéreo).
             2. Panel de control para operarios (Captura, Calibración, Configuración).
             3. Dashboard de telemetría (Gráficas de crecimiento, Sensores IoT).
             4. Gestión del ciclo de vida de los hilos de procesamiento (FrameProcessor).
"""

import os
import time
import json
import csv
import re
import shutil
import threading
import logging
import platform
import subprocess
import urllib.request
from collections import deque
from datetime import datetime, timedelta
import numpy as np
import cv2
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import qtawesome as qta  
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtCore import (
    Qt, QTimer, QSize, QDate, QTime, QUrl,
    QPropertyAnimation, QEasingCurve, QAbstractAnimation
)
from PySide6.QtGui import (
    QImage, QPixmap, QColor, QFont, QIcon, QIntValidator, QAction,
    QPainter, QPen
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSystemTrayIcon,
    QVBoxLayout, QHBoxLayout, QGridLayout, QSplitter,
    QPushButton, QLabel, QTextEdit, QProgressBar,
    QTabWidget, QTabBar, QGroupBox, QFrame,
    QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox,
    QFileDialog, QMessageBox, QDialog, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QListWidget, QListWidgetItem,
    QSizePolicy, QDateEdit, QTimeEdit,
    QAbstractItemView, QStyle, QGraphicsOpacityEffect, QMenu
)
import sqlite3
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Image, PageBreak, Table, TableStyle
)
import qdarktheme
import darkdetect
import qrcode

import io
from scipy.optimize import curve_fit

from BasedeDatos.DatabaseManager import DatabaseManager
from BasedeDatos.DatabaseManager import MEASUREMENT_COLUMNS
from Config.Config import Config
from Herramientas.SensorService import SensorService
from .FishDetector import FishDetector
from .FishTracker import FishTracker
from .FrameProcessor import FrameProcessor
from .StatusBar import StatusBar
from .SensorBar import SensorTopBar
from .MeasurementValidator import MeasurementValidator
from .EditMeasurementDialog import EditMeasurementDialog
from .BiometryService import BiometryService
from .ImageViewerDialog import ImageViewerDialog
from Modulos.AdvancedDetector import AdvancedDetector
from .FishAnatomyValidator import FishAnatomyValidator
from .CaptureDecisionDialog import CaptureDecisionDialog
from .OptimizedCamera import OptimizedCamera
from .ApiService import ApiService
from Herramientas.mobil import (
    start_flask_server,
    mobile_capture_queue,
    get_local_ip,
    build_mobile_access_url,
)

logger = logging.getLogger(__name__)

os.environ["OPENCV_VIDEOIO_DEBUG"] = "0"
os.environ["OPENCV_LOG_LEVEL"] = "OFF"


class CameraAspectLabel(QLabel):
    """QLabel que mantiene relación de aspecto fija (16:9 por defecto)."""

    def __init__(self, ratio_w: int = 16, ratio_h: int = 9, parent=None):
        super().__init__(parent)
        self._ratio_w = max(1, ratio_w)
        self._ratio_h = max(1, ratio_h)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return max(1, int(width * self._ratio_h / self._ratio_w))

    def sizeHint(self) -> QSize:
        base_w = 640
        return QSize(base_w, self.heightForWidth(base_w))

class MainWindow(QMainWindow):

    SPIN_CONFIGS = {
        'length': {'range': (0.1, 200.0), 'decimals': 2, 'suffix': ' cm'},
        'height': {'range': (0.1, 100.0), 'decimals': 2, 'suffix': ' cm'},
        'width':  {'range': (0.1, 100.0), 'decimals': 2, 'suffix': ' cm'},
        'weight': {'range': (0.1, 1000.0), 'decimals': 1, 'suffix': ' g'},
        'area': {'range': (0.1, 1000.0), 'decimals': 1, 'suffix': ' cm2'},
        'volume': {'range': (0.1, 1000.0), 'decimals': 1, 'suffix': ' cm3'},
        'hue_min': {'range': (0.1, 1000.0), 'decimals': 1},
        'hue_max': {'range': (0.1, 1000.0), 'decimals': 1},
        'sat_min': {'range': (0.1, 1000.0), 'decimals': 1},
        'sat_max': {'range': (0.1, 1000.0), 'decimals': 1},
        'val_min': {'range': (0.1, 1000.0), 'decimals': 1},
        'val_max': {'range': (0.1, 1000.0), 'decimals': 1},
    }
    EMOJI_STATES = {
        "✅": "success", "✓": "success", "💾": "success", "🚀": "success",
        "❌": "error", "⛔": "error", "🗑️": "error", 
        "⚠️": "warning", "⏳": "warning", 
        "🔄": "info", "🔍": "info", "📊": "info", "✏️": "info",
        "📷": "info", "▶️": "info", "⚙️": "info", "🧠": "info"
    }
    
    def __init__(self, api_service: ApiService = None):
        super().__init__()
        self.api_service = api_service
        self.setWindowTitle("FishTrace v1.2b")
        self.setGeometry(100, 100, 1600, 1000)
            
        # CONFIGURACIÓN INICIAL DE LÓGICA 
        os.makedirs(Config.OUT_DIR, exist_ok=True)
        self.db = DatabaseManager()
        
        self.advanced_detector = AdvancedDetector()
        self.processor = FrameProcessor(self.advanced_detector)
        self.detector = FishDetector() 
        self.tracker = FishTracker()
        self.anatomy_validator = FishAnatomyValidator()

        # VARIABLES DE ESTADO 
        self.cap_left = None
        self.cap_top = None
        self.current_frame_left = None 
        self.current_frame_top = None
        self.auto_capture_enabled = False
        self.last_result = None
        self.cameras_connected = False
        self.scale_front_left = Config.SCALE_LAT_FRONT
        self.scale_back_left = Config.SCALE_LAT_BACK
        self.scale_front_top = Config.SCALE_TOP_FRONT
        self.scale_back_top = Config.SCALE_TOP_BACK
        self.preview_fps = Config.PREVIEW_FPS
        self.processing_lock = False  
        self.current_tab = 0
        self.tablet_mode_enabled = False
        self._pre_tablet_density = "Normal"
        self._pre_tablet_font = 11
        self._camera_read_failures = 0
        self._left_signal_failures = 0
        self._top_signal_failures = 0
        self._cam_health_left = "warning"
        self._cam_health_top = "warning"
        self._auto_reconnect_attempts = 0
        self._auto_reconnect_running = False
        self._microcuts_left = deque()
        self._microcuts_top = deque()
        self.settings_dirty = False
        self._settings_change_guard = False
        self._fallback_sensor_cache = {}
        self._last_fallback_sensor_pull = 0.0
        self.sensor_env_ranges = {
            "temp_agua": (18.0, 32.0),
            "ph": (6.5, 8.5),
            "cond": (100.0, 2000.0),
            "turb": (0.0, 100.0),
            "do": (4.0, 14.0),
        }
        self.quick_notes = [
            "Sin observaciones",
            "Pez en buen estado",
            "Leve movimiento durante captura",
            "Revisar en próxima medición"
        ]
        self._general_defaults = {
            'theme': 'Sistema',
            'font_size': '11',
            'density': 'Normal',
            'animations': 'Normales',
            'high_contrast': False,
            'cam_left_index': 1,
            'cam_top_index': 0,
            'min_contour_area': 1500,
            'max_contour_area': 20000,
            'confidence_threshold': 0.6,
            'min_length_cm': 4.0,
            'max_length_cm': 50.0,
            'sensor_env_ranges': {
                'temp_agua': (18.0, 32.0),
                'ph': (6.5, 8.5),
                'cond': (100.0, 2000.0),
                'turb': (0.0, 100.0),
                'do': (4.0, 14.0),
            },
        }
        self._quick_note_combos = []

        # INICIALIZAR UI
        self.setWindowIcon(QIcon("logo.ico"))
        self.load_config()
        self.init_ui()
        self.init_tray()
        self.sync_ui_with_config()
        self.apply_appearance()
        self.toggle_theme("Sistema")
        
        self.ram_timer = QTimer(self)
        self.alert_timer = QTimer(self) # Timer para el parpadeo
        self.is_alert_icon = False      # Estado del parpadeo

        # 2. LUEGO HACEMOS LAS CONEXIONES
        if hasattr(self.processor, 'signals'):
            self.processor.signals.ia_time_ready.connect(self.status_bar.set_ia_time)
        
        # Conexiones del procesador
        self.processor.progress_update.connect(self.on_progress_update)
        self.processor.result_ready.connect(self.on_processing_complete)
        
        # Conexiones de la API y Salud del Sistema
        # NOTA: StatusBar tiene su propio timer_hw de 1s para CPU/RAM/GPU.
        # update_api_status_ui consolida: actualizar StatusBar + lógica de alerta en bandeja.
        self.ram_timer.timeout.connect(self.update_api_status_ui)
        self.sensor_bar_timer = QTimer(self)
        self.sensor_bar_timer.timeout.connect(self.update_environment_topbar)
        
        # Conexión del motor de parpadeo
        self.alert_timer.timeout.connect(self.toggle_alert_icon)
        
        # 3. FINALMENTE INICIAMOS LOS TIMERS
        self.ram_timer.start(5000)
        self.sensor_bar_timer.start(1500)
        
        self.save_sound = QSoundEffect(self)
        self.save_sound.setSource(QUrl.fromLocalFile(os.path.abspath("save_ok.wav")))
        self.save_sound.setVolume(1)
        
        try:
            count = self.db.get_today_measurements_count()
            self.status_bar.set_measurement_count(count)
        except Exception as e:
            logger.error(f"Error al cargar contador inicial: {e}.")
            
        self.cache_params = {
            'min_area': 5000,
            'max_area': 500000,
            'conf': 0.6,
            'hsv_lat': [0, 0, 0, 0, 0, 0], 
            'hsv_top': [0, 0, 0, 0, 0, 0]
        }
        
        self.spin_min_area.valueChanged.connect(self.update_cache)
        self.spin_max_area.valueChanged.connect(self.update_cache)
        self.spin_confidence.valueChanged.connect(self.update_cache)

        self.spin_hue_min_lat.valueChanged.connect(self.update_cache)
        self.spin_hue_max_lat.valueChanged.connect(self.update_cache)
        self.spin_sat_min_lat.valueChanged.connect(self.update_cache)
        self.spin_sat_max_lat.valueChanged.connect(self.update_cache)
        self.spin_val_min_lat.valueChanged.connect(self.update_cache)
        self.spin_val_max_lat.valueChanged.connect(self.update_cache)

        self.spin_hue_min_top.valueChanged.connect(self.update_cache)
        self.spin_hue_max_top.valueChanged.connect(self.update_cache)
        self.spin_sat_min_top.valueChanged.connect(self.update_cache)
        self.spin_sat_max_top.valueChanged.connect(self.update_cache)
        self.spin_val_min_top.valueChanged.connect(self.update_cache)
        self.spin_val_max_top.valueChanged.connect(self.update_cache)

        self.update_cache()
        logger.info("Sistema de variables espejo (Cache) sincronizado.")
        
        # VARIABLES DE FPS Y ARRANQUE 
        self.adaptive_fps = True
        self.last_frame_time = time.time()
        self.frames_skipped = 0
        self.fps_counter = 0
        self.last_fps_update = time.time()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frames)

        self.processor.start()
        cameras_ok = self.start_cameras()
        self._configure_camera_tabs(cameras_ok, choose_startup=True)
        self.status_bar.set_status("Sistema listo. Esperando captura")
        
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.on_tab_changed)  
        main_layout.addWidget(self.tabs)
        
        measurement_tab = self.create_measurement_tab()
        self.tabs.addTab(measurement_tab, "Medición Automática")
        
        manual_tab = self.create_manual_tab()
        self.tabs.addTab(manual_tab, "Medición Manual")
        
        history_tab = self.create_history_tab()
        self.tabs.addTab(history_tab, "Historial")
             
        stats_tab = self.create_statistics_tab()
        self.tabs.addTab(stats_tab, "Estadísticas")
        
        settings_tab = self.create_settings_tab()
        self.tabs.addTab(settings_tab, " Configuración")

        self.sensor_top_bar = SensorTopBar(self)
        self.sensor_top_bar.btn_tablet.toggled.connect(self.toggle_tablet_mode)
        self.sensor_top_bar.set_ranges(self.sensor_env_ranges)
        self.tabs.setCornerWidget(self.sensor_top_bar, Qt.TopRightCorner)
        
        self.status_bar = StatusBar(self)
        main_layout.addWidget(self.status_bar)
        
        self.tabs.tabBar().setTabToolTip(0, "Medición automática desde cámara y sensores")
        self.tabs.tabBar().setTabButton(0, QTabBar.RightSide, None)

        # Medición Manual
        self.tabs.tabBar().setTabToolTip(1, "Ingreso manual de datos de medición")

        # Historial
        self.tabs.tabBar().setTabToolTip(2, "Historial de mediciones guardadas")

        # Estadísticas
        self.tabs.tabBar().setTabToolTip(3, "Análisis y estadísticas de mediciones")

        # Configuración
        self.tabs.tabBar().setTabToolTip(4, "Parámetros y configuración del sistema")

        self.tabs.tabBar().setCursor(Qt.PointingHandCursor)
           
    def update_api_status_ui(self):
        """Sincroniza la API con StatusBar y gestiona la alerta de bandeja.
        Consolida update_api_status_ui + check_api_health_for_tray en una sola
        llamada a get_status_info() por tick del timer.
        """
        if not (hasattr(self, 'api_service') and self.api_service):
            return

        text, state, url = self.api_service.get_status_info()
        self.status_bar.update_api_status(text, state, url)

        # Alerta de bandeja: parpadeo si no hay túnel público activo
        api_ok = state == "success" and url is not None
        if not api_ok:
            if not self.alert_timer.isActive():
                logger.warning("API sin túnel público. Activando alerta visual.")
                self.alert_timer.start(600)
        else:
            if self.alert_timer.isActive():
                self.alert_timer.stop()

    def update_environment_topbar(self):
        """Actualiza la barra superior con variables ambientales recientes."""
        if not hasattr(self, "sensor_top_bar"):
            return

        sensor_data = {}

        if hasattr(self, "api_service") and self.api_service and hasattr(self.api_service, "get_live_sensors"):
            sensor_data = self.api_service.get_live_sensors() or {}
        else:
            now = time.time()
            if now - self._last_fallback_sensor_pull > 8.0:
                self._fallback_sensor_cache = SensorService.get_water_quality_data() or {}
                self._last_fallback_sensor_pull = now
            sensor_data = self._fallback_sensor_cache

        self.sensor_top_bar.update_values(sensor_data)

    def _apply_sensor_ranges_from_ui(self):
        """Sincroniza rangos de alerta ambiental desde la pestaña Configuración."""
        if not all(hasattr(self, name) for name in (
            "spin_env_temp_min", "spin_env_temp_max",
            "spin_env_ph_min", "spin_env_ph_max",
            "spin_env_cond_min", "spin_env_cond_max",
            "spin_env_turb_min", "spin_env_turb_max",
            "spin_env_do_min", "spin_env_do_max",
        )):
            return

        def _ordered(a: float, b: float) -> tuple[float, float]:
            return (a, b) if a <= b else (b, a)

        self.sensor_env_ranges = {
            "temp_agua": _ordered(self.spin_env_temp_min.value(), self.spin_env_temp_max.value()),
            "ph": _ordered(self.spin_env_ph_min.value(), self.spin_env_ph_max.value()),
            "cond": _ordered(self.spin_env_cond_min.value(), self.spin_env_cond_max.value()),
            "turb": _ordered(self.spin_env_turb_min.value(), self.spin_env_turb_max.value()),
            "do": _ordered(self.spin_env_do_min.value(), self.spin_env_do_max.value()),
        }

        if hasattr(self, "sensor_top_bar"):
            self.sensor_top_bar.set_ranges(self.sensor_env_ranges)

    def toggle_tablet_mode(self, enabled: bool):
        """Activa o desactiva modo táctil para mejorar uso sin mouse."""
        self.tablet_mode_enabled = enabled

        theme = self.combo_theme.currentText() if hasattr(self, "combo_theme") else "Sistema"

        if enabled:
            if hasattr(self, "combo_density"):
                self._pre_tablet_density = self.combo_density.currentText() or "Normal"
            if hasattr(self, "combo_font_size"):
                try:
                    self._pre_tablet_font = int(self.combo_font_size.currentText() or "11")
                except ValueError:
                    self._pre_tablet_font = 11

            target_font = max(13, self._pre_tablet_font)
            self.toggle_theme(theme, target_font, "Táctil")

            if hasattr(self, "combo_density"):
                self.combo_density.blockSignals(True)
                if self.combo_density.findText("Táctil") != -1:
                    self.combo_density.setCurrentText("Táctil")
                self.combo_density.blockSignals(False)

            if hasattr(self, "combo_font_size"):
                self.combo_font_size.blockSignals(True)
                self.combo_font_size.setCurrentText(str(target_font))
                self.combo_font_size.blockSignals(False)

            self.status_bar.set_status("Modo táctil activado", "info")
        else:
            self.toggle_theme(theme, self._pre_tablet_font, self._pre_tablet_density)

            if hasattr(self, "combo_density"):
                self.combo_density.blockSignals(True)
                self.combo_density.setCurrentText(self._pre_tablet_density)
                self.combo_density.blockSignals(False)

            if hasattr(self, "combo_font_size"):
                self.combo_font_size.blockSignals(True)
                self.combo_font_size.setCurrentText(str(self._pre_tablet_font))
                self.combo_font_size.blockSignals(False)

            self.status_bar.set_status("Modo táctil desactivado", "info")

        if hasattr(self, "sensor_top_bar"):
            self.sensor_top_bar.set_tablet_mode(enabled)
            
    def draw_fish_overlay(self, image, data):
        """
        Motor de anotación.
        """
        if image is None: return None
        img = image.copy()
        h, w = img.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX
        
        sc = w / 2200 
        
        p_w, p_h = int(220 * sc), int(100 * sc)
        cv2.rectangle(img, (0, 0), (p_w, p_h), (15, 15, 15), -1) 
        cv2.rectangle(img, (0, 0), (p_w, p_h), (0, 255, 255), 1) 

        curr_y = int(20 * sc) 
        
        cv2.putText(img, f"{data['tipo']}: {data['numero']}", (int(8*sc), curr_y), 
                    font, 0.5*sc, (0, 255, 255), 1, cv2.LINE_AA)
        
        curr_y += int(22 * sc)
        cv2.putText(img, f"L: {data['longitud']:.2f}cm", (int(8*sc), curr_y), 
                    font, 0.45*sc, (0, 255, 0), 1, cv2.LINE_AA)
        
        curr_y += int(20 * sc)
        cv2.putText(img, f"W: {data['peso']:.1f}g", (int(8*sc), curr_y), 
                    font, 0.45*sc, (0, 255, 0), 1, cv2.LINE_AA)

        curr_y += int(18 * sc)
        cv2.putText(img, data['fecha'], (int(8*sc), curr_y), 
                    font, 0.38*sc, (180, 180, 180), 1, cv2.LINE_AA)

        return img

    def on_processing_complete(self, result):
        """
        Coordina: Desbloqueo, Validación, UI, Auto-captura
        """
        # LIBERAR RECURSOS Y UI 
        self.processing_lock = False
        
        if hasattr(self, 'btn_capture'):
            self.btn_capture.setEnabled(True)
            self.btn_capture.setText("Capturar y Analizar")
            self.btn_capture.setProperty("class", "primary")
            icon_color = self.btn_capture.palette().buttonText().color()
            self.btn_capture.setIcon(qta.icon("fa5s.camera", color=icon_color))
            self._refresh_widget_style(self.btn_capture)

        if hasattr(self, 'btn_manual_ai_assist'):
            self.btn_manual_ai_assist.setEnabled(True)
            self.btn_manual_ai_assist.setText("Analizar y Rellenar con IA")
            self.btn_qr.setEnabled(False)
            
        if hasattr(self, 'btn_qr'):
            self.btn_qr.setEnabled(True)

        # VALIDACIÓN ROBUSTA DEL RESULTADO
        if not result or not isinstance(result, dict):
            self._show_error_result("❌ Error: No se recibió resultado del procesador")
            return
        
        metrics = result.get('metrics', {})
        if not metrics or not isinstance(metrics, dict):
            self._show_error_result("❌ Error: Resultado sin métricas válidas")
            return
        
        length_cm = metrics.get('length_cm')
        if length_cm is None or not isinstance(length_cm, (int, float)) or length_cm <= 0:
            self._show_error_result(
                "❌ La IA no pudo detectar el pez con claridad.\n\n"
                "💡 Sugerencias:\n"
                "   • Asegúrate de que el pez esté completamente visible\n"
                "   • Verifica la iluminación del fondo\n"
                "   • Ajusta los valores HSV en Configuración"
            )
            return

        # EXTRACCIÓN SEGURA DE DATOS
        self.last_result = result
        self.last_metrics = metrics

        contour_left = result.get('contour_left')
        contour_top  = result.get('contour_top')

        if hasattr(self, 'tracker'):
            self.tracker.update(
                metrics, 
                contour_left=contour_left,  # Usar la variable ya extraída
                contour_top=contour_top,    # Usar la variable ya extraída
                timestamp=time.time()
            )

        confidence = float(result.get('confidence', 0.0))
        
        # VALIDACIÓN ANATÓMICA Y BIOMÉTRICA
        val_anatomica = result.get('fish_validation_left', {})
        val_biometrica = MeasurementValidator.validate_measurement(metrics)
        
        warnings = []
        
        # Advertencias de detección

        if contour_left is None and contour_top is None:
            warnings.append("⚠️ No se detectaron contornos válidos")
        elif contour_left is None:
            warnings.append("⚠️ Falta contorno lateral")
        elif contour_top is None:
            warnings.append("⚠️ Falta contorno cenital")
        if not val_anatomica.get('is_fish', True):
            warnings.append("⚠️ Forma anatómica inusual detectada")
        if confidence < Config.CONFIDENCE_THRESHOLD:
            warnings.append(f"⚠️ Confianza baja ({confidence:.0%})")
        
        # Advertencias biométricas
        warnings.extend(val_biometrica)
        
        # ACTUALIZAR VISTAS CON BOUNDING BOXES
        frame_l = result.get('frame_left')
        frame_t = result.get('frame_top')
        
        if frame_l is not None and frame_t is not None:
            frame_l_copy = frame_l.copy()
            frame_t_copy = frame_t.copy()
            
            # Dibujar bounding boxes
            for key, frame in [('box_lat', frame_l_copy), ('box_top', frame_t_copy)]:
                box = result.get(key)
                if box and len(box) == 4:
                    x1, y1, x2, y2 = map(int, box)
                    color = (0, 255, 0) if not warnings else (0, 165, 255)  
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
                    
                    # Etiqueta con confianza
                    label = f"{confidence:.0%}"
                    cv2.putText(frame, label, (x1, y1-10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
            
            self.display_frame(frame_l_copy, self.lbl_left)
            self.display_frame(frame_t_copy, self.lbl_top)
        
        if hasattr(self, 'confidence_bar'):
            target_value = int(confidence * 100)
            
            self.confidence_bar.setValue(0) 
            self._animate_confidence(0, target_value) 

        if self.tabs.currentIndex() == 1:  
            self._auto_fill_manual_form(metrics, confidence)

        self._update_results_report(metrics, confidence, warnings, result)
        fish_detected = (
            contour_left is not None
            and contour_top is not None
            and confidence >= Config.CONFIDENCE_THRESHOLD
        )

        self._handle_stability_and_autocapture(
            result,
            confidence,
            warnings,
            fish_detected
        )

    def _animate_confidence(self, current_value, target_value):
        """
        Anima la barra de confianza usando QPropertyAnimation.
        Se adapta a la velocidad configurada.
        """
        
        if not hasattr(self, 'confidence_bar'):
            return
        
        if self.anim_duration == 0:
            self.confidence_bar.setValue(target_value)
            
            if target_value >= 80:
                new_level = "high"
            elif target_value >= 60:
                new_level = "medium"
            else:
                new_level = "low"
            
            self.confidence_bar.setProperty("level", new_level)
            self.confidence_bar.style().unpolish(self.confidence_bar)
            self.confidence_bar.style().polish(self.confidence_bar)
            return
        
        anim = QPropertyAnimation(self.confidence_bar, b"value")
        anim.setDuration(self.anim_duration * 3)  
        anim.setStartValue(current_value)
        anim.setEndValue(target_value)
        
        if self.anim_duration <= 150:
            anim.setEasingCurve(QEasingCurve.OutCubic)  
        else:
            anim.setEasingCurve(QEasingCurve.OutElastic)
        
        def update_level():
            val = self.confidence_bar.value()
            if val >= 80:
                new_level = "high"
            elif val >= 60:
                new_level = "medium"
            else:
                new_level = "low"
            
            self.confidence_bar.setProperty("level", new_level)
            self.confidence_bar.style().unpolish(self.confidence_bar)
            self.confidence_bar.style().polish(self.confidence_bar)
        
        anim.valueChanged.connect(lambda: update_level())
        anim.start()
        
        # Guardar referencia para evitar garbage collection
        self.confidence_bar._current_anim = anim

    def _set_results_style(self, style_key):
        """Aplica estilos centralizados usando ESTADOS, no CSS manual"""
        state = style_key 
        
        self.results_text.setProperty("state", state)
        self.results_text.style().unpolish(self.results_text)
        self.results_text.style().polish(self.results_text)
        
    def on_progress_update(self, message):
        """ Actualiza barra de estado y resultados con arquitectura de ESTADOS """
        
        if hasattr(self, 'status_bar'):
            state = "normal"
            
            for emoji, mapped_state in self.EMOJI_STATES.items():
                if emoji in message:
                    state = mapped_state
                    break
            
            self.status_bar.set_status(message, state)
        
        if not hasattr(self, 'results_text'): return
        
        important_keywords = ["Detectando", "Calculando", "Analizando", "Procesando", 
                              "Validando", "Midiendo", "Completado", "Finalizado", 
                              "Listo", "Error", "Fallo", "Advertencia", "✅", "❌", "⚠️"]
        
        if not any(k in message for k in important_keywords): return
        
        current_text = self.results_text.toPlainText()
        has_final_report = "═" in current_text and len(current_text) > 200 and "RESULTADOS" in current_text
        
        if has_final_report:
            if "❌" in message or "Error" in message:
                self.results_text.append(f"\n{message}")
            return
        
        if not current_text or "═" in current_text:
            self.results_text.clear()
            if "Error" in message or "❌" in message:
                self._set_results_style("error")
            elif "⚠️" in message:
                self._set_results_style("warning")
            elif "✅" in message or "Listo" in message:
                self._set_results_style("success") 
            else:
                self._set_results_style("info")
        
        if getattr(Config, 'DEBUG_MODE', False):
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            message = f"[{timestamp}] {message}"
        
        self.results_text.append(message)

        sb = self.results_text.verticalScrollBar()
        if sb.value() >= sb.maximum() - 50:
            sb.setValue(sb.maximum())

        if len(self.results_text.toPlainText()) > 5000: 
             self.results_text.setPlainText(self.results_text.toPlainText()[-4000:])

    def _show_error_result(self, message):
        """Muestra errores usando estilo centralizado y estados lógicos"""
        self.results_text.clear()
        
        self._set_results_style("error")
        self.results_text.setPlainText(message)
        
        if hasattr(self, 'status_bar'):
            self.status_bar.set_status("Error en detección", "error")
            
        if hasattr(self, 'confidence_bar'):
            self.confidence_bar.setValue(0)
            self.confidence_bar.setProperty("state", "idle") 
            self.confidence_bar.style().unpolish(self.confidence_bar)
            self.confidence_bar.style().polish(self.confidence_bar)

    def get_next_fish_number(self) -> int:
        """Calcula el siguiente número secuencial basado en el total de registros"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM measurements")
                count = cursor.fetchone()[0]
                return count + 1
        except Exception as e:
            logger.error(f"Error calculando secuencia: {e}.")
            return 1
        
    def _auto_fill_manual_form(self, metrics, confidence):
        """
        Rellena formulario manual con validación y estilos limpios
        """
        try:
            field_mapping = {
                'spin_manual_length': metrics.get('length_cm', 0.0),
                'spin_manual_weight': metrics.get('weight_g', 0.0),
                'spin_manual_height': metrics.get('height_cm', 0.0),
                'spin_manual_width': metrics.get('width_cm', metrics.get('thickness_cm', 0.0))
            }
            
            for widget_name, value in field_mapping.items():
                if hasattr(self, widget_name):
                    widget = getattr(self, widget_name)
                    
                    widget.blockSignals(True)
                    widget.setValue(float(value) if value else 0.0)
                    widget.blockSignals(False)

                    widget.setProperty("state", "success")
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)

                    QTimer.singleShot(1000, lambda w=widget: self._reset_widget_style(w))
            
            if hasattr(self, 'txt_manual_fish_id') and not self.txt_manual_fish_id.text():
                
            
                if hasattr(self, 'db'):
                    next_num = self.db.get_next_fish_number()
                else:
                    next_num = int(time.time()) 
                
                auto_id = f"IA_{next_num}"
                self.txt_manual_fish_id.setText(auto_id)
            
                self.txt_manual_fish_id.setProperty("state", "success")
                self.txt_manual_fish_id.style().unpolish(self.txt_manual_fish_id)
                self.txt_manual_fish_id.style().polish(self.txt_manual_fish_id)
                
                QTimer.singleShot(2000, lambda: self._reset_widget_style(self.txt_manual_fish_id))

            if hasattr(self, 'btn_manual_save'):
                self.btn_manual_save.setEnabled(True)
                self.btn_manual_save.setProperty("class", "success")
                self.btn_manual_save.style().unpolish(self.btn_manual_save)
                self.btn_manual_save.style().polish(self.btn_manual_save)

            if hasattr(self, 'txt_manual_notes'):
                current_notes = self.txt_manual_notes.text()
                ia_note = f"[IA: {confidence:.0%} confianza]"
                
                if ia_note not in current_notes:
                    new_notes = f"{current_notes} {ia_note}".strip()
                    self.txt_manual_notes.setText(new_notes)
  
            self.status_bar.set_status(f"Formulario rellenado (Confianza: {confidence:.0%})", "success")
            
            logger.info(f"Formulario manual auto-rellenado con confianza {confidence:.0%}.")
            
        except Exception as e:
            logger.error(f"Error en auto-rellenado manual: {e}.", exc_info=True)
            self.status_bar.set_status("Error al rellenar formulario", "warning")

    def _reset_widget_style(self, widget):
        """Helper para limpiar el estado visual"""
        widget.setProperty("state", "") 
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _update_results_report(self, metrics, confidence, warnings, result):
        """Reporte visual con validación de datos"""
        
        length_cm = metrics.get('length_cm') or 0
        weight_g = metrics.get('weight_g') or 0
        height_cm = metrics.get('height_cm') or 0
        width_cm = metrics.get('width_cm') or 0
        lat_area_cm2 = metrics.get('lat_area_cm2') or 0
        top_area_cm2 = metrics.get('top_area_cm2') or 0
        volume_cm3 = metrics.get('volume_cm3') or 0

        warning_block = ""
        if warnings:
            warning_block = "⚠️ ADVERTENCIAS:\n" + "\n".join([f"   {w}" for w in warnings]) + "\n\n"
        
        if hasattr(self, 'tracker'):
            stats = self.tracker.get_tracking_stats()
            if stats['quality'] == 0 and confidence > 0.5:
                stats = {'quality': 100, 'is_consistent': True}
        else:
            stats = {'quality': 0, 'is_consistent': False}
        
        output = f"""
    {'═'*60}
    🐟 RESULTADOS DEL ANÁLISIS BIOMÉTRICO
    {'═'*60}

    {warning_block}📏 DIMENSIONES MORFOMÉTRICAS:
    • Longitud Estimada:  {length_cm:.2f} cm
    • Peso Estimado:   {weight_g:.1f} g
    • Altura Estimada:   {height_cm:.2f} cm
    • Ancho Estimado:   {width_cm:.2f} cm
    • Área Lateral Estimada: {lat_area_cm2:.2f} cm²
    • Área Cenital Estimada: {top_area_cm2:.2f} cm²
    • Volumen Estimado: {volume_cm3:.2f} cm³
    

    📊 MÉTRICAS DE CALIDAD:
    • Confianza IA:    {confidence:.1%} {'✓' if confidence >= 0.7 else '⚠️'}
    • Tracking:        {stats['quality']:.0f}% {'(Consistente)' if stats['is_consistent'] else '(Variable)'}
    • Estabilidad:     {'✓ Estable' if result.get('is_stable', False) else '⚠️ En Movimiento'}

    {'═'*60}
    {'✅ DATOS VALIDADOS - Listo para guardar' if not warnings else '⚠️ Revise las advertencias antes de guardar'}
    {'═'*60}
    """
        self._set_results_style("success" if not warnings else "warning")
        self.results_text.setPlainText(output)
        
        if hasattr(self, 'btn_save'):
            self.btn_save.setEnabled(True)
            self.btn_save.setCursor(Qt.PointingHandCursor)
            self.btn_save.setToolTip("Guarde la medición en la base de datos.")
            self.btn_save.setProperty("class", "success")
            self.btn_save.style().unpolish(self.btn_save)
            self.btn_save.style().polish(self.btn_save)

    def _handle_stability_and_autocapture(self, result, confidence, warnings, fish_detected):
        """Manejo de estabilidad, detección y captura automatizada."""
        
        # 1. CASO: NO HAY PEZ
        if not fish_detected:
            self.lbl_stability.setText("NO SE DETECTA ESPÉCIMEN")
            self.lbl_stability.setProperty("state", "neutral") # Gris en CSS
            self._refresh_widget_style(self.lbl_stability)
            return

        # 2. CASO: PEZ DETECTADO - EVALUAR ESTABILIDAD
        is_stable = result.get('is_stable', False)
        motion_level = result.get('motion_level', 0)

        if is_stable:
            self.lbl_stability.setText("SISTEMA ESTABLE - LISTO")
            self.lbl_stability.setProperty("state", "ok")      # Verde en CSS
        else:
            self.lbl_stability.setText(f"EN MOVIMIENTO ({motion_level:.0f}%)")
            self.lbl_stability.setProperty("state", "warn")    # Naranja en CSS

        self._refresh_widget_style(self.lbl_stability)

        # 3. LÓGICA DE AUTO-CAPTURA
        if (
            self.auto_capture_enabled
            and is_stable
            and confidence >= Config.CONFIDENCE_THRESHOLD
            and not self.processing_lock
            and len(warnings) == 0
        ):
            self._execute_auto_capture_sequence()

    def _refresh_widget_style(self, widget):
        """Refresca el CSS del widget para aplicar cambios de estado."""
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _execute_auto_capture_sequence(self):
        """Encapsula la secuencia de guardado para limpiar el código principal."""
        self.processing_lock = True
        self.status_bar.set_status("Guardando medición automática...", "success")

        try:
            # Tiempos ajustados para feedback del usuario
            QTimer.singleShot(100, self.save_sound.play)
            QTimer.singleShot(17100, self.save_sound.play) # Sonido inmediato
            QTimer.singleShot(17000, self._save_measurement_silent)
            QTimer.singleShot(20000, self.unlock_after_save)
        except Exception as e:
            logger.error(f"Error en auto-guardado: {e}")
            self.processing_lock = False
            self.status_bar.set_status(f"Error al guardar: {str(e)}", "error")

    def unlock_after_save(self):
        """
        Desbloqueo BLINDADO: Garantiza que el sistema vuelva a estar disponible
        incluso si hay errores visuales.
        """
        try:
            self.processing_lock = False
            
            if hasattr(self, 'btn_save'):
                self.btn_save.setEnabled(True)

            self.results_text.clear()
            self._set_results_style("ready")
            
            self.results_text.setPlainText(
                "🟢 SISTEMA LISTO PARA SIGUIENTE MEDICIÓN\n\n"
                "Esperando que coloques otro pez...\n\n"
                "💡 El sistema guardará automáticamente cuando detecte:\n"
                " • Pez completamente estable\n"
                " • Confianza ≥ 70%\n"
                " • Sin advertencias anatómicas"
            )
            
            if hasattr(self, 'lbl_stability'):
                self.lbl_stability.setText("🟢 ESPERANDO PEZ")
                self.lbl_stability.setProperty("state", "empty") 
                self.lbl_stability.style().unpolish(self.lbl_stability)
                self.lbl_stability.style().polish(self.lbl_stability)
            
            if hasattr(self, 'confidence_bar'):
                 self.confidence_bar.setValue(0)
                 self.confidence_bar.setProperty("state", "idle")
                 self.confidence_bar.style().unpolish(self.confidence_bar)
                 self.confidence_bar.style().polish(self.confidence_bar)
                 
            if hasattr(self, 'status_bar'):
                self.status_bar.set_status("Listo para próxima captura")
            
            logger.info("Sistema desbloqueado correctamente.")

        except Exception as e:
            logger.error(f"Error NO CRÍTICO al desbloquear UI: {e}")
            self.processing_lock = False
            
    def force_unlock_if_stuck(self):
        """Desbloqueo de emergencia"""
        if self.processing_lock:
            logger.warning("Desbloqueo de emergencia activado")
            self.processing_lock = False
            if hasattr(self, 'btn_capture'):
                self.btn_capture.setEnabled(True)
                self.btn_capture.setText("Capturar y Analizar")
                icon_color = self.btn_capture.palette().buttonText().color()
                self.btn_capture.setIcon(qta.icon("fa5s.camera", color=icon_color))
                self.btn_capture.setProperty("class", "primary")
                self._refresh_widget_style(self.btn_capture)

            if hasattr(self, 'btn_qr'):
                self.btn_qr.setEnabled(True)
            
            self.results_text.clear()
            self._set_results_style("error")
            self.results_text.setPlainText(
                "❌ TIEMPO DE PROCESAMIENTO EXCEDIDO\n\n"
                "El análisis tardó demasiado.\n\n"
                "💡 Soluciones:\n"
                " • Intenta capturar de nuevo\n"
                " • Verifica la iluminación"
            )
            self.status_bar.set_status("Procesamiento cancelado por timeout")
            
            if hasattr(self, 'processor') and hasattr(self.processor, 'queue'):
                try:
                    while not self.processor.queue.empty(): self.processor.queue.get_nowait()
                except: pass

    def on_tab_changed(self, index):
        """
        Se ejecuta cuando cambia la pestaña activa.
        """
        old_tab = self.current_tab
        self.current_tab = index

        if hasattr(self, 'processor') and hasattr(self.processor, 'motion_detector'):
            self.processor.motion_detector.reset()

        # Si estaba activa la auto-captura, desactivarla correctamente
        if hasattr(self, 'auto_capture_enabled') and self.auto_capture_enabled:
            self.auto_capture_enabled = False

            if hasattr(self, 'btn_auto_capture'):
                self.btn_auto_capture.setChecked(False)

                btn_class = "secondary"
                icon_name = "fa5s.play"

                self.btn_auto_capture.setText(" Iniciar Auto-Captura")
                self.btn_auto_capture.setProperty("class", btn_class)

                # Guardar metadatos para refresco en cambio de tema
                self.btn_auto_capture._icon_name = icon_name
                self.btn_auto_capture._icon_class = btn_class

                # Regenerar icono con color correcto
                icon_color = self._btn_text_colors.get(btn_class, "#ffffff")
                self.btn_auto_capture.setIcon(
                    qta.icon(icon_name, color=icon_color)
                )
                self.btn_auto_capture.setIconSize(QSize(18, 18))

                # Refrescar estilos
                self.btn_auto_capture.style().unpolish(self.btn_auto_capture)
                self.btn_auto_capture.style().polish(self.btn_auto_capture)
                self.btn_auto_capture.update()

        self.preview_fps = Config.PREVIEW_FPS

        if hasattr(self, 'timer') and self.timer.isActive():
            fps_ms = int(1000 / self.preview_fps)
            self.timer.setInterval(fps_ms)

        arrow = chr(0x2192)
        logger.info(
            f"Pestana cambiada: {old_tab} {arrow} {index}, FPS: {self.preview_fps}"
        )

        
    def create_measurement_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # VISORES DE VIDEO
        video_layout = QHBoxLayout()
        self.lbl_left = CameraAspectLabel()
        self.lbl_top = CameraAspectLabel()
        
        # Cámara Lateral
        left_group = QGroupBox("Vista Lateral (Perfil)")
        left_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        left_layout = QVBoxLayout(left_group)
        self.lbl_left.setMinimumSize(640, 360)
        self.lbl_left.setProperty("class", "video-lateral") 
        self.lbl_left.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_left.setToolTip("Cámara encargada de medir Longitud y Altura del lomo del pez.")
        left_layout.addWidget(self.lbl_left)
    
        video_layout.addWidget(left_group)
        
        # Cámara Cenital
        top_group = QGroupBox("Vista Cenital (Dorso)")
        top_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        top_layout = QVBoxLayout(top_group)
        self.lbl_top.setMinimumSize(640, 360)
        self.lbl_top.setProperty("class", "video-cenital")
        self.lbl_top.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_top.setToolTip("Cámara encargada de medir el Ancho dorsal del pez.")
        top_layout.addWidget(self.lbl_top)
        
        video_layout.addWidget(top_group)

        layout.addLayout(video_layout)
        
        # FICHA DE RESULTADOS
        results_group = QGroupBox("Diagnóstico Biométrico en Tiempo Real")
        results_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        results_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        results_group.setMinimumHeight(320)
        results_layout = QVBoxLayout(results_group)
        
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setMinimumHeight(180)
        self.results_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.results_text.setProperty("class", "report-text") 
        self.results_text.setPlaceholderText("Esperando detección para generar reporte...")
        results_layout.addWidget(self.results_text)
        
        self.lbl_stability = QLabel("Esperando espécimen...")
        self.lbl_stability.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_stability.setMinimumHeight(34)
        self.lbl_stability.setProperty("state", "dim") 
        results_layout.addWidget(self.lbl_stability)

        confidence_layout = QHBoxLayout()
        lbl_conf = QLabel("Calidad de Detección:")
        lbl_conf.setStyleSheet("font-weight: bold;")
        confidence_layout.addWidget(lbl_conf)
        
        self.confidence_bar = QProgressBar()
        self.confidence_bar.setMaximum(100)
        self.confidence_bar.setFormat("%p% Confianza")
        confidence_layout.addWidget(self.confidence_bar)
        
        results_layout.addLayout(confidence_layout)
        
        layout.addWidget(results_group)
        
        # BOTONERA TÉCNICA
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)
        
        self.btn_capture = QPushButton("Captura Forzada")
        self.btn_capture.setProperty("class", "primary") 
        self.btn_capture.style().unpolish(self.btn_capture) 
        self.btn_capture.style().polish(self.btn_capture)
        self.btn_capture.setCursor(Qt.PointingHandCursor)
        self.btn_capture.setToolTip("Captura y analiza inmediatamente lo que hay en cámara.")
        self.btn_capture.clicked.connect(self.capture_and_analyze)
        controls_layout.addWidget(self.btn_capture)
        
        
        self.btn_auto_capture = QPushButton(" Activar Auto-Captura")
        self.btn_auto_capture.setCheckable(True)
        self.btn_auto_capture.setCursor(Qt.PointingHandCursor)
        self.btn_auto_capture.setMinimumHeight(40)
        self.btn_auto_capture.setToolTip("El sistema detectará automáticamente cuando el pez esté quieto para medirlo.")
        icon_color = self.btn_auto_capture.palette().buttonText().color()
        self.btn_auto_capture.setIcon(qta.icon("fa5s.play", color=icon_color))
        self.btn_auto_capture.setProperty("class", "secondary") 
        self.btn_auto_capture.clicked.connect(self.toggle_auto_capture)
        controls_layout.addWidget(self.btn_auto_capture)
        
        self.btn_save = QPushButton("Guardar")
        self.btn_save.setProperty("class", "success")
        self.btn_save.style().unpolish(self.btn_save) 
        self.btn_save.style().polish(self.btn_save)
        self.btn_save.setCursor(Qt.ForbiddenCursor)
        self.btn_save.setEnabled(False)
        self.btn_save.setToolTip("Primero debe haber una medición para guardar.")
        self.btn_save.clicked.connect(self.save_measurement)
        controls_layout.addWidget(self.btn_save)
        
        layout.addLayout(controls_layout)
        
        return widget
    
    def capture_and_analyze(self):
        """
        Captura frames y los envía al hilo de procesamiento con FEEDBACK VISUAL ANIMADO.
        """
        # 1. VALIDACIONES INICIALES
        if self.processing_lock:
            logger.warning("Procesamiento ya en curso, ignorando nueva captura.")
            self.status_bar.set_status("Ya existe un análisis en proceso", "warning")
            return
        
        if not self.cap_left or not self.cap_top:
            QMessageBox.critical(self, "Error de Hardware", "Los sensores de imagen no están disponibles.")
            return
        
        ret_left, frame_left = self.cap_left.read()
        ret_top, frame_top = self.cap_top.read()
        
        if not (ret_left and ret_top):
            QMessageBox.critical(self, "Error de Captura", "No se pudo obtener el flujo de datos de las cámaras.")
            return
        
        # 2. BLOQUEO DE INTERFAZ Y FEEDBACK VISUAL (ESTADO DE CARGA)
        self.processing_lock = True
        
        if hasattr(self, 'btn_qr'):
            self.btn_qr.setEnabled(False)
        
        # Configurar Botón con Spinner Animado
        self.btn_capture.setEnabled(False)
        self.btn_capture.setText(" Analizando...")
        icon_color = self.btn_capture.palette().buttonText().color()
        self.btn_capture.setIcon(qta.icon( "fa5s.spinner", color=icon_color, animation=qta.Spin(self.btn_capture)))
        self.btn_capture.setProperty("class", "warning") 
        self._refresh_widget_style(self.btn_capture)
        
        self.status_bar.set_status("IA Procesando captura manual...", "info")
        
        # Reiniciar Barra de Confianza
        if hasattr(self, 'confidence_bar'):
             self.confidence_bar.setValue(0)
             self.confidence_bar.setProperty("state", "idle")
             self._refresh_widget_style(self.confidence_bar)
     
        # 3. PREPARAR ÁREA DE RESULTADOS (LIMPIEZA Y FORMATO)
        self.results_text.clear()
        self.results_text.setProperty("state", "info") # Borde azul informativo
        self._refresh_widget_style(self.results_text)
        
        # Usamos un formato más limpio sin tantos caracteres ASCII
        self.results_text.append("INICIANDO ANÁLISIS BIOMÉTRICO")
        self.results_text.append("-" * 40)
        self.results_text.append("• Localizando espécimen en espacio 3D...")
        self.results_text.append("• Extrayendo nubes de puntos morfométricas...")
        self.results_text.append("• Validando integridad de la muestra...")
        self.results_text.append("-" * 40)
        self.results_text.append("\nProcesando... (Tiempo estimado: 10-15s)")
        
        # 4. PREPARAR PARÁMETROS TÉCNICOS
        params = {
            'scales': {
                'lat_front': self.scale_front_left,
                'lat_back': self.scale_back_left,
                'top_front': self.scale_front_top,
                'top_back': self.scale_back_top
            },
            'hsv_lateral': self.cache_params['hsv_lat'],
            'hsv_cenital': self.cache_params['hsv_top'],
            'detection': {
                'min_area': self.cache_params['min_area'],
                'max_area': self.cache_params['max_area'],
                'confidence': self.cache_params['conf']
            }
        }
        
        # 5. ENVÍO AL PROCESADOR (HILO SECUNDARIO)
        self.processor.add_frame(frame_left, frame_top, params)
        
        # 6. SEGURO DE DESBLOQUEO (WATCHDOG)
        QTimer.singleShot(20000, self.force_unlock_if_stuck)
        logger.info("Captura enviada al FrameProcessor.")
        
    def sync_modules_parameters(self):
        """
        Sincroniza los parámetros de FishDetector, FishTracker y FishAnatomyValidator
        con los valores actuales de la interfaz.
        """
        # Sincronizar FishDetector
        hsv_params = (
        self.spin_hue_min.value(), self.spin_hue_max.value(),
        self.spin_sat_min.value(), self.spin_sat_max.value(),
        self.spin_val_min.value(), self.spin_val_max.value()
        )
        
        if hasattr(self, 'detector') and self.detector:
            self.detector.set_hsv_ranges(*hsv_params)
            
        if hasattr(self, 'processor') and hasattr(self.processor, 'chroma_detector'):
            self.processor.chroma_detector.set_hsv_ranges(*hsv_params)

        if hasattr(self, 'tracker') and self.tracker:
            self.tracker.min_confidence = self.spin_confidence.value()
            
        if hasattr(self, 'anatomy_validator') and self.anatomy_validator:
            self.anatomy_validator.set_bounds(
                min_len=self.spin_min_length.value(),
                max_len=self.spin_max_length.value()
            )
        
        self.status_bar.set_status("Módulos sincronizados","info")

    def create_manual_tab(self):
        """Crea la pestaña de medición manual"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Vista previa
        preview_group = QGroupBox("Monitor de Captura")
        preview_layout = QHBoxLayout(preview_group)
        self.lbl_manual_left = CameraAspectLabel()
        self.lbl_manual_top = CameraAspectLabel()

        self.lbl_manual_left.setText("Cámara Lateral")
        self.lbl_manual_left.setMinimumSize(580, 326)
        self.lbl_manual_left.setProperty("class", "video-lateral")
        self.lbl_manual_left.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_manual_left.setToolTip("Cámara encargada de medir Longitud y Altura del lomo del pez.")
        preview_layout.addWidget(self.lbl_manual_left)

        self.lbl_manual_top.setText("Cámara Cenital")
        self.lbl_manual_top.setMinimumSize(580, 326)
        self.lbl_manual_top.setProperty("class", "video-cenital")
        self.lbl_manual_top.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_manual_top.setToolTip("Cámara encargada de medir el Ancho dorsal del pez.")
        preview_layout.addWidget(self.lbl_manual_top)

        layout.addWidget(preview_group)
        
        # Controles de Captura Principal
        controls_container = QHBoxLayout()
        
        self.btn_qr =QPushButton("Cargar Imagen del Móvil")
        self.btn_qr.setProperty("class", "info") 
        self.btn_qr.style().unpolish(self.btn_qr) 
        self.btn_qr.style().polish(self.btn_qr)
        self.btn_qr.setCursor(Qt.PointingHandCursor)
        self.btn_qr.setToolTip("Cargar una fotografía en vivo desde el celular.")
        self.btn_qr.clicked.connect(self.launch_qr_capture)
        self.btn_qr.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        controls_container.addWidget(self.btn_qr, 2)
        
        self.btn_load_image = QPushButton("Cargar Imagen del PC")
        self.btn_load_image.setProperty("class", "info") 
        self.btn_load_image.style().unpolish(self.btn_load_image) 
        self.btn_load_image.style().polish(self.btn_load_image)
        self.btn_load_image.setCursor(Qt.PointingHandCursor)
        self.btn_load_image.setToolTip("Cargar una fotografía de un pez guardada previamente en el equipo.")
        self.btn_load_image.clicked.connect(self.load_external_image)
        self.btn_load_image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        controls_container.addWidget(self.btn_load_image, 3)
        
        self.btn_manual_capture = QPushButton("Capturar Foto")
        self.btn_manual_capture.setProperty("class", "success")
        self.btn_manual_capture.style().unpolish(self.btn_manual_capture)
        self.btn_manual_capture.style().polish(self.btn_manual_capture)
        self.btn_manual_capture.setCursor(Qt.PointingHandCursor)
        self.btn_manual_capture.setToolTip("Congelar la imagen de las cámaras para iniciar la medición.")
        self.btn_manual_capture.setShortcut("Space")
        self.btn_manual_capture.clicked.connect(self.handle_manual_capture_popout)
        self.btn_manual_capture.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        controls_container.addWidget(self.btn_manual_capture, 5)

        layout.addLayout(controls_container)

        # CONTENEDOR DE DECISIÓN
        self.capture_decision_group = QWidget()
        decision_layout = QHBoxLayout(self.capture_decision_group)
        decision_layout.setContentsMargins(0, 0, 0, 0)
        
        # Botón Asistente IA
        self.btn_manual_ai_assist = QPushButton("Asistente IA")
        self.btn_manual_ai_assist.setProperty("class", "primary")
        self.btn_manual_ai_assist.style().unpolish(self.btn_manual_ai_assist)
        self.btn_manual_ai_assist.style().polish(self.btn_manual_ai_assist)
        self.btn_manual_ai_assist.setCursor(Qt.PointingHandCursor)
        self.btn_manual_ai_assist.setToolTip("Utilizar Inteligencia Artificial para detectar las medidas automáticamente sobre la foto capturada.")
        self.btn_manual_ai_assist.clicked.connect(self.run_ai_assist_manual)
        decision_layout.addWidget(self.btn_manual_ai_assist)
        
        # Botón Descartar
        self.btn_manual_discard = QPushButton("Cancelar")
        self.btn_manual_discard.setProperty("class", "warning")
        self.btn_manual_discard.style().unpolish(self.btn_manual_discard)
        self.btn_manual_discard.style().polish(self.btn_manual_discard) 
        self.btn_manual_discard.setCursor(Qt.PointingHandCursor)
        self.btn_manual_discard.setToolTip("Borrar la captura actual y volver al modo de video en vivo.")
        self.btn_manual_discard.clicked.connect(self.discard_manual_photo)
        decision_layout.addWidget(self.btn_manual_discard)

        # Botón Guardar
        self.btn_manual_save = QPushButton("Guardar")
        self.btn_manual_save.setProperty("class", "success")
        self.btn_manual_save.style().unpolish(self.btn_manual_save)
        self.btn_manual_save.style().polish(self.btn_manual_save)
        self.btn_manual_save.setCursor(Qt.PointingHandCursor)
        self.btn_manual_save.setToolTip("Guardar los datos actuales y la fotografía en la base de datos.")
        self.btn_manual_save.clicked.connect(self.save_manual_measurement)
        self.btn_manual_save.setEnabled(False) 
        decision_layout.addWidget(self.btn_manual_save)
        
        self.capture_decision_group.setVisible(False)
        layout.addWidget(self.capture_decision_group)
        
        # Formulario de entrada
        form_group = QGroupBox("Formulario de Biometría")
        form_layout = QGridLayout(form_group)
        form_layout.setSpacing(10)
        
        # ID Pez
        form_layout.addWidget(QLabel("ID del Pez (Diario):"), 0, 0)
        self.txt_manual_fish_id = QLineEdit()
        self.txt_manual_fish_id.setPlaceholderText("Ej: 1")
        self.txt_manual_fish_id.setValidator(QIntValidator(1, 999999))
        self.txt_manual_fish_id.setToolTip("Número identificador único para el pez en la jornada de hoy.")
        form_layout.addWidget(self.txt_manual_fish_id, 0, 1)
        
        def create_biometric_spin(suffix, tooltip):
            sb = QDoubleSpinBox()
            sb.setRange(0.1, 5000.0)
            sb.setDecimals(1)
            sb.setSuffix(f" {suffix}")
            sb.setToolTip(tooltip)
            return sb

        self.spin_manual_length = create_biometric_spin("cm", "Longitud estándar del pez.")
        form_layout.addWidget(QLabel("Longitud:"), 1, 0)
        form_layout.addWidget(self.spin_manual_length, 1, 1)
        
        self.spin_manual_height = create_biometric_spin("cm", "Altura máxima del cuerpo del pez.")
        form_layout.addWidget(QLabel("Altura:"), 2, 0)
        form_layout.addWidget(self.spin_manual_height, 2, 1)

        self.spin_manual_width = create_biometric_spin("cm", "Ancho dorsal del pez.")
        form_layout.addWidget(QLabel("Ancho:"), 3, 0)
        form_layout.addWidget(self.spin_manual_width, 3, 1)
        
        self.spin_manual_weight = create_biometric_spin("g", "Peso corporal total.")
        form_layout.addWidget(QLabel("Peso:"), 4, 0)
        form_layout.addWidget(self.spin_manual_weight, 4, 1)
        
        # Notas y Info adicional
        form_layout.addWidget(QLabel("Notas:"), 5, 0)
        self.txt_manual_notes = QLineEdit()
        self.txt_manual_notes.setPlaceholderText("Observaciones (Ej: salud, color, anomalías)")
        self.txt_manual_notes.setToolTip("Observaciones y notas del pez.")
        form_layout.addWidget(self.txt_manual_notes, 5, 1)

        form_layout.addWidget(QLabel("Archivo:"), 6, 0)
        self.lbl_filename_preview = QLabel("Pendiente...")
        self.lbl_filename_preview.setProperty("class", "report-text")
        self.lbl_filename_preview.setProperty("state", "empty")
        self.lbl_filename_preview.setToolTip("Nombre del archivo.")
        form_layout.addWidget(self.lbl_filename_preview, 6, 1)

        # Factor K con estilo visual
        form_layout.addWidget(QLabel("Factor K:"), 7, 0)
        self.lbl_k_factor_preview = QLabel("--")
        self.lbl_k_factor_preview.setAlignment(Qt.AlignCenter)
        self.lbl_k_factor_preview.setToolTip("Índice de bienestar corporal del pez.")
        self.lbl_k_factor_preview.setProperty("state", "empty")
        form_layout.addWidget(self.lbl_k_factor_preview, 7, 1)
        
        # Conexiones de señales
        self.spin_manual_length.valueChanged.connect(lambda: self.btn_manual_save.setEnabled(True))
        self.spin_manual_weight.valueChanged.connect(lambda: self.btn_manual_save.setEnabled(True))
        self.txt_manual_fish_id.textChanged.connect(self.update_filename_preview)
        self.spin_manual_length.valueChanged.connect(self.update_filename_preview)
        self.spin_manual_length.valueChanged.connect(self.update_k_factor_preview)
        self.spin_manual_height.valueChanged.connect(self.update_filename_preview)
        self.spin_manual_width.valueChanged.connect(self.update_filename_preview)
        self.spin_manual_weight.valueChanged.connect(self.update_filename_preview)
        self.spin_manual_weight.valueChanged.connect(self.update_k_factor_preview)
        
        layout.addWidget(form_group)
        layout.addLayout(self._build_quick_notes_row(self.txt_manual_notes))
        layout.addStretch()
        
        self.update_k_factor_preview()
        if hasattr(self, 'generate_daily_id'):
             self.generate_daily_id()
             
        return widget

    def _build_quick_notes_row(self, target_input: QLineEdit):
        """Crea una fila reutilizable de atajos para notas."""
        row = QHBoxLayout()
        row.setSpacing(8)

        lbl = QLabel("Notas rápidas:")
        row.addWidget(lbl)

        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setMinimumWidth(260)
        combo.setToolTip("Seleccione o escriba una frase frecuente para reutilizar.")
        self._quick_note_combos.append(combo)
        self._refresh_quick_note_combo(combo)
        row.addWidget(combo, 1)

        btn_add = QPushButton("Agregar")
        btn_add.setProperty("class", "info")
        btn_add.setToolTip("Añade la frase al final de la nota actual.")
        btn_add.clicked.connect(lambda: self._apply_quick_note(target_input, combo, mode="append"))
        row.addWidget(btn_add)

        btn_replace = QPushButton("Reemplazar")
        btn_replace.setProperty("class", "secondary")
        btn_replace.setToolTip("Reemplaza el texto actual por la frase seleccionada.")
        btn_replace.clicked.connect(lambda: self._apply_quick_note(target_input, combo, mode="replace"))
        row.addWidget(btn_replace)

        btn_save = QPushButton("Guardar frase")
        btn_save.setProperty("class", "primary")
        btn_save.setToolTip("Guarda la frase para reutilizarla en futuras mediciones.")
        btn_save.clicked.connect(lambda: self._save_quick_note_from_combo(combo))
        row.addWidget(btn_save)

        return row

    def _normalize_note_text(self, text: str) -> str:
        return " ".join(str(text or "").split()).strip()

    def _apply_quick_note(self, target_input: QLineEdit, combo: QComboBox, mode: str = "append") -> None:
        note = self._normalize_note_text(combo.currentText())
        if not note:
            return

        current = self._normalize_note_text(target_input.text())
        if mode == "replace" or not current:
            target_input.setText(note)
        else:
            low_current = current.lower()
            if note.lower() in low_current:
                target_input.setText(current)
            else:
                target_input.setText(f"{current}; {note}")

        self._register_quick_note(note)

    def _save_quick_note_from_combo(self, combo: QComboBox) -> None:
        note = self._normalize_note_text(combo.currentText())
        if not note:
            return
        self._register_quick_note(note)
        combo.setCurrentText(note)

    def _register_quick_note(self, note: str) -> None:
        clean_note = self._normalize_note_text(note)
        if len(clean_note) < 2:
            return

        self.quick_notes = [n for n in self.quick_notes if n.lower() != clean_note.lower()]
        self.quick_notes.insert(0, clean_note)
        self.quick_notes = self.quick_notes[:25]

        self._refresh_quick_note_combos()
        self._persist_quick_notes()

    def _refresh_quick_note_combo(self, combo: QComboBox) -> None:
        try:
            current_text = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(self.quick_notes)
            combo.setCurrentText(current_text)
        finally:
            combo.blockSignals(False)

    def _refresh_quick_note_combos(self) -> None:
        alive_combos = []
        for combo in self._quick_note_combos:
            try:
                self._refresh_quick_note_combo(combo)
                alive_combos.append(combo)
            except RuntimeError:
                continue
        self._quick_note_combos = alive_combos

    def _persist_quick_notes(self) -> None:
        """Persiste atajos de notas sin requerir 'Guardar Configuración'."""
        try:
            data = {}
            if os.path.exists(Config.CONFIG_FILE):
                with open(Config.CONFIG_FILE, 'r') as f:
                    data = json.load(f)

            data['quick_notes'] = self.quick_notes

            with open(Config.CONFIG_FILE, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.warning(f"No se pudieron persistir notas rápidas: {e}")

    def handle_manual_capture_popout(self):
        """Manejador estandarizado de la captura manual"""
        if self.current_frame_left is None or self.current_frame_top is None:
            QMessageBox.warning(self, "Error de Señal", "No se detectó imagen en las cámaras para capturar.")
            return

        frame_l = self.current_frame_left.copy()
        frame_t = self.current_frame_top.copy()

        dialog = CaptureDecisionDialog(frame_l, frame_t, self)
        decision = dialog.exec() 

        if decision in [1, 2]: 
            self.processing_lock = True
            self.manual_frame_left = frame_l
            self.manual_frame_top = frame_t
            
            self.display_frame(self.manual_frame_left, self.lbl_manual_left)
            self.display_frame(self.manual_frame_top, self.lbl_manual_top)
            
            self.btn_manual_capture.setEnabled(False)
            self.btn_load_image.setEnabled(False)
            self.btn_qr.setEnabled(False)
            self.capture_decision_group.setVisible(True)
            
            if decision == 1:
                self.status_bar.set_status("Procesando biometría con IA...", "info")
                self.run_ai_assist_manual() 
            
            elif decision == 2:
                self.btn_manual_save.setEnabled(True)
                self.txt_manual_fish_id.setFocus()
                self.status_bar.set_status("Modo Manual: Ingrese los datos y guarde el registro.", "info")
                
        else: 
            self.status_bar.set_status("Captura descartada. Cámara en vivo.", "warning")
            
    def _calculate_k_factor(self, length_cm, weight_g):
        """Calcula el Factor K de Fulton con validación."""
        if length_cm <= 0 or weight_g <= 0:
            return None
        return 100 * weight_g / (length_cm ** 3)
    
    def _get_k_status(self, k_value):
        """
        Determina el estado del Factor K.
        """
        if k_value is None:
            return ("empty", "--")
        
        opt_min, opt_max = getattr(Config, 'K_FACTOR_OPTIMAL', (1.0, 1.4))
        acc_min, acc_max = getattr(Config, 'K_FACTOR_ACCEPTABLE', (0.8, 1.8))
        
        if opt_min <= k_value <= opt_max:
            return ("ok", "ÓPTIMO")
        elif acc_min <= k_value <= acc_max:
            return ("warn", "ACEPTABLE")
        return ("bad", "ANORMAL")   
               
    def update_k_factor_preview(self):
        """Actualiza la etiqueta K-Factor usando ESTADOS, no colores manuales"""
        length_cm = self.spin_manual_length.value()
        weight_g = self.spin_manual_weight.value()

        k = self._calculate_k_factor(length_cm, weight_g)
        state_code, status_text = self._get_k_status(k)

        if k is not None:
            self.lbl_k_factor_preview.setText(f"{k:.3f} ({status_text})")
        else:
            self.lbl_k_factor_preview.setText(f"{status_text}")
            
        if self.lbl_k_factor_preview.property("state") != state_code:
            self.lbl_k_factor_preview.setProperty("state", state_code)
            self.lbl_k_factor_preview.style().unpolish(self.lbl_k_factor_preview)
            self.lbl_k_factor_preview.style().polish(self.lbl_k_factor_preview)

    def _create_k_factor_label(self, parent_layout):
        """Crea el label del Factor K configurado para el sistema de temas."""
        lbl_k = QLabel("Factor K: --")
        lbl_k.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_k.setMinimumHeight(45)
        lbl_k.setProperty("state", "empty") 
        
        lbl_k.setToolTip("Índice de bienestar corporal del pez.")
        parent_layout.addWidget(lbl_k)
        return lbl_k
    
    def _update_k_factor_display(self, lbl_k, length, weight):
        """Motor visual único para actualizar cualquier label de Factor K."""
        k_value = self._calculate_k_factor(length, weight)
        state, status = self._get_k_status(k_value)
        
        if k_value is None:
            lbl_k.setText(f"Factor K: {status}")
        else:
            lbl_k.setText(f"Factor K: {k_value:.3f} - {status}")

        if lbl_k.property("state") != state:
            lbl_k.setProperty("state", state)
            lbl_k.style().unpolish(lbl_k)
            lbl_k.style().polish(lbl_k)
           
    def _create_biometric_spinbox(self, field_type):
        """
        Crea un QDoubleSpinBox pre-configurado según el tipo de campo.
        Integrado con el sistema de temas mediante clases.
        """

        config = self.SPIN_CONFIGS.get(field_type)
        if not config:
            logger.error(f"Configuracion no encontrada para: {field_type}.")
            return QDoubleSpinBox()

        spin = QDoubleSpinBox()
        spin.setRange(*config['range'])
        spin.setDecimals(config['decimals'])
        spin.setSuffix(config['suffix'])
        spin.setCursor(Qt.IBeamCursor)
        
        return spin
    
    def load_external_image(self):
        """Carga una imagen externa y la analiza como medición manual"""
        filename, _ = QFileDialog.getOpenFileName(
            self, 
            "Seleccionar Imagen del Pez",
            "",
            "Imágenes (*.jpg *.jpeg *.png *.bmp *.webp)"
        )
        
        if not filename:
            return
        
        image = cv2.imread(filename)
        if image is None:
            QMessageBox.critical(self, "Error de Carga", 
                                "No se pudo interpretar el archivo de imagen.")
            return
        
        # Sincronizar con la interfaz principal
        self.display_frame(image, self.lbl_manual_left)
        self.display_frame(image, self.lbl_manual_top)
        self.manual_frame_left = image.copy()
        self.manual_frame_top = image.copy()
        
        # Crear diálogo
        dialog = QDialog(self)
        dialog.setWindowTitle("Registro de Medición Externa")
        dialog.setModal(True)
        dialog.setMinimumWidth(500)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        
        # Banner informativo
        info = QLabel(f"📂 Origen: {os.path.basename(filename)}")
        info.setProperty("state", "info") 
        layout.addWidget(info)
        
        # Formulario
        form_group = QGroupBox("Datos Biométricos")
        form_layout = QGridLayout(form_group)
        form_layout.setSpacing(10)
        
        # ID
        txt_fish_id = QLineEdit()
        if hasattr(self, 'db'):
            next_num = self.db.get_next_fish_number()
            txt_fish_id.setText(f"EXT_{next_num}") 
        
        txt_fish_id.setPlaceholderText("Ej: Lote_01")
        txt_fish_id.setToolTip("Número identificador único para el pez.")
        
        date_edit = QDateEdit()
        date_edit.setCalendarPopup(True)
        date_edit.setSpecialValueText("Seleccione fecha")
        date_edit.setDate(QDate.currentDate())
        date_edit.setMinimumDate(QDate(2025, 10, 1))
        date_edit.setMaximumDate(QDate(2026, 6, 1))
        date_edit.setDisplayFormat("yyyy-MM-dd")
        date_edit.setToolTip("Fecha en la que se midió el pez.")

        time_edit = QTimeEdit()
        time_edit.setDisplayFormat("HH:mm")
        time_edit.setTime(QTime.currentTime())
        time_edit.setMinimumTime(QTime(7, 0))
        time_edit.setMaximumTime(QTime(18, 0))
        time_edit.setToolTip("Hora en la que se midió el pez.")

        spin_length = self._create_biometric_spinbox('length')
        spin_length.setToolTip("Longitud estándar del pez.")
        
        spin_height = self._create_biometric_spinbox('height')
        spin_height.setToolTip("Altura máxima del cuerpo del pez.")
        
        spin_width = self._create_biometric_spinbox('width')
        spin_width.setToolTip("Ancho dorsal del pez.")
        
        spin_weight = self._create_biometric_spinbox('weight')
        spin_weight.setToolTip("Peso corporal total.")
        
        txt_notes = QLineEdit()
        txt_notes.setPlaceholderText("Observaciones opcionales...")
        txt_notes.setToolTip("Observaciones y notas del pez.")
        
        # Agregar al grid
        fields = [
            ("ID del Pez:", txt_fish_id),
            ("Fecha:", date_edit),
            ("Hora:", time_edit),
            ("Longitud:", spin_length),
            ("Altura:", spin_height),
            ("Ancho:", spin_width),
            ("Peso:", spin_weight),
            ("Notas:", txt_notes)
        ]
        
        for i, (label, widget) in enumerate(fields):
            form_layout.addWidget(QLabel(label), i, 0)
            form_layout.addWidget(widget, i, 1)
        
        layout.addWidget(form_group)
        layout.addLayout(self._build_quick_notes_row(txt_notes))
        
        lbl_k_factor = self._create_k_factor_label(layout)
        
        def update_k():
            self._update_k_factor_display(
                lbl_k_factor,
                spin_length.value(),
                spin_weight.value()
            )
        
        spin_length.valueChanged.connect(update_k)
        spin_weight.valueChanged.connect(update_k)
        
        # Botonera
        btn_layout = QHBoxLayout()
        
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setProperty("class", "warning")
        btn_cancel.setToolTip("Cancelar guardado del registro actual.")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(dialog.reject)
        
        btn_save = QPushButton("Guardar")
        btn_save.setToolTip("Guardar los datos actuales y la fotografía en la base de datos.")
        btn_save.setProperty("class", "success")
        btn_save.setCursor(Qt.PointingHandCursor)
        
        def save_and_close():
            if not txt_fish_id.text().strip():
                QMessageBox.warning(dialog, "Datos Faltantes", 
                                    "El ID del pez es obligatorio.")
                return
            
            if date_edit.date() == date_edit.minimumDate():
                QMessageBox.warning(
                    dialog,
                    "Fecha requerida",
                    "Debe seleccionar una fecha válida."
                )
                return
            
            # Preparar datos
            fish_id = txt_fish_id.text().strip()
            qdate = date_edit.date()
            qtime = time_edit.time()

            timestamp = datetime(
                qdate.year(),
                qdate.month(),
                qdate.day(),
                qtime.hour(),
                qtime.minute()
            )
            filename_save = (
                f"EXTERNO"
                f"{fish_id}_"
                f"{timestamp.strftime('%Y%m%d_%H%M%S')}_"
                f"LNAcm_"
                f"HNAcm_"
                f"WNAcm_"
                f"PNAg.jpg"
            )
            filepath = os.path.join(Config.IMAGES_MANUAL_DIR, filename_save)
            
            info_ext = {
                "tipo": "EXTERNA",
                "numero": "S/N",
                "longitud": 0.0,
                "peso": 0.0,
                "fecha": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            img_ann = self.draw_fish_overlay(image, info_ext)
            
            cv2.imwrite(filepath, img_ann)
            
            data = {
                'timestamp': timestamp.isoformat(),
                'fish_id': fish_id,
                'measurement_type': 'manual_externo_pc',
                
                # Campos principales
                'length_cm': spin_length.value(),
                'height_cm': spin_height.value(),
                'width_cm': spin_width.value(),
                'weight_g': spin_weight.value(),
                
                # Campos duplicados para compatibilidad
                'manual_length_cm': spin_length.value(),
                'manual_height_cm': spin_height.value(),
                'manual_width_cm': spin_width.value(),
                'manual_weight_g': spin_weight.value(),
                
                # Campos técnicos
                'lat_area_cm2': 0,
                'top_area_cm2': 0,
                'volume_cm3': 0,
                'confidence_score': 1.0,
                
                # Metadatos
                'notes': f"[IMAGEN EXTERNA PC] {txt_notes.text()}",
                'image_path': filepath,
                'validation_errors': ''
            }

            self._register_quick_note(txt_notes.text())
            
            self.db.save_measurement(data)
            self.refresh_history()
            dialog.accept()
            QMessageBox.information(self, "✅ Guardado", 
                                    "La medición externa se registró correctamente.")
        
        btn_save.clicked.connect(save_and_close)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)
        
        if dialog.exec() == QDialog.Accepted:
            self.status_bar.set_status("Imagen externa procesada y guardada.", "success")
        else:
            self.status_bar.set_status("Carga externa cancelada.", "warning")

    def _process_external_capture(self, image_path, is_mobile=False, medidas_movil=None):
        """Diálogo de registro biométrico para fotos externas/móviles"""
        image = cv2.imread(image_path)
        if image is None:
            QMessageBox.critical(self, "Error", 
                                "No se pudo cargar la imagen capturada.")
            return
        
        # Actualizar vistas previas
        self.display_frame(image, self.lbl_manual_left)
        self.display_frame(image, self.lbl_manual_top)
        self.manual_frame_left = image.copy()
        self.manual_frame_top = image.copy()
        
        # Crear diálogo
        dialog = QDialog(self)
        dialog.setWindowTitle("Registro de Biometría")
        dialog.setMinimumWidth(500)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        
        # Banner
        origin_text = "📱 Dispositivo Móvil (QR)" if is_mobile else "💻 Explorador de Archivos"
        banner = QLabel(f"Origen: {origin_text}")
        banner.setProperty("state", "info")
        layout.addWidget(banner)
        
        # Formulario
        form_group = QGroupBox("Detalles del Pez")
        form_grid = QGridLayout(form_group)
        form_grid.setSpacing(10)
        
        txt_id = QLineEdit()
        if hasattr(self, 'db'):
             prefix = "QR" if is_mobile else "EXT"
             txt_id.setText(f"{prefix}_{self.db.get_next_fish_number()}")
            
        txt_id.setPlaceholderText("Ej: TRUCHA-001")
        txt_id.setToolTip("Número identificador único para el pez.")
        
        date_edit = QDateEdit()
        date_edit.setCalendarPopup(True)
        date_edit.setSpecialValueText("Seleccione fecha")
        date_edit.setDate(QDate.currentDate())   
        date_edit.setMinimumDate(QDate(2025, 10, 1))
        date_edit.setMaximumDate(QDate(2026, 6, 1))
        date_edit.setDisplayFormat("yyyy-MM-dd")
        date_edit.setToolTip("Fecha en la que se midió el pez.")

        time_edit = QTimeEdit()
        time_edit.setDisplayFormat("HH:mm")
        time_edit.setTime(QTime.currentTime()) 
        time_edit.setMinimumTime(QTime(7, 0))
        time_edit.setMaximumTime(QTime(18,0))  
        time_edit.setToolTip("Hora en la que se midió el pez.")
        
        spin_length = self._create_biometric_spinbox('length')
        spin_length.setToolTip("Longitud estándar del pez.")
        
        spin_height = self._create_biometric_spinbox('height')
        spin_height.setToolTip("Altura máxima del cuerpo.")
        
        spin_width = self._create_biometric_spinbox('width')
        spin_width.setToolTip("Ancho dorsal del pez.")
        
        spin_weight = self._create_biometric_spinbox('weight')
        spin_weight.setToolTip("Peso corporal total.")

        if medidas_movil:
            try:
                if medidas_movil.get("peso"): spin_weight.setValue(float(medidas_movil["peso"]))
                if medidas_movil.get("longitud"): spin_length.setValue(float(medidas_movil["longitud"]))
                if medidas_movil.get("ancho"): spin_width.setValue(float(medidas_movil["ancho"]))
                if medidas_movil.get("alto"): spin_height.setValue(float(medidas_movil["alto"]))
            except ValueError:
                print("Aviso: Algún valor enviado desde el móvil no era un número válido.") 

            if medidas_movil.get("device_timestamp"):
                try:
                    parsed_dt = datetime.fromisoformat(
                        str(medidas_movil["device_timestamp"]).replace("Z", "+00:00")
                    )
                    date_edit.setDate(QDate(parsed_dt.year, parsed_dt.month, parsed_dt.day))
                    time_edit.setTime(QTime(parsed_dt.hour, parsed_dt.minute))
                except ValueError:
                    logger.debug("No se pudo parsear device_timestamp de captura móvil")
        
        txt_notes = QLineEdit()
        txt_notes.setPlaceholderText("Observaciones opcionales...")
        txt_notes.setToolTip("Observaciones y notas del pez.")
        if medidas_movil and medidas_movil.get("notes"):
            txt_notes.setText(str(medidas_movil.get("notes", "")).strip())
        
        fields = [
            ("ID Pez:", txt_id),
            ("Fecha:", date_edit),
            ("Hora:", time_edit),
            ("Longitud:", spin_length),
            ("Altura:", spin_height),
            ("Ancho:", spin_width),
            ("Peso:", spin_weight),
            ("Notas:", txt_notes)
        ]
        
        for i, (label, widget) in enumerate(fields):
            form_grid.addWidget(QLabel(label), i, 0)
            form_grid.addWidget(widget, i, 1)
        
        layout.addWidget(form_group)
        layout.addLayout(self._build_quick_notes_row(txt_notes))
        
        lbl_k = self._create_k_factor_label(layout)
        
        def update_k_realtime():
            self._update_k_factor_display(lbl_k, spin_length.value(), spin_weight.value())
        
        spin_length.valueChanged.connect(update_k_realtime)
        spin_weight.valueChanged.connect(update_k_realtime)
        
        # Botonera
        btn_layout = QHBoxLayout()
        
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setProperty("class", "warning")
        btn_cancel.setToolTip("Cancelar guardado del registro actual.")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(dialog.reject)
        
        btn_save = QPushButton("Guardar")
        btn_save.setProperty("class", "success")
        btn_save.setToolTip("Guardar los datos actuales y la fotografía en la base de datos.")
        btn_save.setCursor(Qt.PointingHandCursor)
        
        def save_final():
            if not txt_id.text().strip():
                QMessageBox.warning(dialog, "Error", "El ID del pez es obligatorio.")
                return
            if date_edit.date() == date_edit.minimumDate():
                QMessageBox.warning(
                    dialog,
                    "Fecha requerida",
                    "Debe seleccionar una fecha válida."
                )
                return

            try:
                qdate = date_edit.date()
                qtime = time_edit.time()

                timestamp = datetime(
                    qdate.year(),
                    qdate.month(),
                    qdate.day(),
                    qtime.hour(),
                    qtime.minute()
                )

                data = {
                    'timestamp': timestamp.isoformat(),
                    'fish_id': txt_id.text().strip(),
                    'measurement_type': 'manual_qr' if is_mobile else 'manual_pc',
                    
                    # Campos principales
                    'length_cm': spin_length.value(),
                    'height_cm': spin_height.value(),
                    'width_cm': spin_width.value(),
                    'weight_g': spin_weight.value(),
                    
                    # Campos duplicados para compatibilidad
                    'manual_length_cm': spin_length.value(),
                    'manual_height_cm': spin_height.value(),
                    'manual_width_cm': spin_width.value(),
                    'manual_weight_g': spin_weight.value(),
                    
                    # Campos técnicos
                    'lat_area_cm2': 0,
                    'top_area_cm2': 0,
                    'volume_cm3': 0,
                    'confidence_score': 1.0,
                    
                    # Metadatos
                    'image_path': image_path,
                    'notes': f"[IMAGEN EXTERNA QR] {txt_notes.text()}",
                    'validation_errors': ''
                }

                self._register_quick_note(txt_notes.text())
                
                db = getattr(self, 'db_manager', getattr(self, 'db', None))
                if db:
                    db.save_measurement(data)
                    self.refresh_history()
                    dialog.accept()
                else:
                    raise Exception("Base de datos no disponible")
                        
            except Exception as e:
                logger.error(f"Error guardando captura externa: {e}.")
                QMessageBox.critical(dialog, "Error", f"No se pudo guardar: {str(e)}")
        
        btn_save.clicked.connect(save_final)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)
        
        if dialog.exec() == QDialog.Accepted:
            self.status_bar.set_status("Medición externa guardada con éxito", "success")
        else:
            self.status_bar.set_status("Captura externa descartada", "warning")         

    def launch_qr_capture(self):
        """
        Muestra diálogo con QR para captura remota con diseño estandarizado.
        """
        pc_ip = get_local_ip() 
        port = 5000
        url = build_mobile_access_url(pc_ip, port)
        qr_path = os.path.join(Config.IMAGES_MANUAL_DIR, "temp_qr.png")

        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,  
                box_size=10,
                border=2
            )
            qr.add_data(url)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            img.save(qr_path)
        except Exception as e:
            logger.error(f"Error generando QR: {e}.")
            self.status_bar.set_status("Error al generar código QR", "error")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Captura Remota Móvil")
        dialog.setFixedSize(450, 620)
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)
        
        lbl_title = QLabel("Captura desde Móvil")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setProperty("class", "header-text") 
        layout.addWidget(lbl_title)

        lbl_instructions = QLabel(
            "1. Escanea el código QR con tu celular\n"
            "2. Captura las fotos (lateral + cenital)\n"
            "3. Envía las imágenes al sistema\n"
            "4. El acceso ya viaja embebido en el QR"
        )
        lbl_instructions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_instructions.setProperty("class", "report-text") 
        lbl_instructions.setProperty("state", "info")
        layout.addWidget(lbl_instructions)
        

        lbl_qr = QLabel()
        pixmap = QPixmap(qr_path)
        if not pixmap.isNull():
            lbl_qr.setPixmap(pixmap.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        lbl_qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_qr.setStyleSheet("background-color: white; padding: 15px; border-radius: 10px;")
        layout.addWidget(lbl_qr)
        
        lbl_status = QLabel("Esperando captura del móvil...")
        lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_status.setProperty("state", "warning") 
        layout.addWidget(lbl_status)

        btn_layout = QHBoxLayout()
        
        btn_test = QPushButton("Verificar")
        btn_test.setProperty("class", "primary") 
        btn_test.style().unpolish(btn_test)
        btn_test.style().polish(btn_test)
        btn_test.clicked.connect(lambda: os.system(f'start {url}'))  
        btn_test.setToolTip("Verífica que la página este activa.")
        
        btn_cancel = QPushButton("Cerrar")
        btn_cancel.setProperty("class", "warning") 
        btn_cancel.style().unpolish(btn_cancel)
        btn_cancel.style().polish(btn_cancel)
        btn_cancel.setToolTip("Cerrar el código QR.")
        btn_cancel.clicked.connect(dialog.reject)
        
        btn_layout.addWidget(btn_test)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        if not hasattr(self, "_flask_started") or not self._flask_started:
            try:
                flask_thread = threading.Thread(
                    target=start_flask_server,
                    kwargs={'host': '0.0.0.0', 'port': port, 'debug': Config.DEBUG_MODE},
                    daemon=True, name="FlaskMobileServer"
                )
                flask_thread.start()
                self._flask_started = True
                self.status_bar.set_status(f"Servidor activo en {pc_ip}", "success")
            except Exception as e:
                logger.error(f"Error al iniciar Flask: {e}.")
                self.status_bar.set_status("Error al iniciar servidor", "error")
                dialog.reject()
                return
        else:
            self.status_bar.set_status(f"Servidor reanudado en {pc_ip}", "info")
        
        timer = QTimer(dialog)
        timer.setInterval(300)

        def check_mobile_capture():
            """Verifica si llegó una captura desde el móvil."""
            if not mobile_capture_queue.empty():
                try:
                    # Obtener ruta de la imagen
                    paquete = mobile_capture_queue.get(block=False)
                    image_path = paquete.get("path")
                    medidas_recibidas = paquete.get("medidas")
                    request_id = paquete.get("request_id", "sin-id")
                    
                    Config.logger.info(f"Captura móvil recibida: {image_path} | request_id={request_id}")
                    
                    # Detener timer
                    timer.stop()
                    
                    # Actualizar estado
                    lbl_status.setText(f"✅ ¡Imagen y datos recibidos! ID: {request_id}")
                    lbl_status.setStyleSheet("""
                        padding: 10px;
                        color: #2a9d8f;
                        font-weight: bold;
                    """)
                    
                    # Cerrar diálogo después de un breve delay para feedback visual
                    QTimer.singleShot(800, dialog.accept)
                    
                    # Procesar la imagen capturada y pasar medidas
                    QTimer.singleShot(900, lambda: self._process_external_capture(
                        image_path, 
                        is_mobile=True,
                        medidas_movil=medidas_recibidas # <- Pasamos el diccionario
                    ))
                    
                except Exception as e:
                    Config.logger.error(f"Error procesando captura móvil: {e}")
                    lbl_status.setText("❌ Error al procesar imagen")
                    lbl_status.setStyleSheet("color: #e63946;")
        
        timer.timeout.connect(check_mobile_capture)
        timer.start()
        
        try:
            result = dialog.exec()
            
            # Detener timer al cerrar
            timer.stop()
            
            # Limpiar archivo QR temporal
            try:
                if os.path.exists(qr_path):
                    os.remove(qr_path)
            except Exception as e:
                logger.warning(f"No se pudo eliminar QR temporal: {e}")
            
            # Actualizar estado según resultado
            if result == QDialog.DialogCode.Accepted:
                self.status_bar.set_status("Captura móvil procesada correctamente")
            else:
                self.status_bar.set_status("Captura móvil cancelada")
                logger.info("Usuario cancelo captura movil.")
        
        except Exception as e:
            logger.error(f"Error en dialogo de captura QR: {e}.", exc_info=True)
            self.status_bar.set_status("Error en captura móvil")

    def verify_flask_server(ip, port=5000, timeout=2):
        """
        Verifica si el servidor Flask está activo.
        """
        url = f"http://{ip}:{port}/ping"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                if response.status == 200:
                    data = response.read().decode('utf-8')
                    return "online" in data.lower()
                return False
        except (urllib.error.URLError, TimeoutError, ConnectionRefusedError):
            return False
        except Exception as e:
            logger.debug(f"Error inesperado verificando servidor: {e}.")
            return False

    def update_filename_preview(self):
        """Actualiza el preview del nombre de archivo con estados lógicos"""
        fish_id = self.txt_manual_fish_id.text().strip()
        length_cm = self.spin_manual_length.value()
        height_cm = self.spin_manual_height.value()  
        width_cm = self.spin_manual_width.value()   
        weight_g = self.spin_manual_weight.value()
        
        if fish_id:
            timestamp = datetime.now()

            filename = (
                f"MANUAL_"
                f"{fish_id}_"
                f"{timestamp.strftime('%Y%m%d_%H%M%S')}_"
                f"L{length_cm:.1f}cm_"
                f"H{height_cm:.1f}cm_"
                f"W{width_cm:.1f}cm_"
                f"P{weight_g:.1f}g.jpg"
            )

            self.lbl_filename_preview.setText(filename)

            self.lbl_filename_preview.setProperty("state", "success")
        else:
            self.lbl_filename_preview.setText("⚠️ Ingrese un ID para generar el nombre")
            self.lbl_filename_preview.setProperty("state", "error")

        self.lbl_filename_preview.style().unpolish(self.lbl_filename_preview)
        self.lbl_filename_preview.style().polish(self.lbl_filename_preview)

    def refresh_daily_counter(self):
        """Actualiza el contador de la barra de estado con los datos de HOY"""
        db = getattr(self, 'db_manager', getattr(self, 'db', None))
        
        if db and hasattr(self, 'status_bar'):
            try:
                count_today = db.get_today_measurements_count()
                self.status_bar.set_measurement_count(count_today)
            except Exception as e:

                logger.error(f"Error al refrescar contador diario: {e}.")
                self.status_bar.set_measurement_count(0)

    def discard_manual_photo(self):
        """Limpia la foto capturada y resetea la interfaz con estados limpios"""
        self.manual_frame_left = None
        self.manual_frame_top = None
        
        self.capture_decision_group.setVisible(False)
        self.btn_manual_capture.setEnabled(True)
        self.btn_load_image.setEnabled(True)
        self.btn_qr.setEnabled(True)
        
        self.spin_manual_length.setValue(0.0)
        self.spin_manual_height.setValue(0.0) 
        self.spin_manual_width.setValue(0.0)
        self.spin_manual_weight.setValue(0.0)
        self.txt_manual_notes.clear()
        
        widgets_to_reset = [
            self.spin_manual_length, self.spin_manual_weight, 
            self.spin_manual_height, self.spin_manual_width,
            self.txt_manual_fish_id
        ]
        
        for w in widgets_to_reset:
            w.setProperty("state", "") 
            w.style().unpolish(w)
            w.style().polish(w)

        self.update_k_factor_preview() #
        self.update_filename_preview()
        
        self.status_bar.set_status("Cámara en vivo lista para nueva captura", "info")
        
        logger.info("Captura manual descartada, volviendo a video en vivo.")
    
    def run_ai_assist_manual(self):
        """
        Ejecuta el análisis de IA sobre la foto capturada manualmente.
        """
        if self.manual_frame_left is None or self.manual_frame_top is None:
            QMessageBox.warning(self, "Captura Incompleta", "No se han detectado fotos en el búfer para analizar.")
            return
        self.processing_lock = True
        
        if hasattr(self, 'btn_capture'):
            self.btn_capture.setEnabled(False)

        if hasattr(self, 'btn_qr'):
            self.btn_qr.setEnabled(False)

        if hasattr(self, 'btn_manual_capture'):
            self.btn_manual_capture.setEnabled(False)

        if hasattr(self, 'btn_load_image'):
            self.btn_load_image.setEnabled(False)

        self.btn_manual_ai_assist.setEnabled(False)
        self.btn_manual_ai_assist.setText(" IA Analizando...")
        icon_color = self.btn_manual_ai_assist.palette().buttonText().color()

        self.btn_manual_ai_assist.setIcon(
            qta.icon(
                "fa5s.spinner",
                color=icon_color,
                animation=qta.Spin(self.btn_manual_ai_assist)
            )
        )

        
        self.status_bar.set_status("BiometryService procesando captura forense", "info")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

        try:
            service = BiometryService(self.advanced_detector)
            metrics, img_lat_ann, img_top_ann = service.analyze_and_annotate(
                img_lat=self.manual_frame_left,
                img_top=self.manual_frame_top,
                scale_lat_front=self.scale_front_left,
                scale_lat_back=self.scale_back_left,
                scale_top_front=self.scale_front_top,
                scale_top_back=self.scale_back_top,
                draw_box=True,     
                draw_skeleton=True
            )

            if metrics and metrics.get('length_cm', 0) > 0:
                result_fake = {
                    'metrics': metrics,
                    'confidence': metrics.get('confidence', 0.95),
                    'frame_left': img_lat_ann,
                    'frame_top': img_top_ann,
                    'is_stable': True,
                    'fish_validation_left': {'is_fish': True},
                    'contour_left': True,
                    'contour_top': True
                }

                self.on_processing_complete(result_fake)
                self.display_frame(img_lat_ann, self.lbl_manual_left)
                self.display_frame(img_top_ann, self.lbl_manual_top)

                self.status_bar.set_status("Análisis de Biometría completado con éxito", "success")
            
            else:
                self.status_bar.set_status("IA: No se identificó el espécimen claramente", "warning")
                self.results_text.setProperty("state", "error")
                self.results_text.setPlainText("ERROR DE SEGMENTACIÓN: La IA no pudo aislar la silueta del pez.\n"
                                               "Sugerencia: Mejore el contraste del fondo o centre el ejemplar.")
                self._refresh_widget_style(self.results_text)

        except Exception as e:
            logger.error(f"Error crítico en run_ai_assist_manual: {e}.")
            self.status_bar.set_status(f"Error de Motor IA: {str(e)}", "error")
            self.results_text.setProperty("state", "error")
            self._refresh_widget_style(self.results_text)

        finally:
            QApplication.restoreOverrideCursor()
            self.btn_manual_ai_assist.setEnabled(True)
            self.btn_manual_ai_assist.setText(" Asistente IA")
            self.btn_manual_ai_assist.setIcon(qta.icon("fa5s.magic", color="white"))
            
    def generar_nombre_archivo(self, tipo, fish_id, L, H, W, P, fecha_str):
        """
        Genera el nombre del archivo respetando el formato original (Manual, Auto, Externo).
        fecha_str: Debe venir en formato 'YYYY-MM-DD HH:MM:SS'
        """
        # 1. Convertir fecha de '2026-01-22 10:30:00' a '20260122_103000'
        # Usamos regex o replace simple para limpiar
        ts_clean = fecha_str.replace("-", "").replace(":", "").replace(" ", "_")
        
        # 2. SELECCIÓN DE FORMATO SEGÚN EL TIPO
        tipo = str(tipo).upper()
        
        if "MANUAL" in tipo:
            # FORMATO MANUAL: MANUAL_ID_FECHA_L..._H..._W..._P...
            nombre = (
                f"MANUAL_"
                f"{fish_id}_"
                f"{ts_clean}_"
                f"L{L:.1f}cm_"
                f"H{H:.1f}cm_"
                f"W{W:.1f}cm_"
                f"P{P:.1f}g.jpg"
            )
            
        elif "EXTERNA" in tipo or "EXTERNO" in tipo:
            # FORMATO EXTERNO: EXTERNOID_FECHA_... (Según tu snippet)
            # Nota: Tu snippet original tenía "EXTERNO" pegado al ID o con un formato fijo.
            # Vamos a estandarizarlo para que incluya los datos actualizados:
            nombre = (
                f"EXTERNO_"
                f"{fish_id}_"
                f"{ts_clean}_"
                f"L{L:.1f}cm_"
                f"H{H:.1f}cm_"
                f"W{W:.1f}cm_"
                f"P{P:.1f}g.jpg"
            )
            
        else:
            # FORMATO AUTOMÁTICO (El default de tu snippet)
            # ID_L..._P..._FECHA.jpg (Nota: Auto suele tener menos datos en el nombre)
            nombre = (
                f"AUTO_"
                f"{fish_id}_"
                f"L{L:.1f}_"
                f"P{P:.1f}_"
                f"{ts_clean}.jpg"
            )
            
        return nombre

    def save_measurement(self):
        """
        Guarda mediciones automáticas con TODOS los campos
        
        """

        if not self.last_result or self.processing_lock:
            logger.warning("No hay resultado para guardar o sistema bloqueado.")
            return
        
        metrics = self.last_result.get('metrics', {})
        if not metrics:
            logger.error("Resultado sin metricas validas.")
            return

        validation_errors = MeasurementValidator.validate_measurement(metrics)
        
        if validation_errors and not self.auto_capture_enabled:
            errors_text = "\n".join(validation_errors)
            reply = QMessageBox.question(
                self, "⚠️ Validación", 
                f"Se detectaron las siguientes advertencias:\n\n{errors_text}\n\n"
                "¿Desea guardar de todos modos?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        try:
            QApplication.processEvents()
            
            length_cm = float(metrics.get('length_cm', 0.0))
            weight_g = float(metrics.get('weight_g', 0.0))
     
            height_cm = float(metrics.get('height_cm', 0.0))
            width_cm = float(metrics.get('width_cm', metrics.get('thickness_cm', 0.0)))
            
            lat_area_cm2 = float(metrics.get('lat_area_cm2', 0.0))
            top_area_cm2 = float(metrics.get('top_area_cm2', 0.0))
            volume_cm3 = float(metrics.get('volume_cm3', 0.0))
            confidence = float(self.last_result.get('confidence', 0.8))
            
            timestamp = datetime.now()
            
            try:
                count_today = self.db.get_today_measurements_count()
                fish_id = str(count_today + 1)  
                logger.info(f"Usando el contador diario para fish_id: {fish_id}")
            except:
                fish_id = f"AUTO_{timestamp.strftime('%Y%m%d_%H%M%S')}"
                logger.warning(f"Error en el contador diario al utilizar la marca de tiempo: {fish_id}")

            filename_parts = [
                f"auto_{fish_id}",
                f"L{length_cm:.1f}cm"
            ]
            
            if height_cm > 0:
                filename_parts.append(f"H{height_cm:.1f}cm")
            if width_cm > 0:
                filename_parts.append(f"W{width_cm:.1f}cm")
            
            filename_parts.extend([
                f"P{weight_g:.1f}g",
                timestamp.strftime('%Y%m%d_%H%M%S')
            ])
            
            filename = "_".join(filename_parts) + ".jpg"
            filepath = os.path.join(Config.IMAGES_AUTO_DIR, filename)
            
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # PREPARAR IMAGEN CON ANOTACIONES
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            frame_left = self.last_result['frame_left'].copy()
            frame_top = self.last_result['frame_top'].copy()
            
            # Dibujar contornos si existen
            contour_left = self.last_result.get('contour_left')
            contour_top = self.last_result.get('contour_top')
            
            if contour_left is not None and isinstance(contour_left, np.ndarray) and len(contour_left) >= 3:
                cv2.drawContours(frame_left, [contour_left], -1, (0, 255, 0), 3)
            
            if contour_top is not None and isinstance(contour_top, np.ndarray) and len(contour_top) >= 3:
                cv2.drawContours(frame_top, [contour_top], -1, (0, 255, 0), 3)
            
            # Combinar frames
            combined = np.hstack((
                cv2.resize(frame_left, (Config.SAVE_WIDTH, Config.SAVE_HEIGHT)),
                cv2.resize(frame_top, (Config.SAVE_WIDTH, Config.SAVE_HEIGHT))
            ))
            
            # Encabezado
            info_auto = {
                "tipo": "SEMI-AUTO",
                "numero": fish_id,
                "longitud": length_cm,
                "peso": weight_g,
                "fecha": timestamp.strftime('%Y-%m-%d %H:%M:%S')
            }
            # Generamos la imagen con el panel estandarizado
            combined_final = self.draw_fish_overlay(combined, info_auto)
            cv2.imwrite(filepath, combined_final)
            
            api_data = SensorService.get_water_quality_data()
            data = {
                'timestamp': timestamp.isoformat(),
                'fish_id': fish_id,  
                
                # Dimensiones principales
                'length_cm': length_cm,
                'height_cm': height_cm, 
                'width_cm': width_cm,    
                'weight_g': weight_g,
                
                'manual_length_cm': length_cm,
                'manual_height_cm': height_cm,  
                'manual_width_cm': width_cm,    
                'manual_weight_g': weight_g,
                
                # Campos calculados
                'lat_area_cm2': lat_area_cm2,
                'top_area_cm2': top_area_cm2,
                'volume_cm3': volume_cm3,
                
                # Metadatos
                'confidence_score': confidence,
                'scale_lateral': self.last_result.get('scale_left', self.scale_front_left),
                'scale_top': self.last_result.get('scale_top', self.scale_front_top),
                'image_path': filepath,
                'measurement_type': 'auto',
                'notes': '[Medición Semiautomática]',
                'validation_errors': ', '.join(validation_errors) if validation_errors else ''
            }

            try:
                api_data = SensorService.get_water_quality_data()
                
                if api_data and len(api_data) > 0:
                    # Verificar si los datos son válidos (no todos ceros)
                    has_valid_data = any(
                        v != 0 and v != 0.0 and v is not None 
                        for v in api_data.values()
                    )
                    
                    if has_valid_data:
                        # Agregar datos al diccionario
                        data.update(api_data)
                        logger.info(f"✅ Datos de sensores sincronizados correctamente:")
                        for key, value in api_data.items():
                            logger.info(f"   {key}: {value}")
                    else:
                        logger.warning("⚠️  API devolvió datos pero todos son 0")
                        logger.warning("   Posibles causas:")
                        logger.warning("   - Sensores no están transmitiendo")
                        logger.warning("   - Sensores no calibrados")
                        logger.warning("   - Valores por defecto de la API")
                        # Agregar los datos aunque sean 0 para mantener la estructura
                        data.update(api_data)
                else:
                    logger.warning("⚠️  SensorService devolvió diccionario vacío")
                    logger.warning("   Posibles causas:")
                    logger.warning("   - API no responde (timeout)")
                    logger.warning("   - Sin conexión a internet")
                    logger.warning("   - Servidor de sensores caído")
                    logger.warning("   Se guardarán valores por defecto (0)")
                    
            except Exception as e:
                logger.error(f"❌ Error consultando SensorService: {type(e).__name__}")
                logger.error(f"   Mensaje: {str(e)}")
                logger.error("   Se guardarán valores por defecto (0)")
            
            logger.info("=" * 60)
            
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # GUARDAR EN BASE DE DATOS
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            measurement_id = self.db.save_measurement(data)

            
            logger.info(
                f"Auto measurement saved: "
                f"ID={measurement_id}, "
                f"FishID={fish_id}, "
                f"L={length_cm:.1f}cm, "
                f"H={height_cm:.1f}cm, "
                f"W={width_cm:.1f}cm, "
                f"P={weight_g:.1f}g, "
                f"Conf={confidence:.0%}"
            )
            
            self.btn_save.setEnabled(False)
            
            # Actualizar historial
            self.current_page_offset = 0
            QApplication.processEvents()
            self.refresh_history()
            self.refresh_daily_counter()

            if self.auto_capture_enabled:
                self.status_bar.set_status(f"Pez #{fish_id} guardado con éxito", "success")
            else:
                self.status_bar.set_status(f"Pez #{fish_id} guardado con éxito", "success")
                message_parts = [
                    f"✅ Medición #{measurement_id} guardada correctamente\n",
                    f"🐟 Pez ID: {fish_id}\n",
                    f"📄 Archivo: {filename}\n\n",
                    "📊 DIMENSIONES:\n",
                    f"   • Longitud: {length_cm:.1f} cm\n"
                ]
                
                if height_cm > 0:
                    message_parts.append(f"   • Altura: {height_cm:.1f} cm\n")
                if width_cm > 0:
                    message_parts.append(f"   • Ancho: {width_cm:.1f} cm\n")
                
                message_parts.append(f"   • Peso: {weight_g:.1f} g\n")
                message_parts.append(f"\n🎯 Confianza: {confidence:.0%}")
                
                QMessageBox.information(self, "✅ Guardado Exitoso", "".join(message_parts))
            
        except Exception as e:
            logger.error(f"Error en save_measurement: {e}", exc_info=True)
            
            if not self.auto_capture_enabled:
                QMessageBox.critical(self, "❌ Error", f"No se pudo guardar la medición:\n\n{str(e)}")
            else:
                self.status_bar.set_status(f"Error al guardar: {str(e)}", "error")  
    
    def save_manual_measurement(self):
        """
        Guarda medición manual COMPLETA:
        """

        fish_id = str(self.txt_manual_fish_id.text().strip())
        
        try:
            length_cm = float(self.spin_manual_length.value())
            height_cm = float(self.spin_manual_height.value())
            width_cm = float(self.spin_manual_width.value())
            weight_g = float(self.spin_manual_weight.value())
        except ValueError:
            QMessageBox.warning(self, "Error", "Valores numéricos inválidos.")
            return

        notes = str(self.txt_manual_notes.text().strip())
        
        if not fish_id:
            QMessageBox.warning(self, "⚠️ Campo Requerido", "Debe ingresar un ID para el pez.")
            self.status_bar.set_status("Falta ID del pez", "warning")
            self.txt_manual_fish_id.setFocus()
            return

        if len(fish_id) > 50:
            QMessageBox.warning(self, "⚠️ ID Largo", "El ID no puede superar los 50 caracteres.")
            return
        

        if not re.match(r'^[a-zA-Z0-9_-]+$', fish_id):
            QMessageBox.warning(self, "⚠️ ID Inválido", "Solo letras, números, guiones y guiones bajos.")
            return

        self._register_quick_note(notes)
        
        if not hasattr(self, 'manual_frame_left') or self.manual_frame_left is None:
            QMessageBox.warning(self, "⚠️ Sin Imagen", "Falta la captura lateral.")
            return
        if not hasattr(self, 'manual_frame_top') or self.manual_frame_top is None:
            QMessageBox.warning(self, "⚠️ Sin Imagen", "Falta la captura cenital.")
            return

        # Validación lógica
        if length_cm <= 0 or weight_g <= 0:
            reply = QMessageBox.question(
                self, "⚠️ Valores Cero", 
                "Longitud o peso son 0. ¿Guardar de todos modos?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No: return

        try:
            timestamp = datetime.now()
            safe_fish_id = re.sub(r'[^\w\-]', '_', fish_id)
            
            filename = (
                f"{safe_fish_id}_"
                f"L{length_cm:.1f}_"
                f"P{weight_g:.1f}_"
                f"{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
            )
            filepath = os.path.join(Config.IMAGES_MANUAL_DIR, filename)
            os.makedirs(Config.IMAGES_MANUAL_DIR, exist_ok=True)
            
            frame_left_resized = cv2.resize(self.manual_frame_left, (Config.SAVE_WIDTH, Config.SAVE_HEIGHT), interpolation=cv2.INTER_CUBIC)
            frame_top_resized = cv2.resize(self.manual_frame_top, (Config.SAVE_WIDTH, Config.SAVE_HEIGHT), interpolation=cv2.INTER_CUBIC)
            combined = np.hstack((frame_left_resized, frame_top_resized))
            
            font = cv2.FONT_HERSHEY_SIMPLEX
            color_cyan = (0, 255, 255)
            color_green = (0, 255, 0)
            color_gray = (150, 150, 150)

            # 1. Título con fondo
            info_manual = {
                "tipo": "MANUAL",
                "numero": fish_id,
                "longitud": length_cm,
                "peso": weight_g,
                "fecha": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            imagen_manual = self.draw_fish_overlay(combined, info_manual)
            cv2.imwrite(filepath, imagen_manual)
                
        except Exception as e:
            QMessageBox.critical(self, "Error Guardando Imagen", f"{e}")
            return

        ai_lat_area = 0.0
        ai_top_area = 0.0
        ai_vol = 0.0
        # Intentar recuperar datos de IA si existen
        if hasattr(self, 'last_metrics') and self.last_metrics:
            ai_lat_area = float(self.last_metrics.get('lat_area_cm2', 0))
            ai_top_area = float(self.last_metrics.get('top_area_cm2', 0))
            ai_vol = float(self.last_metrics.get('volume_cm3', 0))
        api_data = SensorService.get_water_quality_data()
        data = {
            'timestamp': timestamp.isoformat(),
            'fish_id': str(fish_id),
            
            # Floats
            'length_cm': float(length_cm),
            'height_cm': float(height_cm),
            'width_cm': float(width_cm),
            'weight_g': float(weight_g),
            
            # Manuales
            'manual_length_cm': float(length_cm),
            'manual_height_cm': float(height_cm),
            'manual_width_cm': float(width_cm),
            'manual_weight_g': float(weight_g),
            
            # IA
            'lat_area_cm2': float(ai_lat_area),
            'top_area_cm2': float(ai_top_area),
            'volume_cm3': float(ai_vol),
            
            'confidence_score': 1.0,
            'measurement_type': 'manual', 
            'notes': str(notes),
            'image_path': str(filepath),
            'validation_errors': '',
            
        }
        data.update(api_data)

        try:
            m_id = self.db.save_measurement(data)
            
            self.status_bar.set_status(f"Registro Manual #{m_id} guardado", "success")
            
            # Éxito y Limpieza
            QMessageBox.information(self, "Guardado", f"Medición #{m_id} guardada con éxito.")
            self.discard_manual_photo()
            self.refresh_history()
            self.generate_daily_id()
            self.refresh_daily_counter()
            
                
        except Exception as e:
            logger.error(f"Error BD: {e}.")
            self.status_bar.set_status("Error de Base de Datos", "error")
            QMessageBox.critical(self, "Error Base de Datos", f"No se pudo registrar en la BD:\n{e}")
            # Intentar borrar la imagen huérfana
            if os.path.exists(filepath): os.remove(filepath)
 
    def _save_measurement_silent(self):
        """
        Versión silenciosa de guardado BLINDADA y con DIBUJO DE CONTORNOS ORIGINAL.
        VERSIÓN CORREGIDA: fish_id definido en orden correcto
        """
        # Validación inicial
        if not self.last_result or not self.last_metrics:
            return False
        
        try:
            metrics = self.last_metrics
            timestamp = datetime.now()

            length_cm = float(metrics.get('length_cm', 0))
            height_cm = float(metrics.get('height_cm', 0))
            width_cm = float(metrics.get('width_cm', 0))
            weight_g = float(metrics.get('weight_g', 0))
            
            # Áreas y volumen
            lat_area = float(metrics.get('lat_area_cm2', 0))
            top_area = float(metrics.get('top_area_cm2', 0))
            vol = float(metrics.get('volume_cm3', 0))
            
            # Calculamos Factor K para la imagen
            factor_k = float(metrics.get('condition_factor', 0))
            confidence = float(self.last_result.get('confidence', 0))

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # PASO 1: DEFINIR fish_id (ANTES DE USARLO)
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            try:
                count_today = self.db.get_today_measurements_count()
                fish_id = str(count_today + 1)
                logger.info(f"Usando el contador diario para fish_id: {fish_id}")
            except Exception as e:
                fish_id = timestamp.strftime('%Y%m%d_%H%M%S')
                logger.warning(f"Error en el contador diario, usando timestamp: {fish_id}")

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # PASO 2: PREPARAR IMAGEN CON fish_id YA DEFINIDO
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            filename = f"AUTO_{fish_id}_L{length_cm:.1f}_P{weight_g:.1f}_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
            filepath = os.path.join(Config.IMAGES_AUTO_DIR, filename)
            os.makedirs(Config.IMAGES_AUTO_DIR, exist_ok=True)
            
            # Copiar frames originales
            frame_left = self.last_result['frame_left'].copy()
            frame_top = self.last_result['frame_top'].copy()
            
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # PASO 3: DIBUJAR CONTORNOS
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            contour_left = self.last_result.get('contour_left')
            contour_top = self.last_result.get('contour_top')
            
            # Dibujo Vista Lateral
            if contour_left is not None and isinstance(contour_left, np.ndarray) and len(contour_left) >= 3:
                cv2.drawContours(frame_left, [contour_left], -1, (0, 255, 0), 3)
                x, y, w, h = cv2.boundingRect(contour_left)
                cv2.rectangle(frame_left, (x, y), (x+w, y+h), (0, 255, 255), 2)
            
            # Dibujo Vista Cenital
            if contour_top is not None and isinstance(contour_top, np.ndarray) and len(contour_top) >= 3:
                cv2.drawContours(frame_top, [contour_top], -1, (0, 255, 0), 3)
                x, y, w, h = cv2.boundingRect(contour_top)
                cv2.rectangle(frame_top, (x, y), (x+w, y+h), (0, 255, 255), 2)
            
            # Combinar imágenes
            combined = np.hstack((
                cv2.resize(frame_left, (Config.SAVE_WIDTH, Config.SAVE_HEIGHT)),
                cv2.resize(frame_top, (Config.SAVE_WIDTH, Config.SAVE_HEIGHT))
            ))
            
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # PASO 4: DIBUJAR OVERLAY (fish_id YA ESTÁ DEFINIDO)
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            info_auto = {
                "tipo": "AUTO",
                "numero": fish_id,  # ✅ AHORA fish_id YA EXISTE
                "longitud": length_cm,
                "peso": weight_g,
                "fecha": timestamp.strftime('%Y-%m-%d %H:%M:%S')
            }
            combined_final = self.draw_fish_overlay(combined, info_auto)
            cv2.imwrite(filepath, combined_final)

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # PASO 5: CONSULTAR API DE SENSORES
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            logger.info("=" * 60)
            logger.info("🌐 Consultando sensores IoT externos (modo silencioso)...")
            
            try:
                api_data = SensorService.get_water_quality_data()
                
                if api_data and len(api_data) > 0:
                    has_valid_data = any(
                        v != 0 and v != 0.0 and v is not None 
                        for v in api_data.values()
                    )
                    
                    if has_valid_data:
                        logger.info(f"✅ Datos de sensores sincronizados")
                    else:
                        logger.warning("⚠️  API devolvió datos en 0")
                else:
                    logger.warning("⚠️  SensorService devolvió diccionario vacío")
                    api_data = {}
                    
            except Exception as e_sensor:
                logger.warning(f"⚠️  Error al consultar sensores: {e_sensor}")
                api_data = {}
            
            logger.info("=" * 60)
            
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # PASO 6: PREPARAR DICCIONARIO DE DATOS
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            data = {
                'timestamp': timestamp.isoformat(),
                'fish_id': str(fish_id),
                
                # Datos principales
                'length_cm': length_cm,
                'height_cm': height_cm,   
                'width_cm': width_cm,
                'weight_g': weight_g,
                
                # Datos Manuales (no aplican en auto)
                'manual_length_cm': 0.0,
                'manual_height_cm': 0.0,
                'manual_width_cm': 0.0,
                'manual_weight_g': 0.0,
                
                # Datos Avanzados
                'lat_area_cm2': lat_area,
                'top_area_cm2': top_area,
                'volume_cm3': vol,
                
                'confidence_score': confidence,
                'image_path': str(filepath),
                'measurement_type': 'auto',
                'notes': '[Medición Automática]',
                'validation_errors': ''
            }
            
            # Agregar datos de sensores
            if api_data:
                data.update(api_data)
            
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # PASO 7: GUARDAR EN BASE DE DATOS
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            measurement_id = self.db.save_measurement(data)
            
            logger.info(
                f"Auto-guardado silencioso: "
                f"ID={measurement_id}, "
                f"Fish={fish_id}, "
                f"L={length_cm:.1f}cm, "
                f"P={weight_g:.1f}g"
            )
            
            # Deshabilitar botón guardar
            self.btn_save.setEnabled(False)
            
            # Actualizar interfaz sin bloquear
            QTimer.singleShot(100, self.refresh_history)
            QTimer.singleShot(100, self.refresh_daily_counter)
            
            if hasattr(self, 'status_bar'):
                self.status_bar.set_status(f"Auto-Guardado #{measurement_id}", "success")
            
            return True
            
        except Exception as e:
            logger.error(f"FALLO en guardado automático: {e}", exc_info=True)
            if hasattr(self, 'unlock_after_save'):
                QTimer.singleShot(100, self.unlock_after_save)
            return False
        
    def generate_daily_id(self):
        """Genera un ID consecutivo basado en la fecha de hoy (Lógica Optimizada)"""
        try:
            db = getattr(self, 'db_manager', getattr(self, 'db', None))
            
            if db:
                next_id = db.get_next_fish_number()
            else:
                next_id = 1

            if hasattr(self, 'txt_manual_fish_id'):
                self.txt_manual_fish_id.setText(str(next_id))

                self.txt_manual_fish_id.setProperty("state", "info")
                self.txt_manual_fish_id.style().unpolish(self.txt_manual_fish_id)
                self.txt_manual_fish_id.style().polish(self.txt_manual_fish_id)

                QTimer.singleShot(2000, lambda: self._reset_widget_state(self.txt_manual_fish_id))
                
        except Exception as e:
            logger.error(f"Error generando ID diario: {e}.")
            if hasattr(self, 'status_bar'):
                self.status_bar.set_status("Error al auto-generar ID", "warning")

    def _reset_widget_state(self, widget):
        """Helper para limpiar estados visuales temporales"""
        if widget and widget.property("state") != "":
            widget.setProperty("state", "")
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def create_history_tab(self):
        """Crea la pestaña de historial con Búsqueda, Filtros y Tooltips Profesionales"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        top_controls = QHBoxLayout()
        
        # Título de Sección
        lbl_title = QLabel("Gestión de Registros")
        lbl_title.setProperty("class", "header-text")
        top_controls.addWidget(lbl_title)
        
        top_controls.addStretch()
        
        # --- Botón Recargar ---
        btn_refresh = QPushButton("Recargar")
        btn_refresh.setProperty("class", "secondary")
        btn_refresh.style().unpolish(btn_refresh)
        btn_refresh.style().polish(btn_refresh)
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setToolTip("Recarga la tabla con la información más reciente")
        btn_refresh.clicked.connect(self.refresh_history)
        top_controls.addWidget(btn_refresh)

        # --- Botón Editar ---
        btn_edit = QPushButton("Editar")
        btn_edit.setProperty("class", "info")
        btn_edit.style().unpolish(btn_edit)
        btn_edit.style().polish(btn_edit)
        btn_edit.setCursor(Qt.PointingHandCursor)
        btn_edit.setToolTip("Abre un editor para cambiar notas o corregir<br>"
                                "datos de la fila seleccionada.")
        btn_edit.clicked.connect(self.edit_selected_measurement)
        top_controls.addWidget(btn_edit)
        
        # --- Botón Eliminar ---
        btn_delete = QPushButton("Eliminar")
        btn_delete.setProperty("class", "warning")
        btn_delete.style().unpolish(btn_delete)
        btn_delete.style().polish(btn_delete)
        btn_delete.setCursor(Qt.PointingHandCursor)
        btn_delete.setToolTip("Elimina permanentemente la medición seleccionada<br>"
                                "y su imagen asociada.")
        btn_delete.clicked.connect(self.delete_selected_measurement)
        top_controls.addWidget(btn_delete)

        self.btn_toggle_history_preview = QPushButton("Ocultar vista previa")
        self.btn_toggle_history_preview.setProperty("class", "secondary")
        self.btn_toggle_history_preview.style().unpolish(self.btn_toggle_history_preview)
        self.btn_toggle_history_preview.style().polish(self.btn_toggle_history_preview)
        self.btn_toggle_history_preview.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_history_preview.setCheckable(True)
        self.btn_toggle_history_preview.setChecked(True)
        self.btn_toggle_history_preview.setToolTip("Mostrar u ocultar el panel de vista previa.")
        self.btn_toggle_history_preview.toggled.connect(self.toggle_history_preview)
        top_controls.addWidget(self.btn_toggle_history_preview)
        
        layout.addLayout(top_controls)

        filter_group = QGroupBox("Filtros de Búsqueda")
        filter_layout = QGridLayout(filter_group)
        filter_layout.setSpacing(10)

        # Buscador
        filter_layout.addWidget(QLabel("Texto (ID, Pez, Notas):"), 0, 0)
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Ej: pez_05, error, 123...")
        self.txt_search.setClearButtonEnabled(True) 
        self.txt_search.setToolTip(
            "Escribe el ID del pez, el número de registro<br>"
            "o palabras clave contenidas en las notas."
        )
        self.txt_search.returnPressed.connect(self.reset_pagination_and_refresh) 
        filter_layout.addWidget(self.txt_search, 0, 1)

        # Tipo
        filter_layout.addWidget(QLabel("Tipo de Medición:"), 0, 2)
        self.combo_filter_type = QComboBox()
        self.combo_filter_type.setCursor(Qt.PointingHandCursor)
        self.combo_filter_type.addItems(["Todos", "auto", "manual", "ia_refined","manual_qr","manual_externo_pc"]) 
        self.combo_filter_type.setToolTip(
            "<b>Filtrar por Origen de Medición</b><br><br>"
            "⚙️ <b>Automática</b>: Generada por el sistema.<br>"
            "✋ <b>Manual</b>: Ingresada directamente.<br>"
            "📱 <b>Manual (QR)</b>: Enviada desde celular.<br>"
            "💻 <b>Manual (PC)</b>: Importada desde el equipo.<br>"
            "🧠 <b>IA Refinada</b>: Ajustada por algoritmo."
        )
        self.combo_filter_type.currentTextChanged.connect(self.reset_pagination_and_refresh)
        filter_layout.addWidget(self.combo_filter_type, 0, 3)
        
        # Fecha Desde
        filter_layout.addWidget(QLabel("Desde:"), 1, 0)
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_from.setDate(QDate.currentDate().addDays(-90)) 
        self.date_from.setToolTip("Fecha inicial del rango de búsqueda.")
        filter_layout.addWidget(self.date_from, 1, 1)

        # Fecha Hasta
        filter_layout.addWidget(QLabel("Hasta:"), 1, 2)
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setDate(QDate.currentDate()) 
        self.date_to.setToolTip("Fecha final del rango de búsqueda (inclusive).")
        filter_layout.addWidget(self.date_to, 1, 3)
        
        # Botones de Filtro
        btn_container = QHBoxLayout()
        
        btn_search = QPushButton("Buscar")
        btn_search.setProperty("class", "primary")
        btn_search.style().unpolish(btn_search)
        btn_search.style().polish(btn_search)
        btn_search.setCursor(Qt.PointingHandCursor)
        btn_search.setToolTip("Aplica los filtros de texto, tipo y fecha seleccionados.")
        btn_search.clicked.connect(self.reset_pagination_and_refresh)
        btn_container.addWidget(btn_search)
        btn_search.style().unpolish(btn_search)
        btn_search.style().polish(btn_search)

        btn_clear = QPushButton("Limpiar")
        btn_clear.setProperty("class", "secondary")
        btn_clear.style().unpolish(btn_clear)
        btn_clear.style().polish(btn_clear)
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.setToolTip("Reinicia todos los filtros a su estado original.")
        btn_clear.clicked.connect(self.clear_filters) 
        btn_container.addWidget(btn_clear)
        
        filter_layout.addLayout(btn_container, 1, 4)

        layout.addWidget(filter_group)
        
        self.fixed_columns = [
            "ID", "Fecha/Hora", "Tipo", "Pez ID", "Largo (cm)",
            "Alto (cm)", "Ancho (cm)", "Peso (g)",
            "Factor K", "Confianza", "Notas"
        ]

        self.optional_columns = [
            "Temp Aire (°C)",
            "Temp Agua (°C)",
            "Humedad Rel (%)",
            "Humedad Abs (g/m3)",
            "pH",
            "Conductividad (µS/cm)",
            "Oxígeno Disuelto (mg/L)",
            "Turbidez (NTU)"
        ]

        all_columns = self.fixed_columns + self.optional_columns

        self.table_history = QTableWidget()
        self.table_history.setColumnCount(len(all_columns))
        self.table_history.setHorizontalHeaderLabels(all_columns)

        # Ocultar columnas opcionales
        start_optional = len(self.fixed_columns)
        for i in range(len(self.optional_columns)):
            self.table_history.setColumnHidden(start_optional + i, True)

        # Ocultar ID técnico
        self.table_history.setColumnHidden(0, True)

        # Configuración visual
        self.table_history.horizontalHeader().setSectionsMovable(False)
        self.table_history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_history.horizontalHeader().setStretchLastSection(True)
        self.table_history.setAlternatingRowColors(True)
        self.table_history.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_history.setSelectionMode(QTableWidget.SingleSelection)
        self.table_history.verticalHeader().setVisible(False)
        self.table_history.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.table_history.setToolTip(
            "💡 <b>Acciones rápidas:</b><br><br>"
            "🖱️ <b>Doble clic</b>: Ver imagen de la medición.<br>"
            "🖱️ <b>Clic derecho</b>: Editar registro seleccionado."
        )

        self.table_history.cellDoubleClicked.connect(self.view_measurement_image)
        self.table_history.itemSelectionChanged.connect(self.update_history_preview)
        self.table_history.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_history.customContextMenuRequested.connect(self.edit_from_right_click)

        # Menú para columnas opcionales
        header = self.table_history.horizontalHeader()
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self.show_column_menu)

        layout.addWidget(self.table_history)

        quick_totals_layout = QHBoxLayout()
        self.lbl_quick_total = QLabel("Total: 0")
        self.lbl_quick_manual = QLabel("Manuales: 0")
        self.lbl_quick_auto = QLabel("Automáticas: 0")
        self.lbl_quick_avg_length = QLabel("Largo Prom: 0.00 cm")
        self.lbl_quick_avg_weight = QLabel("Peso Prom: 0.00 g")

        for lbl in [
            self.lbl_quick_total,
            self.lbl_quick_manual,
            self.lbl_quick_auto,
            self.lbl_quick_avg_length,
            self.lbl_quick_avg_weight,
        ]:
            lbl.setProperty("class", "report-text")
            quick_totals_layout.addWidget(lbl)
            quick_totals_layout.addSpacing(10)
        quick_totals_layout.addStretch()
        layout.addLayout(quick_totals_layout)

        self.history_preview_group = QGroupBox("Vista previa")
        preview_group_layout = QVBoxLayout(self.history_preview_group)
        preview_group_layout.setContentsMargins(4, 4, 4, 4)
        preview_group_layout.setSpacing(0)

        self.lbl_history_preview = QLabel("Sin selección")
        self.lbl_history_preview.setAlignment(Qt.AlignCenter)
        self.lbl_history_preview.setFixedHeight(160)
        self.lbl_history_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.lbl_history_preview.setStyleSheet("border: 1px solid #6c757d;")
        preview_group_layout.addWidget(self.lbl_history_preview)
        layout.addWidget(self.history_preview_group)

        pagination_layout = QHBoxLayout()
        self.lbl_total_records = QLabel("Total: 0 registros")
        self.lbl_total_records.setStyleSheet("color: gray; font-style: italic;")
        pagination_layout.addWidget(self.lbl_total_records)
        
        pagination_layout.addStretch()
        
        pagination_layout.addWidget(QLabel("Mostrar:"))
        self.combo_limit = QComboBox()
        self.combo_limit.setCursor(Qt.PointingHandCursor)
        self.combo_limit.addItems(["25", "50", "100", "500"])
        self.combo_limit.setToolTip("Cantidad de filas a mostrar por página.")
        self.combo_limit.currentTextChanged.connect(self.reset_pagination_and_refresh)
        pagination_layout.addWidget(self.combo_limit)
        
        pagination_layout.addSpacing(20)

        self.btn_prev_page = QPushButton() 
        self.btn_prev_page.setFixedSize(30, 30)
        self.btn_prev_page.setProperty("class", "secondary")
        self.btn_prev_page.style().unpolish(self.btn_prev_page)
        self.btn_prev_page.style().polish(self.btn_prev_page)
        self.btn_prev_page.setCursor(Qt.PointingHandCursor)
        self.btn_prev_page.setToolTip("Ir a la página anterior.")
        icon_left = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowLeft)
        self.btn_prev_page.setIcon(icon_left)
        
        self.btn_prev_page.clicked.connect(self.prev_page)
        pagination_layout.addWidget(self.btn_prev_page)

        self.lbl_page_info = QLabel("1")
        self.lbl_page_info.setAlignment(Qt.AlignCenter)
        self.lbl_page_info.setFixedWidth(30)
        self.lbl_page_info.setProperty("class", "report-text")
        pagination_layout.addWidget(self.lbl_page_info)

        self.btn_next_page = QPushButton() 
        self.btn_next_page.setFixedSize(30, 30)
        self.btn_next_page.setProperty("class", "secondary")
        self.btn_next_page.style().unpolish(self.btn_next_page)
        self.btn_next_page.style().polish(self.btn_next_page)
        self.btn_next_page.setCursor(Qt.PointingHandCursor)
        self.btn_next_page.setToolTip("Ir a la página siguiente.")
        icon_right = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight)
        self.btn_next_page.setIcon(icon_right)
        
        self.btn_next_page.clicked.connect(self.next_page)
        pagination_layout.addWidget(self.btn_next_page)

        layout.addLayout(pagination_layout)
        
        # Inicializar
        self.current_page = 1
        self.current_page_offset = 0
        self.history_total_records = 0
        self.load_measurements()
        
        return widget
    
    def load_measurements(self):
        """
        Wrapper legado: usa el flujo unificado de refresh.
        """
        self.refresh_history()

    def show_column_menu(self, position):
        """Menú contextual para mostrar/ocultar columnas (Click derecho en cabecera)"""
        menu = QMenu(self)

        for i, name in enumerate(self.optional_columns):
            # Calculamos el índice real en la tabla (después de las fijas)
            col_index = len(self.fixed_columns) + i

            action = QAction(name, self)
            action.setCheckable(True)
            # Marcado si la columna NO está oculta
            action.setChecked(not self.table_history.isColumnHidden(col_index))

            # Conectamos la acción
            action.triggered.connect(
                lambda checked, c=col_index:
                    self.table_history.setColumnHidden(c, not checked)
            )

            menu.addAction(action)

        # Mostrar menú en la posición del ratón
        header = self.table_history.horizontalHeader()
        menu.exec(header.mapToGlobal(position))
        
    def edit_from_right_click(self, position):
        item = self.table_history.itemAt(position)

        if item is not None:
            self.table_history.selectRow(item.row())

            self.edit_selected_measurement()

    def clear_filters(self):
        """Resetea los filtros y limpia la búsqueda visualmente"""
        self.txt_search.clear()
        self.combo_filter_type.setCurrentIndex(0) 
        
        self.date_from.setDate(QDate.currentDate().addDays(-90))
        self.date_to.setDate(QDate.currentDate())

        if hasattr(self, 'status_bar'):
            self.status_bar.set_status("Filtros reiniciados", "info")
            
        self.reset_pagination_and_refresh()

    def reset_pagination_and_refresh(self):
        """Reinicia el puntero y refresca toda la data relacionada"""
        self.current_page_offset = 0
        self.refresh_history()
        self.refresh_daily_counter()
        sender = self.sender()
        if sender is not None and hasattr(sender, 'clearFocus'):
            sender.clearFocus()

    def next_page(self):
        """Avanza de página basado en el límite seleccionado"""
        limit = int(self.combo_limit.currentText())
        if self.current_page_offset + limit >= self.history_total_records:
            return
        self.current_page_offset += limit
        self.refresh_history()

    def prev_page(self):
        """Retrocede de página asegurando no llegar a números negativos"""
        limit = int(self.combo_limit.currentText())
        if self.current_page_offset >= limit:
            self.current_page_offset -= limit
            self.refresh_history()
        else:
            self.current_page_offset = 0 # 
    
    def refresh_history(self):
        """Recarga la tabla con filtros aplicados - VERSIÓN CORREGIDA"""
        
        if not hasattr(self, 'db'): 
            return
        
        if not hasattr(self, 'current_page_offset'):
            self.current_page_offset = 0

        search_text = self.txt_search.text().strip()
        
        filter_type = self.combo_filter_type.currentText()
        if filter_type == "Todos": 
            filter_type = None
        elif filter_type == "Automáticas": 
            filter_type = "auto"
        elif filter_type == "Manuales": 
            filter_type = "manual"
        
        date_start = self.date_from.date().toString("yyyy-MM-dd")
        date_end = self.date_to.date().toString("yyyy-MM-dd")

        if self.date_from.date() > self.date_to.date():
            self.status_bar.set_status("Rango de fechas inválido: 'Desde' no puede ser mayor que 'Hasta'", "warning")
            self.table_history.setRowCount(0)
            self.lbl_total_records.setText("No se encontraron registros.")
            self.lbl_page_info.setText("0")
            self.history_total_records = 0
            self.btn_prev_page.setEnabled(False)
            self.btn_next_page.setEnabled(False)
            self.update_history_quick_totals(None)
            self.clear_history_preview()
            return
        
        try:
            limit = int(self.combo_limit.currentText())
        except:
            limit = 25

        self.history_total_records = self.db.get_filtered_measurements_count(
            search_query=search_text,
            filter_type=filter_type,
            date_start=date_start,
            date_end=date_end
        )

        measurements = self.db.get_filtered_measurements(
            limit=limit, 
            offset=self.current_page_offset,
            search_query=search_text,
            filter_type=filter_type,
            date_start=date_start,
            date_end=date_end
        )

        if self.current_page_offset >= self.history_total_records and self.history_total_records > 0:
            last_page_offset = ((self.history_total_records - 1) // limit) * limit
            self.current_page_offset = max(0, last_page_offset)
            measurements = self.db.get_filtered_measurements(
                limit=limit,
                offset=self.current_page_offset,
                search_query=search_text,
                filter_type=filter_type,
                date_start=date_start,
                date_end=date_end
            )
        
        self.table_history.setRowCount(0)
        
        if not measurements:
            self.lbl_total_records.setText("No se encontraron registros.")
            self.lbl_page_info.setText("0")
            self.btn_prev_page.setEnabled(False)
            self.btn_next_page.setEnabled(False)
            self.update_history_quick_totals({
                "total": self.history_total_records,
                "avg_length": 0.0,
                "avg_weight": 0.0,
                "manual_total": 0,
                "auto_total": 0,
            })
            self.clear_history_preview()
            return

        self.table_history.setRowCount(len(measurements))
        
        for row, m in enumerate(measurements):
            
            def get_safe(idx, default=""):
                try:
                    val = m[idx]
                    return val if val is not None else default
                except IndexError:
                    return default

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # COLUMNAS FIJAS (0-10)
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            
            # Columna 0: ID
            val_id = get_safe(0, 0)
            self.table_history.setItem(row, 0, QTableWidgetItem(str(val_id)))
            
            # Columna 1: Fecha/Hora
            ts_str = str(get_safe(1, ""))
            try:
                if "." in ts_str: 
                    ts_str = ts_str.split(".")[0] 
                ts_obj = datetime.fromisoformat(ts_str)
                ts_nice = ts_obj.strftime('%d/%m/%Y %H:%M')
            except:
                ts_nice = ts_str
            self.table_history.setItem(row, 1, QTableWidgetItem(ts_nice))
            
            # Columna 2: Tipo
            val_type = str(get_safe(17, "auto")).upper()
            item_type = QTableWidgetItem(val_type)
            
            if "MANUAL" in val_type:
                item_type.setBackground(QColor("#fff3cd")) 
                item_type.setForeground(QColor("#856404"))
            elif "IA" in val_type:
                item_type.setBackground(QColor("#d4edda"))
                item_type.setForeground(QColor("#155724"))
            else:
                item_type.setBackground(QColor("#e7f1ff")) 
            self.table_history.setItem(row, 2, item_type)
            
            # Columna 3: Pez ID
            val_fish = str(get_safe(2, "-"))
            self.table_history.setItem(row, 3, QTableWidgetItem(val_fish))
            
            def format_num(idx, decimals=2):
                try:
                    val = float(get_safe(idx, 0))
                    return f"{val:.{decimals}f}"
                except: 
                    return "0.00"

            # Columna 4: Largo (cm)
            self.table_history.setItem(row, 4, QTableWidgetItem(format_num(3)))
            
            # Columna 5: Alto (cm)
            h_manual = float(get_safe(8, 0))
            h_ia = float(get_safe(4, 0))
            val_h = h_manual if h_manual > 0 else h_ia
            self.table_history.setItem(row, 5, QTableWidgetItem(f"{val_h:.2f}"))
            
            # Columna 6: Ancho (cm)
            w_manual = float(get_safe(9, 0))
            w_ia = float(get_safe(5, 0))
            val_w = w_manual if w_manual > 0 else w_ia
            self.table_history.setItem(row, 6, QTableWidgetItem(f"{val_w:.2f}"))
            
            # Columna 7: Peso (g)
            weight_val = float(get_safe(6, 0))
            self.table_history.setItem(row, 7, QTableWidgetItem(f"{weight_val:.2f}"))
            
            # Columna 8: Factor K
            l_val = float(get_safe(3, 0)) 
            if l_val > 0 and weight_val > 0:
                k = (100 * weight_val) / (l_val ** 3)
                k_str = f"{k:.3f}"
            else:
                k_str = "-"
            self.table_history.setItem(row, 8, QTableWidgetItem(k_str))
            
            # Columna 9: Confianza
            conf = float(get_safe(14, 0))
            item_conf = QTableWidgetItem(f"{conf:.0%}")
            if conf < 0.85 and conf > 0:
                item_conf.setForeground(QColor("red"))
                item_conf.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table_history.setItem(row, 9, item_conf)
            
            # Columna 10: Notas
            val_notes = str(get_safe(15, ""))
            self.table_history.setItem(row, 10, QTableWidgetItem(val_notes))

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # COLUMNAS API (11-18) - CÓDIGO QUE FALTABA
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            
            # Los índices en MEASUREMENT_COLUMNS:
            # 19: api_air_temp_c
            # 20: api_water_temp_c
            # 21: api_rel_humidity
            # 22: api_abs_humidity_g_m3
            # 23: api_ph
            # 24: api_cond_us_cm
            # 25: api_do_mg_l
            # 26: api_turbidity_ntu
            
            api_indices = [19, 20, 21, 22, 23, 24, 25, 26]
            start_col = 11  # Después de las columnas fijas
            
            for i, idx in enumerate(api_indices):
                raw_val = get_safe(idx)
                
                # Visualización limpia
                if raw_val is None or raw_val == "" or raw_val == 0:
                    display_text = "-"
                else:
                    try:
                        val_float = float(raw_val)
                        if val_float == 0:
                            display_text = "-"
                        else:
                            display_text = f"{val_float:.2f}"
                    except:
                        display_text = str(raw_val)
                
                item = QTableWidgetItem(display_text)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table_history.setItem(row, start_col + i, item)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ACTUALIZAR PAGINACIÓN Y CONTADORES
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        limit = int(self.combo_limit.currentText())
        current_page = (self.current_page_offset // limit) + 1
        self.lbl_page_info.setText(str(current_page))
        
        count_shown = len(measurements)
        self.lbl_total_records.setText(f"Mostrando {count_shown} de {self.history_total_records} registros")
        
        self.btn_prev_page.setEnabled(self.current_page_offset > 0)
        self.btn_next_page.setEnabled(self.current_page_offset + count_shown < self.history_total_records)

        quick_totals = self.db.get_filtered_measurements_quick_totals(
            search_query=search_text,
            filter_type=filter_type,
            date_start=date_start,
            date_end=date_end
        )
        self.update_history_quick_totals(quick_totals)
        self.update_history_preview()
        
        if hasattr(self, 'refresh_daily_counter'):
            self.refresh_daily_counter()

    def update_history_quick_totals(self, totals):
        """Actualiza los indicadores de resumen rápido del historial."""
        if totals is None:
            totals = {
                "total": 0,
                "manual_total": 0,
                "auto_total": 0,
                "avg_length": 0.0,
                "avg_weight": 0.0,
            }

        total = int(totals.get("total", 0) or 0)
        manual_total = int(totals.get("manual_total", 0) or 0)
        auto_total = int(totals.get("auto_total", 0) or 0)
        avg_length = float(totals.get("avg_length", 0.0) or 0.0)
        avg_weight = float(totals.get("avg_weight", 0.0) or 0.0)

        self.lbl_quick_total.setText(f"Total: {total}")
        self.lbl_quick_manual.setText(f"Manuales: {manual_total}")
        self.lbl_quick_auto.setText(f"Automáticas: {auto_total}")
        self.lbl_quick_avg_length.setText(f"Largo Prom: {avg_length:.2f} cm")
        self.lbl_quick_avg_weight.setText(f"Peso Prom: {avg_weight:.2f} g")

    def toggle_history_preview(self, checked):
        """Permite mostrar u ocultar la vista previa del historial."""
        if hasattr(self, 'history_preview_group'):
            self.history_preview_group.setVisible(checked)

        if hasattr(self, 'btn_toggle_history_preview'):
            self.btn_toggle_history_preview.setText(
                "Ocultar vista previa" if checked else "Mostrar vista previa"
            )

        if checked:
            self.update_history_preview()

    def _resolve_measurement_image_path(self, measurement_data):
        """Resuelve la ruta real de la imagen usando ruta directa, nombre y timestamp."""
        if not measurement_data:
            return None

        image_path = str(measurement_data.get('image_path', '') or '').strip()
        fish_id = str(measurement_data.get('fish_id', '') or '').strip()
        ts_str = str(measurement_data.get('timestamp', '') or '').strip()

        if image_path:
            abs_path = os.path.abspath(image_path)
            if os.path.exists(abs_path):
                return abs_path
            if os.path.exists(image_path):
                return image_path

        search_dirs = [
            os.path.abspath(Config.IMAGES_MANUAL_DIR),
            os.path.abspath(Config.IMAGES_AUTO_DIR),
            os.path.abspath(os.path.join("Resultados", "Imagenes_Manuales")),
            os.path.abspath(os.path.join("Resultados", "Imagenes_Automaticas")),
        ]

        unique_dirs = []
        for path in search_dirs:
            if path not in unique_dirs and os.path.isdir(path):
                unique_dirs.append(path)

        filename = os.path.basename(image_path) if image_path else ""
        if filename:
            for base in unique_dirs:
                candidate = os.path.join(base, filename)
                if os.path.exists(candidate):
                    return candidate

        timestamp_key = ""
        if ts_str:
            timestamp_key = ts_str.replace("-", "").replace(":", "").replace(" ", "_")[:15]

        if len(timestamp_key) > 10:
            valid_ext = ('.jpg', '.jpeg', '.png', '.bmp', '.webp')
            matches = []
            for base in unique_dirs:
                try:
                    for name in os.listdir(base):
                        lower_name = name.lower()
                        if timestamp_key in name and lower_name.endswith(valid_ext):
                            matches.append(os.path.join(base, name))
                except Exception:
                    continue

            if matches:
                if fish_id:
                    for candidate in matches:
                        if fish_id in os.path.basename(candidate):
                            return candidate
                return matches[0]

        return None

    def clear_history_preview(self):
        """Limpia el panel de vista previa del historial."""
        self.current_preview_image_path = None
        if hasattr(self, 'lbl_history_preview'):
            self.lbl_history_preview.setPixmap(QPixmap())
            self.lbl_history_preview.setText("Sin selección")

    def _copy_preview_path(self):
        """Copia la ruta de la imagen actual al portapapeles."""
        path = getattr(self, 'current_preview_image_path', None)
        if path and os.path.exists(path):
            QApplication.clipboard().setText(os.path.abspath(path))

    def _render_history_preview_pixmap(self, pixmap):
        """Renderiza miniatura respetando relación de aspecto (imagen completa visible)."""
        if not hasattr(self, 'lbl_history_preview') or pixmap is None or pixmap.isNull():
            return False

        target_size = self.lbl_history_preview.size()
        if target_size.width() <= 1 or target_size.height() <= 1:
            return False

        scaled = pixmap.scaled(
            target_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

        self.lbl_history_preview.setPixmap(scaled)
        self.lbl_history_preview.setText("")
        return True

    def update_history_preview(self):
        """Actualiza la miniatura de la fila seleccionada en historial."""
        if not hasattr(self, 'table_history'):
            return

        if hasattr(self, 'history_preview_group') and not self.history_preview_group.isVisible():
            return

        row = self.table_history.currentRow()
        if row < 0:
            self.clear_history_preview()
            return

        id_item = self.table_history.item(row, 0)
        if id_item is None:
            self.clear_history_preview()
            return

        try:
            measurement_id = int(id_item.text())
        except (TypeError, ValueError):
            self.clear_history_preview()
            return

        data = self.db.get_measurement_as_dict(measurement_id)
        if not data:
            self.clear_history_preview()
            return

        image_path = self._resolve_measurement_image_path(data)
        self.current_preview_image_path = image_path

        has_image = bool(image_path and os.path.exists(image_path))

        if has_image:
            pixmap = QPixmap(image_path)
            if not self._render_history_preview_pixmap(pixmap):
                self.lbl_history_preview.setPixmap(QPixmap())
                self.lbl_history_preview.setText("Sin vista previa")
        else:
            self.lbl_history_preview.setPixmap(QPixmap())
            self.lbl_history_preview.setText("Sin imagen")

    def create_statistics_tab(self):
        """Crea la pestaña de estadísticas """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        controls = QHBoxLayout()

        btn_generate_stats = QPushButton("Generar Estadísticas")
        btn_generate_stats.setProperty("class", "primary")  
        btn_generate_stats.style().unpolish(btn_generate_stats)
        btn_generate_stats.style().polish(btn_generate_stats)
        btn_generate_stats.setCursor(Qt.PointingHandCursor)
        btn_generate_stats.setToolTip(
            "Analiza las mediciones de la base de datos, calcula promedios<br>"
            "y genera los gráficos visuales en la galería."
        )
        btn_generate_stats.clicked.connect(self.generate_statistics)
        controls.addWidget(btn_generate_stats)

        self.btn_toggle_stats_report = QPushButton("Ocultar reporte")
        self.btn_toggle_stats_report.setProperty("class", "secondary")
        self.btn_toggle_stats_report.style().unpolish(self.btn_toggle_stats_report)
        self.btn_toggle_stats_report.style().polish(self.btn_toggle_stats_report)
        self.btn_toggle_stats_report.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_stats_report.setCheckable(True)
        self.btn_toggle_stats_report.setChecked(True)
        self.btn_toggle_stats_report.setToolTip("Mostrar u ocultar el panel de reporte detallado.")
        self.btn_toggle_stats_report.toggled.connect(self.toggle_statistics_report)
        controls.addWidget(self.btn_toggle_stats_report)
        
        controls.addStretch()
        layout.addLayout(controls)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self._stats_splitter_handle_width = self.splitter.handleWidth()
        self.splitter.setChildrenCollapsible(True)
        
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0,0,0,0)
        
        lbl_gallery = QLabel("Explorador de Gráficos")
        lbl_gallery.setProperty("class", "header-text") 
        left_layout.addWidget(lbl_gallery)
        
        self.gallery_list = QListWidget()
        self.gallery_list.setProperty("class", "gallery-list")
        self.gallery_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.gallery_list.setIconSize(QSize(230, 165))
        self.gallery_list.setGridSize(QSize(255, 210))
        self.gallery_list.setWordWrap(True)
        self.gallery_list.setSpacing(10) 
        self.gallery_list.itemDoubleClicked.connect(self.open_enlarged_graph)
        left_layout.addWidget(self.gallery_list)
        
        self.stats_report_panel = QWidget()
        right_layout = QVBoxLayout(self.stats_report_panel)
        right_layout.setContentsMargins(0,0,0,0)
        
        lbl_report = QLabel("Reporte Detallado")
        lbl_report.setProperty("class", "header-text")
        right_layout.addWidget(lbl_report)
        
        self.stats_text = QTextEdit()
        self.stats_text.setProperty("class", "report-text")
        self.stats_text.setReadOnly(True)
        self.stats_text.setPlaceholderText("Genere estadísticas para ver el resumen analítico.")
        right_layout.addWidget(self.stats_text)

        self.splitter.addWidget(left_container)
        self.splitter.addWidget(self.stats_report_panel)
        self.splitter.setStretchFactor(0, 7) 
        self.splitter.setStretchFactor(1, 3) 
        layout.addWidget(self.splitter)
        
        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 5, 0, 0) 
        
        grp_graphs = QGroupBox("Exportar Gráfico Individual")
        grid_graphs = QGridLayout(grp_graphs)
        grid_graphs.setSpacing(8)
        
        buttons_config = [
            # Fila 0: Distribuciones Básicas
            ("📏 Histograma Tallas", 'length', 
               "<b>DISTRIBUCIÓN TALLAS:</b><br>Frecuencia de longitudes del lote para evaluar uniformidad.", 0, 0),
             
            ("⚖️ Histograma Pesos", 'weight', 
               "<b>DISTRIBUCIÓN PESO:</b><br>Frecuencia de biomasa y dispersión de pesos.", 0, 1),
             
            ("📈 Salud (L vs P)", 'correlation', 
               "<b>RELACIÓN L/P:</b><br>Relación longitud-peso por pez para detectar consistencia biológica.", 0, 2),
             
            # Fila 1: Crecimiento y Morfometría
            ("⏱ Crecimiento (Peso)", 'timeline_weight', 
               "<b>EVOLUCIÓN PESO:</b><br>Promedio semanal y tendencia proyectada (Gompertz/lineal).", 1, 0),
             
            ("📏 Crecimiento (Largo)", 'timeline_length', 
               "<b>EVOLUCIÓN LONGITUD:</b><br>Evolución semanal de talla con proyección futura.", 1, 1),
             
            ("🧬 Morfometría (H/W)", 'morphometry', 
               "<b>ANCHO Y ALTO:</b><br>Distribución comparada de altura y ancho corporal.", 1, 2),

              # Fila 2: Condición corporal y variabilidad
              ("🧪 Factor K", 'k_factor',
               "<b>FACTOR K:</b><br>Estado corporal del lote; compara contra zona óptima.", 2, 0),

              ("📐 Perfil Corporal", 'body_profile',
               "<b>PERFIL CORPORAL:</b><br>Dispersión ancho vs altura para forma del pez.", 2, 1),

              ("📦 Variabilidad (CV%)", 'variability',
               "<b>VARIABILIDAD:</b><br>Coeficiente de variación por métrica biométrica.", 2, 2),

              # Fila 3: Operación y control de muestreo
              ("📅 Muestreo Semanal", 'sampling_weekly',
               "<b>INTENSIDAD DE MUESTREO:</b><br>Cantidad de mediciones por semana.", 3, 0),

              ("📊 Clases de Talla", 'size_classes',
               "<b>CLASES DE TALLA:</b><br>Distribución por intervalos de longitud para clasificación del lote.", 3, 1),

              ("🫀 Tendencia Factor K", 'condition_trend',
               "<b>TENDENCIA K:</b><br>Evolución semanal del estado de condición corporal.", 3, 2),
        ]

        for text, key, tip, r, c in buttons_config:
            btn = QPushButton(text)
            btn.setProperty("class", "secondary")
            btn.setCursor(Qt.PointingHandCursor)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda checked, x=key: self.export_individual_graph(x))
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred) 
            grid_graphs.addWidget(btn, r, c)

        bottom_layout.addWidget(grp_graphs, stretch=7) 

        grp_tools = QGroupBox("Datos y Sistema")
        tools_layout = QVBoxLayout(grp_tools)
        tools_layout.setSpacing(8)
        
        btn_csv = QPushButton("Exportar CSV (Excel)")
        btn_csv.setProperty("class", "success") 
        btn_csv.style().unpolish(btn_csv)
        btn_csv.style().polish(btn_csv)
        btn_csv.setCursor(Qt.PointingHandCursor)
        btn_csv.setToolTip(
            "Descarga todas las mediciones en formato .CSV"
        )
        btn_csv.clicked.connect(self.export_to_csv)
        tools_layout.addWidget(btn_csv)
        
        btn_export_stats = QPushButton("Exportar Gráficos (PNG)")
        btn_export_stats.setProperty("class", "success") 
        btn_export_stats.style().unpolish(btn_export_stats) 
        btn_export_stats.style().polish(btn_export_stats)  
        btn_export_stats.setCursor(Qt.PointingHandCursor)
        btn_export_stats.setToolTip(
            "Guarda los gráficos actuales como archivos de imagen (PNG)."
        )
        btn_export_stats.clicked.connect(self.export_statistics)
        tools_layout.addWidget(btn_export_stats)

        btn_export_pdf = QPushButton("Reporte PDF")
        btn_export_pdf.setProperty("class", "success") 
        btn_export_pdf.style().unpolish(btn_export_pdf) 
        btn_export_pdf.style().polish(btn_export_pdf)       
        btn_export_pdf.setCursor(Qt.PointingHandCursor)
        btn_export_pdf.setToolTip(
            "Genera un documento PDF formal que incluye:<br>"
            "• Tabla de resumen de datos.<br>"
            "• Todos los gráficos generados visualmente."
        )
        btn_export_pdf.clicked.connect(self.export_stats_pdf)  
        tools_layout.addWidget(btn_export_pdf)
        
        # Botón Abrir Carpeta
        btn_folder = QPushButton("Abrir Carpeta de Resultados")
        btn_folder.setProperty("class", "info")
        btn_folder.style().unpolish(btn_folder) 
        btn_folder.style().polish(btn_folder)
        btn_folder.setCursor(Qt.PointingHandCursor)
        btn_folder.setToolTip(
            "Abre el explorador de Windows en la carpeta<br>"
            "donde se guardan los gráficos y reportes."
        )
        btn_folder.clicked.connect(self.open_output_folder) 
        tools_layout.addWidget(btn_folder)
        
        bottom_layout.addWidget(grp_tools, stretch=3)
        
        layout.addWidget(bottom_widget)
        
        return widget

    def toggle_statistics_report(self, checked):
        """Permite mostrar u ocultar el panel de reporte detallado."""
        if hasattr(self, 'stats_report_panel'):
            self.stats_report_panel.setVisible(checked)
            self.stats_report_panel.setMaximumWidth(16777215 if checked else 0)

        if hasattr(self, 'btn_toggle_stats_report'):
            self.btn_toggle_stats_report.setText(
                "Ocultar reporte" if checked else "Mostrar reporte"
            )

        if checked and hasattr(self, 'splitter'):
            self.splitter.setHandleWidth(getattr(self, '_stats_splitter_handle_width', 6))
            self.splitter.setSizes([700, 300])
        elif hasattr(self, 'splitter'):
            self.splitter.setHandleWidth(0)
            self.splitter.setSizes([1, 0])
    
    def open_output_folder(self):
        """Abre la carpeta de resultados en el explorador del sistema"""

        
        path = os.path.abspath(Config.OUT_DIR)
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as e:
                self.status_bar.set_status("Error al crear carpeta de salida", "error")
                return

        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin": 
                subprocess.Popen(["open", path])
            else:  
                subprocess.Popen(["xdg-open", path])
            
            if hasattr(self, 'status_bar'):
                self.status_bar.set_status(f"Carpeta abierta: {os.path.basename(path)}", "info")
                
        except Exception as e:
            logger.error(f"Error abriendo carpeta de salida: {e}.")
            QMessageBox.warning(self, "Error", f"No se pudo abrir la carpeta:\n{str(e)}")
    
    def add_graph_to_gallery(self, figure, title):
        """
        Convierte una figura de Matplotlib en un icono de alta calidad y lo añade al explorador.
        Optimizado para evitar pixelado en la miniatura.
        """
        canvas = FigureCanvas(figure)
        canvas.draw()
        
        width, height = canvas.get_width_height()
        image = QImage(canvas.buffer_rgba(), width, height, QImage.Format.Format_RGBA8888)
        pixmap = QPixmap.fromImage(image)

        thumb_size = self.gallery_list.iconSize()
        thumbnail = pixmap.scaled(
            thumb_size, 
            Qt.AspectRatioMode.KeepAspectRatio, 
            Qt.TransformationMode.SmoothTransformation
        )
        
        item = QListWidgetItem(QIcon(thumbnail), title)

        item.setData(Qt.ItemDataRole.UserRole, pixmap)

        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.gallery_list.addItem(item)

    def _build_stats_graph_tooltip(self, graph_key):
        """Devuelve una descripción corta y útil para cada gráfica estadística."""
        tooltip_map = {
            'length': "Frecuencia de tallas del lote. Permite revisar dispersión y uniformidad de longitud.",
            'weight': "Frecuencia de pesos del lote para monitorear biomasa y heterogeneidad.",
            'correlation': "Relación longitud-peso por individuo. Ayuda a detectar crecimiento fuera de patrón.",
            'timeline_weight': "Evolución semanal del peso promedio con tendencia proyectada.",
            'timeline_length': "Evolución semanal de la longitud promedio con tendencia proyectada.",
            'morphometry': "Comparación de distribuciones de altura y ancho corporal.",
            'k_factor': "Distribución del factor de condición K del lote; referencia de estado corporal.",
            'body_profile': "Dispersión ancho vs altura para evaluar perfil corporal y consistencia morfológica.",
            'variability': "Coeficiente de variación (CV%) por indicador: longitud, peso, altura y ancho.",
            'sampling_weekly': "Número de mediciones por semana para control de cobertura de muestreo.",
            'size_classes': "Conteo de peces por clase de talla para segmentación operativa.",
            'condition_trend': "Promedio semanal del factor K para seguimiento de condición del lote.",
        }
        return tooltip_map.get(graph_key, "Gráfica estadística del lote.")

    def export_individual_graph(self, graph_type):
        """
        💾 EXPORTADOR PROFESIONAL (CORREGIDO):
        - Usa mapeo de columnas local (infalible).
        - Genera gráficos de alta calidad (300 DPI) con fondo blanco.
        - Usa matemática Gompertz/Lineal para curvas de crecimiento.
        """
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import numpy as np
        from datetime import datetime, timedelta
        from scipy.optimize import curve_fit 

        # 1. Obtener Datos
        measurements = self.db.get_filtered_measurements(limit=3000)
        if not measurements:
            QMessageBox.warning(self, "Advertencia", "No hay datos en la base de datos.")
            return

        stats_data = self._build_statistics_dataset(measurements)

        # 2. Configurar Estilo de Reporte (Fondo Blanco)
        plt.style.use('default') 
        plt.rcParams.update({'font.size': 10, 'font.family': 'sans-serif'})
        
        # Colores
        C_BLUE = '#2980b9'
        C_GREEN = '#27ae60'
        C_RED = '#c0392b'
        C_PURPLE = '#8e44ad'
        C_ORANGE = '#d35400'

        # Preparar Figura
        fig, ax = plt.subplots(figsize=(10, 6), dpi=300)
        
        has_data = False

        # ======================================================================
        # LÓGICA DE GRÁFICOS
        # ======================================================================

        # A. HISTOGRAMAS
        if graph_type == 'length':
            data = stats_data['lengths']
            if data:
                ax.hist(data, bins=15, color=C_BLUE, alpha=0.7, edgecolor='black')
                ax.set_title('Distribución de Tallas (Longitud)', fontweight='bold')
                ax.set_xlabel('Longitud (cm)'); ax.set_ylabel('Frecuencia')
                ax.axvline(np.mean(data), color='red', linestyle='--', label=f'Promedio: {np.mean(data):.1f} cm')
                has_data = True

        elif graph_type == 'weight':
            data = stats_data['weights']
            if data:
                ax.hist(data, bins=15, color=C_GREEN, alpha=0.7, edgecolor='black')
                ax.set_title('Distribución de Biomasa (Peso)', fontweight='bold')
                ax.set_xlabel('Peso (g)'); ax.set_ylabel('Frecuencia')
                ax.axvline(np.mean(data), color='red', linestyle='--', label=f'Promedio: {np.mean(data):.1f} g')
                has_data = True

        elif graph_type == 'morphometry':
            h_data = stats_data['heights']
            w_data = stats_data['widths']
            
            if h_data:
                ax.hist(h_data, bins=10, color=C_BLUE, alpha=0.5, label='Altura', edgecolor='black')
                has_data = True
            if w_data:
                ax.hist(w_data, bins=10, color=C_ORANGE, alpha=0.5, label='Ancho', edgecolor='black')
                has_data = True
            
            ax.set_title('Morfometría (Altura y Ancho)', fontweight='bold')
            ax.set_xlabel('Medida (cm)')
            ax.set_ylabel('Frecuencia')

        # B. SCATTER (Correlación)
        elif graph_type == 'correlation':
            l_list = [pair[0] for pair in stats_data['pairs']]
            w_list = [pair[1] for pair in stats_data['pairs']]
            
            if l_list:
                # CORRECCIÓN: Agregamos label='Muestras' para que ax.legend() funcione
                ax.scatter(l_list, w_list, c=C_RED, alpha=0.6, edgecolors='black', label='Muestras')
                
                ax.set_title('Relación Longitud / Peso', fontweight='bold')
                ax.set_xlabel('Longitud (cm)'); ax.set_ylabel('Peso (g)')
                has_data = True

        elif graph_type == 'k_factor':
            k_values = stats_data['k_factors']
            if k_values:
                ax.hist(k_values, bins=12, color='#16a085', alpha=0.75, edgecolor='black', label='Muestras')
                ax.axvspan(1.0, 1.4, color='#2ecc71', alpha=0.15, label='Zona óptima')
                ax.axvline(np.mean(k_values), color='#0b5345', linestyle='--', linewidth=1.8, label=f"Promedio: {np.mean(k_values):.3f}")
                ax.set_title('Distribución Factor K', fontweight='bold')
                ax.set_xlabel('Factor de condición K'); ax.set_ylabel('Frecuencia')
                has_data = True

        elif graph_type == 'body_profile':
            body_records = [record for record in stats_data['records'] if record.get('height', 0) > 0 and record.get('width', 0) > 0]
            if body_records:
                widths = [record['width'] for record in body_records]
                heights = [record['height'] for record in body_records]
                ax.scatter(widths, heights, c='#af7ac5', alpha=0.65, edgecolors='black', linewidths=0.4, label='Muestras')

                if len(widths) >= 2:
                    coeffs = np.polyfit(widths, heights, 1)
                    trend_x = np.linspace(min(widths), max(widths), 60)
                    trend_y = np.poly1d(coeffs)(trend_x)
                    ax.plot(trend_x, trend_y, '--', color='#5b2c6f', linewidth=1.6, label='Tendencia')

                ax.set_title('Perfil Corporal (Ancho vs Altura)', fontweight='bold')
                ax.set_xlabel('Ancho dorsal (cm)'); ax.set_ylabel('Altura corporal (cm)')
                has_data = True

        elif graph_type == 'variability':
            metric_map = {
                'Longitud': stats_data['lengths'],
                'Peso': stats_data['weights'],
                'Altura': stats_data['heights'],
                'Ancho': stats_data['widths'],
            }
            labels = []
            cv_values = []
            for label, values in metric_map.items():
                if len(values) >= 2 and np.mean(values) > 0:
                    labels.append(label)
                    cv_values.append((np.std(values) / np.mean(values)) * 100)

            if labels:
                bars = ax.bar(labels, cv_values, color=['#3498db', '#2ecc71', '#1abc9c', '#f1c40f'][:len(labels)], edgecolor='black', alpha=0.85)
                for bar, value in zip(bars, cv_values):
                    ax.text(bar.get_x() + bar.get_width() / 2, value + 0.35, f"{value:.1f}%", ha='center', va='bottom', fontsize=9, fontweight='bold')
                ax.set_title('Variabilidad Biométrica (CV%)', fontweight='bold')
                ax.set_xlabel('Indicador'); ax.set_ylabel('Coeficiente de variación (%)')
                has_data = True

        elif graph_type == 'sampling_weekly':
            weekly_counts = self._build_weekly_metric_map(stats_data['records'], 'length')
            if weekly_counts:
                weeks = sorted(weekly_counts.keys())
                labels = [datetime.combine(week, datetime.min.time()) for week in weeks]
                counts = [len(weekly_counts[week]) for week in weeks]
                ax.bar(labels, counts, color='#5dade2', edgecolor='#1b4f72', width=5, label='Mediciones')
                ax.set_title('Intensidad de Muestreo Semanal', fontweight='bold')
                ax.set_xlabel('Semana'); ax.set_ylabel('Número de mediciones')
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%b'))
                fig.autofmt_xdate(rotation=45, ha='right')
                has_data = True

        elif graph_type == 'size_classes':
            lengths = stats_data['lengths']
            if lengths:
                class_bins = min(7, max(4, int(np.sqrt(len(lengths)))))
                counts, bins = np.histogram(lengths, bins=class_bins)
                labels = [f"{bins[i]:.1f}-{bins[i + 1]:.1f}" for i in range(len(counts))]
                ax.bar(labels, counts, color='#2471a3', alpha=0.85, edgecolor='black', label='Peces')
                ax.set_title('Clases de Talla del Lote', fontweight='bold')
                ax.set_xlabel('Rango de longitud (cm)'); ax.set_ylabel('Cantidad')
                ax.tick_params(axis='x', rotation=25)
                has_data = True

        elif graph_type == 'condition_trend':
            weekly_k = {}
            for record in stats_data['records']:
                length_value = float(record.get('length') or 0)
                weight_value = float(record.get('weight') or 0)
                ts_value = record.get('timestamp')
                if length_value <= 0 or weight_value <= 0 or ts_value is None:
                    continue

                k_value = (100 * weight_value) / (length_value ** 3)
                monday = ts_value.date() - timedelta(days=ts_value.date().weekday())
                weekly_k.setdefault(monday, []).append(k_value)

            if weekly_k:
                weeks = sorted(weekly_k.keys())
                week_dates = [datetime.combine(week, datetime.min.time()) for week in weeks]
                avg_k = [float(np.mean(weekly_k[week])) for week in weeks]

                ax.plot(week_dates, avg_k, 'o-', color='#117864', linewidth=2, markersize=6, label='K semanal')
                ax.axhspan(1.0, 1.4, color='#2ecc71', alpha=0.12, label='Zona óptima')
                ax.set_title('Tendencia Semanal del Factor K', fontweight='bold')
                ax.set_xlabel('Semana'); ax.set_ylabel('Factor de condición K')
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%b'))
                fig.autofmt_xdate(rotation=45, ha='right')
                has_data = True

        # C. CURVAS DE CRECIMIENTO (Soporte Gompertz y Legacy Timeline)
        elif 'timeline' in graph_type:
            # Detectar tipo (Si es el botón viejo 'timeline', asumimos peso)
            is_weight = ('weight' in graph_type) or (graph_type == 'timeline') 
            field = 'weight' if is_weight else 'length'
            unit = 'g' if is_weight else 'cm'
            color = C_PURPLE if is_weight else C_ORANGE
            title_txt = "Crecimiento de Peso" if is_weight else "Crecimiento de Longitud"

            # 1. Agrupar Semanalmente
            weekly_data = self._build_weekly_metric_map(stats_data['records'], field)

            if weekly_data:
                sorted_weeks = sorted(weekly_data.keys())
                sorted_dts = [datetime.combine(d, datetime.min.time()) for d in sorted_weeks]
                avg_vals = np.array([sum(weekly_data[d])/len(weekly_data[d]) for d in sorted_weeks])
                
                # Graficar Puntos
                ax.plot(sorted_dts, avg_vals, 'o', color=color, markersize=8, label='Promedio Semanal')

                # CALCULO DE TENDENCIA
                if len(avg_vals) >= 2:
                    start_date = sorted_dts[0]
                    days_rel = np.array([(d - start_date).days for d in sorted_dts])
                    
                    last_day = days_rel[-1]
                    future_days = np.linspace(0, last_day + 45, 100) # +45 días
                    y_trend = None
                    label_trend = ""

                    # Intento Gompertz
                    try:
                        if len(avg_vals) >= 3:
                            def model_gompertz(t, A, B, k): return A * np.exp(-np.exp(B - k * t))
                            max_val = max(avg_vals)
                            p0 = [max_val * 1.5, 1.0, 0.02]
                            bounds = ([max_val, -10, 0], [np.inf, 10, 1.0])
                            params, _ = curve_fit(model_gompertz, days_rel, avg_vals, p0=p0, bounds=bounds, maxfev=5000)
                            candidate = model_gompertz(future_days, *params)
                            if candidate[-1] < max_val * 3: 
                                y_trend = candidate
                                label_trend = "Tendencia (Gompertz)"
                    except Exception as error:
                        logger.debug("Gompertz descartado en export_individual_graph para %s: %s", graph_type, error)

                    # Fallback Lineal
                    if y_trend is None:
                        coeffs = np.polyfit(days_rel, avg_vals, 1)
                        y_trend = np.poly1d(coeffs)(future_days)
                        label_trend = "Tendencia (Lineal)"

                    # Dibujar Línea
                    future_dates = [start_date + timedelta(days=d) for d in future_days]
                    ax.plot(future_dates, y_trend, '--', color='#2c3e50', linewidth=2, label=label_trend)
                    
                    # Etiqueta final
                    final_val = y_trend[-1]
                    if not np.isinf(final_val) and final_val < 100000:
                        ax.text(future_dates[-1], final_val, f"{final_val:.1f} {unit}", fontweight='bold')

                ax.set_title(title_txt, fontweight='bold')
                ax.set_ylabel(f"Valor ({unit})")
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%b'))
                fig.autofmt_xdate()
                has_data = True

        # ======================================================================
        # GUARDADO FINAL
        # ======================================================================
        if has_data:
            handles, labels = ax.get_legend_handles_labels()
            if handles:
                ax.legend()
            ax.grid(True, linestyle='--', alpha=0.5)
            fig.tight_layout()
            
            save_dir = os.path.join(Config.OUT_DIR, "Graficos")
            os.makedirs(save_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            full_path = os.path.join(save_dir, f"{graph_type}_{timestamp}.png")
            
            plt.savefig(full_path, bbox_inches='tight')
            plt.close(fig)
            
            QMessageBox.information(self, "Exportación Exitosa", f"Gráfico guardado en:\n{full_path}")
            
        else:
            plt.close(fig)
            QMessageBox.warning(self, "Error", "No se encontraron datos para generar este gráfico.")
            
    def refresh_theme(self):
        """Refresco rápido del tema actual"""

        self.apply_appearance()

    def apply_animations(self, mode: str):
        """
        Configura animaciones VISIBLES.
        """
        app = QApplication.instance()
        
        enabled = mode != "Desactivadas"
        app.setEffectEnabled(Qt.UI_AnimateCombo, False) 
        app.setEffectEnabled(Qt.UI_AnimateTooltip, enabled)
        app.setEffectEnabled(Qt.UI_FadeMenu, enabled)
        app.setEffectEnabled(Qt.UI_FadeTooltip, enabled)
        
        if mode == "Desactivadas":
            self.anim_duration = 0
        elif mode == "Normales":
            self.anim_duration = 220
        else: 
            self.anim_duration = 420
        
        self._setup_button_animations()
        self._setup_widget_effects()
        
        logger.info(f"✨ Animaciones: {mode} ({self.anim_duration}ms)")

    def _setup_button_animations(self):
        """
        Aplica efecto visual de "pulso" a botones importantes.
        Compatible con PyQt/PySide - NO usa CSS3.
        """

        critical_buttons = []
        
        for btn in self.findChildren(QPushButton):
            btn_class = btn.property("class")
            if btn_class in ["primary", "success", "warning", "info"]:
                critical_buttons.append(btn)
        
        logger.debug(f"Configurando animaciones en {len(critical_buttons)} botones.")
        
        for btn in critical_buttons:
            # Evitar duplicar si ya tiene animación
            if hasattr(btn, '_has_animation'):
                continue
            
            # Guardar evento original
            btn._original_press = btn.mousePressEvent
            btn._original_release = btn.mouseReleaseEvent
            
            def create_press_handler(button):
                def on_press(event):
                    if self.anim_duration == 0:
                        button._original_press(event)
                        return
                    
                    if not hasattr(button, '_opacity_effect'):
                        button._opacity_effect = QGraphicsOpacityEffect()
                        button.setGraphicsEffect(button._opacity_effect)
                    
                    anim = QPropertyAnimation(button._opacity_effect, b"opacity")
                    anim.setDuration(self.anim_duration // 2)
                    anim.setStartValue(1.0)
                    anim.setEndValue(0.7)
                    anim.setEasingCurve(QEasingCurve.OutCubic)
                    anim.start()
                    
                    button._press_anim = anim  
                    button._original_press(event)
                
                return on_press
            
            def create_release_handler(button):
                def on_release(event):
                    if self.anim_duration == 0:
                        button._original_release(event)
                        return
                    
                    if hasattr(button, '_opacity_effect'):
                        anim = QPropertyAnimation(button._opacity_effect, b"opacity")
                        anim.setDuration(self.anim_duration)
                        anim.setStartValue(0.7)
                        anim.setEndValue(1.0)
                        anim.setEasingCurve(QEasingCurve.OutBounce)
                        anim.start()
                    
                    button._original_release(event)
                
                return on_release
            
            btn.mousePressEvent = create_press_handler(btn)
            btn.mouseReleaseEvent = create_release_handler(btn)
            btn._has_animation = True

    def _setup_widget_effects(self):
        """
        Efectos visuales en widgets especiales.
        """
        for btn in self.findChildren(QPushButton):
            if btn.property("class") == "secondary" and not hasattr(btn, '_hover_setup'):
                btn._original_enter = btn.enterEvent
                btn._original_leave = btn.leaveEvent

                if not hasattr(btn, '_opacity_effect'):
                    btn._opacity_effect = QGraphicsOpacityEffect()
                    btn._opacity_effect.setOpacity(1.0)
                    btn.setGraphicsEffect(btn._opacity_effect)

                def _make_enter_handler(button):
                    def _on_enter(event):
                        if self.anim_duration > 0:
                            anim = QPropertyAnimation(button._opacity_effect, b"opacity")
                            anim.setDuration(max(120, self.anim_duration // 2))
                            anim.setStartValue(button._opacity_effect.opacity())
                            anim.setEndValue(0.82)
                            anim.setEasingCurve(QEasingCurve.OutCubic)
                            anim.start()
                            button._hover_anim = anim
                        button._original_enter(event)
                    return _on_enter

                def _make_leave_handler(button):
                    def _on_leave(event):
                        if self.anim_duration > 0:
                            anim = QPropertyAnimation(button._opacity_effect, b"opacity")
                            anim.setDuration(max(140, self.anim_duration // 2))
                            anim.setStartValue(button._opacity_effect.opacity())
                            anim.setEndValue(1.0)
                            anim.setEasingCurve(QEasingCurve.OutCubic)
                            anim.start()
                            button._hover_anim = anim
                        else:
                            button._opacity_effect.setOpacity(1.0)
                        button._original_leave(event)
                    return _on_leave

                btn.enterEvent = _make_enter_handler(btn)
                btn.leaveEvent = _make_leave_handler(btn)
                btn._hover_setup = True

    def apply_appearance(self):
        """Lee los valores de los widgets y sincroniza el motor de estilos"""
        try:
            theme = self.combo_theme.currentText()
            font_size = int(self.combo_font_size.currentText() or 11)
            density = self.combo_density.currentText()
            animations = self.combo_animations.currentText()

            self.toggle_theme(theme, font_size, density)

            self.apply_animations(animations)
    
            if hasattr(self, 'status_bar'):
                anim_status = {
                "Desactivadas": "Animaciones desactivadas",
                "Normales": "Animaciones normales (220ms)",
                "Suaves": "Animaciones suaves (420ms)"
                }.get(animations, "")
                
                self.status_bar.set_status(
                    f"Tema: {theme} | Densidad: {density} | {anim_status}", 
                    "info"
                )
                
        except Exception as e:
            logger.error(f"Error aplicando configuracion visual: {e}.")
            
    def get_icon(self, name: str, state: str = "normal", size: int = 14):
        import qtawesome as qta
        from PySide6.QtCore import QSize
        
        color = self.theme_colors.get(state, self.theme_colors["normal"])
        return qta.icon(name, color=color)


    def toggle_theme(self, text, font_size=11, density="Normal"):
        """
        Motor de estilos estandarizado para la aplicación.
        Controla Temas, Densidad, Fuentes y Estados Biométricos.
        """
        # 1. DETERMINAR SI USAR MODO OSCURO
        if text == "Sistema":
            is_dark = darkdetect.isDark() 
            theme_mode = "dark" if is_dark else "light"
        else:
            is_dark = (text == "Oscuro")
            theme_mode = "dark" if is_dark else "light"

        qdarktheme.setup_theme(theme_mode)
        self.is_currently_dark = is_dark

        # 2. CONFIGURAR DENSIDAD VISUAL (Padding y Alturas)
        if density == "Súper Compacta":
            row_h = 18         
            padding_val = 0     
            btn_padding = "1px 4px"
            tab_h = 28
        elif density == "Compacta":
            row_h = 24
            padding_val = 2
            btn_padding = "4px 8px"
            tab_h = 32
        elif density == "Cómoda":
            row_h = 42
            padding_val = 12
            btn_padding = "12px 24px"
            tab_h = 44
        elif density == "Táctil":
            row_h = 52
            padding_val = 16
            btn_padding = "16px 28px"
            tab_h = 54
        else: 
            row_h = 32
            padding_val = 6
            btn_padding = "8px 16px"
            tab_h = 36

        # Aplicar altura de filas a todas las tablas de la app
        for table in self.findChildren(QTableWidget):
            table.verticalHeader().setDefaultSectionSize(row_h)
         
        c_high = "rgba(42, 157, 143, 0.12)"
        c_medium = "rgba(231, 111, 81, 0.12)"
        c_low = "rgba(231, 76, 60, 0.12)"
        # 3. DEFINICIÓN DE PALETA TÉCNICA
        if is_dark:
            # ---------- MODO OSCURO ----------
            c_primary_base, c_primary_hover = "#00b4d8", "#48cae4"
            c_success_base, c_success_hover = "#2a9d8f", "#2ec4b6"
            c_info_base, c_info_hover = "#4ea8de", "#74c0fc"   
            c_secondary_base, c_secondary_hover = "#2b2f33", "#3a3f44"
            c_disable_base, c_disable_hover =  "#1f2428", "#2a3035"
            c_warning_base, c_warning_hover = "#e76f51", "#f4a261"
            c_error_base ="#e74c3c"
            
            
            text_col   = "#e0e0e0"
            bg_paper   = "#1e1e1e"     
            border_div = "#2f2f33" 
            c_sec_text = "#dee2e6"
            item_hover = "rgba(78, 168, 222, 0.18)"

            self.report_style = {
                'bg': bg_paper,
                'text': text_col,
                'header': c_primary_hover,
                'accent': c_primary_base,
                'row': '#2d2d2d',
                'border': border_div,
                'val_color': c_success_base
            }
            self._btn_text_colors = {
    "primary": "#ffffff",
    "success": "#ffffff",
    "info": "#ffffff",
    "warning": "#ffffff",
    "secondary": c_sec_text
}


        else:
            # ---------- MODO CLARO ----------
            c_primary_base, c_primary_hover = "#0077b6", "#005f8b"
            c_success_base, c_success_hover = "#264653", "#2f5f73"
            c_info_base, c_info_hover       = "#023e8a", "#00296b"
            c_warning_base, c_warning_hover = "#d62828", "#a61e1e"
            c_secondary_base, c_secondary_hover = "#f1f3f5", "#dee2e6"
            c_disable_base, c_disable_hover =  "#d6d9dc", "#cfd4d8"
            c_error_base ="#e74c3c"
            
            text_col   = "#2c3e50"
            bg_paper   = "#ffffff"
            c_sec_text = "#212529"
            border_div = "#ced4da"
            item_hover = "rgba(0, 119, 182, 0.08)"

            self.report_style = {
                'bg': bg_paper,
                'text': text_col,
                'header': c_primary_base,
                'accent': c_primary_base,
                'row': '#f8f9fa',
                'border': border_div,
                'val_color': c_success_base
            }
            self._btn_text_colors = {
    "primary": "#ffffff",
    "success": "#ffffff",
    "info": "#ffffff",
    "warning": "#ffffff",
    "secondary": c_sec_text
}

            

        # 4. CONSTRUCCIÓN DE LA HOJA DE ESTILO (CSS)
        custom_css = f"""
            /* Configuración Global */
            * {{
                font-size: {font_size}px;
            }}
            
            * , QHeaderView::section, QTableWidget, QLineEdit, QComboBox {{
                font-size: {font_size}px;
            }}
            
            /* Dentro de custom_css en toggle_theme */
            QDoubleSpinBox[class="biometric-input"] {{
                padding: {padding_val}px;
                border: 1px solid {border_div};
                border-radius: 4px;
                background-color: {bg_paper};
                color: {text_col};
                min-width: 100px;
            }}

            /* Resalte cuando el usuario está editando */
            QDoubleSpinBox[class="biometric-input"]:focus {{
                border: 2px solid {c_primary_base};
            }}

        /* --- ESTILOS DE LA BARRA DE ESTADO --- */
            #StatusBar {{
                background-color: {bg_paper};
                border-top: 1px solid {border_div};
            }}
            
            /* Separador Vertical */
            #StatusSeparator {{
                background-color: {border_div}; 
                margin: 8px 2px;
                min-width: 1px;
                max-width: 1px;
            }}

            /* Labels Genéricos de la Barra */
            #StatusBar QLabel {{
                font-family: 'Segoe UI', sans-serif;
                font-size: 10pt;
                padding: 0 4px;
            }}

            /* --- ESTADOS DE COLOR (TEXTO) --- */
            
            /* Normal (Texto base) */
            #StatusBar QLabel[state="normal"] {{ color: {text_col}; }}
            
            /* Dim (Texto secundario / gris) */
            #StatusBar QLabel[state="dim"] {{ color: {c_sec_text}; }}
            
            /* Info (Azul) */
            #StatusBar QLabel[state="info"] {{ color: {c_info_base}; font-weight: bold; }}
            
            /* Success (Verde) */
            #StatusBar QLabel[state="success"] {{ color: {c_success_base}; font-weight: bold; }}
            
            /* Warning (Naranja) */
            #StatusBar QLabel[state="warning"] {{ color: {c_warning_base}; font-weight: bold; }}
            
            /* Error (Rojo) */
            #StatusBar QLabel[state="error"] {{ color: {c_error_base}; font-weight: bold; }}
            
            /* Accent (Para GPU - Usaremos el Primary o un color especial) */
            #StatusBar QLabel[state="accent"] {{ color: {c_primary_base}; font-weight: bold; }}

            /* --- BOTONES CON CLASES --- */
            QPushButton[class] {{
                border-radius: 6px;
                padding: {btn_padding};
                font-weight: bold;
                font-family: "Segoe UI", sans-serif;
                border: none;
            }}
            QPushButton[class="primary"],
QPushButton[class="success"],
QPushButton[class="warning"],
QPushButton[class="info"] {{
    color: #ffffff;
}}


            QPushButton[class="primary"] {{ background-color: {c_primary_base}; color: #ffffff; }}
            QPushButton[class="primary"]:hover {{ background-color: {c_primary_hover}; }}
            QPushButton[class="primary"]:pressed {{ 
    background-color: {c_primary_hover}; 
}}

            QPushButton[class="success"] {{ background-color: {c_success_base}; color: #ffffff; }}
            QPushButton[class="success"]:hover {{ background-color: {c_success_hover}; }}
            QPushButton[class="success"]:checked {{background-color: {c_success_hover};}}
            QPushButton[class="success"]:checked:hover {{background-color: {c_success_base};}}
            QPushButton[class="success"]:pressed {{ 
    background-color: {c_success_hover}; 
}}

            QPushButton[class="info"] {{ background-color: {c_info_base}; color: #ffffff; }}
            QPushButton[class="info"]:hover {{ background-color: {c_info_hover}; }}
            QPushButton[class="info"]:pressed {{ 
    background-color: {c_info_hover}; 
}}

            QPushButton[class="warning"] {{ background-color: {c_warning_base}; color: #ffffff; }}
            QPushButton[class="warning"]:hover {{ background-color: {c_warning_hover}; }}
            QPushButton[class="warning"]:pressed {{ 
    background-color: {c_warning_hover}; 
}}

            QPushButton[class="secondary"] {{background-color: {c_secondary_base}; color: {c_sec_text}; border: 1px solid {border_div};}}
            QPushButton[class="secondary"]:hover {{background-color: {c_secondary_hover}; color: {c_sec_text}; border: 1px solid {border_div};}}
            QPushButton[class="secondary"]:pressed {{ 
    background-color: {c_secondary_hover}; 
}}
            
            QPushButton:disabled {{background-color: {c_disable_base}; color: {c_sec_text}; border: 1px solid {border_div};opacity: 0.6;}}
            QPushButton:disabled:hover {{background-color: {c_disable_hover};}}
            QPushButton:disabled:pressed {{
    background-color: {c_disable_base};
}}
        QMessageBox QPushButton {{
    padding: 6px 12px;
    min-width: 100px;
}}

            /* --- ESTADOS DEL REPORTE DE RESULTADOS --- */
            
            /* Estado Normal / Info / Ready */
            QTextEdit[class="report-text"][state="ready"],
            QTextEdit[class="report-text"][state="info"] {{
                border: 1px solid {c_info_base};
                background-color: {bg_paper}; 
                color: {text_col};
            }}

            /* Estado Éxito (Verde) */
            QTextEdit[class="report-text"][state="success"] {{
                border: 2px solid {c_success_base};
                background-color: {c_high};
                color: {text_col};
            }}

            /* Estado Advertencia (Naranja) */
            QTextEdit[class="report-text"][state="warning"] {{
                border: 2px solid {c_warning_base};
                background-color: {c_medium};
                color: {text_col};
            }}

            /* Estado Error (Rojo) */
            QTextEdit[class="report-text"][state="error"] {{
                border: 2px solid {c_error_base};
                background-color: {c_low};
                color: {text_col};
            }}


            /* --- VISORES DE CÁMARA --- */
            
            /* 1. Estilos Base (Cuando hay video) */
            QLabel[class="video-feed"] {{
                border: 2px solid {border_div};
                background-color: #000000;
                border-radius: 8px;
            }}
            
            /* Borde Sólido AZUL para Lateral (Video Activo) */
            QLabel[class="video-lateral"] {{
                border: 3px solid {c_primary_base}; 
                border-radius: 8px;
                background-color: #000000;
            }}
            
            /* Borde Sólido VERDE para Cenital (Video Activo) */
            QLabel[class="video-cenital"] {{
                border: 3px solid {c_success_base};
                border-radius: 8px;
                background-color: #000000;
            }}
            
            /* 2. Estilos para "CÁMARA NO DISPONIBLE" */
            
            /* Base general para el texto y fondo */
            QLabel[state="no-camera"] {{
                background-color: {c_secondary_base};  /* Gris suave */
                color: {c_sec_text};                   /* Texto secundario */
                font-weight: bold;
                font-size: {font_size + 2}px;
                qproperty-alignment: AlignCenter;
                border-radius: 8px;
            }}

            /* AQUI ESTA LA MAGIA: Bordes Punteados de Color */
            
            /* Si es Lateral y falla: Borde PUNTEADO AZUL */
            QLabel[class="video-lateral"][state="no-camera"] {{
                border: 2px dashed {c_primary_base}; 
                color: {c_primary_base}; /* Texto también azulado para resaltar */
            }}

            /* Si es Cenital y falla: Borde PUNTEADO VERDE */
            QLabel[class="video-cenital"][state="no-camera"] {{
                border: 2px dashed {c_success_base};
                color: {c_success_base}; /* Texto verdoso */
            }}
            
            /* Si es otra cámara genérica: Borde Punteado Gris */
            QLabel[class="video-feed"][state="no-camera"] {{
                border: 2px dashed {c_disable_base};
            }}

            /* --- NIVELES DE CONFIANZA (Semaforización) --- */
            QProgressBar[level="high"]::chunk {{
                background-color: {c_high};
                border: 1.5px solid {c_success_base};
                border-radius: 4px;
            }}
            QProgressBar[level="medium"]::chunk {{
                background-color: {c_medium};
                border: 1.5px solid {c_warning_base};
                border-radius: 4px;
            }}
            QProgressBar[level="low"]::chunk {{
                background-color: {c_low};
                border: 1.5px solid {c_error_base};
                border-radius: 4px;
            }}

            /* --- ESTADOS DEL FACTOR K (SEMÁFORO) --- */
            QLabel[state="empty"] {{
                background-color: rgba(255, 255, 255, 0.04);
                color: {text_col};
                border: 1px dashed {border_div};
                border-radius: 4px;
                padding: 5px;
                font-style: italic;
            }}
            QLabel[state="ok"] {{
                background-color: {c_high};
                color: {text_col};
                border: 1.5px solid {c_success_base};
                border-radius: 4px;
                padding: 5px;
            }}
            QLabel[state="warn"] {{
                background-color: {c_medium};
                color: {text_col};
                border: 1.5px solid {c_warning_base};
                border-radius: 4px;
                padding: 5px;
            }}
            QLabel[state="bad"] {{
                background-color: {c_low};
                color: {text_col};
                border: 1.5px solid {c_error_base};
                border-radius: 4px;
                padding: 5px;
            }}
            QLabel[state="success"] {{
                color: {c_success_base};
                font-weight: bold;
            }}
            QLabel[state="warning"] {{
                color: {c_warning_base};
                font-weight: bold;
            }}
            QLabel[state="error"] {{
                color: {c_error_base};
                font-weight: bold;
            }}
            
            /* Estilos para el Label de Estabilidad en el Dashboard */
            QLabel[state="neutral"] {{
                color: {c_sec_text}; 
                font-weight: normal; 
            }}
            QLabel[state="ok"] {{ 
                color: {c_success_base}; 
                font-weight: bold; 
                border: 1px solid {c_success_base};
                border-radius: 4px;
                padding: 2px;
            }}
            QLabel[state="warn"] {{ 
                color: {c_warning_base}; 
                font-weight: bold; 
            }}
            /* --- BADGES DE TIPO --- */
            QLabel[tipo="auto"] .badge {{ font-weight: bold; }}
            QLabel[tipo="manual"] .badge {{ font-style: italic; }}

            /* --- COMPONENTES DE DATOS --- */
            QTableWidget {{
                background-color: {bg_paper};
                gridline-color: {border_div};
            }}
            QTableWidget::item {{
                padding: {padding_val}px;
            }}
            QHeaderView::section {{
                background-color: {c_primary_base};
                color: #ffffff;
                font-weight: bold;
                border: none;
            }}
            QTextEdit[class="report-text"] {{
                background-color: {bg_paper};
                border: 1px solid {border_div};
                border-radius: 6px;
                padding: 10px;
            }}
            QLabel[class="report-text"] {{
                font-family: 'Consolas', 'Courier New', monospace;
            }}
            
            /* --- ESTILOS DE LA BARRA DE ESTADO INTEGRADOS --- */
            #StatusBar {{
                background-color: {bg_paper};
                border-top: 1px solid {border_div};
            }}
            
            #StatusBar QPushButton {{
                background-color: transparent;
                border: none;
                text-align: left;
                padding: 0px 5px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 10pt;
            }}
            
            #StatusBar QPushButton[interactive="true"] {{
                border-radius: 6px;
                padding: 2px 8px;
            }}

            #StatusBar QPushButton[interactive="true"]:hover {{
                background-color: {item_hover};
                border-radius: 6px;
            }}

            #StatusBar QPushButton[interactive="true"]:pressed {{
    background-color: {c_primary_hover};
    color: #ffffff;
    padding-top: 3px;
    padding-bottom: 1px;
}}

            /* Colores de TEXTO dinámicos según el estado (Usando tus variables) */
            #StatusBar QPushButton[state="normal"]  {{ color: {text_col}; }}
            #StatusBar QPushButton[state="dim"]     {{ color: {c_sec_text}; }}
            #StatusBar QPushButton[state="info"]    {{ color: {c_info_base}; font-weight: bold; }}
            #StatusBar QPushButton[state="success"] {{ color: {c_success_base}; font-weight: bold; }}
            #StatusBar QPushButton[state="warning"] {{ color: {c_warning_base}; font-weight: bold; }}
            #StatusBar QPushButton[state="error"]   {{ color: {c_error_base}; font-weight: bold; }}
            #StatusBar QPushButton[state="accent"]  {{ color: {c_primary_base}; font-weight: bold; }}

            /* Separador */
            #StatusSeparator {{
                background-color: {border_div}; 
                margin: 8px 2px;
            }}

            /* --- BARRA SUPERIOR AMBIENTAL --- */
            #SensorTopBar {{
                background-color: transparent;
                min-height: 34px;
            }}

            #SensorTopBar QPushButton {{
                background-color: transparent;
                border: none;
                text-align: left;
                color: {text_col};
            }}

            #SensorTopBar QPushButton[state="dim"]     {{ color: {c_sec_text}; }}
            #SensorTopBar QPushButton[state="info"]    {{ color: {c_info_base}; font-weight: bold; }}
            #SensorTopBar QPushButton[state="success"] {{ color: {c_success_base}; font-weight: bold; }}
            #SensorTopBar QPushButton[state="warning"] {{ color: {c_warning_base}; font-weight: bold; }}
            #SensorTopBar QPushButton[state="error"]   {{ color: {c_error_base}; font-weight: bold; }}
            #SensorTopBar QPushButton[state="accent"]  {{ color: {c_primary_base}; font-weight: bold; }}
        """

        # --- CAPA DE ALTO CONTRASTE ---
        high_contrast_css = ""
        if hasattr(self, "chk_high_contrast") and self.chk_high_contrast.isChecked():
            high_contrast_css = """
                QWidget { background-color: #000000; color: #ffffff; border-color: #ffffff; }
                QPushButton { border: 2px solid #ffffff; background-color: #000000; color: #ffffff; }
                QPushButton:hover { background-color: #ffffff; color: #000000; }
                QLabel { color: #ffffff; font-weight: bold; }
                QHeaderView::section { background-color: #ffffff; color: #000000; }
            """

        current_palette = {
            "normal":  text_col,
            "dim":     c_sec_text,
            "info":    c_info_base,
            "success": c_success_base,
            "warning": c_warning_base,
            "error":   c_error_base,
            "accent":  c_primary_base
        }
        
        # Si tienes la barra instanciada, le actualizamos los iconos
        if hasattr(self, 'status_bar'):
             self.status_bar.update_theme_colors(current_palette)
        if hasattr(self, 'sensor_top_bar'):
            self.sensor_top_bar.update_theme_colors(current_palette)
             
        # 5. APLICACIÓN FINAL
        app = QApplication.instance()
        app.setStyleSheet(
            qdarktheme.load_stylesheet(theme_mode) +
            custom_css +
            high_contrast_css
        )
        self._refresh_button_icon(self.btn_auto_capture)
        self.update_report_html()
        
        for widget in self.findChildren(QWidget):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        if hasattr(self, "tabs"):
            self.tabs.tabBar().setMinimumHeight(tab_h)
        if hasattr(self, "sensor_top_bar"):
            self.sensor_top_bar.set_visual_density()

    def _configure_widget_animations(self, enabled: bool, duration: int):
        """
        Aplica animaciones programáticas a widgets específicos.
        Se ejecuta después de cambiar el modo de animación.
        """
        if not enabled:
            return  
        primary_buttons = [
            self.btn_capture,
            self.btn_save,
            self.btn_manual_capture,
            self.btn_manual_save
        ]
        
        for btn in primary_buttons:
            if not hasattr(btn, '_animation_setup'):
                btn._original_click = btn.mousePressEvent
                
                def animated_click(event, button=btn):
                    anim = QPropertyAnimation(button, b"geometry")
                    anim.setDuration(duration // 3)  
                    
                    original_geo = button.geometry()
                    pressed_geo = original_geo.adjusted(2, 2, -2, -2)  
                    
                    anim.setStartValue(original_geo)
                    anim.setEndValue(pressed_geo)
                    anim.setEasingCurve(QEasingCurve.OutCubic)
                    anim.start(QAbstractAnimation.DeleteWhenStopped)
                    
                    # Restaurar después
                    def restore():
                        restore_anim = QPropertyAnimation(button, b"geometry")
                        restore_anim.setDuration(duration // 2)
                        restore_anim.setStartValue(pressed_geo)
                        restore_anim.setEndValue(original_geo)
                        restore_anim.setEasingCurve(QEasingCurve.OutBounce)
                        restore_anim.start(QAbstractAnimation.DeleteWhenStopped)
                    
                    QTimer.singleShot(duration // 3, restore)
                    button._original_click(event)
                
                btn.mousePressEvent = animated_click
                btn._animation_setup = True
        
        if hasattr(self, 'tabs') and not hasattr(self.tabs, '_animation_setup'):
            self.tabs._original_tab_change = self.tabs.currentChanged
            
            def animated_tab_change(index):
                fade_widget = self.tabs.currentWidget()
                if fade_widget:
                    fade_anim = QPropertyAnimation(fade_widget, b"windowOpacity")
                    fade_anim.setDuration(duration)
                    fade_anim.setStartValue(0.0)
                    fade_anim.setEndValue(1.0)
                    fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
                    fade_anim.start(QAbstractAnimation.DeleteWhenStopped)
                
                self.tabs._original_tab_change.emit(index)
            
            self.tabs.currentChanged.disconnect()
            self.tabs.currentChanged.connect(animated_tab_change)
            self.tabs._animation_setup = True

        if hasattr(self, 'confidence_bar'):
            pass  
        
        logger.debug(f"Animaciones aplicadas a {len(primary_buttons)} botones y widgets criticos")        
    
        
    def create_settings_tab(self):
        """Crea la pestaña de configuración"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        appearance_group = QGroupBox("Apariencia")
        appearance_layout = QHBoxLayout(appearance_group)

        # Tema
        appearance_layout.addWidget(QLabel("Tema:"))
        self.combo_theme = QComboBox()
        self.combo_theme.setCursor(Qt.PointingHandCursor)
        self.combo_theme.addItems(["Sistema", "Claro", "Oscuro"])
        self.combo_theme.setCurrentText("Sistema")
        self.combo_theme.setToolTip(
            "Cambia el esquema de colores de la aplicación."
        )
        appearance_layout.addWidget(self.combo_theme)

        # Alto contraste
        self.chk_high_contrast = QCheckBox("Alto contraste")
        self.chk_high_contrast.setCursor(Qt.PointingHandCursor)
        self.chk_high_contrast.setToolTip(
            "Mejora la legibilidad usando colores de alto contraste."
        )
        appearance_layout.addWidget(self.chk_high_contrast)
        self.chk_high_contrast.stateChanged.connect(self.apply_appearance)

        # Tamaño de fuente
        appearance_layout.addWidget(QLabel("Fuente:"))
        self.combo_font_size = QComboBox()
        self.combo_font_size.setCursor(Qt.PointingHandCursor)
        self.combo_font_size.addItems(["6", "8", "10", "11", "12", "14", "16", "18"])
        self.combo_font_size.setToolTip(
            "Ajusta el tamaño del texto en toda la interfaz."
        )
        appearance_layout.addWidget(self.combo_font_size)

        # Densidad
        appearance_layout.addWidget(QLabel("Densidad:"))
        self.combo_density = QComboBox()
        self.combo_density.setCursor(Qt.PointingHandCursor)
        self.combo_density.addItems(["Súper Compacta", "Compacta", "Normal", "Cómoda", "Táctil"])
        self.combo_density.setToolTip(
            "Define el espaciado entre elementos de la interfaz."
        )
        appearance_layout.addWidget(self.combo_density)

        # Animaciones
        appearance_layout.addWidget(QLabel("Animaciones:"))
        self.combo_animations = QComboBox()
        self.combo_animations.setCursor(Qt.PointingHandCursor)
        self.combo_animations.addItems(["Desactivadas", "Normales", "Suaves"])
        self.combo_animations.setToolTip(
            "Controla la suavidad de las animaciones visuales."
        )
        appearance_layout.addWidget(self.combo_animations)
        layout.addWidget(appearance_group)

        for w in (self.combo_theme, self.combo_font_size, self.combo_density, self.combo_animations):
            w.blockSignals(True) 
            
        self.combo_theme.setCurrentText("Sistema")
        self.combo_font_size.setCurrentText("11")
        self.combo_density.setCurrentText("Normal")
        self.combo_animations.setCurrentText("Normales")
        self.chk_high_contrast.setChecked(False)

        for w in (self.combo_theme, self.combo_font_size, self.combo_density, self.combo_animations):
            w.blockSignals(False)
            w.currentTextChanged.connect(self.apply_appearance)

        eng_group = QGroupBox("Hardware")
        eng_layout = QGridLayout(eng_group)
        eng_layout.setSpacing(10)

        # Índices de Cámara
        eng_layout.addWidget(QLabel("Cámara Lateral:"), 0, 0)
        self.spin_cam_left = QSpinBox()
        self.spin_cam_left.setRange(0, 10)
        eng_layout.addWidget(self.spin_cam_left, 0, 1)

        eng_layout.addWidget(QLabel("Cámara Cenital:"), 0, 2)
        self.spin_cam_top = QSpinBox()
        self.spin_cam_top.setRange(0, 10)
        eng_layout.addWidget(self.spin_cam_top, 0, 3)

        # Separador visual
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        eng_layout.addWidget(line, 1, 0, 1, 4)
        
        # Botón de Re-conexión
        btn_reconnect = QPushButton("Reconectar Cámaras")
        self.btn_reconnect_cameras = btn_reconnect
        btn_reconnect.setProperty("class", "info")
        btn_reconnect.style().unpolish(btn_reconnect) 
        btn_reconnect.style().polish(btn_reconnect)
        btn_reconnect.setToolTip("Reconectar las cámaras.")
        btn_reconnect.clicked.connect(self.reconnect_cameras)
        eng_layout.addWidget(btn_reconnect, 5, 0, 1, 4)

        self.lbl_camera_hw_status = QLabel("Estado de cámaras: Verificando...")
        self.lbl_camera_hw_status.setProperty("state", "warning")
        self.lbl_camera_hw_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_camera_hw_status.setToolTip("Indica la disponibilidad real de cámaras para captura y calibración en vivo.")
        eng_layout.addWidget(self.lbl_camera_hw_status, 6, 0, 1, 4)

        left_state_widget = QWidget()
        left_state_layout = QHBoxLayout(left_state_widget)
        left_state_layout.setContentsMargins(0, 0, 0, 0)
        left_state_layout.setSpacing(6)
        self.lbl_cam_left_icon = QLabel()
        self.lbl_cam_left_icon.setFixedSize(16, 16)
        self.lbl_cam_left_icon.setToolTip("Estado de cámara lateral")
        self.lbl_cam_left_status = QLabel("Lateral: En verificación")
        self.lbl_cam_left_status.setProperty("state", "warning")
        self.lbl_cam_left_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_cam_left_status.setToolTip("Semáforo de salud de cámara lateral")
        left_state_layout.addWidget(self.lbl_cam_left_icon)
        left_state_layout.addWidget(self.lbl_cam_left_status)
        eng_layout.addWidget(left_state_widget, 7, 0, 1, 2)

        top_state_widget = QWidget()
        top_state_layout = QHBoxLayout(top_state_widget)
        top_state_layout.setContentsMargins(0, 0, 0, 0)
        top_state_layout.setSpacing(6)
        self.lbl_cam_top_icon = QLabel()
        self.lbl_cam_top_icon.setFixedSize(16, 16)
        self.lbl_cam_top_icon.setToolTip("Estado de cámara cenital")
        self.lbl_cam_top_status = QLabel("Cenital: En verificación")
        self.lbl_cam_top_status.setProperty("state", "warning")
        self.lbl_cam_top_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_cam_top_status.setToolTip("Semáforo de salud de cámara cenital")
        top_state_layout.addWidget(self.lbl_cam_top_icon)
        top_state_layout.addWidget(self.lbl_cam_top_status)
        eng_layout.addWidget(top_state_widget, 7, 2, 1, 2)

        self.lbl_cam_microcuts = QLabel("Microcortes (60s) - Lateral: 0 | Cenital: 0")
        self.lbl_cam_microcuts.setProperty("state", "info")
        self.lbl_cam_microcuts.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_cam_microcuts.setToolTip("Cantidad de microcortes de señal detectados en los últimos 60 segundos")
        eng_layout.addWidget(self.lbl_cam_microcuts, 8, 0, 1, 4)

        layout.addWidget(eng_group)
        
        manual_group = QGroupBox("Calibración de Escalas (cm/px)")
        manual_group.setToolTip("Define cuántos centímetros reales equivale 1 píxel en pantalla.")
        manual_layout = QGridLayout(manual_group)
        
        # Encabezados para ordenarlo visualmente
        manual_layout.addWidget(QLabel("<b>Parámetro</b>"), 0, 0)
        manual_layout.addWidget(QLabel("<b>Cámara Lateral</b>"), 0, 1)
        manual_layout.addWidget(QLabel("<b>Cámara Cenital</b>"), 0, 2)

        manual_layout.addWidget(QLabel("Escala Frente:"), 1, 0)
        
        # Lateral Frente
        self.spin_scale_front_left = QDoubleSpinBox()
        self.spin_scale_front_left.setRange(0.00001, 1.0)
        self.spin_scale_front_left.setValue(getattr(self, 'scale_front_left', 0.006666))
        self.spin_scale_front_left.setDecimals(6)
        self.spin_scale_front_left.setSingleStep(0.0001)
        self.spin_scale_front_left.setToolTip("cm/px para objetos pegados al tanque (Lateral)")
        manual_layout.addWidget(self.spin_scale_front_left, 1, 1)

        # Cenital Frente
        self.spin_scale_front_top = QDoubleSpinBox()
        self.spin_scale_front_top.setRange(0.00001, 1.0)
        self.spin_scale_front_top.setValue(getattr(self, 'scale_front_top', 0.004348))
        self.spin_scale_front_top.setDecimals(6)
        self.spin_scale_front_top.setSingleStep(0.0001)
        self.spin_scale_front_top.setToolTip("cm/px para objetos pegados al tanque (Cenital)")
        manual_layout.addWidget(self.spin_scale_front_top, 1, 2)
        
        manual_layout.addWidget(QLabel("Escala Fondo:"), 2, 0)

        # Lateral Fondo
        self.spin_scale_back_left = QDoubleSpinBox()
        self.spin_scale_back_left.setRange(0.00001, 1.0)
        self.spin_scale_back_left.setValue(getattr(self, 'scale_back_left', 0.014926))
        self.spin_scale_back_left.setDecimals(6)
        self.spin_scale_back_left.setSingleStep(0.0001)
        self.spin_scale_back_left.setToolTip("cm/px para el fondo del tanque (Lateral)")
        manual_layout.addWidget(self.spin_scale_back_left, 2, 1)

        # Cenital Fondo
        self.spin_scale_back_top = QDoubleSpinBox()
        self.spin_scale_back_top.setRange(0.00001, 1.0)
        self.spin_scale_back_top.setValue(getattr(self, 'scale_back_top', 0.012582))
        self.spin_scale_back_top.setDecimals(6)
        self.spin_scale_back_top.setSingleStep(0.0001)
        self.spin_scale_back_top.setToolTip("cm/px para el fondo del tanque (Cenital)")
        manual_layout.addWidget(self.spin_scale_back_top, 2, 2)
        
        # Botones específicos de calibración 
        calib_btn_layout = QHBoxLayout()
        
        btn_default = QPushButton("Restaurar Fábrica")
        btn_default.setProperty("class", "warning")
        btn_default.style().unpolish(btn_default)
        btn_default.style().polish(btn_default)
        btn_default.setCursor(Qt.PointingHandCursor)
        btn_default.setToolTip("Carga los valores de escala predeterminados.")
        btn_default.clicked.connect(self.load_default_calibration)
        calib_btn_layout.addWidget(btn_default, 7)
        
        btn_apply_manual = QPushButton("Aplicar Escalas")
        btn_apply_manual.setProperty("class", "success")
        btn_apply_manual.style().unpolish(btn_apply_manual) 
        btn_apply_manual.style().polish(btn_apply_manual)
        btn_apply_manual.setCursor(Qt.PointingHandCursor)
        btn_apply_manual.setToolTip("Aplica estos valores de escala inmediatamente.")
        btn_apply_manual.clicked.connect(self.apply_manual_calibration)
        calib_btn_layout.addWidget(btn_apply_manual, 7)

        btn_open_scale_calibrator = QPushButton("Abrir Calibrador de Escala")
        self.btn_scale_calibrator = btn_open_scale_calibrator
        btn_open_scale_calibrator.setProperty("class", "info")
        btn_open_scale_calibrator.style().unpolish(btn_open_scale_calibrator)
        btn_open_scale_calibrator.style().polish(btn_open_scale_calibrator)
        btn_open_scale_calibrator.setCursor(Qt.PointingHandCursor)
        btn_open_scale_calibrator.setToolTip("Calcula cm/px dentro de la app marcando dos puntos y distancia real.")
        btn_open_scale_calibrator.clicked.connect(self.open_scale_calibration_dialog)
        calib_btn_layout.addWidget(btn_open_scale_calibrator, 2)
        
        manual_layout.addLayout(calib_btn_layout, 3, 0, 1, 3) 
        
        layout.addWidget(manual_group)
        
        detection_group = QGroupBox("Parámetros de Detección (Filtros)")
        detection_layout = QGridLayout(detection_group)
        
        # --- Área Mínima ---
        detection_layout.addWidget(QLabel("Área Mínima Contorno:"), 0, 0)
        self.spin_min_area = QSpinBox()
        self.spin_min_area.setRange(10, 10000)
        self.spin_min_area.setValue(Config.MIN_CONTOUR_AREA)
        self.spin_min_area.setSuffix(" px")
        self.spin_min_area.setToolTip(
            "Ignora objetos más pequeños que este valor (en píxeles).\n"
            "Aumente este valor para filtrar ruido, burbujas o suciedad pequeña."
        )
        detection_layout.addWidget(self.spin_min_area, 0, 1)
        
        # --- Área Máxima ---
        detection_layout.addWidget(QLabel("Área Máxima Contorno:"), 1, 0)
        self.spin_max_area = QSpinBox()
        self.spin_max_area.setRange(1000, 1000000)
        self.spin_max_area.setValue(Config.MAX_CONTOUR_AREA)
        self.spin_max_area.setSuffix(" px")
        self.spin_max_area.setToolTip(
            "Ignora objetos más grandes que este valor.\n"
            "Útil para evitar detectar la mano del operario o reflejos grandes."
        )
        detection_layout.addWidget(self.spin_max_area, 1, 1)
        
        # --- Confianza ---
        detection_layout.addWidget(QLabel("Umbral Confianza:"), 2, 0)
        self.spin_confidence = QDoubleSpinBox()
        self.spin_confidence.setRange(0.0, 1.0)
        self.spin_confidence.setValue(Config.CONFIDENCE_THRESHOLD)
        self.spin_confidence.setDecimals(2)
        self.spin_confidence.setSingleStep(0.05)
        self.spin_confidence.setToolTip(
            "Nivel de certeza requerido para considerar válida una detección."
        )
        detection_layout.addWidget(self.spin_confidence, 2, 1)
        
        layout.addWidget(detection_group)

        env_group = QGroupBox("Rangos de Alertas Ambientales")
        env_group.setToolTip("Define los umbrales para alertar cada variable en la barra superior ambiental.")
        env_layout = QGridLayout(env_group)

        env_layout.addWidget(QLabel("Variable"), 0, 0)
        env_layout.addWidget(QLabel("Mín"), 0, 1)
        env_layout.addWidget(QLabel("Máx"), 0, 2)

        env_layout.addWidget(QLabel("Temperatura Agua (°C)"), 1, 0)
        self.spin_env_temp_min = QDoubleSpinBox(); self.spin_env_temp_min.setRange(-10.0, 60.0); self.spin_env_temp_min.setDecimals(1)
        self.spin_env_temp_max = QDoubleSpinBox(); self.spin_env_temp_max.setRange(-10.0, 60.0); self.spin_env_temp_max.setDecimals(1)
        self.spin_env_temp_min.setValue(self.sensor_env_ranges["temp_agua"][0]); self.spin_env_temp_max.setValue(self.sensor_env_ranges["temp_agua"][1])
        self.spin_env_temp_min.setToolTip("Umbral mínimo de temperatura de agua.")
        self.spin_env_temp_max.setToolTip("Umbral máximo de temperatura de agua.")
        env_layout.addWidget(self.spin_env_temp_min, 1, 1); env_layout.addWidget(self.spin_env_temp_max, 1, 2)

        env_layout.addWidget(QLabel("pH"), 2, 0)
        self.spin_env_ph_min = QDoubleSpinBox(); self.spin_env_ph_min.setRange(0.0, 14.0); self.spin_env_ph_min.setDecimals(2)
        self.spin_env_ph_max = QDoubleSpinBox(); self.spin_env_ph_max.setRange(0.0, 14.0); self.spin_env_ph_max.setDecimals(2)
        self.spin_env_ph_min.setValue(self.sensor_env_ranges["ph"][0]); self.spin_env_ph_max.setValue(self.sensor_env_ranges["ph"][1])
        self.spin_env_ph_min.setToolTip("Umbral mínimo de pH.")
        self.spin_env_ph_max.setToolTip("Umbral máximo de pH.")
        env_layout.addWidget(self.spin_env_ph_min, 2, 1); env_layout.addWidget(self.spin_env_ph_max, 2, 2)

        env_layout.addWidget(QLabel("Conductividad (µS/cm)"), 3, 0)
        self.spin_env_cond_min = QDoubleSpinBox(); self.spin_env_cond_min.setRange(0.0, 10000.0); self.spin_env_cond_min.setDecimals(1)
        self.spin_env_cond_max = QDoubleSpinBox(); self.spin_env_cond_max.setRange(0.0, 10000.0); self.spin_env_cond_max.setDecimals(1)
        self.spin_env_cond_min.setValue(self.sensor_env_ranges["cond"][0]); self.spin_env_cond_max.setValue(self.sensor_env_ranges["cond"][1])
        self.spin_env_cond_min.setToolTip("Umbral mínimo de conductividad.")
        self.spin_env_cond_max.setToolTip("Umbral máximo de conductividad.")
        env_layout.addWidget(self.spin_env_cond_min, 3, 1); env_layout.addWidget(self.spin_env_cond_max, 3, 2)

        env_layout.addWidget(QLabel("Turbidez (NTU)"), 4, 0)
        self.spin_env_turb_min = QDoubleSpinBox(); self.spin_env_turb_min.setRange(0.0, 2000.0); self.spin_env_turb_min.setDecimals(1)
        self.spin_env_turb_max = QDoubleSpinBox(); self.spin_env_turb_max.setRange(0.0, 2000.0); self.spin_env_turb_max.setDecimals(1)
        self.spin_env_turb_min.setValue(self.sensor_env_ranges["turb"][0]); self.spin_env_turb_max.setValue(self.sensor_env_ranges["turb"][1])
        self.spin_env_turb_min.setToolTip("Umbral mínimo de turbidez.")
        self.spin_env_turb_max.setToolTip("Umbral máximo de turbidez.")
        env_layout.addWidget(self.spin_env_turb_min, 4, 1); env_layout.addWidget(self.spin_env_turb_max, 4, 2)

        env_layout.addWidget(QLabel("Oxígeno Disuelto (mg/L)"), 5, 0)
        self.spin_env_do_min = QDoubleSpinBox(); self.spin_env_do_min.setRange(0.0, 30.0); self.spin_env_do_min.setDecimals(1)
        self.spin_env_do_max = QDoubleSpinBox(); self.spin_env_do_max.setRange(0.0, 30.0); self.spin_env_do_max.setDecimals(1)
        self.spin_env_do_min.setValue(self.sensor_env_ranges["do"][0]); self.spin_env_do_max.setValue(self.sensor_env_ranges["do"][1])
        self.spin_env_do_min.setToolTip("Umbral mínimo de oxígeno disuelto.")
        self.spin_env_do_max.setToolTip("Umbral máximo de oxígeno disuelto.")
        env_layout.addWidget(self.spin_env_do_min, 5, 1); env_layout.addWidget(self.spin_env_do_max, 5, 2)

        for env_spin in (
            self.spin_env_temp_min, self.spin_env_temp_max,
            self.spin_env_ph_min, self.spin_env_ph_max,
            self.spin_env_cond_min, self.spin_env_cond_max,
            self.spin_env_turb_min, self.spin_env_turb_max,
            self.spin_env_do_min, self.spin_env_do_max,
        ):
            env_spin.valueChanged.connect(self._apply_sensor_ranges_from_ui)

        layout.addWidget(env_group)

        validation_group = QGroupBox("Parámetros de Validación (Medidas Reales)")
        validation_layout = QGridLayout(validation_group)
        
        # --- Longitud Mínima ---
        validation_layout.addWidget(QLabel("Longitud Mínima (cm):"), 0, 0)
        self.spin_min_length = QDoubleSpinBox()
        self.spin_min_length.setRange(0.1, 100.0)
        self.spin_min_length.setValue(Config.MIN_LENGTH_CM)
        self.spin_min_length.setSuffix(" cm")
        self.spin_min_length.setToolTip(
            "Medida mínima aceptable en centímetros."
        )
        validation_layout.addWidget(self.spin_min_length, 0, 1)
        
        # --- Longitud Máxima ---
        validation_layout.addWidget(QLabel("Longitud Máxima (cm):"), 1, 0)
        self.spin_max_length = QDoubleSpinBox()
        self.spin_max_length.setRange(1.0, 200.0)
        self.spin_max_length.setValue(Config.MAX_LENGTH_CM)
        self.spin_max_length.setSuffix(" cm")
        self.spin_max_length.setToolTip(
            "Medida máxima aceptable en centímetros."
        )
        validation_layout.addWidget(self.spin_max_length, 1, 1)
        
        layout.addWidget(validation_group)

        chroma_group = QGroupBox("Calibración de Color (Chroma Key)")
        chroma_group.setToolTip("Ajuste los rangos HSV para aislar el fondo de cada cámara.")
        chroma_layout = QVBoxLayout(chroma_group)

        hsv_container = QHBoxLayout()

        # --- PANEL CÁMARA LATERAL ---
        group_hsv_lat = QGroupBox("Cámara Lateral (Fondo)")
        layout_hsv_lat = QGridLayout(group_hsv_lat)
        
        self.spin_hue_min_lat = self._add_hsv_spin(layout_hsv_lat, "Hue Mín:", 0, 0, 35, 179)
        self.spin_hue_max_lat = self._add_hsv_spin(layout_hsv_lat, "Hue Máx:", 0, 2, 85, 179)
        self.spin_sat_min_lat = self._add_hsv_spin(layout_hsv_lat, "Sat Mín:", 1, 0, 40, 255)
        self.spin_sat_max_lat = self._add_hsv_spin(layout_hsv_lat, "Sat Máx:", 1, 2, 255, 255)
        self.spin_val_min_lat = self._add_hsv_spin(layout_hsv_lat, "Val Mín:", 2, 0, 40, 255)
        self.spin_val_max_lat = self._add_hsv_spin(layout_hsv_lat, "Val Máx:", 2, 2, 255, 255)
        
        # --- PANEL CÁMARA CENITAL ---
        group_hsv_top = QGroupBox("Cámara Cenital (Fondo)")
        layout_hsv_top = QGridLayout(group_hsv_top)
        
        self.spin_hue_min_top = self._add_hsv_spin(layout_hsv_top, "Hue Mín:", 0, 0, 35, 179)
        self.spin_hue_max_top = self._add_hsv_spin(layout_hsv_top, "Hue Máx:", 0, 2, 85, 179)
        self.spin_sat_min_top = self._add_hsv_spin(layout_hsv_top, "Sat Mín:", 1, 0, 40, 255)
        self.spin_sat_max_top = self._add_hsv_spin(layout_hsv_top, "Sat Máx:", 1, 2, 255, 255)
        self.spin_val_min_top = self._add_hsv_spin(layout_hsv_top, "Val Mín:", 2, 0, 40, 255)
        self.spin_val_max_top = self._add_hsv_spin(layout_hsv_top, "Val Máx:", 2, 2, 255, 255)

        hsv_container.addWidget(group_hsv_lat)
        hsv_container.addWidget(group_hsv_top)
        chroma_layout.addLayout(hsv_container)

        # Botón de Calibración Unificado
        btn_fine_tune = QPushButton("Abrir Calibrador de Color en Vivo")
        self.btn_fine_tune = btn_fine_tune
        btn_fine_tune.setProperty("class", "info")
        btn_fine_tune.style().unpolish(btn_fine_tune)
        btn_fine_tune.style().polish(btn_fine_tune)
        btn_fine_tune.setCursor(Qt.PointingHandCursor)
        btn_fine_tune.clicked.connect(self.open_fine_tune_calibration)
        chroma_layout.addWidget(btn_fine_tune)

        layout.addWidget(chroma_group)

        btn_save_config = QPushButton("Guardar Configuración")
        self.btn_save_config = btn_save_config
        btn_save_config.setProperty("class", "primary")
        btn_save_config.style().unpolish(btn_save_config)
        btn_save_config.style().polish(btn_save_config)
        btn_save_config.setCursor(Qt.PointingHandCursor)
        btn_save_config.clicked.connect(self.save_config)
        btn_save_config.setToolTip("Guarda todos los cambios actuales en el archivo de configuración.")
        layout.addWidget(btn_save_config)

        self.btn_reset_general_config = QPushButton("Restablecer Configuración General")
        self.btn_reset_general_config.setProperty("class", "warning")
        self.btn_reset_general_config.style().unpolish(self.btn_reset_general_config)
        self.btn_reset_general_config.style().polish(self.btn_reset_general_config)
        self.btn_reset_general_config.setCursor(Qt.PointingHandCursor)
        self.btn_reset_general_config.setToolTip("Restablece apariencia, hardware, filtros y rangos ambientales a valores recomendados.")
        self.btn_reset_general_config.clicked.connect(self.reset_general_settings)
        layout.addWidget(self.btn_reset_general_config)

        self.lbl_settings_dirty = QLabel("Configuración guardada")
        self.lbl_settings_dirty.setProperty("state", "success")
        self.lbl_settings_dirty.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.lbl_settings_dirty)

        for section in (
            appearance_group,
            eng_group,
            manual_group,
            detection_group,
            env_group,
            validation_group,
            chroma_group,
        ):
            section.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        layout.addStretch(1)

        self._update_settings_camera_indicator(self.cameras_connected)
        self._set_fine_tune_enabled(self.cameras_connected)
        self._setup_settings_dirty_tracking()
        self._set_settings_dirty(False)

        scroll.setWidget(widget)
        return scroll

    def _set_settings_dirty(self, dirty: bool, reason: str = "") -> None:
        """Actualiza estado visual de cambios pendientes en Configuración."""
        self.settings_dirty = bool(dirty)

        label = getattr(self, "lbl_settings_dirty", None)
        if label is None:
            return

        if self.settings_dirty:
            text = "Cambios sin guardar"
            if reason:
                text = f"Cambios sin guardar ({reason})"
            state = "warning"
        else:
            text = "Configuración guardada"
            state = "success"

        label.setText(text)
        label.setProperty("state", state)
        label.style().unpolish(label)
        label.style().polish(label)

    def _mark_settings_dirty(self, _value=None, reason: str = ""):
        """Marca configuración como pendiente de guardado cuando cambia un control."""
        if self._settings_change_guard:
            return
        self._set_settings_dirty(True, reason)

    def _setup_settings_dirty_tracking(self) -> None:
        """Conecta señales de widgets de configuración para detectar cambios sin guardar."""
        tracked_widgets = [
            getattr(self, 'combo_theme', None),
            getattr(self, 'combo_font_size', None),
            getattr(self, 'combo_density', None),
            getattr(self, 'combo_animations', None),
            getattr(self, 'chk_high_contrast', None),
            getattr(self, 'spin_cam_left', None),
            getattr(self, 'spin_cam_top', None),
            getattr(self, 'spin_min_area', None),
            getattr(self, 'spin_max_area', None),
            getattr(self, 'spin_confidence', None),
            getattr(self, 'spin_min_length', None),
            getattr(self, 'spin_max_length', None),
            getattr(self, 'spin_scale_front_left', None),
            getattr(self, 'spin_scale_back_left', None),
            getattr(self, 'spin_scale_front_top', None),
            getattr(self, 'spin_scale_back_top', None),
            getattr(self, 'spin_hue_min_lat', None),
            getattr(self, 'spin_hue_max_lat', None),
            getattr(self, 'spin_sat_min_lat', None),
            getattr(self, 'spin_sat_max_lat', None),
            getattr(self, 'spin_val_min_lat', None),
            getattr(self, 'spin_val_max_lat', None),
            getattr(self, 'spin_hue_min_top', None),
            getattr(self, 'spin_hue_max_top', None),
            getattr(self, 'spin_sat_min_top', None),
            getattr(self, 'spin_sat_max_top', None),
            getattr(self, 'spin_val_min_top', None),
            getattr(self, 'spin_val_max_top', None),
            getattr(self, 'spin_env_temp_min', None),
            getattr(self, 'spin_env_temp_max', None),
            getattr(self, 'spin_env_ph_min', None),
            getattr(self, 'spin_env_ph_max', None),
            getattr(self, 'spin_env_cond_min', None),
            getattr(self, 'spin_env_cond_max', None),
            getattr(self, 'spin_env_turb_min', None),
            getattr(self, 'spin_env_turb_max', None),
            getattr(self, 'spin_env_do_min', None),
            getattr(self, 'spin_env_do_max', None),
        ]

        for widget in tracked_widgets:
            if widget is None:
                continue
            if getattr(widget, '_dirty_tracking_setup', False):
                continue

            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(lambda _idx, w=widget: self._mark_settings_dirty(reason=w.objectName() or "combo"))
            elif isinstance(widget, QCheckBox):
                widget.stateChanged.connect(lambda _state, w=widget: self._mark_settings_dirty(reason=w.text() or "check"))
            else:
                try:
                    widget.valueChanged.connect(lambda _value, w=widget: self._mark_settings_dirty(reason=w.objectName() or "valor"))
                except Exception:
                    continue

            widget._dirty_tracking_setup = True

    def _validate_settings_ranges(self, show_message: bool = True) -> bool:
        """Valida consistencia de rangos antes de aplicar/guardar configuración."""
        issues = []

        if self.spin_min_area.value() >= self.spin_max_area.value():
            issues.append("Área mínima debe ser menor que área máxima.")

        if self.spin_min_length.value() >= self.spin_max_length.value():
            issues.append("Longitud mínima debe ser menor que longitud máxima.")

        if self.spin_cam_left.value() == self.spin_cam_top.value():
            issues.append("Cámara lateral y cenital no deben usar el mismo índice.")

        env_pairs = [
            ("Temperatura agua", self.spin_env_temp_min.value(), self.spin_env_temp_max.value()),
            ("pH", self.spin_env_ph_min.value(), self.spin_env_ph_max.value()),
            ("Conductividad", self.spin_env_cond_min.value(), self.spin_env_cond_max.value()),
            ("Turbidez", self.spin_env_turb_min.value(), self.spin_env_turb_max.value()),
            ("Oxígeno disuelto", self.spin_env_do_min.value(), self.spin_env_do_max.value()),
        ]
        for name, min_v, max_v in env_pairs:
            if min_v >= max_v:
                issues.append(f"{name}: mínimo debe ser menor que máximo.")

        hsv_pairs = [
            ("HSV Lateral", self.spin_hue_min_lat.value(), self.spin_hue_max_lat.value(), self.spin_sat_min_lat.value(), self.spin_sat_max_lat.value(), self.spin_val_min_lat.value(), self.spin_val_max_lat.value()),
            ("HSV Cenital", self.spin_hue_min_top.value(), self.spin_hue_max_top.value(), self.spin_sat_min_top.value(), self.spin_sat_max_top.value(), self.spin_val_min_top.value(), self.spin_val_max_top.value()),
        ]
        for name, h_min, h_max, s_min, s_max, v_min, v_max in hsv_pairs:
            if h_min > h_max:
                issues.append(f"{name}: Hue min no puede ser mayor que Hue max.")
            if s_min > s_max:
                issues.append(f"{name}: Sat min no puede ser mayor que Sat max.")
            if v_min > v_max:
                issues.append(f"{name}: Val min no puede ser mayor que Val max.")

        if issues and show_message:
            QMessageBox.warning(
                self,
                "Rangos inválidos",
                "Revise los siguientes campos antes de guardar:\n\n- " + "\n- ".join(issues),
            )
            if hasattr(self, 'status_bar'):
                self.status_bar.set_status("Hay rangos inválidos en Configuración", "warning")

        return len(issues) == 0

    def reset_general_settings(self):
        """Restablece configuración general a valores recomendados de operación."""
        reply = QMessageBox.question(
            self,
            "Restablecer configuración",
            "¿Desea restablecer la configuración general?\n\nEsto restablece apariencia, hardware, filtros, validación y rangos ambientales.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._settings_change_guard = True
        try:
            defaults = self._general_defaults

            self.combo_theme.setCurrentText(defaults['theme'])
            self.combo_font_size.setCurrentText(defaults['font_size'])
            self.combo_density.setCurrentText(defaults['density'])
            self.combo_animations.setCurrentText(defaults['animations'])
            self.chk_high_contrast.setChecked(defaults['high_contrast'])

            self.spin_cam_left.setValue(defaults['cam_left_index'])
            self.spin_cam_top.setValue(defaults['cam_top_index'])
            self.spin_min_area.setValue(defaults['min_contour_area'])
            self.spin_max_area.setValue(defaults['max_contour_area'])
            self.spin_confidence.setValue(defaults['confidence_threshold'])
            self.spin_min_length.setValue(defaults['min_length_cm'])
            self.spin_max_length.setValue(defaults['max_length_cm'])

            self.spin_env_temp_min.setValue(defaults['sensor_env_ranges']['temp_agua'][0])
            self.spin_env_temp_max.setValue(defaults['sensor_env_ranges']['temp_agua'][1])
            self.spin_env_ph_min.setValue(defaults['sensor_env_ranges']['ph'][0])
            self.spin_env_ph_max.setValue(defaults['sensor_env_ranges']['ph'][1])
            self.spin_env_cond_min.setValue(defaults['sensor_env_ranges']['cond'][0])
            self.spin_env_cond_max.setValue(defaults['sensor_env_ranges']['cond'][1])
            self.spin_env_turb_min.setValue(defaults['sensor_env_ranges']['turb'][0])
            self.spin_env_turb_max.setValue(defaults['sensor_env_ranges']['turb'][1])
            self.spin_env_do_min.setValue(defaults['sensor_env_ranges']['do'][0])
            self.spin_env_do_max.setValue(defaults['sensor_env_ranges']['do'][1])

            self._apply_sensor_ranges_from_ui()
            self.apply_appearance()
            self.update_cache()
        finally:
            self._settings_change_guard = False

        self._set_settings_dirty(True, "restablecida")
        if hasattr(self, 'status_bar'):
            self.status_bar.set_status("Configuración general restablecida. Falta guardar cambios.", "warning")
    
    def _add_hsv_spin(self, layout, label, row, col, default, max_val):
        """Helper para crear spins HSV rápidamente"""
        layout.addWidget(QLabel(label), row, col)
        spin = QSpinBox()
        spin.setRange(0, max_val)
        spin.setValue(default)
        layout.addWidget(spin, row, col + 1)
        return spin
    
    def _create_scale_spin(self):
        """Helper para crear SpinBoxes de escala uniformes"""
        sb = QDoubleSpinBox()
        sb.setDecimals(6)
        sb.setRange(0.000001, 1.0)
        sb.setSingleStep(0.0001)
        return sb

    def load_default_calibration(self):
        """Carga los valores de calibración predeterminados de fábrica"""

        DEF_VALUES = {
            'FL': Config.SCALE_LAT_FRONT, 'BL': Config.SCALE_LAT_BACK,
            'FT': Config.SCALE_TOP_FRONT, 'BT':Config.SCALE_TOP_BACK
        }
        
        reply = QMessageBox.question(
            self, "Restaurar Fábrica", 
            "¿Desea restaurar los valores de escala predeterminados?\n\n"
            "Esto sobrescribirá cualquier calibración manual actual.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
            
        if reply == QMessageBox.StandardButton.Yes:
            self.spin_scale_front_left.setValue(DEF_VALUES['FL'])
            self.spin_scale_back_left.setValue(DEF_VALUES['BL'])
            self.spin_scale_front_top.setValue(DEF_VALUES['FT'])
            self.spin_scale_back_top.setValue(DEF_VALUES['BT'])

            self.apply_manual_calibration(silent=True)
            self.status_bar.set_status("Valores de fábrica restaurados", "warning")

    def apply_manual_calibration(self, silent=False):
        """Sincroniza las variables del motor de IA con los SpinBoxes de la UI"""
        try:
            self.scale_front_left = self.spin_scale_front_left.value()
            self.scale_back_left  = self.spin_scale_back_left.value()
            self.scale_front_top  = self.spin_scale_front_top.value()
            self.scale_back_top   = self.spin_scale_back_top.value()
            
            widgets = [
                self.spin_scale_front_left, self.spin_scale_back_left,
                self.spin_scale_front_top, self.spin_scale_back_top
            ]
            
            for w in widgets:
                w.setProperty("state", "success")
                w.style().unpolish(w)
                w.style().polish(w)
            
            msg = f"Escalas actualizadas: L:{self.scale_front_left:.5f} | T:{self.scale_front_top:.5f}"
            logger.info(msg)
            
            if not silent:
                self.status_bar.set_status(f"{msg}", "success")

            QTimer.singleShot(2000, lambda: self._clear_scales_highlight(widgets))

        except Exception as e:
            logger.error(f"Error aplicando calibracion: {e}.")
            self.status_bar.set_status("Error al aplicar escalas", "error")

    def _clear_scales_highlight(self, widgets):
        """Limpia el resalte de éxito de los campos de escala"""
        for w in widgets:
            w.setProperty("state", "")
            w.style().unpolish(w)
            w.style().polish(w)

    def open_scale_calibration_dialog(self):
        """Calibrador interno de escala (cm/px) por cámara y zona con sobrescritura opcional."""
        left_ready = bool(self.cap_left and hasattr(self.cap_left, "isOpened") and self.cap_left.isOpened())
        top_ready = bool(self.cap_top and hasattr(self.cap_top, "isOpened") and self.cap_top.isOpened())

        if not (left_ready or top_ready):
            QMessageBox.warning(self, "Sin cámaras", "No hay cámaras activas para calibrar escala.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Calibrador de Escala (cm/px)")
        dialog.setMinimumSize(980, 720)
        root = QVBoxLayout(dialog)

        info = QLabel(
            "1) Seleccione cámara y zona.  2) Capture imagen.  3) Marque dos puntos.\n"
            "4) Ingrese distancia real en cm.  5) Aplique la escala calculada."
        )
        info.setProperty("state", "info")
        root.addWidget(info)

        controls = QGridLayout()
        controls.addWidget(QLabel("Cámara:"), 0, 0)
        combo_camera = QComboBox()
        if left_ready:
            combo_camera.addItem("Lateral", "left")
        if top_ready:
            combo_camera.addItem("Cenital", "top")
        controls.addWidget(combo_camera, 0, 1)

        controls.addWidget(QLabel("Zona de escala:"), 0, 2)
        combo_zone = QComboBox()
        combo_zone.addItem("Frente", "front")
        combo_zone.addItem("Fondo", "back")
        controls.addWidget(combo_zone, 0, 3)

        controls.addWidget(QLabel("Distancia real (cm):"), 1, 0)
        spin_distance_cm = QDoubleSpinBox()
        spin_distance_cm.setRange(0.1, 500.0)
        spin_distance_cm.setDecimals(2)
        spin_distance_cm.setValue(10.0)
        spin_distance_cm.setSuffix(" cm")
        controls.addWidget(spin_distance_cm, 1, 1)

        chk_save_now = QCheckBox("Guardar configuración al aplicar")
        chk_save_now.setChecked(True)
        controls.addWidget(chk_save_now, 1, 2, 1, 2)
        root.addLayout(controls)

        preview = QLabel("Capture una imagen para comenzar")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setMinimumSize(900, 500)
        preview.setStyleSheet("border: 1px solid #666; background-color: #111;")
        root.addWidget(preview)

        lbl_result = QLabel("Escala calculada: -")
        lbl_result.setProperty("state", "warning")
        root.addWidget(lbl_result)

        buttons = QHBoxLayout()
        btn_capture = QPushButton("Capturar Imagen")
        btn_clear = QPushButton("Limpiar Puntos")
        btn_apply = QPushButton("Aplicar Escala")
        btn_close = QPushButton("Cerrar")
        btn_apply.setProperty("class", "success")
        btn_close.setProperty("class", "warning")
        buttons.addWidget(btn_capture)
        buttons.addWidget(btn_clear)
        buttons.addStretch(1)
        buttons.addWidget(btn_apply)
        buttons.addWidget(btn_close)
        root.addLayout(buttons)

        state = {
            'frame': None,
            'points': [],
            'scale': None,
            'render_rect': (0, 0, 1, 1),
        }

        def render_frame_with_points():
            frame = state['frame']
            if frame is None:
                preview.setText("Capture una imagen para comenzar")
                preview.setPixmap(QPixmap())
                return

            draw = frame.copy()
            if len(state['points']) >= 1:
                x1, y1 = state['points'][0]
                cv2.circle(draw, (x1, y1), 7, (0, 255, 255), -1)
            if len(state['points']) >= 2:
                x1, y1 = state['points'][0]
                x2, y2 = state['points'][1]
                cv2.circle(draw, (x2, y2), 7, (0, 255, 255), -1)
                cv2.line(draw, (x1, y1), (x2, y2), (255, 255, 0), 2)
                px_dist = float(np.hypot(x2 - x1, y2 - y1))
                cv2.putText(draw, f"px: {px_dist:.2f}", (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)

            rgb = cv2.cvtColor(draw, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
            pix = QPixmap.fromImage(qimg)

            target_size = preview.size()
            scaled = pix.scaled(target_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

            canvas = QPixmap(target_size)
            canvas.fill(Qt.GlobalColor.black)
            painter = QPainter(canvas)
            ox = (target_size.width() - scaled.width()) // 2
            oy = (target_size.height() - scaled.height()) // 2
            painter.drawPixmap(ox, oy, scaled)
            painter.end()

            state['render_rect'] = (ox, oy, scaled.width(), scaled.height())
            preview.setPixmap(canvas)

        def map_click_to_frame(click_pos):
            frame = state['frame']
            if frame is None:
                return None

            ox, oy, rw, rh = state['render_rect']
            cx, cy = click_pos.x(), click_pos.y()
            if cx < ox or cy < oy or cx > (ox + rw) or cy > (oy + rh):
                return None

            fh, fw = frame.shape[:2]
            rel_x = (cx - ox) / max(1, rw)
            rel_y = (cy - oy) / max(1, rh)
            px = int(rel_x * fw)
            py = int(rel_y * fh)
            px = max(0, min(fw - 1, px))
            py = max(0, min(fh - 1, py))
            return (px, py)

        def on_preview_click(event):
            point = map_click_to_frame(event.pos())
            if point is None:
                return

            if len(state['points']) >= 2:
                state['points'] = []
                state['scale'] = None

            state['points'].append(point)

            if len(state['points']) == 2:
                (x1, y1), (x2, y2) = state['points']
                px_dist = float(np.hypot(x2 - x1, y2 - y1))
                if px_dist <= 0:
                    state['scale'] = None
                    lbl_result.setText("Escala calculada: error (distancia en px inválida)")
                else:
                    cm_dist = float(spin_distance_cm.value())
                    state['scale'] = cm_dist / px_dist
                    lbl_result.setText(f"Escala calculada: {state['scale']:.6f} cm/px  |  Dist px: {px_dist:.2f}")

            render_frame_with_points()

        preview.mousePressEvent = on_preview_click

        def capture_frame():
            camera_key = combo_camera.currentData()
            cap = self.cap_left if camera_key == "left" else self.cap_top
            if cap is None or not cap.isOpened():
                QMessageBox.warning(dialog, "Sin señal", "La cámara seleccionada no está disponible.")
                return

            ret, frame = cap.read()
            if not ret or frame is None:
                QMessageBox.warning(dialog, "Sin frame", "No fue posible capturar imagen de la cámara seleccionada.")
                return

            state['frame'] = frame.copy()
            state['points'] = []
            state['scale'] = None
            lbl_result.setText("Escala calculada: -")
            render_frame_with_points()

        def clear_points():
            state['points'] = []
            state['scale'] = None
            lbl_result.setText("Escala calculada: -")
            render_frame_with_points()

        def apply_scale():
            if state['scale'] is None or state['scale'] <= 0:
                QMessageBox.warning(dialog, "Escala inválida", "Debe capturar imagen y marcar dos puntos válidos.")
                return

            camera_key = combo_camera.currentData()
            zone_key = combo_zone.currentData()

            if camera_key == "left" and zone_key == "front":
                target_spin = self.spin_scale_front_left
                target_name = "Lateral - Frente"
            elif camera_key == "left" and zone_key == "back":
                target_spin = self.spin_scale_back_left
                target_name = "Lateral - Fondo"
            elif camera_key == "top" and zone_key == "front":
                target_spin = self.spin_scale_front_top
                target_name = "Cenital - Frente"
            else:
                target_spin = self.spin_scale_back_top
                target_name = "Cenital - Fondo"

            old_value = float(target_spin.value())
            new_value = float(state['scale'])

            reply = QMessageBox.question(
                dialog,
                "Sobrescribir escala",
                f"Aplicar nueva escala en {target_name}?\n\nActual: {old_value:.6f} cm/px\nNueva: {new_value:.6f} cm/px",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

            target_spin.setValue(new_value)
            self.apply_manual_calibration(silent=True)

            if chk_save_now.isChecked():
                self.save_config()
            else:
                self.status_bar.set_status(f"Escala aplicada en {target_name}: {new_value:.6f} cm/px", "success")

            QMessageBox.information(dialog, "Escala aplicada", f"Nueva escala aplicada en {target_name}: {new_value:.6f} cm/px")

        btn_capture.clicked.connect(capture_frame)
        btn_clear.clicked.connect(clear_points)
        btn_apply.clicked.connect(apply_scale)
        btn_close.clicked.connect(dialog.accept)

        was_main_timer_active = bool(hasattr(self, 'timer') and self.timer.isActive())
        if was_main_timer_active:
            self.timer.stop()

        dialog.exec()

        if was_main_timer_active and self.cameras_connected and hasattr(self, 'timer'):
            fps_ms = int(1000 / max(1, Config.PREVIEW_FPS))
            self.timer.start(fps_ms)

    def set_camera_placeholder(self, label):
        """Configura el estado visual cuando no hay señal de video."""
        if label is None: return

        icon_color = getattr(self, 'c_sec_text', "#888888")
        pixmap = qta.icon("fa5s.video-slash", color=icon_color).pixmap(64, 64)
        
        label.setPixmap(pixmap)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        label.setToolTip("CÁMARA NO DISPONIBLE\nVerifique conexión USB")

        label.setProperty("state", "no-camera")
        
        label.style().unpolish(label)
        label.style().polish(label)
        
    def resizeEvent(self, event):
        super().resizeEvent(event)
        
        camera_map = {
            self.lbl_left: getattr(self, "cap_left", None),
            self.lbl_top: getattr(self, "cap_top", None),
            self.lbl_manual_left: getattr(self, "cap_left", None),
            self.lbl_manual_top: getattr(self, "cap_top", None)
        }

        for label, cap_obj in camera_map.items():
            if label is not None:
                if cap_obj is None or (hasattr(cap_obj, 'isOpened') and not cap_obj.isOpened()):
                    self.set_camera_placeholder(label)
          
    def update_camera_dependent_buttons(self, enabled: bool):
        """
        Activa o desactiva botones que dependen de las cámaras
        """
        self.btn_capture.setEnabled(enabled)
        self.btn_auto_capture.setEnabled(enabled)
        self.btn_manual_capture.setEnabled(enabled)

    def _set_camera_block_tooltip(self, widget, cameras_ok: bool) -> None:
        """Aplica/recupera tooltip base con mensaje de bloqueo por cámaras."""
        if widget is None:
            return

        base_tip = getattr(widget, "_base_tooltip", None)
        if base_tip is None:
            base_tip = widget.toolTip() or ""
            setattr(widget, "_base_tooltip", base_tip)

        if cameras_ok:
            widget.setToolTip(base_tip)
            return

        lock_msg = "Requiere cámaras activas. Revise la conexión en Configuración."
        widget.setToolTip(f"{base_tip}\n\n{lock_msg}" if base_tip else lock_msg)

    def _set_fine_tune_enabled(self, cameras_ok: bool) -> None:
        """Habilita o bloquea calibradores en vivo según estado real de cámaras."""
        for btn in (getattr(self, "btn_fine_tune", None), getattr(self, "btn_scale_calibrator", None)):
            if btn is None:
                continue
            btn.setEnabled(bool(cameras_ok))
            self._set_camera_block_tooltip(btn, bool(cameras_ok))

    def _update_settings_camera_indicator(self, cameras_ok: bool, details: str = "") -> None:
        """Refuerza visualmente el estado de conexión dentro de la pestaña Configuración."""
        label = getattr(self, "lbl_camera_hw_status", None)
        if label is None:
            return

        if cameras_ok:
            text = "Estado de cámaras: Conectadas y operativas"
            state = "success"
        else:
            text = "Estado de cámaras: No disponibles"
            state = "error"

        if details:
            text = f"{text} ({details})"

        label.setText(text)
        label.setProperty("state", state)
        label.style().unpolish(label)
        label.style().polish(label)
        label.setToolTip(text)

    def _set_single_camera_health_label(self, label, camera_name: str, state: str, detail: str = "") -> None:
        """Actualiza un indicador tipo semáforo para una cámara específica."""
        if label is None:
            return

        if state == "success":
            base_text = "Estable"
            icon_name = "fa5s.check-circle"
            icon_color = "#2a9d8f"
        elif state == "warning":
            base_text = "Inestable"
            icon_name = "fa5s.exclamation-circle"
            icon_color = "#f39c12"
        else:
            base_text = "Sin señal"
            icon_name = "fa5s.times-circle"
            icon_color = "#e74c3c"

        text = f"{camera_name}: {base_text}"
        if detail:
            text = f"{text} ({detail})"

        icon_label = None
        if camera_name == "Lateral":
            icon_label = getattr(self, "lbl_cam_left_icon", None)
        elif camera_name == "Cenital":
            icon_label = getattr(self, "lbl_cam_top_icon", None)

        if icon_label is not None:
            pix = qta.icon(icon_name, color=icon_color).pixmap(16, 16)
            icon_label.setPixmap(pix)
            icon_label.setToolTip(text)

        label.setText(text)
        label.setProperty("state", state)
        label.style().unpolish(label)
        label.style().polish(label)
        label.setToolTip(text)

    def _prune_microcuts_window(self) -> None:
        """Mantiene únicamente microcortes registrados en los últimos 60 segundos."""
        now = time.time()
        while self._microcuts_left and now - self._microcuts_left[0] > 60.0:
            self._microcuts_left.popleft()
        while self._microcuts_top and now - self._microcuts_top[0] > 60.0:
            self._microcuts_top.popleft()

    def _register_microcut(self, camera_key: str) -> None:
        """Registra un microcorte para diagnóstico por cámara."""
        if camera_key == "left":
            self._microcuts_left.append(time.time())
        elif camera_key == "top":
            self._microcuts_top.append(time.time())
        self._prune_microcuts_window()

    def _update_microcuts_indicator(self) -> None:
        """Actualiza contador visual de microcortes en la pestaña Configuración."""
        self._prune_microcuts_window()
        label = getattr(self, "lbl_cam_microcuts", None)
        if label is None:
            return

        left_count = len(self._microcuts_left)
        top_count = len(self._microcuts_top)
        label.setText(f"Microcortes (60s) - Lateral: {left_count} | Cenital: {top_count}")

        total = left_count + top_count
        if total == 0:
            state = "success"
        elif total <= 3:
            state = "warning"
        else:
            state = "error"

        label.setProperty("state", state)
        label.style().unpolish(label)
        label.style().polish(label)
        label.setToolTip("Si el contador crece seguido, revisar cable USB, puerto o alimentación.")

    def _update_camera_health_indicators(self, left_state: str, top_state: str, left_detail: str = "", top_detail: str = "") -> None:
        """Sincroniza semáforo por cámara en pestaña Configuración."""
        self._cam_health_left = left_state
        self._cam_health_top = top_state
        self._set_single_camera_health_label(getattr(self, "lbl_cam_left_status", None), "Lateral", left_state, left_detail)
        self._set_single_camera_health_label(getattr(self, "lbl_cam_top_status", None), "Cenital", top_state, top_detail)
        self._update_microcuts_indicator()

    def _request_auto_reconnect(self, reason: str) -> None:
        """Lanza recuperación automática acotada cuando la señal de cámara cae."""
        if self._auto_reconnect_running:
            return

        if self._auto_reconnect_attempts >= 2:
            self.status_bar.set_status("Reconexión automática agotada. Use 'Reconectar Cámaras'.", "warning")
            return

        self._auto_reconnect_running = True
        next_attempt = self._auto_reconnect_attempts + 1
        self.status_bar.set_status(f"Recuperación automática de cámaras ({next_attempt}/2): {reason}", "warning")
        QTimer.singleShot(1100, self._run_auto_reconnect)

    def _run_auto_reconnect(self) -> None:
        """Ejecuta un intento de reconexión automática sin popups."""
        self._auto_reconnect_attempts += 1
        ok = self.reconnect_cameras(interactive=False)
        self._auto_reconnect_running = False

        if ok:
            self._auto_reconnect_attempts = 0
            self.status_bar.set_status("Cámaras recuperadas automáticamente", "success")
        elif self._auto_reconnect_attempts < 2:
            self._request_auto_reconnect("reintento")

    def _apply_camera_blocking_tooltips(self, cameras_ok: bool) -> None:
        """Sincroniza tooltips de pestaña automática y widgets dependientes de cámara."""
        if hasattr(self, "tabs") and self.tabs is not None:
            tab_tip = "Medición automática desde cámara y sensores"
            if not cameras_ok:
                tab_tip += "\n\nBloqueada: no se detectaron cámaras activas"
            self.tabs.tabBar().setTabToolTip(0, tab_tip)

        widgets = [
            getattr(self, "btn_capture", None),
            getattr(self, "btn_auto_capture", None),
            getattr(self, "btn_manual_capture", None),
            getattr(self, "lbl_left", None),
            getattr(self, "lbl_top", None),
            getattr(self, "lbl_manual_left", None),
            getattr(self, "lbl_manual_top", None),
            getattr(self, "btn_fine_tune", None),
        ]
        for widget in widgets:
            self._set_camera_block_tooltip(widget, cameras_ok)

        self._set_fine_tune_enabled(cameras_ok)
        self._update_settings_camera_indicator(cameras_ok)
        if cameras_ok:
            self._update_camera_health_indicators("success", "success", "Operativa", "Operativa")
        else:
            self._update_camera_health_indicators("error", "error", "Desconectada", "Desconectada")

    def _configure_camera_tabs(self, cameras_ok: bool, choose_startup: bool = False) -> None:
        """Habilita/bloquea pestañas según estado de cámaras y define pestaña inicial."""
        if not hasattr(self, "tabs"):
            return

        self.tabs.setTabEnabled(0, cameras_ok)
        self._apply_camera_blocking_tooltips(cameras_ok)

        if cameras_ok:
            if choose_startup:
                self.tabs.setCurrentIndex(0)
        else:
            if choose_startup or self.tabs.currentIndex() == 0:
                self.tabs.setCurrentIndex(1)

    def start_cameras(self):
        """
        Inicia el streaming de video con arquitectura de estados
        """

        try:
            self.cap_left = OptimizedCamera(Config.CAM_LEFT_INDEX).start()
            self.cap_top  = OptimizedCamera(Config.CAM_TOP_INDEX).start()

            left_ok = self.cap_left and self.cap_left.isOpened()
            top_ok  = self.cap_top and self.cap_top.isOpened()

            if not left_ok or not top_ok:

                error_msg = "❌ Error de hardware en:\n"
                if not left_ok:
                    error_msg += f"- Cámara Lateral (ID: {Config.CAM_LEFT_INDEX})\n"
                if not top_ok:
                    error_msg += f"- Cámara Cenital (ID: {Config.CAM_TOP_INDEX})\n"

                QMessageBox.critical(self, "Error de Cámaras", error_msg)

                self._handle_camera_failure("Hardware de cámara no detectado")
                return False

            fps_ms = int(1000 / Config.PREVIEW_FPS)
            self.timer.start(fps_ms)

            self.last_frame_time = time.time()
            self._camera_read_failures = 0
            self._left_signal_failures = 0
            self._top_signal_failures = 0
            self._auto_reconnect_attempts = 0
            self._microcuts_left.clear()
            self._microcuts_top.clear()

            self.cameras_connected = True
            self.update_camera_dependent_buttons(True)

            self.status_bar.set_camera_status(True)
            self.status_bar.set_status(
                "Sistema de visión activo",
                "success"
            )
            self._update_settings_camera_indicator(True, "Streaming activo")
            self._set_fine_tune_enabled(True)
            self._update_camera_health_indicators("success", "success", "Señal estable", "Señal estable")

            return True

        except Exception as e:

            QMessageBox.critical(
                self,
                "Error",
                f"Error al iniciar cámaras:\n{str(e)}"
            )

            logger.error(f"Error al iniciar camaras: {str(e)}")
            self._handle_camera_failure("Error crítico de inicialización")
            return False

    def _handle_camera_failure(self, message: str) -> None:
        """Centraliza el estado de fallo de cámara: placeholders, botones, StatusBar."""
        if hasattr(self, 'timer') and self.timer.isActive():
            self.timer.stop()

        for cam_attr in ('cap_left', 'cap_top'):
            cam_obj = getattr(self, cam_attr, None)
            if cam_obj is not None:
                try:
                    cam_obj.release()
                except Exception:
                    pass
                setattr(self, cam_attr, None)

        labels = [self.lbl_left, self.lbl_top, self.lbl_manual_left, self.lbl_manual_top]
        for lbl in labels:
            self.set_camera_placeholder(lbl)

        self._camera_read_failures = 0
        self._left_signal_failures = 0
        self._top_signal_failures = 0
        self.cameras_connected = False
        self.update_camera_dependent_buttons(False)
        self._configure_camera_tabs(False)
        self._set_fine_tune_enabled(False)
        self._update_settings_camera_indicator(False, message)
        self._update_camera_health_indicators("error", "error", "Sin conexión", "Sin conexión")
        self.status_bar.set_camera_status(False)
        self.status_bar.set_status(message, "error")

    def reconnect_cameras(self, interactive: bool = True):
        """Libera y reconecta los puertos USB de forma segura"""

        if interactive:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status_bar.set_status("Reiniciando puertos USB...", "info")

        try:
            # Detener timer si existe
            if hasattr(self, 'timer') and self.timer.isActive():
                self.timer.stop()

            # Liberar cámaras si existen
            for cam in ['cap_left', 'cap_top']:
                obj = getattr(self, cam, None)  
                if obj is not None:
                    try:
                        obj.release()
                    except Exception:
                        pass
                    setattr(self, cam, None)

            # Actualizar índices desde UI
            Config.CAM_LEFT_INDEX = self.spin_cam_left.value()
            Config.CAM_TOP_INDEX  = self.spin_cam_top.value()

            # Intentar reconexión
            connected = self.start_cameras()

            if connected:
                self._configure_camera_tabs(True)
                self.status_bar.set_status(
                    "Cámaras conectadas correctamente.",
                    "success"
                )
                self._update_settings_camera_indicator(True, "Reconectadas")
                self._update_camera_health_indicators("success", "success", "Recuperada", "Recuperada")
                if interactive:
                    QMessageBox.information(
                        self,
                        "Reconexión exitosa",
                        "Las cámaras lateral y cenital fueron reconectadas correctamente.\nEl calibrador en vivo ya está habilitado."
                    )
            else:
                self.status_bar.set_status(
                    "No se pudieron conectar las cámaras.",
                    "error"
                )
                self._update_settings_camera_indicator(False, "Reconexión fallida")
                self._update_camera_health_indicators("error", "error", "Falló reconexión", "Falló reconexión")
                if interactive:
                    QMessageBox.warning(
                        self,
                        "Reconexión fallida",
                        "No se pudieron reconectar las cámaras.\nVerifique cableado USB y los índices configurados."
                    )

            return bool(connected)

        finally:
            if interactive:
                QApplication.restoreOverrideCursor()
     
    def update_frames(self):
        """🚀 MOTOR ULTRA-RÁPIDO: Mantiene 60 FPS estables"""
        if self.current_tab not in [0, 1] or not self.cameras_connected or not self.cap_left or not self.cap_top:
            return
        
        # 1. Captura de frames (Thread-Safe)
        ret_l, frame_l = self.cap_left.read()
        ret_t, frame_t = self.cap_top.read()

        if ret_l:
            self._left_signal_failures = 0
        else:
            self._left_signal_failures += 1
            if self._left_signal_failures == 1:
                self._register_microcut("left")

        if ret_t:
            self._top_signal_failures = 0
        else:
            self._top_signal_failures += 1
            if self._top_signal_failures == 1:
                self._register_microcut("top")

        left_state = "success" if self._left_signal_failures == 0 else ("warning" if self._left_signal_failures < 4 else "error")
        top_state = "success" if self._top_signal_failures == 0 else ("warning" if self._top_signal_failures < 4 else "error")

        self._prune_microcuts_window()
        left_cuts = len(self._microcuts_left)
        top_cuts = len(self._microcuts_top)
        left_detail = (
            f"Señal estable · {left_cuts}/60s" if left_state == "success"
            else (f"Intermitencia · {left_cuts}/60s" if left_state == "warning" else f"Sin lectura · {left_cuts}/60s")
        )
        top_detail = (
            f"Señal estable · {top_cuts}/60s" if top_state == "success"
            else (f"Intermitencia · {top_cuts}/60s" if top_state == "warning" else f"Sin lectura · {top_cuts}/60s")
        )
        self._update_camera_health_indicators(left_state, top_state, left_detail, top_detail)

        if not (ret_l and ret_t):
            self._camera_read_failures += 1
            if self._camera_read_failures >= 6:
                self._handle_camera_failure("Se perdió la conexión de cámaras durante la captura")
                self._request_auto_reconnect("sin señal en stream")
            return

        self._camera_read_failures = 0

        # Guardamos referencia para cuentagotas (sin copiar memoria)
        self.current_frame_left = frame_l
        self.current_frame_top = frame_t

        # 2. Renderizado en UI (Usamos el frame directo, sin resize previo)
        if self.current_tab == 0:  
            self.display_frame(frame_l, self.lbl_left)
            self.display_frame(frame_t, self.lbl_top)

            # 3. Lógica de Procesamiento IA (Solo si no está bloqueado)
            if self.auto_capture_enabled and not self.processing_lock:
                # Construimos el diccionario usando la CACHÉ, NO los widgets
                params = {
                    'scales': {
                        'lat_front': self.scale_front_left, 'lat_back': self.scale_back_left,
                        'top_front': self.scale_front_top, 'top_back': self.scale_back_top
                    },
                    'hsv_lateral': self.cache_params['hsv_lat'],
                    'hsv_cenital': self.cache_params['hsv_top'],
                    'detection': {
                        'min_area': self.cache_params['min_area'],
                        'max_area': self.cache_params['max_area'],
                        'confidence': self.cache_params['conf']
                    }
                }
                self.processing_lock = True
                self.processor.add_frame(frame_l, frame_t, params)
                
        elif self.current_tab == 1:
            self.display_frame(frame_l, self.lbl_manual_left)
            self.display_frame(frame_t, self.lbl_manual_top)

        # 4. Contador de FPS (Monitor de salud del sistema)
        self.fps_counter += 1
        now = time.time()
        if now - self.last_fps_update >= 1.0:
            if hasattr(self, 'status_bar'):
                self.status_bar.update_system_info(fps=self.fps_counter)
            self.fps_counter = 0
            self.last_fps_update = now
    
    def display_frame(self, frame, label, is_mask=False):
        """
        Muestra el frame forzando una relación de aspecto 16:9.
        """
        if frame is None: return
        
        try:
            # 1. Validar dimensiones
            win_w = label.width()
            win_h = label.height()
            if win_w < 10 or win_h < 10: return

            # 2. Calcular 16:9
            target_aspect = 16 / 9
            
            if win_w / win_h > target_aspect:
                new_h = win_h
                new_w = int(win_h * target_aspect)
            else:
                new_w = win_w
                new_h = int(win_w / target_aspect)

            # 3. Redimensionar (OpenCV)
            frame_resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

            # 4. Convertir a QImage
            if is_mask or len(frame_resized.shape) == 2:
                h, w = frame_resized.shape
                bytes_per_line = w
                q_img = QImage(frame_resized.data, w, h, bytes_per_line, QImage.Format.Format_Grayscale8)
            else:
                frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
                h, w, ch = frame_rgb.shape
                bytes_per_line = ch * w
                q_img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)

            # 5. Mostrar (SOLO setPixmap)
            pixmap = QPixmap.fromImage(q_img)
            label.setPixmap(pixmap)

        except Exception as e:
            logger.error(f"Error en display_frame: {e}")  
            
    def _refresh_button_icon(self, button):
        """Regenera el icono del botón según el tema actual."""
        
        if not hasattr(button, "_icon_name"):
            return
        
        btn_class = getattr(button, "_icon_class", "primary")
        icon_name = button._icon_name
        
        icon_color = self._btn_text_colors.get(btn_class, "#ffffff")
        
        button.setIcon(qta.icon(icon_name, color=icon_color))
        button.setIconSize(QSize(18, 18))

            
    def update_cache(self):
        """Actualiza la caché de parámetros para el motor de visión"""
        self.cache_params['min_area'] = self.spin_min_area.value()
        self.cache_params['max_area'] = self.spin_max_area.value()
        self.cache_params['conf'] = self.spin_confidence.value()
        
        # Sincronizar HSV Lateral
        self.cache_params['hsv_lat'] = [
            self.spin_hue_min_lat.value(), self.spin_hue_max_lat.value(),
            self.spin_sat_min_lat.value(), self.spin_sat_max_lat.value(),
            self.spin_val_min_lat.value(), self.spin_val_max_lat.value()
        ]
        # Sincronizar HSV Cenital
        self.cache_params['hsv_top'] = [
            self.spin_hue_min_top.value(), self.spin_hue_max_top.value(),
            self.spin_sat_min_top.value(), self.spin_sat_max_top.value(),
            self.spin_val_min_top.value(), self.spin_val_max_top.value()
        ]
    
    def toggle_auto_capture(self, checked):
        """Activa/desactiva la captura automática con feedback visual e iconos sincronizados con el texto."""

        self.auto_capture_enabled = checked

        if checked:
            btn_class = "success"
            icon_name = "fa5s.stop"

            self.btn_auto_capture.setText(" Detener Auto-Captura")
            self.status_bar.set_status(
                "Detección IA activa: Buscando ejemplares...",
                "success"
            )
            logger.info("Auto-captura habilitada.")

        else:
            btn_class = "secondary"
            icon_name = "fa5s.play"

            self.btn_auto_capture.setText(" Iniciar Auto-Captura")
            self.status_bar.set_status(
                "Monitoreo automático pausado",
                "warning"
            )
            self.processing_lock = False
            logger.info("Auto-captura deshabilitada.")

        # Guardar metadatos correctos para refresco en cambio de tema
        self.btn_auto_capture._icon_name = icon_name
        self.btn_auto_capture._icon_class = btn_class

        # Aplicar clase visual
        self.btn_auto_capture.setProperty("class", btn_class)

        # Obtener color según clase actual
        icon_color = self._btn_text_colors.get(btn_class, "#ffffff")

        # Generar icono con color correcto
        self.btn_auto_capture.setIcon(
            qta.icon(icon_name, color=icon_color)
        )
        self.btn_auto_capture.setIconSize(QSize(18, 18))

        # Refrescar estilos
        self.btn_auto_capture.style().unpolish(self.btn_auto_capture)
        self.btn_auto_capture.style().polish(self.btn_auto_capture)
        self.btn_auto_capture.update()
    
    def delete_selected_measurement(self):
        """Elimina de forma segura la medición seleccionada y su evidencia fotográfica"""
        selected_items = self.table_history.selectedItems()
        if not selected_items:
            self.status_bar.set_status("Seleccione una fila para eliminar", "warning")
            return
        
        row = self.table_history.currentRow()
        try:
            measurement_id = int(self.table_history.item(row, 0).text())
            fish_id = self.table_history.item(row, 3).text()
        except (AttributeError, ValueError) as e:
            logger.error(f"Error al recuperar ID de la tabla: {e}")
            return

        reply = QMessageBox.question(
            self, "Confirmar Eliminación",
            f"¿Está seguro de eliminar permanentemente esta medición?\n\n"
            f"🔹 ID Registro: {measurement_id}\n"
            f"🔹 ID Pez: {fish_id}\n\n"
            f"Esta acción borrará la imagen y el dato de la base de datos.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._execute_measurement_deletion(measurement_id)

    def _execute_measurement_deletion(self, measurement_id):
        """Lógica interna de borrado físico y lógico"""
        try:
            image_path = self.db.get_image_path(measurement_id)
            
            success = self.db.delete_measurement(measurement_id)
            
            if success:
                if image_path and os.path.exists(image_path):
                    try:
                        os.remove(image_path)
                        logger.info(f"Archivo eliminado: {image_path}")
                    except OSError as e:
                        logger.warning(f"No se pudo borrar el archivo físico: {e}")

                self.status_bar.set_status(f"Medición {measurement_id} eliminada correctamente", "success")
                self.refresh_history()
                self.refresh_daily_counter()
            else:
                QMessageBox.critical(self, "Error", "No se pudo eliminar el registro de la base de datos.")

        except Exception as e:
            logger.error(f"Fallo crítico en proceso de eliminación: {e}")
            self.status_bar.set_status("Error al procesar la eliminación", "error")
    
    def edit_selected_measurement(self):
        """Versión Blindada: Asegura que la ruta sea válida antes de abrir el editor."""
        selected_items = self.table_history.selectedItems()
        if not selected_items:
            self.status_bar.set_status("Seleccione una fila para editar", "warning")
            return

        row = self.table_history.currentRow()
        try:
            measurement_id = int(self.table_history.item(row, 0).text())
        except: return

        measurement_data = self.db.get_measurement_as_dict(measurement_id)
        if not measurement_data: return

        measurement_data['image_path'] = self._resolve_measurement_image_path(measurement_data) or ""

        # Abrir el diálogo
        dialog = EditMeasurementDialog(measurement_data, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated_data = dialog.get_updated_data()
            if self.db.update_measurement(measurement_id, updated_data):
                self.status_bar.set_status(f"Registro e imagen actualizados.", "success")
                self.refresh_history()
            else:
                QMessageBox.critical(self, "Error", "No se pudo actualizar la BD.")
   
    def view_measurement_image(self, *_):
        """
        Abre el visor. Si la ruta falla, busca el archivo por su FECHA exacta.
        """
        # 1. Validación de selección
        selected = self.table_history.selectedItems()
        if not selected:
            self.status_bar.set_status("Seleccione una medición", "warning")
            return
        
        row = self.table_history.currentRow()
        try:
            m_id = int(self.table_history.item(row, 0).text())
        except (AttributeError, ValueError): return

        # 2. Obtener datos de BD
        m_data = self.db.get_measurement_as_dict(m_id)
        if not m_data:
            self.status_bar.set_status("Error de lectura BD", "error")
            return

        # -------------------------------------------------------------
        # 3. RECUPERACIÓN INTELIGENTE DE IMAGEN (unificada)
        # -------------------------------------------------------------
        image_path = str(m_data.get('image_path', "")).strip()
        archivo_encontrado = self._resolve_measurement_image_path(m_data)

        if not archivo_encontrado:
            self.status_bar.set_status(f"Buscando imagen perdida para ID {m_id}...", "warning")

        # -------------------------------------------------------------
        # 4. RESULTADO FINAL
        # -------------------------------------------------------------
        if archivo_encontrado:
            # ¡Éxito! Abrimos el visor con el archivo recuperado
            try:
                # Opcional: Auto-reparar la BD para la próxima vez
                if archivo_encontrado != image_path:
                   print(f"✅ Imagen recuperada y re-vinculada: {archivo_encontrado}")
                   # self.db.update_measurement_path(m_id, archivo_encontrado)

                self.status_bar.set_status(f"Visualizando registro {m_id}", "info")
                
                dialog = ImageViewerDialog(
                    archivo_encontrado, # Usamos la ruta recuperada
                    m_data,  
                    self.advanced_detector,
                    getattr(self, 'scale_front_left', 1.0),
                    getattr(self, 'scale_back_left', 1.0),
                    getattr(self, 'scale_front_top', 1.0),
                    getattr(self, 'scale_back_top', 1.0),
                    parent=self,
                    on_update_callback=self.refresh_history
                )
                if dialog.exec():
                    self.refresh_history()

            except Exception as e:
                QMessageBox.critical(self, "Error Visor", f"Fallo al abrir visualizador:\n{e}")
        else:
            # Fallo total
            QMessageBox.warning(self, "Imagen No Encontrada", 
                f"No se pudo localizar la imagen para el registro #{m_id}.\n\n"
                f"• Ruta BD: {image_path}\n"
                f"• Fecha buscada: {m_data.get('timestamp')}\n\n"
                "Verifique si el archivo fue eliminado manualmente de la carpeta 'Capturas'.")

    def _stats_get_preferred_numeric(self, measurement_row, *field_names, default=0.0):
        """Obtiene el primer valor numérico positivo disponible para estadísticas."""
        for field_name in field_names:
            try:
                value = self.db.get_field_value(measurement_row, field_name, None)
                if value in (None, ""):
                    continue
                numeric = float(value)
                if numeric > 0:
                    return numeric
            except (TypeError, ValueError):
                continue
        return float(default)

    def _stats_get_text(self, measurement_row, field_name, default=""):
        """Obtiene un texto de forma robusta para reportes y exportaciones."""
        value = self.db.get_field_value(measurement_row, field_name, default)
        if value in (None, ""):
            return default
        return str(value)

    def _stats_get_datetime(self, measurement_row):
        """Convierte el timestamp de una medición a datetime si es válido."""
        ts_str = self._stats_get_text(measurement_row, 'timestamp', '')
        if not ts_str:
            return None

        try:
            return datetime.fromisoformat(ts_str)
        except Exception:
            try:
                return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None

    def _build_statistics_dataset(self, measurements):
        """Construye una fuente única de datos para pantalla, PNG, PDF y CSV."""
        dataset = {
            'count': len(measurements),
            'records': [],
            'lengths': [],
            'weights': [],
            'heights': [],
            'widths': [],
            'k_factors': [],
            'dates': [],
            'dates_for_lengths': [],
            'dates_for_weights': [],
            'pairs': [],
        }

        for measurement in measurements:
            try:
                record = {
                    'fish_id': self._stats_get_text(measurement, 'fish_id', '-'),
                    'timestamp': self._stats_get_datetime(measurement),
                    'length': self._stats_get_preferred_numeric(measurement, 'manual_length_cm', 'length_cm'),
                    'weight': self._stats_get_preferred_numeric(measurement, 'manual_weight_g', 'weight_g'),
                    'height': self._stats_get_preferred_numeric(measurement, 'manual_height_cm', 'height_cm'),
                    'width': self._stats_get_preferred_numeric(measurement, 'manual_width_cm', 'width_cm'),
                }
            except Exception:
                logger.debug("Registro omitido en estadísticas por datos inválidos", exc_info=True)
                continue

            dataset['records'].append(record)

            if record['timestamp'] is not None:
                dataset['dates'].append(record['timestamp'])

            if record['length'] > 0:
                dataset['lengths'].append(record['length'])
                if record['timestamp'] is not None:
                    dataset['dates_for_lengths'].append(record['timestamp'])

            if record['weight'] > 0:
                dataset['weights'].append(record['weight'])
                if record['timestamp'] is not None:
                    dataset['dates_for_weights'].append(record['timestamp'])

            if record['height'] > 0:
                dataset['heights'].append(record['height'])

            if record['width'] > 0:
                dataset['widths'].append(record['width'])

            if record['length'] > 0 and record['weight'] > 0:
                dataset['pairs'].append((record['length'], record['weight']))
                dataset['k_factors'].append((100 * record['weight']) / (record['length'] ** 3))

        return dataset

    def _build_weekly_metric_map(self, records, field_name):
        """Agrupa una métrica semanalmente para curvas de crecimiento."""
        weekly_data = {}
        for record in records:
            value = float(record.get(field_name) or 0)
            dt_value = record.get('timestamp')
            if value <= 0 or dt_value is None:
                continue

            monday = dt_value.date() - timedelta(days=dt_value.date().weekday())
            weekly_data.setdefault(monday, []).append(value)

        return weekly_data

    def _set_scaled_graph_preview(self, label, pixmap, container):
        """Reescala el gráfico ampliado cada vez que cambia el tamaño del visor."""
        if pixmap is None or pixmap.isNull() or label is None or container is None:
            return

        target_size = container.viewport().size()
        if target_size.width() <= 1 or target_size.height() <= 1:
            target_size = pixmap.size()

        label.setPixmap(
            pixmap.scaled(
                target_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _stats_log_graph_error(self, graph_name, error):
        """Centraliza el registro de errores al construir gráficas."""
        logger.error("Error generando grafica '%s': %s", graph_name, error, exc_info=True)

    def _apply_stats_axis_style(self, ax, title, xlabel, ylabel):
        """Aplica un estilo consistente y legible para el panel estadístico."""
        ax.set_title(title, fontweight='bold', pad=10)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(True, linestyle=':', alpha=0.35)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

    def export_statistics(self):
        """
        📊 EXPORTAR PANEL COMPLETO (6 en 1):
        Genera una lámina resumen de alta resolución con fondo blanco.
        Incluye la curva de crecimiento inteligente (Gompertz/Lineal).
        """

        # 1. Obtener datos
        measurements = self.db.get_filtered_measurements(limit=3000)
        
        if not measurements:
            QMessageBox.warning(self, "Advertencia", "No Hay Mediciones Para Exportar")
            return

        stats_data = self._build_statistics_dataset(measurements)
        lengths = stats_data['lengths']
        weights = stats_data['weights']
        heights = stats_data['heights']
        widths = stats_data['widths']
        k_factors = stats_data['k_factors']
        records = stats_data['records']
        pairs = stats_data['pairs']
        
        try:
            # Configurar Estilo "Reporte Científico" (Fondo Blanco)
            plt.style.use('default') 
            plt.rcParams.update({'font.size': 9, 'font.family': 'sans-serif'})
            
            # Directorio
            output_dir = os.path.join(Config.OUT_DIR, "Graficos")
            os.makedirs(output_dir, exist_ok=True)

            # --- LIENZO 3x2 ---
            fig = plt.figure(figsize=(16, 10), constrained_layout=True, dpi=200)
            fig.patch.set_facecolor('white')
            gs = fig.add_gridspec(3, 2)
            
            # Título Global
            fig.suptitle(f'Reporte de Trazabilidad - {datetime.now().strftime("%d/%m/%Y")}', 
                         fontsize=16, fontweight='bold', color='#2c3e50')
            
            # 1. DISTRIBUCIÓN LONGITUD
            ax1 = fig.add_subplot(gs[0, 0])
            if lengths:
                ax1.hist(lengths, bins=15, edgecolor='black', color='#3498db', alpha=0.8)
                ax1.axvline(np.mean(lengths), color='red', linestyle='--', label=f'Prom: {np.mean(lengths):.1f}cm')
                ax1.legend()
            ax1.set_title('Distribución de Tallas', fontweight='bold'); ax1.set_xlabel('cm')

            # 2. DISTRIBUCIÓN PESO
            ax2 = fig.add_subplot(gs[0, 1])
            if weights:
                ax2.hist(weights, bins=15, edgecolor='black', color='#2ecc71', alpha=0.8)
                ax2.axvline(np.mean(weights), color='red', linestyle='--', label=f'Prom: {np.mean(weights):.1f}g')
                ax2.legend()
            ax2.set_title('Distribución de Peso', fontweight='bold'); ax2.set_xlabel('g')

            # 3. RELACIÓN L/P (Scatter)
            ax3 = fig.add_subplot(gs[1, 0])
            if pairs:
                l_scat = [pair[0] for pair in pairs]
                w_scat = [pair[1] for pair in pairs]
                ax3.scatter(l_scat, w_scat, alpha=0.5, color='#e74c3c', edgecolors='black')
            ax3.set_title('Relación Longitud vs Peso', fontweight='bold')
            ax3.set_xlabel('Longitud (cm)'); ax3.set_ylabel('Peso (g)')
            ax3.grid(True, linestyle=':', alpha=0.5)

            # 4. EVOLUCIÓN CRECIMIENTO (GOMPERTZ INTELIGENTE)
            ax4 = fig.add_subplot(gs[1, 1])
            
            # Agrupar por Semana (Peso)
            weekly_data = {}
            for record in records:
                w = float(record.get('weight') or 0)
                dt = record.get('timestamp')
                if w > 0 and dt:
                    monday = dt.date() - timedelta(days=dt.date().weekday())
                    weekly_data[monday] = weekly_data.get(monday, []) + [w]
            
            if weekly_data:
                sorted_weeks = sorted(weekly_data.keys())
                sorted_dts = [datetime.combine(d, datetime.min.time()) for d in sorted_weeks]
                avg_vals = np.array([sum(weekly_data[d])/len(weekly_data[d]) for d in sorted_weeks])
                
                # Puntos Reales
                ax4.plot(sorted_dts, avg_vals, 'o', color='#8e44ad', markersize=6, label='Promedio Semanal')
                
                # --- MATEMÁTICA AVANZADA ---
                if len(avg_vals) >= 2:
                    start = sorted_dts[0]
                    days_rel = np.array([(d - start).days for d in sorted_dts])
                    last_day = days_rel[-1]
                    future_rel = np.linspace(0, last_day + 45, 100) # +45 días
                    y_trend = None
                    lbl = ""

                    # Intento Gompertz
                    try:
                        if len(avg_vals) >= 3:
                            def model_gompertz(t, A, B, k): return A * np.exp(-np.exp(B - k * t))
                            mx = max(avg_vals)
                            p0 = [mx * 1.5, 1.0, 0.02]
                            bounds = ([mx, -10, 0], [np.inf, 10, 1.0])
                            params, _ = curve_fit(model_gompertz, days_rel, avg_vals, p0=p0, bounds=bounds, maxfev=5000)
                            cand = model_gompertz(future_rel, *params)
                            if cand[-1] < mx * 4: # Sanity check
                                y_trend = cand
                                lbl = "Tendencia (Gompertz)"
                    except Exception as error:
                        logger.debug("Gompertz descartado en export_statistics: %s", error)

                    # Fallback Lineal
                    if y_trend is None:
                        z = np.polyfit(days_rel, avg_vals, 1)
                        y_trend = np.poly1d(z)(future_rel)
                        lbl = "Tendencia (Lineal)"
                    
                    # Dibujar
                    fut_dates = [start + timedelta(days=x) for x in future_rel]
                    ax4.plot(fut_dates, y_trend, '--', color='#2c3e50', linewidth=2, label=lbl)
                    
                    # Etiqueta Final
                    end_val = y_trend[-1]
                    if end_val < 100000:
                        ax4.text(fut_dates[-1], end_val, f"{end_val:.1f} g", fontweight='bold', ha='left')

                ax4.xaxis.set_major_formatter(mdates.DateFormatter('%d/%b'))
                ax4.legend()
            
            ax4.set_title('Proyección de Crecimiento (Peso)', fontweight='bold')
            ax4.set_ylabel('Peso (g)'); ax4.grid(True, linestyle=':', alpha=0.5)

            # 5. ALTURAS
            ax5 = fig.add_subplot(gs[2, 0])
            if heights:
                ax5.hist(heights, bins=10, color='#1abc9c', edgecolor='black', alpha=0.7)
                ax5.axvline(np.mean(heights), color='red', linestyle='--')
            ax5.set_title('Distribución Alturas'); ax5.set_xlabel('cm')

            # 6. ANCHOS
            ax6 = fig.add_subplot(gs[2, 1])
            if widths:
                ax6.hist(widths, bins=10, color='#f1c40f', edgecolor='black', alpha=0.7)
                ax6.axvline(np.mean(widths), color='red', linestyle='--')
            ax6.set_title('Distribución Anchos'); ax6.set_xlabel('cm')

            # --- GUARDAR ---
            filename = f'Panel_Reporte_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
            save_path = os.path.join(output_dir, filename)
            
            plt.savefig(save_path, dpi=200, bbox_inches='tight', facecolor='white')
            plt.close(fig)
            
            QMessageBox.information(self, "Éxito", f"Reporte generado:\n{save_path}")
            
            # Abrir carpeta automáticamente
            try:
                os.startfile(output_dir)
            except Exception as error:
                logger.debug("No se pudo abrir la carpeta de gráficos automáticamente: %s", error)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error generando reporte:\n{e}")
            logger.error(f"Export Error: {e}")
            
    def export_to_csv(self):
        """
        Exporta a CSV leyendo DIRECTAMENTE la estructura real de la Base de Datos.
        Soluciona problemas de columnas desordenadas, datos corridos o campos nuevos.
        """
        # 1. Preparar ruta de guardado
        try:
            report_dir = getattr(Config, 'CSV_DIR', os.path.join("Resultados", "CSV"))
        except:
            report_dir = os.path.join("Resultados", "CSV")
            
        os.makedirs(report_dir, exist_ok=True)
        default_name = f"Base_Datos_Full_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        default_path = os.path.join(report_dir, default_name)

        filename, _ = QFileDialog.getSaveFileName(
            self, "Exportar CSV", default_path, "CSV Files (*.csv)"
        )
        if not filename: 
            return
        
        conn = None
        try:
            
            # 2. CONEXIÓN DIRECTA A LA BASE DE DATOS
            conn = sqlite3.connect(self.db.db_path)
            conn.row_factory = sqlite3.Row 
            cursor = conn.cursor()
            
            # 3. OBTENER DATOS Y ESTRUCTURA REAL
            cursor.execute("SELECT * FROM measurements")
            rows = cursor.fetchall()
            
            if not rows:
                QMessageBox.warning(self, "Vacío", "La base de datos está vacía.")
                return

            # 4. DETECTAR NOMBRES DE COLUMNAS AUTOMÁTICAMENTE
            db_column_names = [desc[0] for desc in cursor.description]
            
            # Preparamos encabezados finales (DB + Cálculos Extra)
            final_headers = [name.upper() for name in db_column_names]
            final_headers.append("FACTOR_K_CALCULADO")

            # 5. ESCRIBIR EL ARCHIVO
            # utf-8-sig: Permite que Excel lea correctamente caracteres especiales (ñ, tildes)
            # delimiter=',': Estándar internacional (compatible con Excel, Python, R, etc.)
            with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=',')
                writer.writerow(final_headers)
                
                for row in rows:
                    # Variables para cálculo de K
                    l_val = self._stats_get_preferred_numeric(row, 'manual_length_cm', 'length_cm')
                    w_val = self._stats_get_preferred_numeric(row, 'manual_weight_g', 'weight_g')
                    cleaned_row = []

                    for col_name, val in zip(db_column_names, row):
                        # Limpieza y formato
                        if val is None:
                            cleaned_row.append("")
                        elif isinstance(val, float):
                            # CRÍTICO: Usar punto decimal SIEMPRE para compatibilidad
                            cleaned_row.append(f"{val:.4f}")
                        else:
                            cleaned_row.append(str(val))
                    
                    # --- CÁLCULO FACTOR K ---
                    # K = 100 * W / L³
                    k_factor = 0.0
                    if l_val > 0:
                        k_factor = (100 * w_val) / (l_val ** 3)
                    
                    cleaned_row.append(f"{k_factor:.4f}")
                    writer.writerow(cleaned_row)

            QMessageBox.information(
                self, "Éxito", 
                f"✅ Base de datos exportada correctamente:\n{filename}\n\n"
                f"📊 Total de registros: {len(rows)}"
            )
            if hasattr(self, 'status_bar'):
                self.status_bar.set_status(f"CSV se ha generado en:\n{filename}", "success")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error crítico al exportar:\n{e}")
            logger.error(f"Error CSV Directo: {e}", exc_info=True)
            if hasattr(self, 'status_bar'):
                self.status_bar.set_status(f"Error generando el CSV.", "error")
        finally:
            if conn: 
                conn.close()
            
    def export_stats_pdf(self):
        """
        📄 GENERADOR DE INFORME PDF CIENTÍFICO (V2.0):
        - Incluye Resumen Estadístico.
        - Gráficos de Alta Resolución (Histogramas + Curvas Gompertz).
        - Tabla de Datos Recientes.
        """

        # 1. Configurar directorio
        try:
            report_dir = getattr(Config, 'REPORTS_DIR', os.path.join("Resultados", "Reportes"))
        except:
            report_dir = os.path.join("Resultados", "Reportes")
        os.makedirs(report_dir, exist_ok=True)
        
        # 2. Diálogo de guardado
        default_name = f"Informe_Tecnico_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        default_path = os.path.join(report_dir, default_name)
        
        path, _ = QFileDialog.getSaveFileName(self, "Exportar Informe PDF", default_path, "PDF Files (*.pdf)")
        if not path: return

        # 3. Obtener datos
        measurements = self.db.get_filtered_measurements(limit=3000)
        if not measurements:
            QMessageBox.warning(self, "Sin Datos", "No hay registros para generar el informe.")
            return

        stats_data = self._build_statistics_dataset(measurements)
        lengths = stats_data['lengths']
        weights = stats_data['weights']
        heights = stats_data['heights']
        widths = stats_data['widths']
        k_factors = stats_data['k_factors']
        records = stats_data['records']

        # Directorio temporal para imágenes del PDF
        temp_plots_dir = os.path.join(report_dir, "_temp_pdf_plots")
        os.makedirs(temp_plots_dir, exist_ok=True)

        try:
            # --- CONFIGURACIÓN PDF ---
            doc = SimpleDocTemplate(path, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
            styles = getSampleStyleSheet()
            
            title_style = ParagraphStyle('MainTitle', parent=styles['Title'], fontSize=16, alignment=TA_CENTER, textColor=colors.HexColor('#2c3e50'))
            subtitle_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER, textColor=colors.HexColor('#7f8c8d'))
            h2_style = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=12, spaceBefore=15, spaceAfter=8, textColor=colors.HexColor('#2980b9'))

            elements = []
            elements.append(Paragraph("INFORME TÉCNICO DE CRECIMIENTO", title_style))
            elements.append(Paragraph(f"Generado el: {datetime.now().strftime('%d/%m/%Y %H:%M')}", subtitle_style))
            elements.append(Spacer(1, 20))

            # --- 1. TABLA RESUMEN ---
            elements.append(Paragraph("1. Resumen Estadístico", h2_style))
            
            def calc_row(name, d, unit):
                if not d: return [name, "0", "-", "-", "-"]
                return [name, str(len(d)), f"{np.mean(d):.2f} {unit}", f"{np.min(d):.2f} {unit}", f"{np.max(d):.2f} {unit}"]

            t_data = [['Variable', 'N', 'Promedio', 'Mínimo', 'Máximo']]
            t_data.append(calc_row("Longitud", lengths, "cm"))
            t_data.append(calc_row("Peso", weights, "g"))
            t_data.append(calc_row("Altura", heights, "cm"))
            t_data.append(calc_row("Ancho", widths, "cm"))
            t_data.append(calc_row("Factor K", k_factors, ""))
            
            t = Table(t_data, colWidths=[100, 60, 100, 100, 100])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#34495e')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.whitesmoke, colors.HexColor('#ecf0f1')])
            ]))
            elements.append(t)
            elements.append(Spacer(1, 20))

            # --- 2. GRÁFICOS CIENTÍFICOS ---
            elements.append(Paragraph("2. Galería Analítica Extendida", h2_style))

            plt.style.use('default')
            plt.rcParams.update({'font.size': 9})

            rendered_graphs = 0

            def save_plot(fig, file_name):
                file_path = os.path.join(temp_plots_dir, file_name)
                fig.tight_layout()
                fig.savefig(file_path, bbox_inches='tight', dpi=220)
                plt.close(fig)
                return file_path

            def append_graph(caption, fig, file_name, width=460, height=220):
                nonlocal rendered_graphs
                image_path = save_plot(fig, file_name)
                elements.append(Paragraph(caption, subtitle_style))
                elements.append(Image(image_path, width=width, height=height))
                elements.append(Spacer(1, 8))
                rendered_graphs += 1
                if rendered_graphs % 3 == 0:
                    elements.append(PageBreak())

            def build_weekly_map(field_name):
                return self._build_weekly_metric_map(records, field_name)

            def plot_weekly_trend(ax, weekly_data, color_line, label, unit):
                sorted_weeks = sorted(weekly_data.keys())
                if not sorted_weeks:
                    return

                sorted_dts = [datetime.combine(d, datetime.min.time()) for d in sorted_weeks]
                avg_vals = np.array([sum(weekly_data[d]) / len(weekly_data[d]) for d in sorted_weeks])
                start_date = sorted_dts[0]
                days_since_start = np.array([(d - start_date).days for d in sorted_dts])

                ax.plot(sorted_dts, avg_vals, 'o', color=color_line, markersize=6, label=f'{label} semanal')

                if len(avg_vals) >= 2:
                    future_days = np.linspace(0, days_since_start[-1] + 45, 100)
                    trend_values = None
                    trend_label = ""

                    try:
                        if len(avg_vals) >= 3:
                            def gompertz(t, A, B, k):
                                return A * np.exp(-np.exp(B - k * t))

                            max_val = max(avg_vals)
                            p0 = [max_val * 1.5, 1.0, 0.02]
                            bounds = ([max_val, -10, 0], [np.inf, 10, 1.0])
                            params, _ = curve_fit(gompertz, days_since_start, avg_vals, p0=p0, bounds=bounds, maxfev=5000)
                            candidate = gompertz(future_days, *params)
                            if candidate[-1] < max_val * 3:
                                trend_values = candidate
                                trend_label = "Tendencia Gompertz"
                    except Exception as error:
                        logger.debug("Gompertz descartado en PDF para %s: %s", label, error)

                    if trend_values is None:
                        coeffs = np.polyfit(days_since_start, avg_vals, 1)
                        trend_values = np.poly1d(coeffs)(future_days)
                        trend_label = "Tendencia lineal"

                    future_dates = [start_date + timedelta(days=float(d)) for d in future_days]
                    ax.plot(future_dates, trend_values, '--', color='#2c3e50', linewidth=1.8, label=trend_label)

                ax.set_title(f"Evolución de {label}")
                ax.set_xlabel("Semana")
                ax.set_ylabel(f"{label} ({unit})")
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%b'))
                ax.grid(True, linestyle=':', alpha=0.4)
                ax.legend()

            # 2.1 Histograma longitudinal y biomasa
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.5, 3.8))
            if lengths:
                ax1.hist(lengths, bins=15, color='#3498db', alpha=0.75, edgecolor='black')
                ax1.axvline(np.mean(lengths), color='#1f3a5f', linestyle='--', linewidth=1.4)
            ax1.set_title("Distribución de Tallas")
            ax1.set_xlabel("Longitud (cm)")
            ax1.set_ylabel("Frecuencia")

            if weights:
                ax2.hist(weights, bins=15, color='#2ecc71', alpha=0.75, edgecolor='black')
                ax2.axvline(np.mean(weights), color='#145a32', linestyle='--', linewidth=1.4)
            ax2.set_title("Distribución de Pesos")
            ax2.set_xlabel("Peso (g)")
            ax2.set_ylabel("Frecuencia")
            append_graph("2.1 Distribuciones base (talla y peso)", fig, "pdf_01_distribuciones.png", width=470, height=215)

            # 2.2 Morfometría (altura y ancho)
            if heights or widths:
                fig, ax = plt.subplots(figsize=(8.5, 3.8))
                if heights:
                    ax.hist(heights, bins=10, color='#3498db', alpha=0.45, edgecolor='black', label='Altura')
                if widths:
                    ax.hist(widths, bins=10, color='#f39c12', alpha=0.45, edgecolor='black', label='Ancho')
                ax.set_title("Morfometría combinada")
                ax.set_xlabel("Medida (cm)")
                ax.set_ylabel("Frecuencia")
                ax.legend()
                append_graph("2.2 Distribución morfométrica (altura y ancho)", fig, "pdf_02_morfometria.png", width=470, height=215)

            # 2.3 Crecimiento de peso
            weekly_weights = build_weekly_map('weight')
            if weekly_weights:
                fig, ax = plt.subplots(figsize=(8.5, 3.9))
                plot_weekly_trend(ax, weekly_weights, '#9b59b6', 'Peso', 'g')
                fig.autofmt_xdate(rotation=35, ha='right')
                append_graph("2.3 Proyección de crecimiento en peso", fig, "pdf_03_peso.png", width=470, height=220)

            # 2.4 Crecimiento de longitud
            weekly_lengths = build_weekly_map('length')
            if weekly_lengths:
                fig, ax = plt.subplots(figsize=(8.5, 3.9))
                plot_weekly_trend(ax, weekly_lengths, '#e67e22', 'Longitud', 'cm')
                fig.autofmt_xdate(rotation=35, ha='right')
                append_graph("2.4 Proyección de crecimiento en longitud", fig, "pdf_04_longitud.png", width=470, height=220)

            # 2.5 Relación longitud/peso
            if stats_data['pairs']:
                fig, ax = plt.subplots(figsize=(8.5, 3.9))
                paired_lengths = [pair[0] for pair in stats_data['pairs']]
                paired_weights = [pair[1] for pair in stats_data['pairs']]
                ax.scatter(paired_lengths, paired_weights, c='#e74c3c', alpha=0.62, edgecolors='black', linewidths=0.4)
                ax.set_title("Relación Longitud / Peso")
                ax.set_xlabel("Longitud (cm)")
                ax.set_ylabel("Peso (g)")
                ax.grid(True, linestyle=':', alpha=0.35)
                append_graph("2.5 Correlación biométrica longitud-peso", fig, "pdf_05_correlacion.png", width=470, height=220)

            # 2.6 Factor K
            if k_factors:
                fig, ax = plt.subplots(figsize=(8.5, 3.9))
                ax.hist(k_factors, bins=12, color='#16a085', alpha=0.78, edgecolor='black')
                ax.axvspan(1.0, 1.4, color='#2ecc71', alpha=0.14, label='Zona óptima')
                ax.axvline(np.mean(k_factors), color='#0b5345', linestyle='--', linewidth=1.5, label=f"Prom: {np.mean(k_factors):.3f}")
                ax.set_title("Distribución del Factor K")
                ax.set_xlabel("Factor de condición K")
                ax.set_ylabel("Frecuencia")
                ax.legend()
                ax.grid(True, linestyle=':', alpha=0.35)
                append_graph("2.6 Estado corporal del lote (factor K)", fig, "pdf_06_factor_k.png", width=470, height=220)

            # 2.7 Perfil corporal (ancho vs altura)
            body_records = [record for record in records if record.get('height', 0) > 0 and record.get('width', 0) > 0]
            if body_records:
                fig, ax = plt.subplots(figsize=(8.5, 3.9))
                body_widths = [record['width'] for record in body_records]
                body_heights = [record['height'] for record in body_records]
                ax.scatter(body_widths, body_heights, c='#af7ac5', alpha=0.66, edgecolors='black', linewidths=0.4)
                if len(body_widths) >= 2:
                    coeffs = np.polyfit(body_widths, body_heights, 1)
                    trend_x = np.linspace(min(body_widths), max(body_widths), 60)
                    trend_y = np.poly1d(coeffs)(trend_x)
                    ax.plot(trend_x, trend_y, '--', color='#5b2c6f', linewidth=1.5, label='Tendencia')
                    ax.legend()
                ax.set_title("Perfil corporal")
                ax.set_xlabel("Ancho dorsal (cm)")
                ax.set_ylabel("Altura corporal (cm)")
                ax.grid(True, linestyle=':', alpha=0.35)
                append_graph("2.7 Perfil corporal (ancho vs altura)", fig, "pdf_07_perfil.png", width=470, height=220)

            # 2.8 Variabilidad biométrica
            metric_map = {
                'Longitud': lengths,
                'Peso': weights,
                'Altura': heights,
                'Ancho': widths,
            }
            labels = []
            cv_values = []
            for metric_name, metric_values in metric_map.items():
                if len(metric_values) >= 2 and np.mean(metric_values) > 0:
                    labels.append(metric_name)
                    cv_values.append((np.std(metric_values) / np.mean(metric_values)) * 100)

            if labels:
                fig, ax = plt.subplots(figsize=(8.5, 3.9))
                bars = ax.bar(labels, cv_values, color=['#3498db', '#2ecc71', '#1abc9c', '#f1c40f'][:len(labels)], edgecolor='black', alpha=0.85)
                for bar, value in zip(bars, cv_values):
                    ax.text(bar.get_x() + bar.get_width() / 2, value + 0.35, f"{value:.1f}%", ha='center', va='bottom', fontsize=8.5, fontweight='bold')
                ax.set_title("Variabilidad del lote (CV%)")
                ax.set_xlabel("Indicador")
                ax.set_ylabel("Coeficiente de variación (%)")
                ax.grid(True, axis='y', linestyle=':', alpha=0.35)
                append_graph("2.8 Variabilidad por indicador biométrico", fig, "pdf_08_variabilidad.png", width=470, height=220)

            # 2.9 Intensidad de muestreo semanal
            weekly_counts = build_weekly_map('length')
            if weekly_counts:
                fig, ax = plt.subplots(figsize=(8.5, 3.9))
                weeks = sorted(weekly_counts.keys())
                week_dates = [datetime.combine(week, datetime.min.time()) for week in weeks]
                counts = [len(weekly_counts[week]) for week in weeks]
                ax.bar(week_dates, counts, color='#5dade2', edgecolor='#1b4f72', width=5)
                ax.set_title("Intensidad de muestreo semanal")
                ax.set_xlabel("Semana")
                ax.set_ylabel("Número de mediciones")
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%b'))
                ax.grid(True, axis='y', linestyle=':', alpha=0.35)
                fig.autofmt_xdate(rotation=35, ha='right')
                append_graph("2.9 Cobertura de muestreo por semana", fig, "pdf_09_muestreo.png", width=470, height=220)

            # 2.10 Clases de talla
            if lengths:
                fig, ax = plt.subplots(figsize=(8.5, 3.9))
                class_bins = min(7, max(4, int(np.sqrt(len(lengths)))))
                counts, bins = np.histogram(lengths, bins=class_bins)
                class_labels = [f"{bins[i]:.1f}-{bins[i + 1]:.1f}" for i in range(len(counts))]
                bars = ax.bar(class_labels, counts, color='#2471a3', alpha=0.86, edgecolor='black')
                for bar, value in zip(bars, counts):
                    ax.text(bar.get_x() + bar.get_width() / 2, value + 0.2, str(int(value)), ha='center', va='bottom', fontsize=8.5, fontweight='bold')
                ax.set_title("Clases de talla")
                ax.set_xlabel("Rango de longitud (cm)")
                ax.set_ylabel("Cantidad")
                ax.tick_params(axis='x', rotation=24)
                ax.grid(True, axis='y', linestyle=':', alpha=0.35)
                append_graph("2.10 Segmentación del lote por clases de talla", fig, "pdf_10_clases_talla.png", width=470, height=220)

            # 2.11 Tendencia semanal del factor K
            weekly_k = {}
            for record in records:
                length_value = float(record.get('length') or 0)
                weight_value = float(record.get('weight') or 0)
                ts_value = record.get('timestamp')
                if length_value <= 0 or weight_value <= 0 or ts_value is None:
                    continue
                k_value = (100 * weight_value) / (length_value ** 3)
                monday = ts_value.date() - timedelta(days=ts_value.date().weekday())
                weekly_k.setdefault(monday, []).append(k_value)

            if weekly_k:
                fig, ax = plt.subplots(figsize=(8.5, 3.9))
                weeks = sorted(weekly_k.keys())
                week_dates = [datetime.combine(week, datetime.min.time()) for week in weeks]
                avg_k = [float(np.mean(weekly_k[week])) for week in weeks]
                ax.plot(week_dates, avg_k, 'o-', color='#117864', linewidth=2, markersize=5.5, label='K semanal')
                ax.axhspan(1.0, 1.4, color='#2ecc71', alpha=0.12, label='Zona óptima')
                ax.set_title("Tendencia semanal del Factor K")
                ax.set_xlabel("Semana")
                ax.set_ylabel("Factor K")
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%b'))
                ax.grid(True, linestyle=':', alpha=0.35)
                ax.legend()
                fig.autofmt_xdate(rotation=35, ha='right')
                append_graph("2.11 Evolución semanal del estado corporal", fig, "pdf_11_tendencia_k.png", width=470, height=220)

            if rendered_graphs == 0:
                elements.append(Paragraph("No se encontraron datos suficientes para construir gráficas en el informe.", styles['Normal']))

            if rendered_graphs % 3 != 0:
                elements.append(PageBreak())

            # --- 3. REGISTRO DE DATOS ---
            elements.append(Paragraph("3. Últimos Registros (Muestra)", h2_style))
            
            data_rows = [['ID', 'Fecha', 'Largo', 'Peso', 'Ancho']]
            sorted_records = sorted(
                records,
                key=lambda record: record.get('timestamp') or datetime.min,
                reverse=True,
            )[:40]

            for record in sorted_records:
                ts_value = record.get('timestamp')
                ts = ts_value.strftime('%Y-%m-%d') if ts_value else '-'
                data_rows.append([
                    str(record.get('fish_id') or '-'),
                    ts,
                    f"{float(record.get('length') or 0):.2f}",
                    f"{float(record.get('weight') or 0):.2f}",
                    f"{float(record.get('width') or 0):.2f}"
                ])

            t_rec = Table(data_rows, colWidths=[60, 90, 80, 80, 80])
            t_rec.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2980b9')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f2f2f2')]),
                ('GRID', (0,0), (-1,-1), 0.5, colors.grey)
            ]))
            elements.append(t_rec)

            # GENERAR
            doc.build(elements)
            
            # Limpieza
            try:
                shutil.rmtree(temp_plots_dir)
            except Exception as error:
                logger.debug("No se pudo limpiar carpeta temporal PDF: %s", error)

            QMessageBox.information(self, "Éxito", f"Informe PDF generado:\n{path}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error PDF:\n{e}")
            try:
                shutil.rmtree(temp_plots_dir)
            except Exception as error:
                logger.debug("No se pudo limpiar carpeta temporal PDF tras error: %s", error)
            
    def generate_statistics(self):
        """
        🚀 MOTOR ANALÍTICO: Procesa datos (priorizando manuales) y coordina el Dashboard.
        """
        if hasattr(self, 'stats_text'):
            self.stats_text.clear()
        if hasattr(self, 'gallery_list'):
            self.gallery_list.clear()
        
        measurements = self.db.get_filtered_measurements(limit=2000)
        
        if not measurements:
            if hasattr(self, 'stats_text'):
                self.stats_text.setHtml("<h3 style='color:#e74c3c; text-align:center;'>⚠️ No hay registros para analizar.</h3>")
            return

        self.current_stats_data = self._build_statistics_dataset(measurements)

        if not any([
            self.current_stats_data['lengths'],
            self.current_stats_data['weights'],
            self.current_stats_data['heights'],
            self.current_stats_data['widths'],
        ]):
            self.stats_text.setHtml("<h3 style='text-align:center;'>No hay mediciones válidas para construir estadísticas confiables.</h3>")
            if hasattr(self, 'status_bar'):
                self.status_bar.set_status("No hay mediciones válidas para estadísticas", "warning")
            return

        self.update_report_html() 
        self.generate_graphs()
        
        if hasattr(self, 'status_bar'):
            self.status_bar.set_status(f"Análisis de {len(measurements)} muestras completado", "success")
        
    def update_report_html(self):
        """Genera un reporte con diseño de Dashboard Corporativo"""
        if not hasattr(self, 'current_stats_data'): return

        d = self.current_stats_data
        style = self.report_style

        def summary_value(values, pattern, transform=None):
            if not values:
                return "-"
            raw_value = transform(values) if transform else values
            return pattern.format(raw_value)

        html = f"""
            <style>
            body {{
                font-family: 'Segoe UI', sans-serif;
                background-color: {style['bg']};
                color: {style['text']};
            }}

            .card {{
                border: 1px solid {style['border']};
                border-radius: 8px;
                padding: 15px;
                margin-bottom: 20px;
                background-color: {style['bg']};
            }}

            .title {{
                color: {style['header']};
                font-size: 18px;
                font-weight: bold;
                border-bottom: 2px solid {style['accent']};
                margin-bottom: 6px;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
            }}

            td {{
                padding: 8px;
                border-bottom: 1px solid {style['border']};
            }}

            tr.section td {{
                background-color: {style['row']};
                font-weight: bold;
            }}

            .val {{
                font-weight: bold;
                color: {style['val_color']};
                text-align: right;
            }}

            .badge {{
                background: {style['accent']};
                color: white;
                padding: 2px 8px;
                border-radius: 10px;
                font-size: 11px;
            }}
        </style>
        <div class='card'>
            <span class='badge'>REPORTE OFICIAL</span>
            <div class='title'>Dashboard de Trazabilidad Biométrica</div>
            <p style='font-size: 11px;'>Muestras procesadas: <b>{d['count']}</b> | Fecha: {datetime.now().strftime('%d/%m/%Y')}</p>
            
            <table>
                <tr class="section">
                    <td colspan="2">📏 Biometría Longitudinal (cm)</td>
                </tr>
                <tr><td>Promedio de Talla</td><td class='val'>{summary_value(d['lengths'], '{:.2f} cm', np.mean)}</td></tr>
                <tr><td>Desviación Estándar</td><td class='val'>{summary_value(d['lengths'], '±{:.2f}', np.std)}</td></tr>
                
                <tr class="section">
                    <td colspan="2">⚖️ Análisis de Masa (g)</td>
                </tr>
                <tr><td>Peso Promedio</td><td class='val'>{summary_value(d['weights'], '{:.2f} g', np.mean)}</td></tr>
                <tr><td>Biomasa Total Estimada</td><td class='val'>{summary_value(d['weights'], '{:.2f} kg', lambda values: np.sum(values) / 1000)}</td></tr>
                
                <tr class="section">
                    <td colspan="2">🧬 Morfometría Complementaria</td>
                </tr>
                <tr><td>Altura Promedio</td><td class='val'>{summary_value(d['heights'], '{:.2f} cm', np.mean)}</td></tr>
                <tr><td>Ancho Promedio</td><td class='val'>{summary_value(d['widths'], '{:.2f} cm', np.mean)}</td></tr>
                <tr><td>Factor K Promedio</td><td class='val'>{summary_value(d['k_factors'], '{:.3f}', np.mean)}</td></tr>
            </table>
        </div>
        """
        self.stats_text.setHtml(html)

    def generate_graphs(self):
        """
        🧬 PINTOR DE GRÁFICAS (INTELIGENTE CON PLAN B):
        - Intenta Gompertz (Modelo Biológico).
        - Si Gompertz falla o da resultados locos -> FALLBACK A LINEAL (Plan B).
        - Proyección a futuro segura.
        """

        data = getattr(self, 'current_stats_data', None)
        if not data or not data['records']:
            return

        plt.style.use('seaborn-v0_8-whitegrid')
        self.gallery_list.clear()

        # ----------------------------------------------------------------------
        # 1. AGRUPACIÓN SEMANAL
        # ----------------------------------------------------------------------
        weekly_weights = {}
        weekly_lengths = {}
        
        def get_monday(d):
            return d - timedelta(days=d.weekday())

        if data['dates_for_weights'] and data['weights']:
            for dt, w in zip(data['dates_for_weights'], data['weights']):
                monday = get_monday(dt.date())
                weekly_weights[monday] = weekly_weights.get(monday, []) + [w]

        if data['dates_for_lengths'] and data['lengths']:
            for dt, l in zip(data['dates_for_lengths'], data['lengths']):
                monday = get_monday(dt.date())
                weekly_lengths[monday] = weekly_lengths.get(monday, []) + [l]

        # ----------------------------------------------------------------------
        # 2. HELPER: FIGURE -> PIXMAP
        # ----------------------------------------------------------------------
        def fig_to_pixmap(figure):
            buf = io.BytesIO()
            figure.savefig(buf, format='png', dpi=300, bbox_inches='tight')
            buf.seek(0)
            qimg = QImage.fromData(buf.getvalue())
            plt.close(figure)
            return QPixmap.fromImage(qimg)

        # ----------------------------------------------------------------------
        # 3. HELPER MATEMÁTICO (GOMPERTZ -> LINEAL)
        # ----------------------------------------------------------------------
        def plot_bio_trend(ax, date_dict, color_line, label, unit):
            sorted_weeks = sorted(date_dict.keys())
            if not sorted_weeks:
                return
            
            sorted_dts = [datetime.combine(d, datetime.min.time()) for d in sorted_weeks]
            avg_vals = np.array([sum(date_dict[d])/len(date_dict[d]) for d in sorted_weeks])

            # Tiempo Relativo (Días 0, 7, 14...)
            start_date = sorted_dts[0]
            days_since_start = np.array([(d - start_date).days for d in sorted_dts])

            # Graficar Puntos Reales
            ax.plot(sorted_dts, avg_vals, 'o', color=color_line, markersize=7, alpha=0.8, label=f'{label} (Promedio)')

            # --- DEFINICIÓN DE MODELOS ---
            def model_gompertz(t, A, B, k):
                return A * np.exp(-np.exp(B - k * t))

            # Variables para el resultado
            last_day = days_since_start[-1]
            future_days = np.linspace(0, last_day + 45, 100) # Proyección 45 días
            y_trend = None
            model_used = ""

            # --- INTENTO 1: GOMPERTZ ---
            try:
                if len(avg_vals) >= 3:
                    max_val = max(avg_vals)
                    # Estimaciones iniciales
                    p0 = [max_val * 1.5, 1.0, 0.02]
                    bounds = ([max_val, -10, 0], [np.inf, 10, 1.0])
                    
                    params, _ = curve_fit(model_gompertz, days_since_start, avg_vals, p0=p0, bounds=bounds, maxfev=5000)
                    y_candidate = model_gompertz(future_days, *params)
                    
                    # CHEQUEO DE CORDURA (Sanity Check)
                    # Si predice que el peso se triplicará en 1 mes, es un error matemático.
                    prediction_last = y_candidate[-1]
                    if prediction_last > max_val * 3:
                        raise ValueError(f"Predicción exagerada ({prediction_last}), descartando Gompertz.")
                    
                    y_trend = y_candidate
                    model_used = "Gompertz"
                else:
                    raise ValueError("Pocos datos para Gompertz")

            except Exception as error:
                logger.debug("Gompertz descartado en galería para %s: %s", label, error)
                y_trend = None # Forzar fallback

            # --- INTENTO 2: PLAN B (LINEAL) ---
            if y_trend is None:
                try:
                    if len(avg_vals) >= 2:
                        # Ajuste Lineal (y = mx + b)
                        coeffs = np.polyfit(days_since_start, avg_vals, 1)
                        poly_eq = np.poly1d(coeffs)
                        y_trend = poly_eq(future_days)
                        model_used = "Lineal (Plan B)"
                except Exception as error:
                    logger.debug("Fallback lineal falló para %s: %s", label, error)

            # --- DIBUJAR ---
            if y_trend is not None:
                future_dates = [start_date + timedelta(days=d) for d in future_days]
                ax.plot(future_dates, y_trend, '--', color=color_line, linewidth=2, alpha=0.6, label=f'Tendencia {model_used}')
                
                final_val = y_trend[-1]
                final_date = future_dates[-1]
                
                # Evitar etiquetas infinitas
                if not np.isinf(final_val) and final_val < 100000:
                    ax.text(final_date, final_val, f"{final_val:.1f} {unit}", 
                            color=color_line, fontweight='bold', fontsize=9, ha='left')
                
                ax.set_xlim(sorted_dts[0] - timedelta(days=5), final_date + timedelta(days=7))

            # Estética Eje X
            ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%b'))
            self._apply_stats_axis_style(ax, ax.get_title(), ax.get_xlabel(), ax.get_ylabel())
            ax.grid(True, axis='x', linestyle=':', alpha=0.5)

        # ----------------------------------------------------------------------
        # 4. GENERACIÓN DE GRÁFICAS
        # ----------------------------------------------------------------------

        # Tallas
        try:
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.hist(data['lengths'], bins=10, color='#3498db', alpha=0.7, edgecolor='black')
            if data['lengths']:
                ax.axvline(np.mean(data['lengths']), color='#1f3a5f', linestyle='--', linewidth=1.5, label=f"Prom: {np.mean(data['lengths']):.2f} cm")
                ax.legend()
            self._apply_stats_axis_style(ax, "Distribución de Tallas", "Longitud (cm)", "Frecuencia")
            self._add_to_gallery("📏 Distribución Tallas", fig_to_pixmap(fig), "length")
        except Exception as error:
            self._stats_log_graph_error("Distribución Tallas", error)

        # Pesos
        try:
            if data['weights']:
                fig, ax = plt.subplots(figsize=(8, 5))
                ax.hist(data['weights'], bins=10, color='#2ecc71', alpha=0.7, edgecolor='black')
                ax.axvline(np.mean(data['weights']), color='#145a32', linestyle='--', linewidth=1.5, label=f"Prom: {np.mean(data['weights']):.2f} g")
                ax.legend()
                self._apply_stats_axis_style(ax, "Distribución de Biomasa", "Peso (g)", "Frecuencia")
                self._add_to_gallery("⚖️ Distribución Peso", fig_to_pixmap(fig), "weight")
        except Exception as error:
            self._stats_log_graph_error("Distribución Peso", error)

        # Morfometría combinada (altura y ancho)
        try:
            if data['heights'] or data['widths']:
                fig, ax = plt.subplots(figsize=(8.8, 4.8))
                has_any = False
                if data['heights']:
                    ax.hist(data['heights'], bins=10, color='#3498db', alpha=0.45, edgecolor='black', label='Altura')
                    has_any = True
                if data['widths']:
                    ax.hist(data['widths'], bins=10, color='#f39c12', alpha=0.45, edgecolor='black', label='Ancho')
                    has_any = True

                if has_any:
                    self._apply_stats_axis_style(ax, "Morfometría Combinada", "Medida (cm)", "Frecuencia")
                    ax.legend()
                    self._add_to_gallery("🧬 Morfometría (H/W)", fig_to_pixmap(fig), "morphometry")
                else:
                    plt.close(fig)
        except Exception as error:
            self._stats_log_graph_error("Morfometría (H/W)", error)

        # Curva Peso
        try:
            if weekly_weights:
                fig, ax = plt.subplots(figsize=(11, 5))
                plot_bio_trend(ax, weekly_weights, '#9b59b6', 'Peso', 'g')
                self._apply_stats_axis_style(ax, "Proyección de Crecimiento (Peso)", "Semana de muestreo", "Peso (g)")
                ax.legend()
                fig.autofmt_xdate(rotation=45, ha='right')
                self._add_to_gallery("⏱ Crecimiento Peso", fig_to_pixmap(fig), "timeline_weight")
        except Exception as error:
            self._stats_log_graph_error("Crecimiento Peso", error)

        # Curva Longitud
        try:
            if weekly_lengths:
                fig, ax = plt.subplots(figsize=(11, 5))
                plot_bio_trend(ax, weekly_lengths, '#e67e22', 'Longitud', 'cm')
                self._apply_stats_axis_style(ax, "Proyección de Crecimiento (Longitud)", "Semana de muestreo", "Longitud (cm)")
                ax.legend()
                fig.autofmt_xdate(rotation=45, ha='right')
                self._add_to_gallery("📏 Crecimiento Talla", fig_to_pixmap(fig), "timeline_length")
        except Exception as error:
            self._stats_log_graph_error("Crecimiento Talla", error)

        # Scatter
        try:
            if data['pairs']:
                fig, ax = plt.subplots(figsize=(8, 5))
                scatter_lengths = [pair[0] for pair in data['pairs']]
                scatter_weights = [pair[1] for pair in data['pairs']]
                ax.scatter(scatter_lengths, scatter_weights, c='#e74c3c', alpha=0.6, edgecolors='black', linewidths=0.4)
                self._apply_stats_axis_style(ax, "Relación Longitud / Peso", "Longitud (cm)", "Peso (g)")
                self._add_to_gallery("📈 Salud (L vs P)", fig_to_pixmap(fig), "correlation")
        except Exception as error:
            self._stats_log_graph_error("Relación Longitud/Peso", error)

        # Factor K del lote
        try:
            if data['k_factors']:
                fig, ax = plt.subplots(figsize=(8, 5))
                ax.hist(data['k_factors'], bins=10, color='#16a085', alpha=0.75, edgecolor='black')
                ax.axvspan(1.0, 1.4, color='#2ecc71', alpha=0.15, label='Zona óptima')
                ax.axvline(np.mean(data['k_factors']), color='#0b5345', linestyle='--', linewidth=1.5, label=f"Prom: {np.mean(data['k_factors']):.3f}")
                self._apply_stats_axis_style(ax, "Factor K del Lote", "Factor de condición K", "Frecuencia")
                ax.legend()
                self._add_to_gallery("🧬 Factor K del Lote", fig_to_pixmap(fig), "k_factor")
        except Exception as error:
            self._stats_log_graph_error("Factor K del Lote", error)

        # Perfil corporal altura vs ancho
        try:
            body_records = [record for record in data['records'] if record.get('height', 0) > 0 and record.get('width', 0) > 0]
            if body_records:
                fig, ax = plt.subplots(figsize=(8, 5))
                body_heights = [record['height'] for record in body_records]
                body_widths = [record['width'] for record in body_records]
                ax.scatter(body_widths, body_heights, c='#af7ac5', alpha=0.65, edgecolors='black', linewidths=0.4)
                if len(body_widths) >= 2:
                    coeffs = np.polyfit(body_widths, body_heights, 1)
                    trend_x = np.linspace(min(body_widths), max(body_widths), 60)
                    trend_y = np.poly1d(coeffs)(trend_x)
                    ax.plot(trend_x, trend_y, '--', color='#5b2c6f', linewidth=1.4, label='Tendencia')
                self._apply_stats_axis_style(ax, "Perfil Corporal del Lote", "Ancho dorsal (cm)", "Altura corporal (cm)")
                if ax.get_legend_handles_labels()[0]:
                    ax.legend()
                self._add_to_gallery("📐 Perfil Corporal", fig_to_pixmap(fig), "body_profile")
        except Exception as error:
            self._stats_log_graph_error("Perfil Corporal", error)

        # Variabilidad del lote
        try:
            metric_map = {
                'Longitud': data['lengths'],
                'Peso': data['weights'],
                'Altura': data['heights'],
                'Ancho': data['widths'],
            }
            labels = []
            cvs = []
            for label, values in metric_map.items():
                if len(values) >= 2 and np.mean(values) > 0:
                    labels.append(label)
                    cvs.append((np.std(values) / np.mean(values)) * 100)

            if labels:
                fig, ax = plt.subplots(figsize=(8.8, 4.8))
                colors_bar = ['#3498db', '#2ecc71', '#1abc9c', '#f1c40f'][:len(labels)]
                bars = ax.bar(labels, cvs, color=colors_bar, edgecolor='black', alpha=0.8)
                for bar, value in zip(bars, cvs):
                    ax.text(bar.get_x() + bar.get_width() / 2, value + 0.4, f"{value:.1f}%", ha='center', va='bottom', fontsize=9, fontweight='bold')
                self._apply_stats_axis_style(ax, "Variabilidad del Lote", "Indicador biométrico", "Coeficiente de variación (%)")
                self._add_to_gallery("📦 Variabilidad del Lote", fig_to_pixmap(fig), "variability")
        except Exception as error:
            self._stats_log_graph_error("Variabilidad del Lote", error)

        # Intensidad de muestreo semanal
        try:
            weekly_counts = self._build_weekly_metric_map(data['records'], 'length')
            if weekly_counts:
                fig, ax = plt.subplots(figsize=(10, 4.8))
                weeks = sorted(weekly_counts.keys())
                labels = [datetime.combine(week, datetime.min.time()) for week in weeks]
                counts = [len(weekly_counts[week]) for week in weeks]
                ax.bar(labels, counts, color='#5dade2', edgecolor='#1b4f72', width=5)
                self._apply_stats_axis_style(ax, "Intensidad de Muestreo Semanal", "Semana", "Número de mediciones")
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%b'))
                fig.autofmt_xdate(rotation=45, ha='right')
                self._add_to_gallery("📅 Muestreo Semanal", fig_to_pixmap(fig), "sampling_weekly")
        except Exception as error:
            self._stats_log_graph_error("Muestreo Semanal", error)

        # Clases de talla
        try:
            if data['lengths']:
                fig, ax = plt.subplots(figsize=(9, 4.8))
                class_bins = min(7, max(4, int(np.sqrt(len(data['lengths'])))))
                counts, bins = np.histogram(data['lengths'], bins=class_bins)
                class_labels = [f"{bins[i]:.1f}-{bins[i + 1]:.1f}" for i in range(len(counts))]
                bars = ax.bar(class_labels, counts, color='#2471a3', alpha=0.85, edgecolor='black')
                for bar, value in zip(bars, counts):
                    ax.text(bar.get_x() + bar.get_width() / 2, value + 0.2, str(int(value)), ha='center', va='bottom', fontsize=9, fontweight='bold')
                self._apply_stats_axis_style(ax, "Clases de Talla del Lote", "Rango de longitud (cm)", "Cantidad")
                ax.tick_params(axis='x', rotation=25)
                self._add_to_gallery("📊 Clases de Talla", fig_to_pixmap(fig), "size_classes")
        except Exception as error:
            self._stats_log_graph_error("Clases de Talla", error)

        # Tendencia semanal del factor K
        try:
            weekly_k = {}
            for record in data['records']:
                length_value = float(record.get('length') or 0)
                weight_value = float(record.get('weight') or 0)
                ts_value = record.get('timestamp')
                if length_value <= 0 or weight_value <= 0 or ts_value is None:
                    continue

                k_value = (100 * weight_value) / (length_value ** 3)
                monday = ts_value.date() - timedelta(days=ts_value.date().weekday())
                weekly_k.setdefault(monday, []).append(k_value)

            if weekly_k:
                fig, ax = plt.subplots(figsize=(10, 4.8))
                weeks = sorted(weekly_k.keys())
                week_dates = [datetime.combine(week, datetime.min.time()) for week in weeks]
                avg_k = [float(np.mean(weekly_k[week])) for week in weeks]
                ax.plot(week_dates, avg_k, 'o-', color='#117864', linewidth=2, markersize=6, label='K semanal')
                ax.axhspan(1.0, 1.4, color='#2ecc71', alpha=0.12, label='Zona óptima')
                self._apply_stats_axis_style(ax, "Tendencia Semanal Factor K", "Semana", "Factor de condición K")
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%b'))
                fig.autofmt_xdate(rotation=45, ha='right')
                ax.legend()
                self._add_to_gallery("🫀 Tendencia Factor K", fig_to_pixmap(fig), "condition_trend")
        except Exception as error:
            self._stats_log_graph_error("Tendencia Factor K", error)

    def _add_to_gallery(self, title, pixmap, graph_key=None):
        """Añade un gráfico a la galería usando un QPixmap en memoria."""
        item = QListWidgetItem(title)
        icon = QIcon(pixmap)
        item.setIcon(icon)
        item.setSizeHint(QSize(220, 190))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setToolTip(self._build_stats_graph_tooltip(graph_key))
        
        # Guardamos el Pixmap entero en la memoria del ítem
        item.setData(Qt.ItemDataRole.UserRole, pixmap)
        item.setData(Qt.ItemDataRole.UserRole + 1, graph_key)
        
        self.gallery_list.addItem(item)

    def open_enlarged_graph(self, item):
        """Abre el visor usando el QPixmap almacenado en memoria."""
        pixmap = item.data(Qt.ItemDataRole.UserRole)
        title = item.text()
        
        if not pixmap or pixmap.isNull():
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Visualización: {title}")
        dialog.setMinimumSize(900, 650) 
        
        layout = QVBoxLayout(dialog)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        
        lbl_image = QLabel()
        lbl_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        scroll_area.setWidget(lbl_image)
        layout.addWidget(scroll_area)

        btn_close = QPushButton("Cerrar")
        btn_close.setProperty("class", "warning") 
        btn_close.style().unpolish(btn_close)
        btn_close.style().polish(btn_close)
        btn_close.setToolTip("Cerrar el visor de imágenes.")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)

        base_resize_event = dialog.resizeEvent

        def _refresh_preview():
            self._set_scaled_graph_preview(lbl_image, pixmap, scroll_area)

        def _on_resize(event):
            base_resize_event(event)
            _refresh_preview()

        dialog.resizeEvent = _on_resize
        QTimer.singleShot(0, _refresh_preview)
        
        dialog.exec()
    
    def save_config(self):
        if not self._validate_settings_ranges(show_message=True):
            return

        Config.CAM_LEFT_INDEX = self.spin_cam_left.value()
        Config.CAM_TOP_INDEX = self.spin_cam_top.value()
        Config.MIN_CONTOUR_AREA = self.spin_min_area.value()
        Config.MAX_CONTOUR_AREA = self.spin_max_area.value()
        Config.CONFIDENCE_THRESHOLD = self.spin_confidence.value()
        Config.MIN_LENGTH_CM = self.spin_min_length.value()
        Config.MAX_LENGTH_CM = self.spin_max_length.value()

        # 2. Preparar Diccionarios para JSON y BD
        hsv_left = {
            'h_min': self.spin_hue_min_lat.value(), 'h_max': self.spin_hue_max_lat.value(),
            's_min': self.spin_sat_min_lat.value(), 's_max': self.spin_sat_max_lat.value(),
            'v_min': self.spin_val_min_lat.value(), 'v_max': self.spin_val_max_lat.value()
        }
        
        hsv_top = {
            'h_min': self.spin_hue_min_top.value(), 'h_max': self.spin_hue_max_top.value(),
            's_min': self.spin_sat_min_top.value(), 's_max': self.spin_sat_max_top.value(),
            'v_min': self.spin_val_min_top.value(), 'v_max': self.spin_val_max_top.value()
        }

        config_data = {
            'cam_left_index': Config.CAM_LEFT_INDEX,
            'cam_top_index': Config.CAM_TOP_INDEX,
            'min_contour_area': Config.MIN_CONTOUR_AREA,
            'max_contour_area': Config.MAX_CONTOUR_AREA,
            'confidence_threshold': Config.CONFIDENCE_THRESHOLD,
            'min_length_cm': Config.MIN_LENGTH_CM,
            'max_length_cm': Config.MAX_LENGTH_CM,
            'scale_front_left': self.scale_front_left,
            'scale_back_left': self.scale_back_left,
            'scale_front_top': self.scale_front_top,
            'scale_back_top': self.scale_back_top,
            'sensor_env_ranges': {
                'temp_agua': [self.sensor_env_ranges['temp_agua'][0], self.sensor_env_ranges['temp_agua'][1]],
                'ph': [self.sensor_env_ranges['ph'][0], self.sensor_env_ranges['ph'][1]],
                'cond': [self.sensor_env_ranges['cond'][0], self.sensor_env_ranges['cond'][1]],
                'turb': [self.sensor_env_ranges['turb'][0], self.sensor_env_ranges['turb'][1]],
                'do': [self.sensor_env_ranges['do'][0], self.sensor_env_ranges['do'][1]],
            },
            'quick_notes': self.quick_notes,
            'hsv_left': hsv_left,  
            'hsv_top': hsv_top
        }
        
        # Guardar en BD
        self.db.save_calibration(
            scale_lat_front=self.scale_front_left,
            scale_lat_back=self.scale_back_left,
            scale_top_front=self.scale_front_top,
            scale_top_back=self.scale_back_top,
            hsv_left=hsv_left,
            hsv_top=hsv_top,
            notes="Guardado desde GUI principal"
        )
        
        try:
            with open(Config.CONFIG_FILE, 'w') as f:
                json.dump(config_data, f, indent=4)
            
            self.status_bar.set_status("Configuración guardada en disco y BD", "success")
            self._set_settings_dirty(False)
            QMessageBox.information(self, "Éxito", "Configuración y Calibración guardadas correctamente.")
        except Exception as e:
            logger.error(f"Error escribiendo config.json: {e}")

    def load_config(self):
        """Carga la configuración siguiendo la jerarquía: Config.py -> config.json -> Base de Datos"""
        
        # 1. Valores Base (Config.py)
        self._load_base_values()

        # 2. Sobrescribir con config.json (Preferencias locales)
        if os.path.exists(Config.CONFIG_FILE):
            try:
                with open(Config.CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    self._parse_json_config(data)
                logger.info("Configuracion cargada desde JSON.")
            except Exception as e:
                logger.error(f"Error en JSON: {e}")

        # 3. Sobrescribir con lo ÚLTIMO de la Base de Datos (Calibración más reciente)
        try:
            last_calib = self.db.get_latest_calibration()
            if last_calib:
                self._parse_db_calibration(last_calib)
                logger.info("Calibracion final sincronizada con la Base de Datos.")
        except Exception as e:
            logger.warning(f"No se pudo acceder a la BD para calibración: {e}")

    def _load_base_values(self):
        """Inicializa las variables internas con valores seguros de Config.py"""
        # Escalas base
        self.scale_front_left = getattr(Config, 'SCALE_LAT_FRONT', 0.006666)
        self.scale_back_left  = getattr(Config, 'SCALE_LAT_BACK', 0.014926)
        self.scale_front_top  = getattr(Config, 'SCALE_TOP_FRONT', 0.004348)
        self.scale_back_top   = getattr(Config, 'SCALE_TOP_BACK', 0.012582)
        
        # HSV Lateral Base
        self.hsv_left_h_min = getattr(Config, 'HSV_H_MIN', 35)
        self.hsv_left_h_max = getattr(Config, 'HSV_H_MAX', 85)
        self.hsv_left_s_min = getattr(Config, 'HSV_S_MIN', 40)
        self.hsv_left_s_max = getattr(Config, 'HSV_S_MAX', 255)
        self.hsv_left_v_min = getattr(Config, 'HSV_V_MIN', 40)
        self.hsv_left_v_max = getattr(Config, 'HSV_V_MAX', 255)
        
        # HSV Cenital Base (Copiamos los mismos por defecto)
        self.hsv_top_h_min, self.hsv_top_h_max = self.hsv_left_h_min, self.hsv_left_h_max
        self.hsv_top_s_min, self.hsv_top_s_max = self.hsv_left_s_min, self.hsv_left_s_max
        self.hsv_top_v_min, self.hsv_top_v_max = self.hsv_left_v_min, self.hsv_left_v_max
        
        logger.info("Valores base inicializados desde memoria.")
        
    def sync_ui_with_config(self):
        """
        Sincroniza los widgets de la interfaz con las variables cargadas.
        Se debe llamar SOLO DESPUÉS de initUI().
        """
        logger.info("Sincronizando widgets con la configuracion...")
        self._settings_change_guard = True
        
        # Agrupamos widgets para bloquear sus señales temporalmente
        widgets_to_sync = [
            self.spin_cam_left, self.spin_cam_top,
            self.spin_min_area, self.spin_max_area,
            self.spin_confidence, self.spin_min_length, self.spin_max_length,
            self.spin_scale_front_left, self.spin_scale_back_left,
            self.spin_scale_front_top, self.spin_scale_back_top,
            self.spin_hue_min_lat, self.spin_hue_max_lat,
            self.spin_sat_min_lat, self.spin_sat_max_lat,
            self.spin_val_min_lat, self.spin_val_max_lat,
            self.spin_hue_min_top, self.spin_hue_max_top,
            self.spin_sat_min_top, self.spin_sat_max_top,
            self.spin_val_min_top, self.spin_val_max_top,
            self.spin_env_temp_min, self.spin_env_temp_max,
            self.spin_env_ph_min, self.spin_env_ph_max,
            self.spin_env_cond_min, self.spin_env_cond_max,
            self.spin_env_turb_min, self.spin_env_turb_max,
            self.spin_env_do_min, self.spin_env_do_max,
        ]

        for w in widgets_to_sync:
            w.blockSignals(True)

        try:
            # --- Configuración General ---
            self.spin_cam_left.setValue(Config.CAM_LEFT_INDEX)
            self.spin_cam_top.setValue(Config.CAM_TOP_INDEX)
            self.spin_min_area.setValue(Config.MIN_CONTOUR_AREA)
            self.spin_max_area.setValue(Config.MAX_CONTOUR_AREA)
            self.spin_confidence.setValue(Config.CONFIDENCE_THRESHOLD)
            self.spin_min_length.setValue(Config.MIN_LENGTH_CM)
            self.spin_max_length.setValue(Config.MAX_LENGTH_CM)

            # --- Escalas de Fotogrametría ---
            self.spin_scale_front_left.setValue(self.scale_front_left)
            self.spin_scale_back_left.setValue(self.scale_back_left)
            self.spin_scale_front_top.setValue(self.scale_front_top)
            self.spin_scale_back_top.setValue(self.scale_back_top)

            # --- Chroma Key Lateral ---
            self.spin_hue_min_lat.setValue(self.hsv_left_h_min)
            self.spin_hue_max_lat.setValue(self.hsv_left_h_max)
            self.spin_sat_min_lat.setValue(self.hsv_left_s_min)
            self.spin_sat_max_lat.setValue(self.hsv_left_s_max)
            self.spin_val_min_lat.setValue(self.hsv_left_v_min)
            self.spin_val_max_lat.setValue(self.hsv_left_v_max)

            # --- Chroma Key Cenital ---
            self.spin_hue_min_top.setValue(self.hsv_top_h_min)
            self.spin_hue_max_top.setValue(self.hsv_top_h_max)
            self.spin_sat_min_top.setValue(self.hsv_top_s_min)
            self.spin_sat_max_top.setValue(self.hsv_top_s_max)
            self.spin_val_min_top.setValue(self.hsv_top_v_min)
            self.spin_val_max_top.setValue(self.hsv_top_v_max)

            # --- Rangos de Alertas Ambientales ---
            self.spin_env_temp_min.setValue(self.sensor_env_ranges["temp_agua"][0])
            self.spin_env_temp_max.setValue(self.sensor_env_ranges["temp_agua"][1])
            self.spin_env_ph_min.setValue(self.sensor_env_ranges["ph"][0])
            self.spin_env_ph_max.setValue(self.sensor_env_ranges["ph"][1])
            self.spin_env_cond_min.setValue(self.sensor_env_ranges["cond"][0])
            self.spin_env_cond_max.setValue(self.sensor_env_ranges["cond"][1])
            self.spin_env_turb_min.setValue(self.sensor_env_ranges["turb"][0])
            self.spin_env_turb_max.setValue(self.sensor_env_ranges["turb"][1])
            self.spin_env_do_min.setValue(self.sensor_env_ranges["do"][0])
            self.spin_env_do_max.setValue(self.sensor_env_ranges["do"][1])

            self._apply_sensor_ranges_from_ui()
            self._refresh_quick_note_combos()

            self.status_bar.set_status("Interfaz sincronizada con éxito", "success")
            self._set_settings_dirty(False)

        except Exception as e:
            logger.error(f"Error sincronizando UI: {e}")
        
        finally:
            # Desbloquear señales para que el usuario pueda interactuar
            for w in widgets_to_sync:
                w.blockSignals(False)   
            self._settings_change_guard = False

    def _parse_json_config(self, data):
        """Mapea el JSON plano a las variables de la instancia"""
        try:
            # 1. Configuración de Cámaras e IA
            Config.CAM_LEFT_INDEX = data.get('cam_left_index', Config.CAM_LEFT_INDEX)
            Config.CAM_TOP_INDEX = data.get('cam_top_index', Config.CAM_TOP_INDEX)
            Config.MIN_CONTOUR_AREA = data.get('min_contour_area', Config.MIN_CONTOUR_AREA)
            Config.MAX_CONTOUR_AREA = data.get('max_contour_area', Config.MAX_CONTOUR_AREA)
            Config.CONFIDENCE_THRESHOLD = data.get('confidence_threshold', Config.CONFIDENCE_THRESHOLD)
            Config.MIN_LENGTH_CM = data.get('min_length_cm', Config.MIN_LENGTH_CM)
            Config.MAX_LENGTH_CM = data.get('max_length_cm', Config.MAX_LENGTH_CM)

            # 2. Escalas Fotogramétricas
            self.scale_front_left = data.get('scale_front_left', self.scale_front_left)
            self.scale_back_left = data.get('scale_back_left', self.scale_back_left)
            self.scale_front_top = data.get('scale_front_top', self.scale_front_top)
            self.scale_back_top = data.get('scale_back_top', self.scale_back_top)

            # 3. HSV (Se aplica a ambos por defecto si el JSON es plano)
            if 'hsv_left' in data:
                h = data['hsv_left']
                self.hsv_left_h_min = h.get('h_min', 35)
                self.hsv_left_h_max = h.get('h_max', 85)
                self.hsv_left_s_min = h.get('s_min', 40)
                self.hsv_left_s_max = h.get('s_max', 255)
                self.hsv_left_v_min = h.get('v_min', 40)
                self.hsv_left_v_max = h.get('v_max', 255)

            # 4. HSV DUAL (Cenital)
            if 'hsv_top' in data:
                h = data['hsv_top']
                self.hsv_top_h_min = h.get('h_min', 35)
                self.hsv_top_h_max = h.get('h_max', 85)
                self.hsv_top_s_min = h.get('s_min', 40)
                self.hsv_top_s_max = h.get('s_max', 255)
                self.hsv_top_v_min = h.get('v_min', 40)
                self.hsv_top_v_max = h.get('v_max', 255)

            # 5. Rangos de alerta ambiental para SensorTopBar
            if 'sensor_env_ranges' in data and isinstance(data['sensor_env_ranges'], dict):
                env = data['sensor_env_ranges']
                for key in ("temp_agua", "ph", "cond", "turb", "do"):
                    pair = env.get(key)
                    if isinstance(pair, (list, tuple)) and len(pair) == 2:
                        self.sensor_env_ranges[key] = (float(pair[0]), float(pair[1]))

            # 6. Notas rápidas reutilizables
            raw_notes = data.get('quick_notes')
            if isinstance(raw_notes, list):
                parsed_notes = []
                for note in raw_notes:
                    clean = self._normalize_note_text(note)
                    if clean and clean.lower() not in [n.lower() for n in parsed_notes]:
                        parsed_notes.append(clean)
                if parsed_notes:
                    self.quick_notes = parsed_notes[:25]
            
        except Exception as e:
            logger.error(f"Error parseando JSON: {e}")                
                       
    def _parse_db_calibration(self, calib):
        """Mapea la fila de la BD a las variables de la instancia (Dual-Chroma)"""
        if not calib: return

        try:
            # 1. Escalas (Directo de las columnas de la tabla)
            self.scale_front_left = calib.get('scale_lat_front', self.scale_front_left)
            self.scale_back_left = calib.get('scale_lat_back', self.scale_back_left)
            self.scale_front_top = calib.get('scale_top_front', self.scale_front_top)
            self.scale_back_top = calib.get('scale_top_back', self.scale_back_top)

            # 2. HSV Lateral (Si los guardaste como diccionarios/objetos en la BD)
            if 'hsv_left' in calib and isinstance(calib['hsv_left'], dict):
                h = calib['hsv_left']
                self.hsv_left_h_min = h.get('h_min', self.hsv_left_h_min)
                self.hsv_left_h_max = h.get('h_max', self.hsv_left_h_max)
                self.hsv_left_s_min = h.get('s_min', self.hsv_left_s_min)
                self.hsv_left_s_max = h.get('s_max', self.hsv_left_s_max)
                self.hsv_left_v_min = h.get('v_min', self.hsv_left_v_min)
                self.hsv_left_v_max = h.get('v_max', self.hsv_left_v_max)

            # 3. HSV Cenital
            if 'hsv_top' in calib and isinstance(calib['hsv_top'], dict):
                h = calib['hsv_top']
                self.hsv_top_h_min = h.get('h_min', self.hsv_top_h_min)
                self.hsv_top_h_max = h.get('h_max', self.hsv_top_h_max)
                self.hsv_top_s_min = h.get('s_min', self.hsv_top_s_min)
                self.hsv_top_s_max = h.get('s_max', self.hsv_top_s_max)
                self.hsv_top_v_min = h.get('v_min', self.hsv_top_v_min)
                self.hsv_top_v_max = h.get('v_max', self.hsv_top_v_max)

        except Exception as e:
            logger.error(f"Error parseando Calibración de BD: {e}")
            
    def open_fine_tune_calibration(self):
        """
        CALIBRACIÓN INDEPENDIENTE POR CÁMARA CON VISTA PREVIA SEGURA
        """
        left_ready = bool(self.cap_left and hasattr(self.cap_left, "isOpened") and self.cap_left.isOpened())
        top_ready = bool(self.cap_top and hasattr(self.cap_top, "isOpened") and self.cap_top.isOpened())

        if not (left_ready and top_ready):
            self._set_fine_tune_enabled(False)
            self._update_settings_camera_indicator(False, "Calibrador bloqueado")
            QMessageBox.warning(self, "Error", "Cámaras no disponibles para calibración en vivo")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Calibración Chroma Key en Vivo")
        dialog.setMinimumSize(1400, 900)
        layout = QVBoxLayout(dialog)

        was_main_timer_active = bool(hasattr(self, 'timer') and self.timer.isActive())
        if was_main_timer_active:
            self.timer.stop()

        # 1. Cargar valores temporales (clonados de la configuración actual)
        self.temp_hsv_left = {
            'h_min': getattr(self, 'hsv_left_h_min', self.spin_hue_min_lat.value()),
            'h_max': getattr(self, 'hsv_left_h_max', self.spin_hue_max_lat.value()),
            's_min': getattr(self, 'hsv_left_s_min', self.spin_sat_min_lat.value()),
            's_max': getattr(self, 'hsv_left_s_max', self.spin_sat_max_lat.value()),
            'v_min': getattr(self, 'hsv_left_v_min', self.spin_val_min_lat.value()),
            'v_max': getattr(self, 'hsv_left_v_max', self.spin_val_max_lat.value())
        }
        
        self.temp_hsv_top = {
            'h_min': getattr(self, 'hsv_top_h_min', self.spin_hue_min_top.value()),
            'h_max': getattr(self, 'hsv_top_h_max', self.spin_hue_max_top.value()),
            's_min': getattr(self, 'hsv_top_s_min', self.spin_sat_min_top.value()),
            's_max': getattr(self, 'hsv_top_s_max', self.spin_sat_max_top.value()),
            'v_min': getattr(self, 'hsv_top_v_min', self.spin_val_min_top.value()),
            'v_max': getattr(self, 'hsv_top_v_max', self.spin_val_max_top.value())
        }

        # 2. Interfaz de Video
        grid_layout = QGridLayout()
        
        def create_video_block(title):
            lbl_title = QLabel(f"<b>{title}</b>")
            lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            raw = QLabel()
            raw.setFixedSize(650, 380)
            raw.setStyleSheet("background-color: black; border: 2px solid #333;")
            raw.setCursor(Qt.CursorShape.CrossCursor)
            mask = QLabel()
            mask.setFixedSize(650, 380)
            mask.setStyleSheet("background-color: black; border: 2px solid #333;")
            return lbl_title, raw, mask

        t1, lbl_left_raw, lbl_left_mask = create_video_block("Cámara Lateral (Click para capturar color)")
        t2, lbl_top_raw, lbl_top_mask = create_video_block("Cámara Cenital (Click para capturar color)")

        grid_layout.addWidget(t1, 0, 0)
        grid_layout.addWidget(lbl_left_raw, 1, 0)
        grid_layout.addWidget(QLabel("Máscara Lateral"), 2, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid_layout.addWidget(lbl_left_mask, 3, 0)

        grid_layout.addWidget(t2, 0, 1)
        grid_layout.addWidget(lbl_top_raw, 1, 1)
        grid_layout.addWidget(QLabel("Máscara Cenital"), 2, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        grid_layout.addWidget(lbl_top_mask, 3, 1)

        layout.addLayout(grid_layout)

        # 3. Lógica de captura de color al hacer click
        def capture_color(event, is_lateral=True):
            frame = self.current_frame_left if is_lateral else self.current_frame_top
            if frame is None: return
            
            # Mapeo de coordenadas del click al tamaño real del frame
            x = int(event.pos().x() * frame.shape[1] / 650)
            y = int(event.pos().y() * frame.shape[0] / 380)
            
            if 0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]:
                pixel_hsv = cv2.cvtColor(np.uint8([[frame[y, x]]]), cv2.COLOR_BGR2HSV)[0][0]
                target = self.temp_hsv_left if is_lateral else self.temp_hsv_top
                
                # Ajuste automático de rango alrededor del pixel tocado
                target['h_min'] = max(0, int(pixel_hsv[0]) - 12)
                target['h_max'] = min(179, int(pixel_hsv[0]) + 12)
                target['s_min'] = max(30, int(pixel_hsv[1]) - 50)
                target['v_min'] = max(30, int(pixel_hsv[2]) - 50)
                target['s_max'] = 255
                target['v_max'] = 255
                
                self.status_bar.set_status(f"Color capturado en {'Lateral' if is_lateral else 'Cenital'}", "info")

        lbl_left_raw.mousePressEvent = lambda e: capture_color(e, True)
        lbl_top_raw.mousePressEvent = lambda e: capture_color(e, False)
        
        # 4. Timer de actualización (Uso de display_frame estándar)
        timer = QTimer(dialog)
        
        def update_preview():
            # Procesar Cámara Lateral
            if self.cap_left and self.cap_left.isOpened():
                ret, frame = self.cap_left.read()
                if ret:
                    self.current_frame_left = frame.copy()
                    # Aplicar máscara con valores temporales
                    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                    lower = np.array([self.temp_hsv_left['h_min'], self.temp_hsv_left['s_min'], self.temp_hsv_left['v_min']])
                    upper = np.array([self.temp_hsv_left['h_max'], self.temp_hsv_left['s_max'], self.temp_hsv_left['v_max']])
                    mask = cv2.bitwise_not(cv2.inRange(hsv, lower, upper))
                    
                    self.display_frame(frame, lbl_left_raw)
                    self.display_frame(mask, lbl_left_mask, is_mask=True)

            # Procesar Cámara Cenital
            if self.cap_top and self.cap_top.isOpened():
                ret, frame = self.cap_top.read()
                if ret:
                    self.current_frame_top = frame.copy()
                    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                    lower = np.array([self.temp_hsv_top['h_min'], self.temp_hsv_top['s_min'], self.temp_hsv_top['v_min']])
                    upper = np.array([self.temp_hsv_top['h_max'], self.temp_hsv_top['s_max'], self.temp_hsv_top['v_max']])
                    mask = cv2.bitwise_not(cv2.inRange(hsv, lower, upper))
                    
                    self.display_frame(frame, lbl_top_raw)
                    self.display_frame(mask, lbl_top_mask, is_mask=True)

        timer.timeout.connect(update_preview)
        timer.start(120) 
        
        dialog.finished.connect(timer.stop)

        btns = QHBoxLayout()
        
        btn_reset = QPushButton("Restaurar Fábrica")
        btn_reset.setProperty("class", "warning")
        btn_reset.setToolTip("Cancelar la calibración actual.")
        btn_reset.clicked.connect(lambda: reset_values())
        
        def reset_values():
            default = {'h_min': 35, 'h_max': 85, 's_min': 40, 's_max': 255, 'v_min': 40, 'v_max': 255}
            self.temp_hsv_left = default.copy()
            self.temp_hsv_top = default.copy()
            self.status_bar.set_status("Valores reseteados", "info")

        btn_save = QPushButton("Guardar y Aplicar")
        btn_save.setProperty("class", "success")
        btn_save.setToolTip("Guardar los datos actuales en la base de datos.")
        btn_save.setMinimumHeight(40)
        btn_save.clicked.connect(lambda: save_and_close())

        def save_and_close():
            # Sincronizar con variables globales de la clase
            # Lateral
            self.hsv_left_h_min = self.temp_hsv_left['h_min']
            self.hsv_left_h_max = self.temp_hsv_left['h_max']
            self.hsv_left_s_min = self.temp_hsv_left['s_min']
            self.hsv_left_s_max = self.temp_hsv_left['s_max']
            self.hsv_left_v_min = self.temp_hsv_left['v_min']
            self.hsv_left_v_max = self.temp_hsv_left['v_max']
            # Cenital
            self.hsv_top_h_min = self.temp_hsv_top['h_min']
            self.hsv_top_h_max = self.temp_hsv_top['h_max']
            self.hsv_top_s_min = self.temp_hsv_top['s_min']
            self.hsv_top_s_max = self.temp_hsv_top['s_max']
            self.hsv_top_v_min = self.temp_hsv_top['v_min']
            self.hsv_top_v_max = self.temp_hsv_top['v_max']

            # Actualizar SpinBoxes de la UI principal
            if hasattr(self, 'sync_ui_with_config'):
                self.sync_ui_with_config()
            
            self.save_config() 
            
            timer.stop()
            dialog.accept()
            self.status_bar.set_status("Calibración dual aplicada", "success")

        btns.addWidget(btn_reset)
        btns.addStretch()
        btns.addWidget(btn_save)
        layout.addLayout(btns)

        dialog.exec()

        if was_main_timer_active and self.cameras_connected and hasattr(self, 'timer'):
            fps_ms = int(1000 / max(1, Config.PREVIEW_FPS))
            self.timer.start(fps_ms)
        
    def init_tray(self):
        """Configura el icono en la barra de tareas (junto al reloj)."""
        self.tray_icon = QSystemTrayIcon(self)
        self.normal_icon = QIcon("logo.ico")
        
        # Usar el estilo global de la app para asegurar la carga del icono nativo
        self.error_icon = QApplication.style().standardIcon(QStyle.SP_MessageBoxWarning) 
        
        self.is_alert_icon = False # Asegurar que la variable existe
        self.tray_icon.setIcon(self.normal_icon)
        self.tray_icon.show()
        
        # Menú del icono de bandeja
        tray_menu = QMenu()
        show_action = QAction("Abrir FishTrace", self)
        quit_action = QAction("Cerrar Completamente", self)
        
        show_action.triggered.connect(self.showNormal)
        quit_action.triggered.connect(self.force_quit)
        
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.showNormal()

    def closeEvent(self, event):
        """Intercepta el clic en la X y aplica el tema de FishTrace."""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("FishTrace - Opciones de Salida")
        msg_box.setText("¿Qué desea hacer con el sistema?")
        # Agregamos un texto informativo para que el cuadro sea más ancho y no corte botones
        msg_box.setInformativeText("La API y el monitoreo requieren seguir activos.")
        
        # Creamos los botones
        btn_hide = msg_box.addButton("Seguir transmitiendo", QMessageBox.ActionRole)
        btn_quit = msg_box.addButton("Cerrar completamente", QMessageBox.DestructiveRole)
        btn_cancel = msg_box.addButton("Cancelar", QMessageBox.RejectRole)
        
        # --- ARREGLO DE ESTILO Y TAMAÑO ---
        # 1. Forzamos un tamaño mínimo para que el texto no se amontone
        msg_box.setStyleSheet(f"""
            QLabel {{ min-width: 400px; color: {self.report_style['text']}; }}
            QPushButton {{ 
                padding: 8px 16px; 
                font-weight: bold; 
                border-radius: 4px; 
                min-width: 120px;
            }}
        """)
        
        # 2. Aplicamos tus colores técnicos manualmente a cada botón
        # Usamos los colores que ya definiste en toggle_theme
        is_dark = self.is_currently_dark
        bg_primary = "#00b4d8" if is_dark else "#0077b6"
        bg_error = "#e74c3c"
        
        btn_hide.setStyleSheet(f"background-color: {bg_primary}; color: white; border: none;")
        btn_quit.setStyleSheet(f"background-color: {bg_error}; color: white; border: none;")
        # ----------------------------------

        msg_box.exec()
        
        if msg_box.clickedButton() == btn_hide:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "FishTrace Activo",
                "El motor de IA sigue funcionando en segundo plano.",
                QSystemTrayIcon.Information, 3000
            )
        elif msg_box.clickedButton() == btn_quit:
            event.accept()
        else:
            event.ignore()

    def force_quit(self):
        """Cierre total desde el menú de la bandeja."""
        self.api_service.stop()
        QApplication.quit()
        
    def toggle_alert_icon(self):
        """Alterna entre el logo normal y el icono de error."""
        if self.is_alert_icon:
            self.tray_icon.setIcon(self.normal_icon)
        else:
            self.tray_icon.setIcon(self.error_icon)
        
        self.is_alert_icon = not self.is_alert_icon
          
    def check_api_health_for_tray(self):
        """Monitorea el estado y activa parpadeo si no hay conexión pública."""
        is_ok = False
        
        if hasattr(self, 'api_service') and self.api_service:
            # Obtenemos el estado real del servicio
            _, state, url = self.api_service.get_status_info()
            
            # Consideramos 'Sano' solo si el estado es success y existe una URL de ngrok
            if state == "success" and url is not None:
                is_ok = True

        # SI NO ESTÁ OK -> Iniciar parpadeo
        if not is_ok:
            if not self.alert_timer.isActive():
                logger.warning("API Offline o sin Túnel. Iniciando parpadeo de alerta.")
                self.alert_timer.start(600) # Velocidad del parpadeo
        else:
            # SI ESTÁ OK -> Detener parpadeo y restaurar logo
            if self.alert_timer.isActive():
                self.alert_timer.stop()
                self.tray_icon.setIcon(self.normal_icon)