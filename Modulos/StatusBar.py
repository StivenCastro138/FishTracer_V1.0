"""
PROYECTO: FishTrace - Trazabilidad de Crecimiento de Peces
MÓDULO: Barra de Estado y Telemetría (StatusBar.py)
DESCRIPCIÓN: Widget personalizado que reside en la parte inferior de la ventana principal.
            Proporciona monitoreo en tiempo real de los recursos del sistema (CPU, RAM, GPU)
            y métricas de rendimiento de la aplicación (FPS, Latencia de Inferencia).
"""

import time
import os
import psutil
import logging
from collections import deque
from typing import Optional, Final, Dict, Any
import qtawesome as qta  
from PySide6.QtWidgets import QWidget, QHBoxLayout, QFrame, QPushButton, QApplication
from PySide6.QtCore import Slot, QTimer, Qt
from PySide6.QtGui import QCloseEvent

try:
    import pynvml 
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning, module="pynvml")
except ImportError:
    pynvml = None

logger = logging.getLogger(__name__)

class StatusBar(QWidget):
    
    HELP_TEXTS: Final[Dict[str, str]] = {
        "status": "Estado global del sistema.",
        "ia": "Latencia de inferencia por frame.",
        "fps": "Frames por segundo.",
        "cpu": "Uso total del procesador.",    
        "ram": "Uso de memoria RAM del proceso actual.",
        "gpu": "Uso de núcleos de procesamiento gráfico.", 
        "vram": "Uso de memoria de video.",
        "measurements": "Contador de mediciones validadas.",
        "cameras": "Estado de conexión de los sensores.",
        "api": "Estado de la API Cloud. Haz clic para copiar la URL pública."
    }

    UPDATE_INTERVAL_HW: Final[float] = 1.0

    CPU_WARN:         Final[int]   = 60
    CPU_ERROR:        Final[int]   = 85
    FPS_ERROR:        Final[float] = 15.0
    IA_ERROR_MS:      Final[float] = 3000.0
    GPU_ERROR_PCT:    Final[int]   = 90
    GPU_MAX_FAILURES: Final[int]   = 3
    SMOOTH_SAMPLES:   Final[int]   = 5

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._current_api_url = None
        self._last_hw_update: float = 0.0
        self._process: psutil.Process = psutil.Process(os.getpid())
        self._gpu_handle: Any = None
        self._nvml_initialized: bool = False
        self._gpu_fail_count: int = 0
        self._fps_buffer: deque = deque(maxlen=self.SMOOTH_SAMPLES)
        self._ia_buffer:  deque = deque(maxlen=self.SMOOTH_SAMPLES)
        self.theme_colors: Dict[str, str] = {}

        psutil.cpu_percent(interval=None)

        self.setFixedHeight(35)
        self._init_hardware_monitors()
        self.init_ui()
        
        self.timer_hw = QTimer(self)
        self.timer_hw.timeout.connect(self.update_system_info)
        self.timer_hw.start(1000)

    def _init_hardware_monitors(self) -> None:
        if pynvml:
            try:
                pynvml.nvmlInit()
                self._gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                self._nvml_initialized = True
            except Exception as e:
                logger.info(f"NVML no disponible: {e}.")
                self._gpu_handle = None

    def init_ui(self) -> None:
        self.layout_main = QHBoxLayout(self) 
        self.layout_main.setContentsMargins(15, 0, 15, 0)
        self.layout_main.setSpacing(10)
        self.setObjectName("StatusBar")
        
        # 1. Estado Global
        self.btn_status = self._create_metric("Iniciando...", "fa5s.info-circle", self.HELP_TEXTS["status"], "info")
        self.layout_main.addWidget(self.btn_status)
        self.layout_main.addStretch() 
        
        # API 
        self.btn_api = self._create_metric("API: --", "fa5s.globe", self.HELP_TEXTS["api"], "dim")
        self.btn_api.setProperty("interactive", True)
        self.btn_api.setCursor(Qt.PointingHandCursor)
        self.btn_api.clicked.connect(self._on_api_clicked)

        # 2. Telemetría
        self.btn_ia = self._create_metric("IA: -- ms", "fa5s.microchip", self.HELP_TEXTS["ia"], "info")
        self.btn_fps = self._create_metric("FPS: 0.0", "fa5s.film", self.HELP_TEXTS["fps"], "normal")
        
        # CPU / RAM
        self.btn_cpu = self._create_metric("CPU: 0%", "fa5s.server", self.HELP_TEXTS["cpu"], "dim")
        self.btn_ram = self._create_metric("RAM: -- MB", "fa5s.memory", self.HELP_TEXTS["ram"], "dim")
        
        # GPU 
        self.btn_gpu = self._create_metric("GPU: 0%", "fa5s.layer-group", self.HELP_TEXTS["gpu"], "accent") 
        self.btn_vram = self._create_metric("VRAM: -- MB", "fa5s.hdd", self.HELP_TEXTS["vram"], "accent")
        
        # Sensores
        self.btn_measurements = self._create_metric("Hoy: 0", "fa5s.ruler-horizontal", self.HELP_TEXTS["measurements"], "warning")
        self.btn_cameras = self._create_metric("--", "fa5s.video", self.HELP_TEXTS["cameras"], "normal")

        widgets_telemetry = [
            self.btn_ia, self.btn_fps, 
            self.btn_cpu, self.btn_ram,   
            self.btn_gpu, self.btn_vram,
            self.btn_measurements, self.btn_cameras,
            self.btn_api
        ]

        for i, w in enumerate(widgets_telemetry):
            if (w == self.btn_vram or w == self.btn_gpu) and not self._gpu_handle:
                w.hide()
            else:
                self.layout_main.addWidget(w)
                if i < len(widgets_telemetry) - 1:
                     line = QFrame()
                     line.setFrameShape(QFrame.Shape.VLine)
                     line.setObjectName("StatusSeparator") 
                     self.layout_main.addWidget(line)

    def _create_metric(self, text: str, icon_name: str, tooltip: str, initial_state: str) -> QPushButton:
        """Crea un botón plano configurado para parecer una etiqueta con icono"""
        btn = QPushButton(text)
        btn.setToolTip(tooltip)
        btn.setFlat(True)
        btn.setProperty("icon_name", icon_name)
        btn.setProperty("state", initial_state)
        # Icono con color neutro de fallback: no queda vacío antes del primer tema
        btn.setIcon(qta.icon(icon_name, color="#7f8c8d"))
        return btn

    def update_theme_colors(self, palette: Dict[str, str]):
        """
        Actualiza el diccionario de colores y repinta todos los iconos.
        """
        self.theme_colors = palette
        for btn in self.findChildren(QPushButton):
            self._refresh_icon_color(btn)

    def _refresh_icon_color(self, btn: QPushButton):
        """Genera el icono nuevamente con el color correcto según el estado actual"""
        state = btn.property("state")
        icon_name = btn.property("icon_name")
        
        if not icon_name: return

        hex_color = self.theme_colors.get(state, "#7f8c8d")
        
        btn.setIcon(qta.icon(icon_name, color=hex_color))

    def _update_btn_state(self, btn: QPushButton, new_state: str):
        """Cambia el estado lógico, actualiza el estilo CSS y el color del icono"""
        if btn.property("state") != new_state:
            btn.setProperty("state", new_state)
            
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            
            self._refresh_icon_color(btn)

    @Slot(str, str)
    def set_status(self, message: str, state: str = "info"):
        clean = message.lstrip("●").strip()
        self.btn_status.setText(clean)
        self._update_btn_state(self.btn_status, state)

    @Slot(float)
    def set_ia_time(self, ms: float):
        self._ia_buffer.append(ms)
        smooth = sum(self._ia_buffer) / len(self._ia_buffer)
        self.btn_ia.setText(f"IA: {smooth:.1f} ms")
        state = "error" if smooth > self.IA_ERROR_MS else "info"
        self._update_btn_state(self.btn_ia, state)

    @Slot(int)
    def set_measurement_count(self, count: int):
        self.btn_measurements.setText(f"Hoy: {count}")

    @Slot(bool)
    def set_camera_status(self, ok: bool):
        if ok:
            self.btn_cameras.setText("OK")
            self._update_btn_state(self.btn_cameras, "success") 
        else:
            self.btn_cameras.setText("ERROR")
            self._update_btn_state(self.btn_cameras, "error")   

    @Slot(float)
    def update_system_info(self, fps: Optional[float] = None):
        current_time = time.time()

        # 1. Actualizar FPS con media móvil
        if fps is not None:
            self._fps_buffer.append(fps)
            smooth_fps = sum(self._fps_buffer) / len(self._fps_buffer)
            self.btn_fps.setText(f"FPS: {smooth_fps:.1f}")
            state = "error" if smooth_fps < self.FPS_ERROR else "normal"
            self._update_btn_state(self.btn_fps, state)

        # 2. Refresco Hardware
        if current_time - self._last_hw_update >= self.UPDATE_INTERVAL_HW:
            self._update_cpu_stats()
            self._update_gpu_stats()
            self._last_hw_update = current_time
            
    @Slot(str, str, object)
    def update_api_status(self, text: str, state: str, url: Optional[str]):
        self.btn_api.setText(f"API: {text}")
        self._current_api_url = url
        self._update_btn_state(self.btn_api, state)

    def _on_api_clicked(self):
        if self._current_api_url:
            if "localhost" in self._current_api_url:
                self.set_status("URL Local copiada", "warning")
            else:
                self.set_status("URL Global copiada", "success")
            QApplication.clipboard().setText(self._current_api_url)
        else:
            self.set_status("API no disponible", "error")
            
    def _update_cpu_stats(self) -> None:
        try:
            cpu = psutil.cpu_percent(interval=None)
            self.btn_cpu.setText(f"CPU: {int(cpu)}%")
            if cpu > self.CPU_ERROR:
                self._update_btn_state(self.btn_cpu, "error")
            elif cpu > self.CPU_WARN:
                self._update_btn_state(self.btn_cpu, "warning")
            else:
                self._update_btn_state(self.btn_cpu, "dim")

            mem = self._process.memory_info().rss / 1024**2
            self.btn_ram.setText(f"RAM: {int(mem)} MB")
        except Exception as e:
            logger.warning(f"Error leyendo CPU/RAM: {e}")
            self._set_metric_unavailable(self.btn_cpu, "CPU")
            self._set_metric_unavailable(self.btn_ram, "RAM")

    def _update_gpu_stats(self) -> None:
        if not self._gpu_handle:
            return
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(self._gpu_handle)
            self.btn_gpu.setText(f"GPU: {util.gpu}%")
            if util.gpu > self.GPU_ERROR_PCT:
                self._update_btn_state(self.btn_gpu, "warning")
            else:
                self._update_btn_state(self.btn_gpu, "accent")

            mem = pynvml.nvmlDeviceGetMemoryInfo(self._gpu_handle).used / 1024**2
            self.btn_vram.setText(f"VRAM: {int(mem)} MB")
            self._gpu_fail_count = 0
        except Exception as e:
            self._gpu_fail_count += 1
            logger.warning(f"Error leyendo GPU (fallo #{self._gpu_fail_count}): {e}")
            if self._gpu_fail_count >= self.GPU_MAX_FAILURES:
                logger.error("Monitor GPU desactivado por fallos consecutivos. Llama a retry_gpu_monitor().")
                self._gpu_handle = None
                self._set_metric_unavailable(self.btn_gpu, "GPU")
                self._set_metric_unavailable(self.btn_vram, "VRAM")

    def closeEvent(self, event: QCloseEvent):
        self.timer_hw.stop()
        if self._nvml_initialized:
            try:
                pynvml.nvmlShutdown()
            except Exception as e:
                logger.warning(f"Error al cerrar NVML: {e}")
        event.accept()

    def _set_metric_unavailable(self, btn: QPushButton, label: str) -> None:
        """Marca una métrica como no disponible de forma visual y uniforme."""
        btn.setText(f"{label}: N/A")
        self._update_btn_state(btn, "dim")

    def reset_metrics(self) -> None:
        """Devuelve todos los indicadores a su estado neutro inicial.
        Útil al reiniciar sesión, cambiar modo o desconectar cámaras.
        """
        self.btn_fps.setText("FPS: --")
        self._update_btn_state(self.btn_fps, "normal")
        self.btn_ia.setText("IA: -- ms")
        self._update_btn_state(self.btn_ia, "info")
        self.btn_cpu.setText("CPU: --%")
        self._update_btn_state(self.btn_cpu, "dim")
        self.btn_ram.setText("RAM: -- MB")
        self._update_btn_state(self.btn_ram, "dim")
        self.btn_gpu.setText("GPU: --%")
        self._update_btn_state(self.btn_gpu, "accent")
        self.btn_vram.setText("VRAM: -- MB")
        self._update_btn_state(self.btn_vram, "accent")
        self.btn_cameras.setText("--")
        self._update_btn_state(self.btn_cameras, "normal")
        self.btn_api.setText("API: --")
        self._current_api_url = None
        self._update_btn_state(self.btn_api, "dim")
        self._fps_buffer.clear()
        self._ia_buffer.clear()

    def retry_gpu_monitor(self) -> bool:
        """Reintenta inicializar NVML manualmente sin reiniciar la app.
        Devuelve True si el monitor GPU vuelve a estar activo.
        """
        if not pynvml:
            logger.info("pynvml no instalado; retry_gpu_monitor no tiene efecto.")
            return False
        try:
            pynvml.nvmlInit()
            self._gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._nvml_initialized = True
            self._gpu_fail_count = 0
            logger.info("Monitor GPU reiniciado correctamente.")
            self.set_status("Monitor GPU reconectado", "success")
            return True
        except Exception as e:
            logger.warning(f"retry_gpu_monitor falló: {e}")
            self.set_status("GPU aún no disponible", "warning")
            return False