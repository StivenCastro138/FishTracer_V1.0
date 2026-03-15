"""
PROYECTO: FishTrace - Trazabilidad de Crecimiento de Peces
MÓDULO: Pasarela de Captura Móvil (Mobile Gateway)
DESCRIPCIÓN: Servidor web ligero (Flask) que expone una interfaz HTML5 responsiva
             para permitir la captura remota de imágenes desde dispositivos móviles
             en la misma red local (LAN).

INTEGRACIÓN: Actúa como un servicio secundario que alimenta la cola de procesamiento
             de la aplicación principal.
"""

from flask import Flask, jsonify, make_response, render_template_string, request
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
from queue import Full, Queue
import logging
import os
import secrets
import socket
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

from Config.Config import Config

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURACIÓN DE FLASK
# ============================================================================

flask_app = Flask(__name__)

MAX_UPLOAD_MB = 16
flask_app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

MAX_NOTES_LENGTH = 240
MAX_FIELD_LENGTH = 32
MIN_IMAGE_WIDTH = 320
MIN_IMAGE_HEIGHT = 240
MAX_IMAGE_AGE_SECONDS = 3600
STATUS_POLL_MS = 4000
MOBILE_TOKEN_COOKIE = "fishtrace_mobile_token"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
ALLOWED_MIME_PREFIXES = ("image/",)
MEASUREMENT_LIMITS = {
    "peso": (0.0, 100000.0),
    "longitud": (0.0, 300.0),
    "ancho": (0.0, 150.0),
    "alto": (0.0, 150.0),
}

# Cola thread-safe para comunicación con la app principal
mobile_capture_queue = Queue(maxsize=10)

# Token temporal usado por la URL del QR
_mobile_access_token = os.getenv("FISHTRACE_MOBILE_TOKEN") or secrets.token_urlsafe(24)
_mobile_access_token_issued_at = time.time()

# Dimensiones objetivo para el collage
TARGET_HEIGHT = Config.TARGET_HEIGHT
TARGET_QUALITY = Config.TARGET_QUALITY

