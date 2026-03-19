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

from database import init_db, SessionLocal, Lead, PushLog

app = FastAPI(title="SCRM 线索管理系统")
app.add_middleware(SessionMiddleware, secret_key="scrm-leads-secret-key-2026")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

init_db()

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
    msgs = request.session.pop("_messages", [])
    return msgs


def tpl(request, name, page, **ctx):
    ctx["request"] = request
    ctx["page"] = page
    ctx["get_flashed_messages"] = lambda with_categories=False: get_flashed_messages(request)
    return templates.TemplateResponse(name, ctx)


# ─── 页面路由 ───

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
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
    return tpl(request, "lead_form.html", "lead_add", lead=None)


@app.post("/leads/add")
def lead_add(request: Request,
             lead_id: str = Form(...), name: str = Form(default=""),
             tel_phone: str = Form(...), gender: str = Form(default="0"),
             create_time: str = Form(default=""),
             source1: str = Form(default="A13"), source2: str = Form(default="A1304"),
             source3: str = Form(default="A130403"),
             dealer_id: str = Form(default=""), series_id: str = Form(default=""),
             series_name: str = Form(default=""),
             province_name: str = Form(default=""), city_name: str = Form(default=""),
             county_name: str = Form(default="")):
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
            source_channel="手动录入",
        )
        db.add(lead)
        db.commit()
    flash(request, "线索添加成功", "success")
    return RedirectResponse("/leads", status_code=303)


@app.get("/leads/{lid}/edit", response_class=HTMLResponse)
def lead_edit_page(request: Request, lid: int):
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
              source1: str = Form(default="A13"), source2: str = Form(default="A1304"),
              source3: str = Form(default="A130403"),
              dealer_id: str = Form(default=""), series_id: str = Form(default=""),
              series_name: str = Form(default=""),
              province_name: str = Form(default=""), city_name: str = Form(default=""),
              county_name: str = Form(default="")):
    with get_db() as db:
        lead = db.query(Lead).filter(Lead.id == lid).first()
        if not lead:
            flash(request, "线索不存在", "error")
            return RedirectResponse("/leads", status_code=303)
        lead.lead_id = lead_id
        lead.name = name
        lead.tel_phone = tel_phone
        lead.gender = gender
        lead.create_time = create_time
        lead.source1 = source1
        lead.source2 = source2
        lead.source3 = source3
        lead.dealer_id = dealer_id
        lead.series_id = series_id
        lead.series_name = series_name
        lead.province_name = province_name
        lead.city_name = city_name
        lead.county_name = county_name
        db.commit()
    flash(request, "线索已更新", "success")
    return RedirectResponse("/leads", status_code=303)


@app.get("/push-log", response_class=HTMLResponse)
def push_log_page(request: Request):
    with get_db() as db:
        logs = db.query(PushLog).order_by(PushLog.pushed_at.desc()).limit(200).all()
    return tpl(request, "push_log.html", "push_log", logs=logs)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    webhook_url = str(request.base_url).rstrip("/") + "/api/webhook/kuaishou"
    return tpl(request, "settings.html", "settings", config=CONFIG, webhook_url=webhook_url)


@app.post("/settings")
def settings_save(request: Request,
                  app_id: str = Form(...), app_secret: str = Form(...),
                  source1: str = Form(default="A13"), source2: str = Form(default="A1304"),
                  source3: str = Form(default="A130403")):
    CONFIG["app_id"] = app_id
    CONFIG["app_secret"] = app_secret
    CONFIG["source1"] = source1
    CONFIG["source2"] = source2
    CONFIG["source3"] = source3
    flash(request, "配置已保存", "success")
    return RedirectResponse("/settings", status_code=303)


# ─── API 接口 ───

@app.delete("/api/leads/{lid}")
def api_delete_lead(lid: int):
    with get_db() as db:
        lead = db.query(Lead).filter(Lead.id == lid).first()
        if lead:
            db.delete(lead)
            db.commit()
            return {"success": True}
    return {"success": False, "message": "线索不存在"}


@app.post("/api/push")
async def api_push(request: Request):
    body = await request.json()
    ids = body.get("ids", [])
    env = body.get("env", "test")

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

                log = PushLog(
                    lead_id=lead.lead_id, tel_phone=lead.tel_phone, name=lead.name,
                    environment=env_label, result_code=code, result_msg=msg,
                )
                db.add(log)

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
                    environment=env_label, result_code="error", result_msg=str(e),
                ))

            time.sleep(random.uniform(0.5, 2.0))

        db.commit()

    return JSONResponse({"success": True, "success_count": success_count, "fail_count": fail_count})


@app.post("/api/webhook/kuaishou")
async def webhook_kuaishou(request: Request):
    """快手线索推送 Webhook 接收接口"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"code": -1, "msg": "invalid json"})

    leads_data = body if isinstance(body, list) else [body]

    with get_db() as db:
        count = 0
        for item in leads_data:
            lead_id = item.get("id") or item.get("lead_id") or item.get("ID", "")
            phone = item.get("telPhone") or item.get("phone") or item.get("电话", "")

            if not phone:
                continue

            existing = db.query(Lead).filter(Lead.lead_id == str(lead_id)).first() if lead_id else None
            if existing:
                continue

            if not lead_id:
                lead_id = f"ks_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}"

            lead = Lead(
                lead_id=str(lead_id),
                name=item.get("name") or item.get("姓名", ""),
                tel_phone=str(phone),
                gender=str(item.get("gender", "0")),
                create_time=item.get("createTime") or item.get("create_time")
                            or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                source1=CONFIG["source1"],
                source2=CONFIG["source2"],
                source3=CONFIG["source3"],
                province_name=item.get("provinceName") or item.get("province", ""),
                city_name=item.get("cityName") or item.get("city", ""),
                county_name=item.get("countyName") or item.get("county", ""),
                source_channel="快手",
            )
            db.add(lead)
            count += 1

        db.commit()

    return JSONResponse({"code": 0, "msg": "success", "received": count})


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
