import os
import json
import time
import random
from datetime import datetime
from contextlib import contextmanager

import requests as http_requests
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from database import init_db, SessionLocal, Lead, PushLog, User, LeadHistory, Dealer, CarModel, DealerModel

app = FastAPI(title="SCRM 线索管理系统")
app.add_middleware(SessionMiddleware, secret_key="scrm-leads-secret-key-2026")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

init_db()

# ─── 初始化超级管理员 ───

with SessionLocal() as db:
    if not db.query(User).filter(User.role == "admin").first():
        admin = User(username="admin", display_name="超级管理员", role="admin")
        admin.set_password("admin123")
        db.add(admin)
        db.commit()

# ─── 初始化经销商和车型数据 ───

DATA_FILE = os.path.join(os.path.dirname(__file__), "init_data.json")
with SessionLocal() as db:
    if db.query(Dealer).count() == 0 and os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for d in data.get("dealers", []):
            db.add(Dealer(**d))
        for m in data.get("models", []):
            db.add(CarModel(**m))
        for erp, codes in data.get("dealer_models", {}).items():
            for code in codes:
                db.add(DealerModel(erp_code=str(erp), model_code=code))
        db.commit()

# ─── 配置 ───

CONFIG = {
    "app_id": "crm_appId_10118",
    "app_secret": "e949232768be4fb5b73b027f9b5f91c4",
    "source1": "A13",
    "source2": "A1304",
    "source3": "A130403",
}

ENV_URLS = {
    "test": "https://scrm-gf-api-uat.mychery.com/api/app/chery-clue",
    "prod": "https://scrm-gf-api.mychery.com/api/app/chery-clue",
}


@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def flash(request, msg, cat="info"):
    if "_messages" not in request.session:
        request.session["_messages"] = []
    request.session["_messages"].append((cat, msg))


def get_flashed_messages(request):
    return request.session.pop("_messages", [])


def get_current_user(request):
    uid = request.session.get("user_id")
    if not uid:
        return None
    with get_db() as db:
        return db.query(User).filter(User.id == uid).first()


def get_operator(request):
    return request.session.get("display_name") or request.session.get("username") or "system"


def tpl(request, name, page, **ctx):
    ctx["request"] = request
    ctx["page"] = page
    ctx["current_user"] = get_current_user(request)
    ctx["get_flashed_messages"] = lambda with_categories=False: get_flashed_messages(request)
    return templates.TemplateResponse(name, ctx)


def require_login(request):
    if not request.session.get("user_id"):
        return RedirectResponse("/login", status_code=303)
    return None


def require_admin(request):
    r = require_login(request)
    if r:
        return r
    user = get_current_user(request)
    if not user or user.role != "admin":
        return RedirectResponse("/", status_code=303)
    return None


def log_action(db, lead_id, action, operator, field_name="", old_value="", new_value=""):
    db.add(LeadHistory(
        lead_id=str(lead_id), action=action, operator=operator,
        field_name=field_name, old_value=str(old_value), new_value=str(new_value),
    ))


def log_lead_changes(db, lead, new_data, operator):
    """比较并记录字段变更，返回变更数量"""
    field_map = {
        "lead_id": "线索ID", "name": "姓名", "tel_phone": "电话", "gender": "性别",
        "create_time": "创建时间", "source1": "source1", "source2": "source2", "source3": "source3",
        "dealer_id": "经销商", "series_id": "车系代码", "series_name": "车系名称",
        "province_name": "省份", "city_name": "城市", "county_name": "区县",
    }
    count = 0
    for attr, label in field_map.items():
        old_val = getattr(lead, attr, "") or ""
        new_val = new_data.get(attr, "") or ""
        if str(old_val) != str(new_val):
            log_action(db, lead.lead_id, "edit", operator, label, old_val, new_val)
            count += 1
    return count


# ─── 健康检查 ───

@app.head("/")
def health_check():
    return JSONResponse({"status": "ok"})


# ─── 登录注册 ───

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "mode": "login", "error": None, "success": None})


@app.post("/login")
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    with get_db() as db:
        user = db.query(User).filter(User.username == username).first()
        if user and user.check_password(password):
            request.session["user_id"] = user.id
            request.session["username"] = user.username
            request.session["display_name"] = user.display_name or user.username
            request.session["role"] = user.role
            return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "mode": "login", "error": "用户名或密码错误", "success": None})


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "mode": "register", "error": None, "success": None})


