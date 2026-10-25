"""Acceso de SOLO LECTURA a Gmail, Google Calendar y Google Tasks del usuario."""
import os
import re
import base64
import html as _html
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CAL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
TASKS = "https://tasks.googleapis.com/tasks/v1"

TZ = ZoneInfo(os.environ.get("APP_TIMEZONE", "America/Bogota"))
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

# Correos que suelen ser de la universidad (tareas, entregas, plataformas, profesores)
ACADEMICO = (
    'newer_than:30d -category:promotions -category:social '
    '(tarea OR entrega OR trabajo OR taller OR examen OR parcial OR quiz OR proyecto OR laboratorio '
    'OR "fecha límite" OR plazo OR deadline OR assignment OR homework OR classroom OR moodle '
    'OR canvas OR blackboard OR profesor OR docente OR universidad OR materia)'
)
NO_LEIDOS = 'is:unread newer_than:7d -category:promotions -category:social'

MAX_CONTEXTO = 16000


class GoogleAuthError(Exception):
    """El permiso de Google caducó o fue revocado: hay que volver a conectar."""


# ---------------------------------------------------------------- Autenticación

def refresh_access_token(refresh_token, client_id, client_secret):
    r = requests.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }, timeout=15)
    if r.status_code != 200:
        raise GoogleAuthError(r.text[:200])
    return r.json()["access_token"]


def _get(url, token, params=None):
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=15)
    if r.status_code == 401:
        raise GoogleAuthError("token inválido")
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise RuntimeError(f"{r.status_code} {msg}"[:200])
    return r.json()


# ---------------------------------------------------------------- Gmail

