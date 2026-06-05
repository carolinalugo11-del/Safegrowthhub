"""
SafeGrowthHub - Bot Lector de Telegram
Lee el canal de tu bot y carga operaciones automáticamente a Firebase.
"""

import os
import re
import time
import json
import logging
import requests
from datetime import datetime

# ─────────────────────────────────────────
# CONFIGURACIÓN — solo edita esta sección
# ─────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "8178392369:AAGvSJdvzk4veavI6g3SFX6JRwW9OEKZuOI")
CHANNEL_ID       = os.getenv("CHANNEL_ID",     "-1003843087333")

# Firebase REST — usa tu proyecto exacto
FIREBASE_PROJECT = "safe-growth-hub-6bd5d"
FIREBASE_URL     = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT}/databases/(default)/documents/sgh/maindb"

# Capital % por defecto que se usará para cada operación (igual al manual)
DEFAULT_CAP_PCT  = 30   # 30 % del capital total

# ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("bot_lector")

# ── Telegram polling ──────────────────────
def get_updates(offset=None):
    params = {"timeout": 30, "allowed_updates": ["channel_post"]}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params=params, timeout=40
        )
        return r.json()
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return {}

# ── Parsear mensajes ──────────────────────
def parse_message(text: str):
    """
    Detecta el tipo de mensaje y extrae los campos clave.
    Devuelve un dict con: tipo, moneda, rango, entry, tp, tpPct, pnl
    o None si no reconoce el mensaje.
    """
    t = text.strip()

    # — NUEVA COMPRA —
    if "NUEVA COMPRA REAL EJECUTADA" in t:
        return {
            "tipo":    "open",
            "moneda":  _re(r"Moneda:\s*(.+)",           t),
            "rango":   _re(r"Rango Actual:\s*(\S+)",    t),
            "entry":   _float(r"Precio Entrada:\s*\$?([\d.]+)", t),
            "tp":      _float(r"Venta límite TP:\s*\$?([\d.]+)", t),
            "tpPct":   None,   # se calcula abajo
        }

    # — CERRADA TP —
    if "OPERACIÓN CERRADA" in t and "TP" in t:
        entry = _float(r"Entrada:\s*\$?([\d.]+)", t)
        tp    = _float(r"Salida \(TP\):\s*\$?([\d.]+)", t)
        pct   = round((tp - entry) / entry * 100, 4) if entry and tp else 0
        return {
            "tipo":    "closed",
            "moneda":  _re(r"Moneda:\s*(.+)",       t),
            "rango":   _re(r"Rango:\s*(\S+)",        t),
            "entry":   entry,
            "tp":      tp,
            "tpPct":   pct,
            "pnl":     _float(r"Ganancia:\s*\+?\$?([\d.]+)", t),
        }

    # — FLOTANTE —
    if "OPERACIÓN PASÓ A FLOTANTE" in t:
        return {
            "tipo":    "flotante",
            "moneda":  _re(r"Moneda:\s*(.+)",               t),
            "rango":   _re(r"Rango:\s*(\S+)",                t),
            "entry":   _float(r"Precio Cayó a:\s*\$?([\d.]+)", t),
        }

    # — FLOTANTE RECUPERADO —
    if "FLOTANTE RECUPERADO" in t:
        entry = _float(r"Entrada original:\s*\$?([\d.]+)", t)
        tp    = _float(r"Salida \(TP\):\s*\$?([\d.]+)",    t)
        pct   = round((tp - entry) / entry * 100, 4) if entry and tp else 0
        return {
            "tipo":    "closed",
            "moneda":  _re(r"Moneda:\s*(.+)",                 t),
            "rango":   _re(r"Rango:\s*(\S+)",                  t),
            "entry":   entry,
            "tp":      tp,
            "tpPct":   pct,
            "pnl":     _float(r"PNL Realizado:\s*\+?\$?([\d.]+)", t),
        }

    return None   # mensaje irrelevante

def _re(pattern, text):
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ""

def _float(pattern, text):
    m = re.search(pattern, text)
    try:    return float(m.group(1)) if m else None
    except: return None

# ── Estrategia ────────────────────────────
STRATEGY_MAP = {
    "ETH": "GRID-SCAL ETH",
    "BTC": "GRID-SCAL BTC",
    "SOL": "GRID-SCAL SOLANA",
    "XRP": "GRID-SCAL XRP",
    "TRX": "GRID-SCAL TRX",
    "POL": "GRID-SCAL POL",
}