@app.post("/register")
def register_post(request: Request, username: str = Form(...), password: str = Form(...),
                  password2: str = Form(...), display_name: str = Form(default="")):
    if len(username) < 3:
        return templates.TemplateResponse("login.html", {"request": request, "mode": "register", "error": "用户名至少3位", "success": None})
    if len(password) < 6:
        return templates.TemplateResponse("login.html", {"request": request, "mode": "register", "error": "密码至少6位", "success": None})
    if password != password2:
        return templates.TemplateResponse("login.html", {"request": request, "mode": "register", "error": "两次密码不一致", "success": None})
    with get_db() as db:
        if db.query(User).filter(User.username == username).first():
            return templates.TemplateResponse("login.html", {"request": request, "mode": "register", "error": "用户名已存在", "success": None})
        user = User(username=username, display_name=display_name or username)
        user.set_password(password)
        db.add(user)
        db.commit()
    return templates.TemplateResponse("login.html", {"request": request, "mode": "login", "error": None, "success": "注册成功，请登录"})


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ─── 页面路由 ───

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    r = require_login(request)
    if r: return r
    with get_db() as db:
        total = db.query(Lead).count()
        pending = db.query(Lead).filter(Lead.push_status == "pending").count()
        success = db.query(Lead).filter(Lead.push_status == "success").count()
        fail = db.query(Lead).filter(Lead.push_status == "fail").count()
        recent = db.query(Lead).order_by(Lead.created_at.desc()).limit(10).all()
    stats = {"total": total, "pending": pending, "success": success, "fail": fail}
    return tpl(request, "dashboard.html", "dashboard", stats=stats, recent_leads=recent)


