from flask import Flask, render_template, request, jsonify, session
import json, os, datetime, uuid

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "safegrowth-secret-2024")

DATA_FILE = "data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "operations": [], "news": [], "trades_screenshots": [], "motivational": ""}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)

@app.route("/")
def index():
    ref = request.args.get("ref", "")
    return render_template("index.html", ref=ref)

# ── AUTH ──────────────────────────────────────────────────────────────────────

@app.route("/api/login", methods=["POST"])
def login():
    d = request.json
    data = load_data()
    phone = d.get("phone","").strip()
    pin   = d.get("pin","").strip()
    for uid, u in data["users"].items():
        if u["phone"] == phone and u["pin"] == pin:
            session["uid"] = uid
            return jsonify({"ok": True, "user": {k: v for k,v in u.items() if k != "pin" and k != "pin_retiro"}})
    return jsonify({"ok": False, "msg": "Teléfono o PIN incorrecto"})

@app.route("/api/register", methods=["POST"])
def register():
    d = request.json
    data = load_data()
    phone = d.get("phone","").strip()
    for u in data["users"].values():
        if u["phone"] == phone:
            return jsonify({"ok": False, "msg": "Teléfono ya registrado"})
    uid = str(uuid.uuid4())[:8]
    ref_code = str(uuid.uuid4())[:6].upper()
    referred_by = d.get("ref_code","").strip().upper()
    # validate referrer
    referrer_uid = None
    for ruid, ru in data["users"].items():
        if ru.get("ref_code","") == referred_by:
            referrer_uid = ruid
            break
    data["users"][uid] = {
        "uid": uid, "name": d.get("name",""), "email": d.get("email",""),
        "phone": phone, "pin": d.get("pin",""), "pin_retiro": d.get("pin_retiro",""),
        "ref_code": ref_code, "referred_by": referrer_uid,
        "capital_bot": 0.0, "ganancia_hoy": 0.0, "capital_acciones": 0.0,
        "movimientos": [], "acciones": {}, "ganancias": {"hoy":0,"semana":0,"mes":0,"todo":0},
        "dividendos": [], "depositos_pendientes": [], "retiros_pendientes": [],
        "mensajes": [], "created": str(datetime.datetime.now())
    }
    save_data(data)
    session["uid"] = uid
    return jsonify({"ok": True, "user": data["users"][uid]})

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/me")
def me():
    uid = session.get("uid")
    if not uid:
        return jsonify({"ok": False})
    data = load_data()
    u = data["users"].get(uid)
    if not u:
        return jsonify({"ok": False})
    # count active referrals
    referidos = sum(1 for x in data["users"].values() if x.get("referred_by") == uid and x.get("capital_bot",0) > 0)
    safe = {k: v for k,v in u.items() if k not in ("pin","pin_retiro")}
    safe["referidos_activos"] = referidos
    return jsonify({"ok": True, "user": safe})

# ── DEPOSITS ──────────────────────────────────────────────────────────────────

@app.route("/api/depositar", methods=["POST"])
def depositar():
    uid = session.get("uid")
    if not uid: return jsonify({"ok": False, "msg": "No autenticado"})
    d = request.json
    data = load_data()
    dep = {"id": str(uuid.uuid4())[:8], "uid": uid, "monto": float(d.get("monto",0)),
           "tipo": d.get("tipo","bot"), "fecha": str(datetime.datetime.now()), "estado": "pendiente"}
    data["users"][uid]["depositos_pendientes"].append(dep)
    save_data(data)
    return jsonify({"ok": True, "msg": "Depósito notificado. El admin confirmará pronto."})