def strategy_from_moneda(moneda: str) -> str:
    for k, v in STRATEGY_MAP.items():
        if k in moneda.upper():
            return v
    return moneda.upper()

# ── Fechas ────────────────────────────────
def date_str():
    return datetime.now().strftime("%d/%m/%Y")

def time_str():
    return datetime.now().strftime("%H:%M")

def dt_str():
    return datetime.now().strftime("%d/%m/%Y %H:%M")

# ── Firebase helpers ──────────────────────
def fb_get():
    """Lee el documento maindb desde Firestore REST."""
    try:
        r = requests.get(FIREBASE_URL, timeout=15)
        if r.status_code == 200:
            return r.json()
        log.error(f"Firebase GET {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log.error(f"Firebase GET error: {e}")
    return None

def fb_parse_db(doc):
    """Convierte el formato Firestore → dict Python plano."""
    try:
        raw = doc["fields"]["db"]["mapValue"]["fields"]
        return _fb_decode({"mapValue": {"fields": raw}})
    except Exception as e:
        log.error(f"Firebase parse error: {e}")
        return None

def _fb_decode(val):
    if "stringValue"  in val: return val["stringValue"]
    if "integerValue" in val: return int(val["integerValue"])
    if "doubleValue"  in val: return float(val["doubleValue"])
    if "booleanValue" in val: return val["booleanValue"]
    if "nullValue"    in val: return None
    if "arrayValue"   in val:
        return [_fb_decode(v) for v in val["arrayValue"].get("values", [])]
    if "mapValue"     in val:
        return {k: _fb_decode(v) for k, v in val["mapValue"].get("fields", {}).items()}
    return None

def _fb_encode(val):
    if val is None:               return {"nullValue": None}
    if isinstance(val, bool):     return {"booleanValue": val}
    if isinstance(val, int):      return {"integerValue": str(val)}
    if isinstance(val, float):    return {"doubleValue": val}
    if isinstance(val, str):      return {"stringValue": val}
    if isinstance(val, list):
        return {"arrayValue": {"values": [_fb_encode(v) for v in val]}}
    if isinstance(val, dict):
        return {"mapValue": {"fields": {k: _fb_encode(v) for k, v in val.items()}}}
    return {"stringValue": str(val)}

def fb_save(db: dict):
    """Escribe el dict Python completo de vuelta a Firestore."""
    body = {"fields": {"db": _fb_encode(db)}}
    try:
        r = requests.patch(FIREBASE_URL, json=body, timeout=20)
        if r.status_code == 200:
            log.info("✅ Firebase guardado correctamente")
            return True
        log.error(f"Firebase PATCH {r.status_code}: {r.text[:300]}")
    except Exception as e:
        log.error(f"Firebase PATCH error: {e}")
    return False

# ── Operaciones en Firebase ───────────────
def handle_open(db: dict, parsed: dict):
    """Registra una operación nueva (status=open)."""
    entry  = parsed.get("entry") or 0
    tp     = parsed.get("tp")    or 0
    tpPct  = parsed.get("tpPct")
    if not tpPct and entry and tp:
        tpPct = round((tp - entry) / entry * 100, 4)

    op = {
        "id":        "op" + str(int(time.time() * 1000)),
        "strategy":  strategy_from_moneda(parsed.get("moneda", "")),
        "entry":     entry,
        "tp":        tp,
        "tpPct":     tpPct or 0,
        "capUsado":  DEFAULT_CAP_PCT,
        "capPct":    DEFAULT_CAP_PCT,
        "openDate":  date_str(),
        "openTime":  time_str(),
        "closeDate": "",
        "closeTime": "",
        "status":    "open",
        "date":      date_str(),
        "rango":     parsed.get("rango", ""),
        "fuente":    "bot_auto",
    }
    db.setdefault("botOps", []).append(op)
    log.info(f"📥 NUEVA OP: {op['strategy']} entry={entry} tp={tp} tpPct={tpPct}%")
    return op

def handle_closed(db: dict, parsed: dict):
    """Cierra la operación abierta más reciente de esa estrategia."""
    strategy = strategy_from_moneda(parsed.get("moneda", ""))
    rango    = parsed.get("rango", "")
    ops      = db.get("botOps", [])

    # Busca la op abierta más reciente del mismo par y rango
    target = None
    for op in reversed(ops):
        if op.get("status") == "open" and op.get("strategy") == strategy:
            if not rango or op.get("rango", "") == rango:
                target = op
                break
    # Si no coincide por rango, busca solo por estrategia
    if not target:
        for op in reversed(ops):
            if op.get("status") == "open" and op.get("strategy") == strategy:
                target = op
                break

    if target:
        target["status"]    = "closed"
        target["closeDate"] = date_str()
        target["closeTime"] = time_str()
        target["tp"]        = parsed.get("tp") or target.get("tp", 0)
        target["tpPct"]     = parsed.get("tpPct") or target.get("tpPct", 0)
        log.info(f"✅ OP CERRADA: {target['strategy']} tpPct={target['tpPct']}%")
    else:
        # No encontró op abierta → crea una ya cerrada para el historial
        op = {
            "id":        "op" + str(int(time.time() * 1000)),
            "strategy":  strategy,
            "entry":     parsed.get("entry") or 0,
            "tp":        parsed.get("tp")    or 0,
            "tpPct":     parsed.get("tpPct") or 0,
            "capUsado":  DEFAULT_CAP_PCT,
            "capPct":    DEFAULT_CAP_PCT,
            "openDate":  date_str(),
            "openTime":  time_str(),
            "closeDate": date_str(),
            "closeTime": time_str(),
            "status":    "closed",
            "date":      date_str(),
            "rango":     rango,
            "fuente":    "bot_auto",
        }
        db.setdefault("botOps", []).append(op)
        log.info(f"✅ OP CERRADA (nueva entrada): {strategy} tpPct={op['tpPct']}%")
        target = op

    # Registrar ganancia del día
    pct      = target.get("tpPct", 0)
    cap_used = target.get("capUsado", DEFAULT_CAP_PCT)
    hoy      = date_str()

    if not db.get("ganancias"):
        db["ganancias"] = []

    day_block = next((g for g in db["ganancias"] if g.get("dateKey") == hoy), None)
    if not day_block:
        day_block = {"dateKey": hoy, "dateStr": hoy, "ops": []}
        db["ganancias"].append(day_block)

    day_block.setdefault("ops", []).append({
        "strategy": target["strategy"],
        "pct":      pct,
        "note":     f"Auto · {target['strategy']} TP {target['tp']} · {time_str()}",
        "capUsado": cap_used,
        "ganBruta": round(cap_used * pct / 100, 4),
        "ts":       dt_str(),
    })
    log.info(f"📈 Ganancia registrada: {pct}% sobre cap {cap_used}")

def handle_flotante(db: dict, parsed: dict):
    """Marca la operación abierta como flotante (status=blocked)."""
    strategy = strategy_from_moneda(parsed.get("moneda", ""))
    ops      = db.get("botOps", [])
    for op in reversed(ops):
        if op.get("status") == "open" and op.get("strategy") == strategy:
            op["status"] = "blocked"
            log.info(f"⚠️  FLOTANTE: {strategy}")
            return
    log.warning(f"⚠️  No se encontró op abierta para marcar flotante: {strategy}")

# ── Procesar mensaje ──────────────────────
def process_message(text: str):
    parsed = parse_message(text)
    if not parsed:
        return   # mensaje irrelevante

    doc = fb_get()
    if not doc:
        log.error("No se pudo leer Firebase. Se omite este mensaje.")
        return

    db = fb_parse_db(doc)
    if not db:
        log.error("No se pudo parsear la DB de Firebase.")
        return

    tipo = parsed["tipo"]
    if   tipo == "open":     handle_open(db, parsed)
    elif tipo == "closed":   handle_closed(db, parsed)
    elif tipo == "flotante": handle_flotante(db, parsed)

    fb_save(db)

# ── Loop principal ────────────────────────
def main():
    log.info("🚀 Bot lector SafeGrowthHub iniciado")
    log.info(f"   Canal: {CHANNEL_ID}")
    offset = None

    while True:
        try:
            data = get_updates(offset)
            if not data.get("ok"):
                time.sleep(5)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                post   = update.get("channel_post", {})

                # Solo mensajes del canal correcto
                if str(post.get("chat", {}).get("id", "")) != CHANNEL_ID:
                    continue

                text = post.get("text", "")
                if not text:
                    continue

                log.info(f"📨 Mensaje recibido: {text[:60].replace(chr(10),' ')}...")
                process_message(text)

        except KeyboardInterrupt:
            log.info("Bot detenido manualmente.")
            break
        except Exception as e:
            log.error(f"Error en loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
