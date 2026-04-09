from typing import Dict, Any

import qtawesome as qta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton


class SensorTopBar(QWidget):
    """Barra compacta para mostrar variables ambientales junto a las pestañas."""

    FIXED_FONT_SIZE = 10
    FIXED_MIN_HEIGHT = 35
    FIXED_SPACING = 8
    FIXED_PADDING = "0px 5px"

    HELP_TEXTS = {
        "temp_agua": "Temperatura del agua en °C.",
        "ph": "Nivel de acidez/alcalinidad del agua (pH).",
        "cond": "Conductividad eléctrica del agua en µS/cm.",
        "turb": "Turbidez del agua en NTU.",
        "do": "Oxígeno disuelto en mg/L.",
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SensorTopBar")
        self.theme_colors: Dict[str, str] = {}
        self._blink_phase: bool = False
        self._latest_values: Dict[str, Any] = {}
        self._alert_flags: Dict[str, bool] = {
            "temp_agua": False,
            "ph": False,
            "cond": False,
            "turb": False,
            "do": False,
        }
        self.ranges: Dict[str, tuple[float, float]] = {
            "temp_agua": (18.0, 32.0),
            "ph": (6.5, 8.5),
            "cond": (100.0, 2000.0),
            "turb": (0.0, 100.0),
            "do": (4.0, 14.0),
        }

        self.layout_main = QHBoxLayout(self)
        self.layout_main.setContentsMargins(6, 2, 6, 2)
        self.layout_main.setSpacing(8)

        self.lbl_temp_agua = self._create_metric("Agua --°C", "fa5s.thermometer-half", "info")
        self.lbl_ph = self._create_metric("pH --", "fa5s.flask", "accent")
        self.lbl_cond = self._create_metric("Cond --", "fa5s.bolt", "warning")
        self.lbl_turb = self._create_metric("Turb --", "fa5s.tint", "dim")
        self.lbl_do = self._create_metric("O₂ --", "fa5s.wind", "success")

        self.layout_main.addWidget(self.lbl_temp_agua)
        self.layout_main.addWidget(self.lbl_ph)
        self.layout_main.addWidget(self.lbl_cond)
        self.layout_main.addWidget(self.lbl_turb)
        self.layout_main.addWidget(self.lbl_do)

        self.btn_tablet = QPushButton("Táctil")
        self.btn_tablet.setCheckable(True)
        self.btn_tablet.setCursor(Qt.PointingHandCursor)
        self.btn_tablet.setToolTip("Activa una interfaz más cómoda para uso táctil.")
        self.btn_tablet.setProperty("icon_name", "fa5s.tablet-alt")
        self.btn_tablet.setProperty("state", "info")
        self._refresh_icon_color(self.btn_tablet)
        self.set_visual_density()

        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self._update_blink_phase)
        self.blink_timer.start(550)

    def _create_metric(self, text: str, icon_name: str, state: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFlat(True)
        btn.setEnabled(True)
        btn.setCursor(Qt.ArrowCursor)
        btn.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setStyleSheet("text-align: left; padding: 2px 6px;")
        btn.setProperty("icon_name", icon_name)
        btn.setProperty("state", state)
        self._refresh_icon_color(btn)
        return btn

    def _refresh_icon_color(self, btn: QPushButton) -> None:
        state = btn.property("state")
        icon_name = btn.property("icon_name")
        if not icon_name:
            return
        hex_color = self.theme_colors.get(state, "#7f8c8d")
        btn.setIcon(qta.icon(icon_name, color=hex_color))

    def _update_btn_state(self, btn: QPushButton, new_state: str) -> None:
        if btn.property("state") != new_state:
            btn.setProperty("state", new_state)
            self._refresh_icon_color(btn)

    def _format_range(self, key: str) -> str:
        low, high = self.ranges[key]
        unit = {
            "temp_agua": "°C",
            "ph": "",
            "cond": "µS/cm",
            "turb": "NTU",
            "do": "mg/L",
        }[key]
        suffix = f" {unit}" if unit else ""
        return f"Rango recomendado: {low:g} - {high:g}{suffix}"

    def _set_metric_tooltip(self, key: str, btn: QPushButton, value: float | None) -> None:
        base = self.HELP_TEXTS[key]
        range_text = self._format_range(key)
        if value is None:
            btn.setToolTip(f"{base}\n{range_text}\nValor actual: --")
        else:
            btn.setToolTip(f"{base}\n{range_text}\nValor actual: {value:.2f}")

    def _is_out_of_range(self, key: str, value: float | None) -> bool:
        if value is None:
            return False
        low, high = self.ranges[key]
        return value < low or value > high

    def _apply_metric_state(self, key: str, btn: QPushButton, nominal_state: str) -> None:
        if self._alert_flags.get(key, False):
            self._update_btn_state(btn, "error" if self._blink_phase else "dim")
        else:
            self._update_btn_state(btn, nominal_state)

    def _update_blink_phase(self) -> None:
        self._blink_phase = not self._blink_phase
        self._apply_metric_state("temp_agua", self.lbl_temp_agua, "info")
        self._apply_metric_state("ph", self.lbl_ph, "accent")
        self._apply_metric_state("cond", self.lbl_cond, "warning")
        self._apply_metric_state("turb", self.lbl_turb, "dim")
        self._apply_metric_state("do", self.lbl_do, "success")

    def update_theme_colors(self, palette: Dict[str, str]) -> None:
        """Actualiza colores de iconos según el tema activo."""
        self.theme_colors = palette
        self._apply_metric_state("temp_agua", self.lbl_temp_agua, "info")
        self._apply_metric_state("ph", self.lbl_ph, "accent")
        self._apply_metric_state("cond", self.lbl_cond, "warning")
        self._apply_metric_state("turb", self.lbl_turb, "dim")
        self._apply_metric_state("do", self.lbl_do, "success")
        self._refresh_icon_color(self.btn_tablet)

    def set_ranges(self, ranges: Dict[str, tuple[float, float]]) -> None:
        """Actualiza rangos de alerta por variable y refresca tooltips/estados."""
        self.ranges.update(ranges or {})
        self._alert_flags["temp_agua"] = self._is_out_of_range("temp_agua", self._latest_values.get("temp_agua"))
        self._alert_flags["ph"] = self._is_out_of_range("ph", self._latest_values.get("ph"))
        self._alert_flags["cond"] = self._is_out_of_range("cond", self._latest_values.get("cond"))
        self._alert_flags["turb"] = self._is_out_of_range("turb", self._latest_values.get("turb"))
        self._alert_flags["do"] = self._is_out_of_range("do", self._latest_values.get("do"))
        self._set_metric_tooltip("temp_agua", self.lbl_temp_agua, self._latest_values.get("temp_agua"))
        self._set_metric_tooltip("ph", self.lbl_ph, self._latest_values.get("ph"))
        self._set_metric_tooltip("cond", self.lbl_cond, self._latest_values.get("cond"))
        self._set_metric_tooltip("turb", self.lbl_turb, self._latest_values.get("turb"))
        self._set_metric_tooltip("do", self.lbl_do, self._latest_values.get("do"))
        self._update_blink_phase()

    @staticmethod
    def _as_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def update_values(self, data: Dict[str, Any]) -> None:
        t_agua = None
        ph = None
        cond = None
        turb = None
        od = None

        if not data:
            self.lbl_temp_agua.setText("Agua --°C")
            self.lbl_ph.setText("pH --")
            self.lbl_cond.setText("Cond --")
            self.lbl_turb.setText("Turb --")
            self.lbl_do.setText("O₂ --")
        else:
            t_agua = self._as_float(data.get("api_water_temp_c"))
            ph = self._as_float(data.get("api_ph"))
            cond = self._as_float(data.get("api_cond_us_cm"))
            turb = self._as_float(data.get("api_turbidity_ntu"))
            od = self._as_float(data.get("api_do_mg_l"))

            self.lbl_temp_agua.setText(f"Agua {t_agua:.1f}°C" if t_agua is not None else "Agua --°C")
            self.lbl_ph.setText(f"pH {ph:.2f}" if ph is not None else "pH --")
            self.lbl_cond.setText(f"Cond {int(cond)}" if cond is not None else "Cond --")
            self.lbl_turb.setText(f"Turb {turb:.1f}" if turb is not None else "Turb --")
            self.lbl_do.setText(f"O₂ {od:.1f}" if od is not None else "O₂ --")

        self._latest_values = {
            "temp_agua": t_agua,
            "ph": ph,
            "cond": cond,
            "turb": turb,
            "do": od,
        }

        self._alert_flags["temp_agua"] = self._is_out_of_range("temp_agua", t_agua)
        self._alert_flags["ph"] = self._is_out_of_range("ph", ph)
        self._alert_flags["cond"] = self._is_out_of_range("cond", cond)
        self._alert_flags["turb"] = self._is_out_of_range("turb", turb)
        self._alert_flags["do"] = self._is_out_of_range("do", od)

        self._set_metric_tooltip("temp_agua", self.lbl_temp_agua, t_agua)
        self._set_metric_tooltip("ph", self.lbl_ph, ph)
        self._set_metric_tooltip("cond", self.lbl_cond, cond)
        self._set_metric_tooltip("turb", self.lbl_turb, turb)
        self._set_metric_tooltip("do", self.lbl_do, od)

        self._update_blink_phase()

    def set_tablet_mode(self, enabled: bool) -> None:
        self.btn_tablet.setChecked(enabled)
        self.btn_tablet.setText("Táctil ON" if enabled else "Táctil")

    def set_visual_density(self, font_size: int | None = None, density: str | None = None) -> None:
        """Mantiene densidad fija; el modo táctil no modifica esta barra."""
        _ = density
        _ = font_size
        effective_font = self.FIXED_FONT_SIZE

        self.setMinimumHeight(self.FIXED_MIN_HEIGHT)
        self.layout_main.setSpacing(self.FIXED_SPACING)

        style = f"text-align: left; padding: {self.FIXED_PADDING}; font-size: {effective_font}px;"
        for btn in (self.lbl_temp_agua, self.lbl_ph, self.lbl_cond, self.lbl_turb, self.lbl_do):
            btn.setStyleSheet(style)

        self.btn_tablet.setMinimumHeight(self.FIXED_MIN_HEIGHT - 6)
        self.btn_tablet.setStyleSheet(f"padding: {self.FIXED_PADDING}; font-size: {effective_font}px;")