@app.route("/api/retirar", methods=["POST"])
def retirar():
    uid = session.get("uid")
    if not uid: return jsonify({"ok": False, "msg": "No autenticado"})
    d = request.json
    data = load_data()
    u = data["users"][uid]
    if d.get("pin_retiro","") != u["pin_retiro"]:
        return jsonify({"ok": False, "msg": "PIN de retiro incorrecto"})
    monto = float(d.get("monto", 0))
    if monto < 5:
        return jsonify({"ok": False, "msg": "Monto mínimo $5"})
    if monto > u["capital_bot"]:
        return jsonify({"ok": False, "msg": "Saldo insuficiente"})
    # check open operations
    open_ops = [o for o in data["operations"] if o["estado"] == "abierta"]
    if open_ops:
        return jsonify({"ok": False, "msg": "Hay operaciones activas. Espera que cierren."})
    ret = {"id": str(uuid.uuid4())[:8], "uid": uid, "monto": monto,
           "metodo": d.get("metodo","usdt"), "datos": d.get("datos",""),
           "fecha": str(datetime.datetime.now()), "estado": "pendiente"}
    data["users"][uid]["retiros_pendientes"].append(ret)
    save_data(data)
    return jsonify({"ok": True, "msg": "Retiro solicitado. El admin procesará pronto."})

# ── ACCIONES ──────────────────────────────────────────────────────────────────

@app.route("/api/acciones/mercado")
def mercado():
    data = load_data()
    return jsonify(data.get("acciones_catalogo", {}))

@app.route("/api/acciones/comprar", methods=["POST"])
def comprar_accion():
    uid = session.get("uid")
    if not uid: return jsonify({"ok": False, "msg": "No autenticado"})
    d = request.json
    data = load_data()
    u = data["users"][uid]
    if d.get("pin","") != u["pin"]:
        return jsonify({"ok": False, "msg": "PIN incorrecto"})
    ticker = d.get("ticker","").upper()
    cantidad = float(d.get("cantidad", 0))
    sol = {"id": str(uuid.uuid4())[:8], "uid": uid, "ticker": ticker,
           "cantidad": cantidad, "fecha": str(datetime.datetime.now()), "estado": "pendiente"}
    data["users"][uid].setdefault("solicitudes_acciones",[]).append(sol)
    save_data(data)
    return jsonify({"ok": True, "msg": "Solicitud enviada. El admin confirmará."})

# ── GANANCIAS ─────────────────────────────────────────────────────────────────

@app.route("/api/ganancias")
def ganancias():
    uid = session.get("uid")
    if not uid: return jsonify({"ok": False})
    data = load_data()
    u = data["users"][uid]
    return jsonify({"ok": True, "ganancias": u.get("ganancias",{}), "dividendos": u.get("dividendos",[])})

# ── OPERACIONES PÚBLICAS ───────────────────────────────────────────────────────

@app.route("/api/operaciones")
def operaciones():
    data = load_data()
    ops = data.get("operations", [])
    return jsonify({"ok": True, "operaciones": ops, "motivacional": data.get("motivational","")})

@app.route("/api/noticias")
def noticias():
    data = load_data()
    return jsonify({"ok": True, "noticias": data.get("news", [])})

@app.route("/api/trades_capturas")
def trades_capturas():
    data = load_data()
    return jsonify({"ok": True, "capturas": data.get("trades_screenshots", [])})

# ── MENSAJES ──────────────────────────────────────────────────────────────────

@app.route("/api/mensaje", methods=["POST"])
def mensaje():
    uid = session.get("uid")
    if not uid: return jsonify({"ok": False, "msg": "No autenticado"})
    d = request.json
    data = load_data()
    msg = {"id": str(uuid.uuid4())[:8], "uid": uid, "texto": d.get("texto",""),
           "fecha": str(datetime.datetime.now()), "leido": False}
    data["users"][uid].setdefault("mensajes",[]).append(msg)
    save_data(data)
    return jsonify({"ok": True})

# ── CAMBIO PIN ────────────────────────────────────────────────────────────────