@app.get("/leads", response_class=HTMLResponse)
def leads_list(request: Request,
               q: str = Query(default=None),
               status: str = Query(default=None),
               source: str = Query(default=None),
               page: int = Query(default=1)):
    r = require_login(request)
    if r: return r
    per_page = 20
    with get_db() as db:
        query = db.query(Lead)
        if q:
            query = query.filter((Lead.name.contains(q)) | (Lead.tel_phone.contains(q)))
        if status:
            query = query.filter(Lead.push_status == status)
        if source:
            if source == "手动录入":
                query = query.filter((Lead.source_channel == "") | (Lead.source_channel == "手动录入"))
            else:
                query = query.filter(Lead.source_channel.contains(source))
        total = query.count()
        total_pages = max(1, (total + per_page - 1) // per_page)
        leads = query.order_by(Lead.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return tpl(request, "leads.html", "leads",
               leads=leads, total=total, current_page=page, total_pages=total_pages,
               q=q, status_filter=status, source_filter=source)


@app.get("/leads/add", response_class=HTMLResponse)
def lead_add_page(request: Request):
    r = require_login(request)
    if r: return r
    return tpl(request, "lead_form.html", "lead_add", lead=None)


@app.post("/leads/add")
def lead_add(request: Request,
             lead_id: str = Form(...), name: str = Form(default=""),
             tel_phone: str = Form(...), gender: str = Form(default="0"),
             create_time: str = Form(default=""),
             source_channel: str = Form(default="手动录入"),
             source1: str = Form(default="A13"), source2: str = Form(default="A1304"),
             source3: str = Form(default="A130403"),
             dealer_id: str = Form(default=""), series_id: str = Form(default=""),
             series_name: str = Form(default=""),
             province_name: str = Form(default=""), city_name: str = Form(default=""),
             county_name: str = Form(default="")):
    operator = get_operator(request)
    with get_db() as db:
        existing = db.query(Lead).filter(Lead.lead_id == lead_id).first()
        if existing:
            flash(request, f"线索ID {lead_id} 已存在", "error")
            return RedirectResponse("/leads/add", status_code=303)

        lead = Lead(
            lead_id=lead_id, name=name, tel_phone=tel_phone, gender=gender,
            create_time=create_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            source1=source1, source2=source2, source3=source3,
            dealer_id=dealer_id, series_id=series_id, series_name=series_name,
            province_name=province_name, city_name=city_name, county_name=county_name,
            source_channel=source_channel, updated_by=operator,
        )
        db.add(lead)
        log_action(db, lead_id, "create", operator, "新增线索", "", f"{name} {tel_phone}")
        db.commit()
    flash(request, "线索添加成功", "success")
    return RedirectResponse("/leads", status_code=303)


@app.get("/leads/{lid}/edit", response_class=HTMLResponse)
def lead_edit_page(request: Request, lid: int):
    r = require_login(request)
    if r: return r
    with get_db() as db:
        lead = db.query(Lead).filter(Lead.id == lid).first()
    if not lead:
        flash(request, "线索不存在", "error")
        return RedirectResponse("/leads", status_code=303)
    return tpl(request, "lead_form.html", "leads", lead=lead)


@app.post("/leads/{lid}/edit")
def lead_edit(request: Request, lid: int,
              lead_id: str = Form(...), name: str = Form(default=""),
              tel_phone: str = Form(...), gender: str = Form(default="0"),
              create_time: str = Form(default=""),
              source_channel: str = Form(default=""),
              source1: str = Form(default="A13"), source2: str = Form(default="A1304"),
              source3: str = Form(default="A130403"),
              dealer_id: str = Form(default=""), series_id: str = Form(default=""),
              series_name: str = Form(default=""),
              province_name: str = Form(default=""), city_name: str = Form(default=""),
              county_name: str = Form(default="")):
    operator = get_operator(request)
    new_data = dict(lead_id=lead_id, name=name, tel_phone=tel_phone, gender=gender,
                    create_time=create_time, source_channel=source_channel,
                    source1=source1, source2=source2, source3=source3,
                    dealer_id=dealer_id, series_id=series_id, series_name=series_name,
                    province_name=province_name, city_name=city_name, county_name=county_name)
    with get_db() as db:
        lead = db.query(Lead).filter(Lead.id == lid).first()
        if not lead:
            flash(request, "线索不存在", "error")
            return RedirectResponse("/leads", status_code=303)
        changes = log_lead_changes(db, lead, new_data, operator)
        if not changes:
            log_action(db, lead.lead_id, "edit", operator, "保存线索", "", "无字段变更")
        for k, v in new_data.items():
            setattr(lead, k, v)
        lead.updated_by = operator
        db.commit()
    flash(request, "线索已更新", "success")
    return RedirectResponse("/leads", status_code=303)


@app.get("/push-log", response_class=HTMLResponse)
def push_log_page(request: Request):
    r = require_login(request)
    if r: return r
    with get_db() as db:
        logs = db.query(PushLog).order_by(PushLog.pushed_at.desc()).limit(200).all()
    return tpl(request, "push_log.html", "push_log", logs=logs)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    r = require_login(request)
    if r: return r
    webhook_url = str(request.base_url).rstrip("/") + "/api/webhook/kuaishou"
    return tpl(request, "settings.html", "settings", config=CONFIG, webhook_url=webhook_url)


@app.post("/settings")
def settings_save(request: Request,
                  app_id: str = Form(...), app_secret: str = Form(...),
                  source1: str = Form(default="A13"), source2: str = Form(default="A1304"),
                  source3: str = Form(default="A130403")):
    operator = get_operator(request)
    CONFIG["app_id"] = app_id
    CONFIG["app_secret"] = app_secret
    CONFIG["source1"] = source1
    CONFIG["source2"] = source2
    CONFIG["source3"] = source3
    with get_db() as db:
        log_action(db, "-", "config", operator, "系统设置", "", "更新API配置")
        db.commit()
    flash(request, "配置已保存", "success")
    return RedirectResponse("/settings", status_code=303)


# ─── 超管：操作记录 ───

@app.get("/admin/logs", response_class=HTMLResponse)
def admin_logs_page(request: Request, q: str = Query(default=None), page: int = Query(default=1)):
    r = require_admin(request)
    if r: return r
    per_page = 30
    with get_db() as db:
        query = db.query(LeadHistory)
        if q:
            query = query.filter(
                (LeadHistory.operator.contains(q)) |
                (LeadHistory.lead_id.contains(q)) |
                (LeadHistory.action.contains(q))
            )
        total = query.count()
        total_pages = max(1, (total + per_page - 1) // per_page)
        logs = query.order_by(LeadHistory.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return tpl(request, "admin_logs.html", "admin_logs",
               logs=logs, total=total, current_page=page, total_pages=total_pages, q=q)


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request):
    r = require_admin(request)
    if r: return r
    with get_db() as db:
        users = db.query(User).order_by(User.created_at.desc()).all()
    return tpl(request, "admin_users.html", "admin_users", users=users)


# ─── 经销商管理 ───

@app.get("/dealers", response_class=HTMLResponse)
def dealers_page(request: Request,
                 q: str = Query(default=None),
                 province: str = Query(default=None),
                 page: int = Query(default=1)):
    r = require_login(request)
    if r: return r
    per_page = 30
    with get_db() as db:
        query = db.query(Dealer)
        if q:
            query = query.filter((Dealer.name.contains(q)) | (Dealer.erp_code.contains(q)) | (Dealer.short_name.contains(q)))
        if province:
            query = query.filter(Dealer.province == province)
        total = query.count()
        total_pages = max(1, (total + per_page - 1) // per_page)
        dealers = query.order_by(Dealer.province, Dealer.city).offset((page - 1) * per_page).limit(per_page).all()
        provinces = [r[0] for r in db.query(Dealer.province).distinct().order_by(Dealer.province).all()]
    return tpl(request, "dealers.html", "dealers",
               dealers=dealers, total=total, current_page=page, total_pages=total_pages,
               q=q, province_filter=province, provinces=provinces)


@app.get("/dealers/add", response_class=HTMLResponse)
def dealer_add_page(request: Request):
    r = require_login(request)
    if r: return r
    return tpl(request, "dealer_form.html", "dealers", dealer=None)


@app.post("/dealers/add")
def dealer_add(request: Request,
               network: str = Form(default=""), region: str = Form(default=""),
               province: str = Form(default=""), city: str = Form(default=""),
               erp_code: str = Form(...), name: str = Form(default=""),
               short_name: str = Form(default="")):
    with get_db() as db:
        if db.query(Dealer).filter(Dealer.erp_code == erp_code).first():
            flash(request, f"ERP码 {erp_code} 已存在", "error")
            return RedirectResponse("/dealers/add", status_code=303)
        db.add(Dealer(network=network, region=region, province=province, city=city,
                      erp_code=erp_code, name=name, short_name=short_name))
        db.commit()
    flash(request, "经销商添加成功", "success")
    return RedirectResponse("/dealers", status_code=303)


@app.get("/dealers/{did}/edit", response_class=HTMLResponse)
def dealer_edit_page(request: Request, did: int):
    r = require_login(request)
    if r: return r
    with get_db() as db:
        dealer = db.query(Dealer).filter(Dealer.id == did).first()
    return tpl(request, "dealer_form.html", "dealers", dealer=dealer)


@app.post("/dealers/{did}/edit")
def dealer_edit(request: Request, did: int,
                network: str = Form(default=""), region: str = Form(default=""),
                province: str = Form(default=""), city: str = Form(default=""),
                erp_code: str = Form(...), name: str = Form(default=""),
                short_name: str = Form(default="")):
    with get_db() as db:
        dealer = db.query(Dealer).filter(Dealer.id == did).first()
        if not dealer:
            flash(request, "经销商不存在", "error")
            return RedirectResponse("/dealers", status_code=303)
        dealer.network = network
        dealer.region = region
        dealer.province = province
        dealer.city = city
        dealer.erp_code = erp_code
        dealer.name = name
        dealer.short_name = short_name
        db.commit()
    flash(request, "经销商已更新", "success")
    return RedirectResponse("/dealers", status_code=303)


@app.delete("/api/dealers/{did}")
def api_delete_dealer(did: int):
    with get_db() as db:
        dealer = db.query(Dealer).filter(Dealer.id == did).first()
        if dealer:
            db.delete(dealer)
            db.commit()
            return {"success": True}
    return {"success": False, "message": "不存在"}


# ─── 车型管理 ───

@app.get("/car-models", response_class=HTMLResponse)
def car_models_page(request: Request):
    r = require_login(request)
    if r: return r
    with get_db() as db:
        models = db.query(CarModel).order_by(CarModel.category, CarModel.code).all()
    return tpl(request, "car_models.html", "car_models", models=models)


@app.get("/car-models/add", response_class=HTMLResponse)
def car_model_add_page(request: Request):
    r = require_login(request)
    if r: return r
    return tpl(request, "car_model_form.html", "car_models", model=None)


@app.post("/car-models/add")
def car_model_add(request: Request,
                  category: str = Form(default=""), code: str = Form(...), name: str = Form(default="")):
    with get_db() as db:
        if db.query(CarModel).filter(CarModel.code == code).first():
            flash(request, f"车型代码 {code} 已存在", "error")
            return RedirectResponse("/car-models/add", status_code=303)
        db.add(CarModel(category=category, code=code, name=name))
        db.commit()
    flash(request, "车型添加成功", "success")
    return RedirectResponse("/car-models", status_code=303)


@app.get("/car-models/{mid}/edit", response_class=HTMLResponse)
def car_model_edit_page(request: Request, mid: int):
    r = require_login(request)
    if r: return r
    with get_db() as db:
        model = db.query(CarModel).filter(CarModel.id == mid).first()
    return tpl(request, "car_model_form.html", "car_models", model=model)


@app.post("/car-models/{mid}/edit")
def car_model_edit(request: Request, mid: int,
                   category: str = Form(default=""), code: str = Form(...), name: str = Form(default="")):
    with get_db() as db:
        model = db.query(CarModel).filter(CarModel.id == mid).first()
        if not model:
            flash(request, "车型不存在", "error")
            return RedirectResponse("/car-models", status_code=303)
        model.category = category
        model.code = code
        model.name = name
        db.commit()
    flash(request, "车型已更新", "success")
    return RedirectResponse("/car-models", status_code=303)


@app.delete("/api/car-models/{mid}")
def api_delete_car_model(mid: int):
    with get_db() as db:
        model = db.query(CarModel).filter(CarModel.id == mid).first()
        if model:
            db.delete(model)
            db.commit()
            return {"success": True}
    return {"success": False, "message": "不存在"}


# ─── API 接口 ───

@app.get("/api/dealers")
def api_dealers_list(q: str = Query(default=""), province: str = Query(default="")):
    with get_db() as db:
        query = db.query(Dealer)
        if q:
            query = query.filter(
                (Dealer.name.contains(q)) | (Dealer.short_name.contains(q)) |
                (Dealer.erp_code.contains(q)) | (Dealer.city.contains(q)) |
                (Dealer.province.contains(q))
            )
        if province:
            query = query.filter(Dealer.province == province)
        dealers = query.order_by(Dealer.province, Dealer.city).all()
        return [{"value": d.erp_code, "text": f"{d.short_name} ({d.erp_code}) - {d.province}{d.city}"}
                for d in dealers]


@app.get("/api/car-models-list")
def api_car_models_list(dealer: str = Query(default="")):
    with get_db() as db:
        if dealer:
            codes = [r.model_code for r in db.query(DealerModel).filter(DealerModel.erp_code == dealer).all()]
            if codes:
                models = db.query(CarModel).filter(CarModel.code.in_(codes)).order_by(CarModel.category, CarModel.code).all()
                return [{"value": m.code, "text": f"{m.name} ({m.code})", "name": m.name} for m in models]
        models = db.query(CarModel).order_by(CarModel.category, CarModel.code).all()
        return [{"value": m.code, "text": f"{m.name} ({m.code})", "name": m.name} for m in models]


@app.get("/api/provinces")
def api_provinces():
    with get_db() as db:
        provinces = [r[0] for r in db.query(Dealer.province).distinct().order_by(Dealer.province).all() if r[0]]
        return provinces


@app.get("/api/cities")
def api_cities(province: str = Query(default="")):
    with get_db() as db:
        query = db.query(Dealer.city).distinct()
        if province:
            query = query.filter(Dealer.province == province)
        cities = [r[0] for r in query.order_by(Dealer.city).all() if r[0]]
        return cities


@app.delete("/api/leads/{lid}")
async def api_delete_lead(request: Request, lid: int):
    operator = get_operator(request)
    with get_db() as db:
        lead = db.query(Lead).filter(Lead.id == lid).first()
        if lead:
            log_action(db, lead.lead_id, "delete", operator, "删除线索", f"{lead.name} {lead.tel_phone}", "")
            db.delete(lead)
            db.commit()
            return {"success": True}
    return {"success": False, "message": "线索不存在"}


@app.post("/api/push")
async def api_push(request: Request):
    body = await request.json()
    ids = body.get("ids", [])
    env = body.get("env", "test")
    operator = get_operator(request)

    if not ids:
        return JSONResponse({"success": False, "message": "未选择线索"})

    base_url = ENV_URLS.get(env, ENV_URLS["test"])
    env_label = "正式环境" if env == "prod" else "测试环境"

    try:
        token_resp = http_requests.get(
            f"{base_url}/api/clue/channel/getToken",
            params={"appId": CONFIG["app_id"], "appSecret": CONFIG["app_secret"]},
            timeout=15,
        )
        token_data = token_resp.json()
        if token_data.get("code") != "0":
            return JSONResponse({"success": False, "message": f"Token获取失败: {token_data.get('msg')}"})
        token = token_data["data"]
    except Exception as e:
        return JSONResponse({"success": False, "message": f"Token请求异常: {e}"})

    success_count = 0
    fail_count = 0

    with get_db() as db:
        leads = db.query(Lead).filter(Lead.id.in_(ids)).all()

        for lead in leads:
            api_data = [lead.to_api_dict()]
            try:
                resp = http_requests.post(
                    f"{base_url}/api/clue/push/channel",
                    headers={"Content-Type": "application/json", "x-csrf-token": token},
                    json=api_data,
                    timeout=30,
                )
                result = resp.json()
                code = str(result.get("code", ""))
                msg = result.get("msg", "")

                db.add(PushLog(
                    lead_id=lead.lead_id, tel_phone=lead.tel_phone, name=lead.name,
                    environment=env_label, result_code=code, result_msg=msg, pushed_by=operator,
                ))
                log_action(db, lead.lead_id, "push", operator, "推送线索",
                           "", f"{env_label} code={code} {msg}")

                if code == "0":
                    lead.push_status = "success"
                    lead.push_msg = msg
                    lead.push_time = datetime.now()
                    success_count += 1
                else:
                    lead.push_status = "fail"
                    lead.push_msg = msg
                    fail_count += 1

            except Exception as e:
                lead.push_status = "fail"
                lead.push_msg = str(e)
                fail_count += 1
                db.add(PushLog(
                    lead_id=lead.lead_id, tel_phone=lead.tel_phone, name=lead.name,
                    environment=env_label, result_code="error", result_msg=str(e), pushed_by=operator,
                ))

            time.sleep(random.uniform(0.5, 2.0))

        db.commit()

    return JSONResponse({"success": True, "success_count": success_count, "fail_count": fail_count})


@app.post("/api/webhook/kuaishou")
async def webhook_kuaishou(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"code": -1, "msg": "invalid json"})

    leads_data = body if isinstance(body, list) else [body]

    with get_db() as db:
        count = 0
        for item in leads_data:
            lead_id = (item.get("clue_id") or item.get("id")
                       or item.get("lead_id") or item.get("ID") or "")
            phone = (item.get("phone") or item.get("telPhone")
                     or item.get("coupon_phone") or "")

            if not phone:
                continue

            if lead_id:
                existing = db.query(Lead).filter(Lead.lead_id == str(lead_id)).first()
                if existing:
                    continue

            if not lead_id:
                lead_id = f"ks_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}"

            name = (item.get("consumer_name") or item.get("name")
                    or item.get("姓名") or "")
            create_time = (item.get("create_time_date_time")
                           or item.get("createTime") or item.get("create_time")
                           or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            province = (item.get("province_name") or item.get("provinceName")
                        or item.get("intention_province_name") or "")
            city = (item.get("city_name") or item.get("cityName")
                    or item.get("intention_city_name") or "")

            lead = Lead(
                lead_id=str(lead_id), name=name, tel_phone=str(phone),
                gender=str(item.get("gender", "0")), create_time=create_time,
                source1=CONFIG["source1"], source2=CONFIG["source2"], source3=CONFIG["source3"],
                province_name=province, city_name=city,
                county_name=item.get("countyName") or item.get("county_name") or "",
                source_channel="快手",
            )
            db.add(lead)
            log_action(db, lead_id, "receive", "快手Webhook", "接收线索", "", f"{name} {phone}")
            count += 1

        db.commit()

    return JSONResponse({"code": 0, "msg": "success", "received": count})


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