MOBILE_PAGE_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>FishTrace Movil</title>
    <style>
        :root {
            --primary: #0ea5a4;
            --primary-dark: #0b7d7c;
            --bg: #0f172a;
            --panel: rgba(15, 23, 42, 0.88);
            --panel-soft: rgba(30, 41, 59, 0.88);
            --text: #e2e8f0;
            --muted: #94a3b8;
            --border: rgba(148, 163, 184, 0.24);
            --shadow: 0 18px 50px rgba(2, 6, 23, 0.35);
        }

        * { box-sizing: border-box; }

        body {
            margin: 0;
            min-height: 100vh;
            color: var(--text);
            font-family: "Segoe UI", "SF Pro Text", sans-serif;
            background:
                radial-gradient(circle at top, rgba(14, 165, 164, 0.18), transparent 36%),
                linear-gradient(180deg, #020617 0%, #0f172a 52%, #111827 100%);
        }

        .shell {
            width: min(760px, 100%);
            margin: 0 auto;
            padding: 18px 16px 36px;
        }

        .hero {
            background: linear-gradient(145deg, rgba(14, 165, 164, 0.28), rgba(15, 23, 42, 0.96));
            border: 1px solid rgba(94, 234, 212, 0.2);
            border-radius: 24px;
            padding: 22px 20px;
            box-shadow: var(--shadow);
            backdrop-filter: blur(12px);
        }

        h1 {
            margin: 0 0 8px;
            font-size: 1.8rem;
            letter-spacing: 0.02em;
        }

        .subtitle {
            margin: 0;
            color: var(--muted);
            line-height: 1.5;
        }

        .panel {
            margin-top: 16px;
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 22px;
            padding: 18px;
            box-shadow: var(--shadow);
            backdrop-filter: blur(12px);
        }

        .panel h2 {
            margin: 0 0 12px;
            font-size: 1rem;
            letter-spacing: 0.01em;
        }

        .status-card {
            display: grid;
            gap: 8px;
            background: rgba(30, 41, 59, 0.88);
        }

        .status-row {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            color: var(--muted);
            font-size: 0.95rem;
        }

        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            border-radius: 999px;
            font-weight: 600;
            width: fit-content;
        }

        .status-pill.info { background: rgba(56, 189, 248, 0.16); color: #bae6fd; }
        .status-pill.success { background: rgba(34, 197, 94, 0.16); color: #bbf7d0; }
        .status-pill.warning { background: rgba(245, 158, 11, 0.16); color: #fde68a; }
        .status-pill.error { background: rgba(239, 68, 68, 0.18); color: #fecaca; }

        .drop-grid {
            display: grid;
            gap: 14px;
        }

        .photo-slot {
            background: rgba(30, 41, 59, 0.88);
            border: 1px dashed rgba(148, 163, 184, 0.35);
            border-radius: 20px;
            padding: 16px;
        }

        .slot-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
        }

        .slot-title {
            font-weight: 700;
        }

        .slot-title small {
            display: block;
            margin-top: 4px;
            color: var(--muted);
            font-weight: 400;
        }

        .preview-wrap {
            position: relative;
            display: none;
            margin-top: 12px;
        }

        .preview {
            width: 100%;
            max-height: 240px;
            object-fit: contain;
            border-radius: 16px;
            background: rgba(15, 23, 42, 0.92);
            border: 1px solid rgba(148, 163, 184, 0.2);
        }

        .preview-meta {
            margin-top: 8px;
            color: var(--muted);
            font-size: 0.9rem;
        }

        .button,
        .ghost-button,
        #btnSend {
            appearance: none;
            border: none;
            border-radius: 14px;
            padding: 14px 16px;
            font-weight: 700;
            font-size: 1rem;
        }

        .button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            background: linear-gradient(135deg, var(--primary), var(--primary-dark));
            color: white;
        }

        .ghost-button {
            background: rgba(148, 163, 184, 0.12);
            color: var(--text);
            min-width: 140px;
        }

        .ghost-button:disabled,
        .button:disabled,
        #btnSend:disabled {
            opacity: 0.55;
        }

        .measurements-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
        }

        .field.full { grid-column: 1 / -1; }

        label {
            display: block;
            margin-bottom: 6px;
            color: #99f6e4;
            font-size: 0.82rem;
            letter-spacing: 0.02em;
            font-weight: 700;
            text-transform: uppercase;
        }

        input,
        textarea {
            width: 100%;
            background: rgba(15, 23, 42, 0.92);
            border: 1px solid rgba(148, 163, 184, 0.25);
            color: var(--text);
            padding: 13px 14px;
            border-radius: 14px;
            font-size: 1rem;
        }

        textarea {
            min-height: 96px;
            resize: vertical;
        }

        input:focus,
        textarea:focus {
            outline: 2px solid rgba(45, 212, 191, 0.35);
            border-color: rgba(45, 212, 191, 0.5);
        }

        .help {
            margin-top: 6px;
            color: var(--muted);
            font-size: 0.88rem;
        }

        .message-box {
            display: none;
            margin-top: 16px;
            padding: 14px 16px;
            border-radius: 16px;
            border: 1px solid transparent;
            line-height: 1.5;
        }

        .message-box.info { display: block; background: rgba(56, 189, 248, 0.12); border-color: rgba(56, 189, 248, 0.24); }
        .message-box.success { display: block; background: rgba(34, 197, 94, 0.14); border-color: rgba(34, 197, 94, 0.24); }
        .message-box.warning { display: block; background: rgba(245, 158, 11, 0.14); border-color: rgba(245, 158, 11, 0.24); }
        .message-box.error { display: block; background: rgba(239, 68, 68, 0.14); border-color: rgba(239, 68, 68, 0.24); }

        .history-list {
            margin: 12px 0 0;
            padding-left: 18px;
            color: var(--muted);
        }

        .footer-actions {
            position: sticky;
            bottom: 12px;
            margin-top: 18px;
        }

        #btnSend {
            width: 100%;
            background: linear-gradient(135deg, #22c55e, #15803d);
            color: white;
            box-shadow: 0 18px 40px rgba(21, 128, 61, 0.28);
        }

        @media (max-width: 640px) {
            .measurements-grid { grid-template-columns: 1fr; }
            .field.full { grid-column: auto; }
            .shell { padding-inline: 12px; }
        }
    </style>