@app.route("/api/cambiar_pin", methods=["POST"])
def cambiar_pin():
    uid = session.get("uid")
    if not uid: return jsonify({"ok": False, "msg": "No autenticado"})
    d = request.json
    data = load_data()
    u = data["users"][uid]
    tipo = d.get("tipo","acceso")
    key = "pin" if tipo == "acceso" else "pin_retiro"
    if d.get("pin_actual","") != u[key]:
        return jsonify({"ok": False, "msg": "PIN actual incorrecto"})
    data["users"][uid][key] = d.get("nuevo_pin","")
    save_data(data)
    return jsonify({"ok": True, "msg": "PIN actualizado"})

# ── RECUPERAR PIN ─────────────────────────────────────────────────────────────

@app.route("/api/recuperar_pin", methods=["POST"])
def recuperar_pin():
    d = request.json
    data = load_data()
    phone = d.get("phone","").strip()
    email = d.get("email","").strip()
    nuevo_pin = d.get("nuevo_pin","").strip()
    for uid, u in data["users"].items():
        if u["phone"] == phone and u["email"] == email:
            data["users"][uid]["pin"] = nuevo_pin
            save_data(data)
            return jsonify({"ok": True, "msg": "PIN actualizado correctamente"})
    return jsonify({"ok": False, "msg": "Teléfono y correo no coinciden"})

# ── ADMIN ─────────────────────────────────────────────────────────────────────

ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234")

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    d = request.json
    if d.get("pin","") == ADMIN_PIN:
        session["admin"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "PIN incorrecto"})

def require_admin():
    return session.get("admin") == True

@app.route("/api/admin/stats")
def admin_stats():
    if not require_admin(): return jsonify({"ok": False})
    data = load_data()
    users = data["users"]
    total_bot = sum(u.get("capital_bot",0) for u in users.values())
    total_acc = sum(u.get("capital_acciones",0) for u in users.values())
    total_gan = sum(u.get("ganancias",{}).get("todo",0) for u in users.values())
    dep_pend = sum(len(u.get("depositos_pendientes",[])) for u in users.values())
    ret_pend = sum(len(u.get("retiros_pendientes",[])) for u in users.values())
    msgs = sum(len([m for m in u.get("mensajes",[]) if not m.get("leido")]) for u in users.values())
    return jsonify({"ok": True, "stats": {
        "usuarios": len(users), "capital_bot": total_bot, "capital_acciones": total_acc,
        "ganancias": total_gan, "dep_pendientes": dep_pend, "ret_pendientes": ret_pend, "mensajes": msgs
    }})

@app.route("/api/admin/usuarios")
def admin_usuarios():
    if not require_admin(): return jsonify({"ok": False})
    data = load_data()
    users = [{k: v for k,v in u.items() if k not in ("pin","pin_retiro")} for u in data["users"].values()]
    return jsonify({"ok": True, "users": users})