def _b64(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def _partes(payload, plain, htmls):
    mime = payload.get("mimeType", "")
    data = (payload.get("body") or {}).get("data")
    if data and mime == "text/plain":
        plain.append(_b64(data))
    elif data and mime == "text/html":
        htmls.append(_b64(data))
    for p in payload.get("parts") or []:
        _partes(p, plain, htmls)


def _html_a_texto(h):
    h = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    return _html.unescape(h)


def limpiar(texto):
    lineas = [l for l in texto.splitlines() if not l.lstrip().startswith(">")]
    t = "\n".join(lineas)
    t = re.sub(r"https?://\S+", "[enlace]", t)
    t = re.sub(r"[ \t\u00a0\u200b]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    return t


def extract_text(payload):
    plain, htmls = [], []
    _partes(payload, plain, htmls)
    texto = "\n".join(plain) if plain else _html_a_texto("\n".join(htmls))
    return limpiar(texto)


def _ids(token, query, n):
    data = _get(f"{GMAIL}/messages", token, {"q": query, "maxResults": n})
    return [m["id"] for m in data.get("messages", [])]


def _fecha(valor):
    try:
        return parsedate_to_datetime(valor).astimezone(TZ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return valor or "?"


def _leer(token, mid):
    m = _get(f"{GMAIL}/messages/{mid}", token, {"format": "full"})
    payload = m.get("payload", {})
    h = {x["name"].lower(): x["value"] for x in payload.get("headers", [])}
    return {
        "de": h.get("from", "?"),
        "asunto": h.get("subject", "(sin asunto)"),
        "fecha": _fecha(h.get("date")),
        "sin_leer": "UNREAD" in (m.get("labelIds") or []),
        "texto": extract_text(payload),
    }


def _correos(token):
    ids_a = _ids(token, ACADEMICO, 20)
    ids_u = [i for i in _ids(token, NO_LEIDOS, 10) if i not in ids_a]
    ids = ids_a + ids_u

    def leer(mid):
        try:
            return _leer(token, mid)
        except GoogleAuthError:
            raise
        except Exception:
            return None

    with ThreadPoolExecutor(8) as ex:
        correos = [c for c in ex.map(leer, ids) if c]

    lineas = []
    for n, c in enumerate(correos, 1):
        limite = 1200 if n <= 6 else 300
        texto = c["texto"][:limite].replace("\n", " ")
        marca = " (sin leer)" if c["sin_leer"] else ""
        lineas.append(f"[{n}] De: {c['de']} | Fecha: {c['fecha']} | Asunto: {c['asunto']}{marca}\n    {texto}")
    return "\n".join(lineas) if lineas else "(No encontré correos relevantes.)"


# ---------------------------------------------------------------- Calendario

def _eventos(token, dias=21):
    ahora = datetime.now(TZ)
    params = {
        "timeMin": ahora.isoformat(),
        "timeMax": (ahora + timedelta(days=dias)).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 40,
    }
    items = _get(CAL, token, params).get("items", [])
    lineas = []
    for ev in items:
        ini = ev.get("start", {})
        if "dateTime" in ini:
            d = datetime.fromisoformat(ini["dateTime"].replace("Z", "+00:00")).astimezone(TZ)
            cuando = d.strftime("%Y-%m-%d %H:%M")
        else:
            cuando = ini.get("date", "?") + " (todo el día)"
        lugar = f" ({ev['location']})" if ev.get("location") else ""
        lineas.append(f"- {cuando} · {ev.get('summary', '(sin título)')}{lugar}")
    return "\n".join(lineas) if lineas else "(No hay eventos próximos.)"


# ---------------------------------------------------------------- Tareas

def _tareas(token):
    listas = _get(f"{TASKS}/users/@me/lists", token, {"maxResults": 10}).get("items", [])
    lineas = []
    for lst in listas[:6]:
        items = _get(f"{TASKS}/lists/{lst['id']}/tasks", token,
                     {"showCompleted": "false", "showHidden": "false", "maxResults": 50}).get("items", [])
        for t in items:
            due = (t.get("due") or "")[:10]
            marca = f"vence {due}" if due else "sin fecha"
            notas = (t.get("notes") or "").replace("\n", " ")[:150]
            extra = f" — {notas}" if notas else ""
            lineas.append(f"- [{marca}] {t.get('title', '(sin título)')} (lista: {lst.get('title', '')}){extra}")
    return "\n".join(lineas) if lineas else "(No hay tareas pendientes en Google Tasks.)"


# ---------------------------------------------------------------- Todo junto

def construir_contexto(refresh_token, client_id, client_secret, permisos):
    """Devuelve un bloque de texto con los datos del usuario para dárselo a la IA."""
    token = refresh_access_token(refresh_token, client_id, client_secret)
    ahora = datetime.now(TZ)
    cabecera = (f"FECHA Y HORA ACTUAL: {DIAS[ahora.weekday()]} {ahora.day} de {MESES[ahora.month - 1]} "
                f"de {ahora.year}, {ahora.strftime('%H:%M')} (zona {TZ.key})")

    tareas = {"tareas": ("== TAREAS PENDIENTES (Google Tasks) ==", _tareas),
              "cal": ("== EVENTOS DEL CALENDARIO (próximos 21 días) ==", _eventos),
              "mail": ("== CORREOS RELEVANTES (últimos 30 días y sin leer) ==", _correos)}
    activos = [k for k in tareas if permisos.get(k)]

    resultados, notas = {}, []
    with ThreadPoolExecutor(3) as ex:
        futuros = {k: ex.submit(tareas[k][1], token) for k in activos}
        for k, f in futuros.items():
            try:
                resultados[k] = f.result()
            except GoogleAuthError:
                raise
            except Exception as e:
                notas.append(f"(No pude leer {tareas[k][0].strip('= ')}: {e})")

    partes = [cabecera]
    for k in ("tareas", "cal", "mail"):
        if k in resultados:
            partes.append(f"{tareas[k][0]}\n{resultados[k]}")
    partes.extend(notas)
    return "\n\n".join(partes)[:MAX_CONTEXTO]