</head>
<body>
    <main class="shell">
        <section class="hero">
            <h1>Captura FishTrace</h1>
            <p class="subtitle">Toma la foto lateral obligatoria, agrega la cenital si la tienes, completa las medidas manuales opcionales y envía el paquete directo al sistema.</p>
        </section>

        <section class="panel status-card">
            <div class="status-pill info" id="serverState">Verificando servidor...</div>
            <div class="status-row"><span>Cola del sistema</span><strong id="queueState">--</strong></div>
            <div class="status-row"><span>Tamaño maximo por solicitud</span><strong>{{ max_upload_mb }} MB</strong></div>
        </section>

        <section class="panel">
            <h2>Fotos</h2>
            <div class="drop-grid">
                <div class="photo-slot">
                    <div class="slot-header">
                        <div class="slot-title">Foto lateral obligatoria<small>Base minima para registrar la medicion.</small></div>
                        <button type="button" class="ghost-button" id="clear1" disabled>Limpiar</button>
                    </div>
                    <label for="input1" class="button">Capturar lateral</label>
                    <input type="file" id="input1" accept="image/*" capture="environment" hidden>
                    <div class="preview-wrap" id="wrap1">
                        <img id="prev1" class="preview" alt="Vista previa lateral">
                        <div class="preview-meta" id="meta1"></div>
                    </div>
                </div>

                <div class="photo-slot">
                    <div class="slot-header">
                        <div class="slot-title">Foto cenital opcional<small>Mejora la trazabilidad cuando este disponible.</small></div>
                        <button type="button" class="ghost-button" id="clear2" disabled>Limpiar</button>
                    </div>
                    <label for="input2" class="button">Capturar cenital</label>
                    <input type="file" id="input2" accept="image/*" capture="environment" hidden>
                    <div class="preview-wrap" id="wrap2">
                        <img id="prev2" class="preview" alt="Vista previa cenital">
                        <div class="preview-meta" id="meta2"></div>
                    </div>
                </div>
            </div>
        </section>

        <section class="panel">
            <h2>Medidas y notas</h2>
            <div class="measurements-grid">
                <div class="field full">
                    <label for="peso">Peso (g)</label>
                    <input type="number" id="peso" placeholder="0.00" step="0.01" min="0">
                </div>
                <div class="field">
                    <label for="longitud">Longitud (cm)</label>
                    <input type="number" id="longitud" placeholder="0.0" step="0.1" min="0">
                </div>
                <div class="field">
                    <label for="ancho">Ancho (cm)</label>
                    <input type="number" id="ancho" placeholder="0.0" step="0.1" min="0">
                </div>
                <div class="field">
                    <label for="alto">Alto (cm)</label>
                    <input type="number" id="alto" placeholder="0.0" step="0.1" min="0">
                </div>
                <div class="field full">
                    <label for="notes">Observaciones</label>
                    <textarea id="notes" maxlength="{{ max_notes_length }}" placeholder="Notas opcionales: condicion del pez, lote, coloracion, incidencia durante la captura..."></textarea>
                    <div class="help">Este texto se precargara en el formulario de la app principal.</div>
                </div>
            </div>
        </section>

        <section class="panel">
            <h2>Actividad reciente</h2>
            <div class="help">Se guardan localmente en este celular los ultimos envios para trazabilidad rapida.</div>
            <ol class="history-list" id="historyList">
                <li>Sin envios recientes.</li>
            </ol>
        </section>

        <div id="messageBox" class="message-box"></div>

        <div class="footer-actions">
            <button id="btnSend" type="button" disabled>Enviar al sistema</button>
        </div>
    </main>

    <script>
        const STATUS_POLL_MS = {{ status_poll_ms|int }};
        const HISTORY_KEY = 'fishtrace-mobile-history';
        const ACCESS_PARAM = new URLSearchParams(window.location.search).get('access') || '';

        const input1 = document.getElementById('input1');
        const input2 = document.getElementById('input2');
        const prev1 = document.getElementById('prev1');
        const prev2 = document.getElementById('prev2');
        const wrap1 = document.getElementById('wrap1');
        const wrap2 = document.getElementById('wrap2');
        const meta1 = document.getElementById('meta1');
        const meta2 = document.getElementById('meta2');
        const clear1 = document.getElementById('clear1');
        const clear2 = document.getElementById('clear2');
        const btnSend = document.getElementById('btnSend');
        const messageBox = document.getElementById('messageBox');
        const serverState = document.getElementById('serverState');
        const queueState = document.getElementById('queueState');
        const historyList = document.getElementById('historyList');

        let busy = false;
        let serverAcceptingUploads = false;

        function setMessage(message, tone = 'info') {
            messageBox.className = `message-box ${tone}`;
            messageBox.textContent = message;
        }

        function setServerState(message, tone = 'info') {
            serverState.className = `status-pill ${tone}`;
            serverState.textContent = message;
        }

        function formatFileMeta(file) {
            if (!file) {
                return '';
            }
            const kb = Math.max(1, Math.round(file.size / 1024));
            return `${file.name} · ${kb} KB`;
        }

        function readHistory() {
            try {
                return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
            } catch {
                return [];
            }
        }

        function writeHistory(items) {
            localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, 5)));
        }

        function renderHistory() {
            const entries = readHistory();
            if (!entries.length) {
                historyList.innerHTML = '<li>Sin envios recientes.</li>';
                return;
            }
            historyList.innerHTML = entries.map((entry) => (`<li>${entry.when} · ${entry.id} · ${entry.summary}</li>`)).join('');
        }

        function registerHistory(id, summary) {
            const entries = readHistory();
            entries.unshift({
                id,
                summary,
                when: new Date().toLocaleString()
            });
            writeHistory(entries);
            renderHistory();
        }

        function clearSelection(input, preview, wrapper, meta, button) {
            input.value = '';
            preview.removeAttribute('src');
            wrapper.style.display = 'none';
            meta.textContent = '';
            button.disabled = true;
            updateSendState();
        }

        function bindPreview(input, preview, wrapper, meta, button) {
            input.addEventListener('change', (event) => {
                const file = event.target.files[0];
                if (!file) {
                    clearSelection(input, preview, wrapper, meta, button);
                    return;
                }

                const reader = new FileReader();
                reader.onload = (loadEvent) => {
                    preview.src = loadEvent.target.result;
                    wrapper.style.display = 'block';
                    meta.textContent = formatFileMeta(file);
                    button.disabled = false;
                    updateSendState();
                };
                reader.readAsDataURL(file);
            });
        }

        async function compressImage(file) {
            if (!file || !file.type.startsWith('image/')) {
                return file;
            }

            if (file.size < 1500000) {
                return file;
            }

            const bitmap = await createImageBitmap(file);
            const maxDimension = 2200;
            const ratio = Math.min(1, maxDimension / Math.max(bitmap.width, bitmap.height));
            const width = Math.max(1, Math.round(bitmap.width * ratio));
            const height = Math.max(1, Math.round(bitmap.height * ratio));
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;

            const context = canvas.getContext('2d');
            context.drawImage(bitmap, 0, 0, width, height);

            const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.88));
            if (!blob) {
                return file;
            }

            const baseName = (file.name || 'capture').replace(/\.[^.]+$/, '');
            return new File([blob], `${baseName}_opt.jpg`, { type: 'image/jpeg' });
        }

        async function refreshServerStatus() {
            try {
                const response = await fetch('/status', {
                    credentials: 'same-origin',
                    headers: ACCESS_PARAM ? { 'X-FishTrace-Access': ACCESS_PARAM } : {}
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || 'No se pudo consultar el estado del sistema.');
                }

                serverAcceptingUploads = !!data.accepting_uploads;
                queueState.textContent = `${data.queue_size}/${data.queue_capacity}`;

                if (data.accepting_uploads) {
                    setServerState('Servidor listo para recibir capturas', 'success');
                } else if (data.queue_size >= data.queue_capacity) {
                    setServerState('Servidor ocupado, espere a que se vacie la cola', 'warning');
                } else {
                    setServerState('Servidor en verificacion', 'info');
                }
            } catch (error) {
                serverAcceptingUploads = false;
                queueState.textContent = '--';
                setServerState('No se pudo conectar con la app principal', 'error');
            }
            updateSendState();
        }

        function updateSendState() {
            const hasLateral = !!input1.files[0];
            btnSend.disabled = busy || !hasLateral || !serverAcceptingUploads;
        }

        function buildFormData() {
            const formData = new FormData();
            formData.append('peso', document.getElementById('peso').value.trim());
            formData.append('longitud', document.getElementById('longitud').value.trim());
            formData.append('ancho', document.getElementById('ancho').value.trim());
            formData.append('alto', document.getElementById('alto').value.trim());
            formData.append('notes', document.getElementById('notes').value.trim());
            formData.append('device_timestamp', new Date().toISOString());
            formData.append('client_user_agent', navigator.userAgent || '');
            formData.append('client_screen', `${window.screen.width}x${window.screen.height}`);
            formData.append('access_token', ACCESS_PARAM);
            return formData;
        }

        function resetForm() {
            clearSelection(input1, prev1, wrap1, meta1, clear1);
            clearSelection(input2, prev2, wrap2, meta2, clear2);
            document.getElementById('peso').value = '';
            document.getElementById('longitud').value = '';
            document.getElementById('ancho').value = '';
            document.getElementById('alto').value = '';
            document.getElementById('notes').value = '';
        }

        btnSend.addEventListener('click', async () => {
            if (!input1.files[0]) {
                setMessage('La foto lateral es obligatoria antes de enviar.', 'warning');
                return;
            }

            busy = true;
            updateSendState();
            btnSend.textContent = 'Enviando captura...';
            setMessage('Preparando imagenes y enviando al sistema...', 'info');

            try {
                const formData = buildFormData();
                formData.append('foto1', await compressImage(input1.files[0]));
                if (input2.files[0]) {
                    formData.append('foto2', await compressImage(input2.files[0]));
                }

                const response = await fetch('/upload', {
                    method: 'POST',
                    body: formData,
                    credentials: 'same-origin',
                    headers: ACCESS_PARAM ? { 'X-FishTrace-Access': ACCESS_PARAM } : {}
                });

                const payload = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(payload.error || payload.message || 'No se pudo completar el envio.');
                }

                const summary = input2.files[0] ? 'Lateral + cenital' : 'Solo lateral';
                registerHistory(payload.request_id || 'sin-id', summary);
                setMessage(`Captura enviada correctamente. ID: ${payload.request_id}.`, 'success');
                resetForm();
                await refreshServerStatus();
            } catch (error) {
                setMessage(error.message || 'No se pudo enviar la captura.', 'error');
            } finally {
                busy = false;
                btnSend.textContent = 'Enviar al sistema';
                updateSendState();
            }
        });

        clear1.addEventListener('click', () => clearSelection(input1, prev1, wrap1, meta1, clear1));
        clear2.addEventListener('click', () => clearSelection(input2, prev2, wrap2, meta2, clear2));

        bindPreview(input1, prev1, wrap1, meta1, clear1);
        bindPreview(input2, prev2, wrap2, meta2, clear2);
        renderHistory();
        refreshServerStatus();
        setInterval(refreshServerStatus, STATUS_POLL_MS);
    </script>