@app.route("/api/admin/operacion", methods=["POST"])
def admin_operacion():
    if not require_admin(): return jsonify({"ok": False})
    d = request.json
    data = load_data()
    op = {"id": str(uuid.uuid4())[:8], "estrategia": d.get("estrategia",""),
          "entry": d.get("entry",""), "tp_precio": d.get("tp_precio",""),
          "tp_pct": float(d.get("tp_pct",0)), "capital_pct": float(d.get("capital_pct",0)),
          "fecha_apertura": d.get("fecha_apertura",""), "hora_apertura": d.get("hora_apertura",""),
          "estado": d.get("estado","abierta"), "fecha_cierre": d.get("fecha_cierre",""),
          "hora_cierre": d.get("hora_cierre","")}
    data["operations"].append(op)
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/admin/registrar_ganancia", methods=["POST"])
def admin_registrar_ganancia():
    if not require_admin(): return jsonify({"ok": False})
    d = request.json
    data = load_data()
    op_id = d.get("op_id","")
    pct = float(d.get("pct", 0))
    # find op
    for op in data["operations"]:
        if op["id"] == op_id:
            op["estado"] = "cerrada"
            op["ganancia_pct"] = pct
            break
    # distribute to users
    today = str(datetime.date.today())
    for uid, u in data["users"].items():
        capital = u.get("capital_bot", 0)
        if capital <= 0: continue
        referidos = sum(1 for x in data["users"].values() if x.get("referred_by") == uid and x.get("capital_bot",0) > 0)
        pct_usuario = 0.75 if referidos > 0 else 0.50
        ganancia = capital * (pct / 100) * pct_usuario
        data["users"][uid]["capital_bot"] = capital + ganancia
        data["users"][uid]["ganancia_hoy"] = u.get("ganancia_hoy", 0) + ganancia
        g = data["users"][uid].setdefault("ganancias", {"hoy":0,"semana":0,"mes":0,"todo":0})
        g["hoy"] = g.get("hoy",0) + ganancia
        g["semana"] = g.get("semana",0) + ganancia
        g["mes"] = g.get("mes",0) + ganancia
        g["todo"] = g.get("todo",0) + ganancia
        data["users"][uid]["movimientos"].append({"tipo":"ganancia","monto":ganancia,"fecha":today,"nota":d.get("nota","")})
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/admin/confirmar_deposito", methods=["POST"])
def admin_confirmar_deposito():
    if not require_admin(): return jsonify({"ok": False})
    d = request.json
    uid = d.get("uid","")
    dep_id = d.get("dep_id","")
    data = load_data()
    deps = data["users"][uid].get("depositos_pendientes",[])
    for dep in deps:
        if dep["id"] == dep_id:
            dep["estado"] = "confirmado"
            monto = dep["monto"]
            data["users"][uid]["capital_bot"] = data["users"][uid].get("capital_bot",0) + monto
            data["users"][uid]["movimientos"].append({"tipo":"deposito","monto":monto,"fecha":str(datetime.date.today())})
            break
    data["users"][uid]["depositos_pendientes"] = [x for x in deps if x["id"] != dep_id]
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/admin/confirmar_retiro", methods=["POST"])
def admin_confirmar_retiro():
    if not require_admin(): return jsonify({"ok": False})
    d = request.json
    uid = d.get("uid","")
    ret_id = d.get("ret_id","")
    data = load_data()
    rets = data["users"][uid].get("retiros_pendientes",[])
    for ret in rets:
        if ret["id"] == ret_id:
            ret["estado"] = "procesado"
            monto = ret["monto"]
            comision = monto * 0.03
            neto = monto - comision
            data["users"][uid]["capital_bot"] = max(0, data["users"][uid].get("capital_bot",0) - monto)
            data["users"][uid]["movimientos"].append({"tipo":"retiro","monto":-neto,"fecha":str(datetime.date.today())})
            break
    data["users"][uid]["retiros_pendientes"] = [x for x in rets if x["id"] != ret_id]
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/admin/accion_catalogo", methods=["POST"])
def admin_accion_catalogo():
    if not require_admin(): return jsonify({"ok": False})
    d = request.json
    data = load_data()
    ticker = d.get("ticker","").upper()
    data.setdefault("acciones_catalogo",{})[ticker] = {
        "ticker": ticker, "nombre": d.get("nombre",""), "logo": d.get("logo","📈"),
        "precio": float(d.get("precio",0)), "cambio": d.get("cambio","0%"),
        "descripcion": d.get("descripcion",""), "dividendo_info": d.get("dividendo_info","")
    }
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/admin/confirmar_compra_accion", methods=["POST"])
def admin_confirmar_compra_accion():
    if not require_admin(): return jsonify({"ok": False})
    d = request.json
    uid = d.get("uid","")
    sol_id = d.get("sol_id","")
    precio_real = float(d.get("precio_real", 0))
    data = load_data()
    sols = data["users"][uid].get("solicitudes_acciones",[])
    for sol in sols:
        if sol["id"] == sol_id:
            ticker = sol["ticker"]
            cant_bruta = sol["cantidad"]
            cant_neta = cant_bruta * 0.98  # 2% fee
            costo = cant_bruta * precio_real
            portafolio = data["users"][uid].setdefault("acciones",{})
            portafolio[ticker] = portafolio.get(ticker, 0) + cant_neta
            data["users"][uid]["capital_acciones"] = data["users"][uid].get("capital_acciones",0) + costo
            sol["estado"] = "confirmado"
            # referral bonus
            ref_uid = data["users"][uid].get("referred_by")
            if ref_uid and ref_uid in data["users"]:
                bonus = cant_neta * 0.02
                data["users"][ref_uid]["acciones"][ticker] = data["users"][ref_uid].get("acciones",{}).get(ticker,0) + bonus
            break
    data["users"][uid]["solicitudes_acciones"] = [x for x in sols if x["id"] != sol_id]
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/admin/dividendo", methods=["POST"])
def admin_dividendo():
    if not require_admin(): return jsonify({"ok": False})
    d = request.json
    ticker = d.get("ticker","").upper()
    div_por_accion = float(d.get("dividendo",0))
    nota = d.get("nota","")
    data = load_data()
    for uid, u in data["users"].items():
        acciones_usuario = u.get("acciones",{}).get(ticker, 0)
        if acciones_usuario > 0:
            monto = acciones_usuario * div_por_accion
            data["users"][uid]["capital_acciones"] = u.get("capital_acciones",0) + monto
            data["users"][uid].setdefault("dividendos",[]).append(
                {"ticker": ticker, "monto": monto, "fecha": str(datetime.date.today()), "nota": nota})
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/admin/noticia", methods=["POST"])
def admin_noticia():
    if not require_admin(): return jsonify({"ok": False})
    d = request.json
    data = load_data()
    noticia = {"id": str(uuid.uuid4())[:8], "fuente": d.get("fuente",""), "titulo": d.get("titulo",""),
               "resumen": d.get("resumen",""), "categoria": d.get("categoria",""),
               "fecha": str(datetime.date.today())}
    data.setdefault("news",[]).append(noticia)
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/admin/captura", methods=["POST"])
def admin_captura():
    if not require_admin(): return jsonify({"ok": False})
    d = request.json
    data = load_data()
    data.setdefault("trades_screenshots",[]).append({"url": d.get("url",""), "desc": d.get("desc",""), "fecha": str(datetime.date.today())})
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/admin/motivacional", methods=["POST"])
def admin_motivacional():
    if not require_admin(): return jsonify({"ok": False})
    d = request.json
    data = load_data()
    data["motivational"] = d.get("frase","")
    save_data(data)
    return jsonify({"ok": True})

@app.route("/api/admin/depositos_pendientes")
def admin_depositos():
    if not require_admin(): return jsonify({"ok": False})
    data = load_data()
    result = []
    for uid, u in data["users"].items():
        for dep in u.get("depositos_pendientes",[]):
            result.append({**dep, "nombre": u["name"], "telefono": u["phone"]})
    return jsonify({"ok": True, "depositos": result})

@app.route("/api/admin/retiros_pendientes")
def admin_retiros():
    if not require_admin(): return jsonify({"ok": False})
    data = load_data()
    result = []
    for uid, u in data["users"].items():
        for ret in u.get("retiros_pendientes",[]):
            result.append({**ret, "nombre": u["name"], "telefono": u["phone"]})
    return jsonify({"ok": True, "retiros": result})

@app.route("/api/admin/mensajes")
def admin_mensajes():
    if not require_admin(): return jsonify({"ok": False})
    data = load_data()
    result = []
    for uid, u in data["users"].items():
        for msg in u.get("mensajes",[]):
            if not msg.get("leido"):
                result.append({**msg, "nombre": u["name"]})
    return jsonify({"ok": True, "mensajes": result})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