</body>
</html>
"""

UNAUTHORIZED_PAGE_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Acceso restringido</title>
    <style>
        body {
            margin: 0;
            min-height: 100vh;
            display: grid;
            place-items: center;
            background: #020617;
            color: #e2e8f0;
            font-family: "Segoe UI", sans-serif;
            padding: 24px;
        }
        .card {
            width: min(460px, 100%);
            background: rgba(15, 23, 42, 0.94);
            border: 1px solid rgba(148, 163, 184, 0.24);
            border-radius: 20px;
            padding: 24px;
        }
        h1 { margin-top: 0; }
        p { color: #94a3b8; line-height: 1.6; }
    </style>
</head>
<body>
    <section class="card">
        <h1>Acceso no autorizado</h1>
        <p>Abra esta pagina escaneando el codigo QR vigente desde la aplicacion de escritorio. El enlace del QR ya incluye el acceso temporal y no necesita escribir ningun PIN manual.</p>
    </section>
</body>
</html>
"""


# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================

def get_local_ip():
    """Obtiene la IP local del servidor para mostrar al usuario."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def configure_mobile_access_token(token=None):
    """Configura o genera el token temporal usado por la pasarela móvil."""
    global _mobile_access_token, _mobile_access_token_issued_at
    _mobile_access_token = token or secrets.token_urlsafe(24)
    _mobile_access_token_issued_at = time.time()
    return _mobile_access_token


def get_mobile_access_token():
    """Retorna el token temporal actual para acceso móvil."""
    return _mobile_access_token


def build_mobile_access_url(host, port=5000):
    """Genera la URL completa del QR con token embebido."""
    token = get_mobile_access_token() or configure_mobile_access_token()
    query = urlencode({"access": token})
    return f"http://{host}:{port}/?{query}"


def _get_queue_size():
    try:
        return mobile_capture_queue.qsize()
    except NotImplementedError:
        return 0


def _safe_unlink(path):
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        logger.warning(f"No se pudo eliminar archivo temporal {path}: {exc}")


def _json_error(message, status_code, code=None, details=None):
    payload = {
        "status": "error",
        "error": message,
    }
    if code:
        payload["code"] = code
    if details:
        payload["details"] = details
    return jsonify(payload), status_code


def _ensure_manual_dir():
    os.makedirs(Config.IMAGES_MANUAL_DIR, exist_ok=True)


def _extract_access_token():
    return (
        request.args.get("access")
        or request.form.get("access_token")
        or request.headers.get("X-FishTrace-Access")
        or request.cookies.get(MOBILE_TOKEN_COOKIE)
        or ""
    )


def _is_access_authorized():
    candidate = _extract_access_token()
    current = get_mobile_access_token()
    return bool(candidate and current and secrets.compare_digest(candidate, current))


def _require_mobile_access_json():
    if _is_access_authorized():
        return None
    return _json_error(
        "Acceso no autorizado. Escanee nuevamente el QR vigente.",
        403,
        code="unauthorized"
    )


def _format_metric_value(value):
    if value == "":
        return ""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _parse_measurements():
    cleaned = {}
    errors = []

    for field, (min_value, max_value) in MEASUREMENT_LIMITS.items():
        raw_value = (request.form.get(field, "") or "").strip()
        if not raw_value:
            cleaned[field] = ""
            continue

        try:
            numeric_value = float(raw_value)
        except ValueError:
            errors.append(f"El campo '{field}' debe ser numerico.")
            continue

        if not (min_value <= numeric_value <= max_value):
            errors.append(f"El campo '{field}' debe estar entre {min_value:g} y {max_value:g}.")
            continue

        cleaned[field] = _format_metric_value(numeric_value)

    notes = (request.form.get("notes", "") or "").strip()
    cleaned["notes"] = notes[:MAX_NOTES_LENGTH]
    cleaned["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
    cleaned["device_timestamp"] = (request.form.get("device_timestamp", "") or "").strip()[:48]
    cleaned["client_user_agent"] = (request.form.get("client_user_agent", "") or "").strip()[:220]
    cleaned["client_screen"] = (request.form.get("client_screen", "") or "").strip()[:MAX_FIELD_LENGTH]
    return cleaned, errors


def resize_keep_aspect(image, target_height):
    """Redimensiona imagen manteniendo aspect ratio."""
    if image.height <= 0 or image.width <= 0:
        raise ValueError("La imagen no tiene dimensiones validas.")
    aspect_ratio = image.width / image.height
    new_width = max(1, int(target_height * aspect_ratio))
    return image.resize((new_width, target_height), Image.Resampling.LANCZOS)


def add_label_to_image(image, label_text):
    """Agrega etiqueta en la esquina superior de la imagen."""
    img_copy = image.copy()
    draw = ImageDraw.Draw(img_copy)
    bbox_height = 40
    draw.rectangle([(0, 0), (img_copy.width, bbox_height)], fill=(0, 0, 0, 180))

    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except OSError:
        font = ImageFont.load_default()

    draw.text((10, 10), label_text, fill=(255, 255, 255), font=font)
    return img_copy


def cleanup_temp_files(directory, pattern="MOB_"):
    """Limpia archivos temporales antiguos (>1 hora)."""
    try:
        now = time.time()
        for file in Path(directory).glob(f"{pattern}*"):
            if now - file.stat().st_mtime > MAX_IMAGE_AGE_SECONDS:
                file.unlink()
                logger.info(f"Limpieza: {file.name} eliminado")
    except Exception as e:
        logger.warning(f"Error en limpieza: {e}")


def _build_temp_path(key, extension):
    return os.path.join(
        Config.IMAGES_MANUAL_DIR,
        f"MOB_{int(time.time() * 1000)}_{key}_{uuid.uuid4().hex[:8]}{extension}"
    )


def _build_output_path(prefix="MOBILE"):
    return os.path.join(
        Config.IMAGES_MANUAL_DIR,
        f"{prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.jpg"
    )


def _validate_upload(file_obj, key):
    extension = Path(file_obj.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(f"{key}: formato no permitido. Use JPG, PNG, BMP o WEBP.")

    mime_type = (file_obj.mimetype or "").lower()
    if mime_type and not mime_type.startswith(ALLOWED_MIME_PREFIXES):
        raise ValueError(f"{key}: el archivo no parece ser una imagen valida.")

    return extension


def _load_valid_image(file_obj, key):
    extension = _validate_upload(file_obj, key)
    temp_path = _build_temp_path(key, extension)
    file_obj.save(temp_path)

    try:
        with Image.open(temp_path) as img_check:
            img_check.verify()

        with Image.open(temp_path) as verified_image:
            rgb_image = verified_image.convert("RGB")
            width, height = rgb_image.size
            if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
                raise ValueError(
                    f"{key}: resolucion insuficiente. Minimo {MIN_IMAGE_WIDTH}x{MIN_IMAGE_HEIGHT}."
                )

        metadata = {
            "field": key,
            "source_name": Path(file_obj.filename).name,
            "mime_type": file_obj.mimetype or "",
            "width": width,
            "height": height,
            "size_bytes": os.path.getsize(temp_path),
        }
        return rgb_image, temp_path, metadata
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        _safe_unlink(temp_path)
        raise ValueError(f"{key}: imagen invalida ({exc})") from exc


def _save_processed_capture(received_images):
    result_path = _build_output_path("MOBILE")

    if len(received_images) == 2:
        img1_resized = resize_keep_aspect(received_images[0][0], TARGET_HEIGHT)
        img2_resized = resize_keep_aspect(received_images[1][0], TARGET_HEIGHT)

        total_width = img1_resized.width + img2_resized.width
        collage = Image.new("RGB", (total_width, TARGET_HEIGHT))
        collage.paste(img1_resized, (0, 0))
        collage.paste(img2_resized, (img1_resized.width, 0))
        final_image = add_label_to_image(collage, "CAPTURA REMOTA (LATERAL + CENITAL)")
    else:
        img, label = received_images[0]
        img_resized = resize_keep_aspect(img, TARGET_HEIGHT)
        etiqueta = "LATERAL" if label == "foto1" else "CENITAL"
        final_image = add_label_to_image(img_resized, f"CAPTURA REMOTA ({etiqueta})")

    final_image.save(result_path, quality=TARGET_QUALITY, optimize=True)
    final_image.close()
    return result_path


# ============================================================================
# RUTAS DE FLASK
# ============================================================================

@flask_app.route("/", methods=["GET"])
def mobile_page():
    """Página HTML responsive para captura móvil."""
    if not _is_access_authorized():
        return render_template_string(UNAUTHORIZED_PAGE_HTML), 403

    response = make_response(
        render_template_string(
            MOBILE_PAGE_HTML,
            max_upload_mb=MAX_UPLOAD_MB,
            max_notes_length=MAX_NOTES_LENGTH,
            status_poll_ms=STATUS_POLL_MS,
        )
    )
    response.set_cookie(
        MOBILE_TOKEN_COOKIE,
        get_mobile_access_token(),
        max_age=8 * 60 * 60,
        samesite="Lax",
        httponly=False,
    )
    return response


@flask_app.route("/upload", methods=["POST"])
def upload_from_mobile():
    """Recibe imagen y medidas del móvil, procesa y notifica a la app principal."""
    temp_paths = []
    received_images = []
    result_path = None
    request_id = uuid.uuid4().hex[:12]
    started_at = time.time()

    try:
        auth_error = _require_mobile_access_json()
        if auth_error is not None:
            return auth_error

        _ensure_manual_dir()
        cleanup_temp_files(Config.IMAGES_MANUAL_DIR)

        medidas, measurement_errors = _parse_measurements()
        if measurement_errors:
            return _json_error(
                "Revise los campos numericos antes de enviar.",
                400,
                code="invalid_measurements",
                details=measurement_errors,
            )

        if "foto1" not in request.files or not request.files["foto1"].filename:
            return _json_error(
                "La foto lateral es obligatoria para registrar la captura.",
                400,
                code="missing_lateral",
            )

        image_metadata = []
        image_errors = []
        for key in ("foto1", "foto2"):
            file_obj = request.files.get(key)
            if not file_obj or not file_obj.filename:
                continue

            try:
                image, temp_path, metadata = _load_valid_image(file_obj, key)
                temp_paths.append(temp_path)
                received_images.append((image, key))
                image_metadata.append(metadata)
            except ValueError as exc:
                image_errors.append(str(exc))

        if not received_images:
            return _json_error(
                "No se pudo validar ninguna imagen recibida.",
                400,
                code="invalid_images",
                details=image_errors,
            )

        if received_images[0][1] != "foto1":
            return _json_error(
                "La captura lateral es obligatoria y debe ser valida.",
                400,
                code="invalid_lateral",
                details=image_errors or None,
            )

        result_path = _save_processed_capture(received_images)

        paquete_datos = {
            "request_id": request_id,
            "path": result_path,
            "medidas": medidas,
            "metadata": {
                "received_at": medidas["timestamp"],
                "processing_ms": int((time.time() - started_at) * 1000),
                "image_count": len(received_images),
                "image_details": image_metadata,
                "image_errors": image_errors,
                "remote_ip": request.headers.get("X-Forwarded-For", request.remote_addr or ""),
            }
        }

        try:
            mobile_capture_queue.put(paquete_datos, block=False)
            logger.info(
                "Captura movil encolada | request_id=%s | cola=%s/%s | fotos=%s",
                request_id,
                _get_queue_size(),
                mobile_capture_queue.maxsize,
                len(received_images),
            )
        except Full:
            _safe_unlink(result_path)
            result_path = None
            return _json_error(
                "El sistema esta ocupado en este momento. Espere unos segundos e intente de nuevo.",
                503,
                code="queue_full",
                details={
                    "queue_size": _get_queue_size(),
                    "queue_capacity": mobile_capture_queue.maxsize,
                },
            )

        return jsonify({
            "status": "success",
            "message": "Datos encolados correctamente.",
            "request_id": request_id,
            "queue_size": _get_queue_size(),
            "queue_capacity": mobile_capture_queue.maxsize,
            "warnings": image_errors,
        }), 200

    except Exception as exc:
        logger.exception(f"Error en upload movil: {exc}")
        if result_path:
            _safe_unlink(result_path)
        return _json_error(
            "No se pudo procesar la captura movil.",
            500,
            code="upload_failed",
            details=str(exc) if Config.DEBUG_MODE else None,
        )
    finally:
        for image, _ in received_images:
            try:
                image.close()
            except Exception:
                pass
        for temp_path in temp_paths:
            _safe_unlink(temp_path)


@flask_app.route("/status", methods=["GET"])
def mobile_status():
    """Entrega estado operativo para la UI móvil."""
    auth_error = _require_mobile_access_json()
    if auth_error is not None:
        return auth_error

    queue_size = _get_queue_size()
    queue_capacity = mobile_capture_queue.maxsize
    return jsonify({
        "status": "online",
        "server": "FishTrace Mobile Capture",
        "queue_size": queue_size,
        "queue_capacity": queue_capacity,
        "accepting_uploads": queue_size < queue_capacity,
        "token_age_seconds": int(time.time() - _mobile_access_token_issued_at),
    })


@flask_app.route("/ping", methods=["GET"])
def ping():
    """Endpoint para verificar que el servidor está activo."""
    return jsonify({
        "status": "online",
        "server": "TroutBiometry Mobile Capture",
        "version": "2.1"
    })


@flask_app.errorhandler(413)
def request_entity_too_large(error):
    """Manejo de archivos muy grandes."""
    return _json_error(
        f"Archivo muy grande. Maximo {MAX_UPLOAD_MB}MB permitido.",
        413,
        code="payload_too_large",
    )


# ============================================================================
# INICIALIZACIÓN
# ============================================================================

def start_flask_server(host="0.0.0.0", port=5000, debug=False):
    """Inicia el servidor Flask."""
    _ensure_manual_dir()
    local_ip = get_local_ip()
    access_url = build_mobile_access_url(local_ip, port)

    logger.info("=" * 70)
    logger.info("SERVIDOR DE CAPTURA MOVIL INICIADO")
    logger.info("=" * 70)
    logger.info("Accede desde tu movil en:")
    logger.info(f"  URL QR segura: {access_url}")
    logger.info(f"  🌐 http://localhost:{port} (solo en esta PC)")
    logger.info("=" * 70)

    flask_app.run(
        host=host,
        port=port,
        debug=debug,
        threaded=True,
        use_reloader=False
    )


if __name__ == "__main__":
    start_flask_server(
        host="0.0.0.0",
        port=5000,
        debug=Config.DEBUG_MODE
    )