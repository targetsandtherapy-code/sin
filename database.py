import hashlib
import os
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///./leads.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, index=True)
    password_hash = Column(String(128))
    display_name = Column(String(64), default="")
    role = Column(String(16), default="user")
    created_at = Column(DateTime, default=datetime.now)

    def set_password(self, raw):
        salt = os.urandom(8).hex()
        h = hashlib.sha256((salt + raw).encode()).hexdigest()
        self.password_hash = f"{salt}${h}"

    def check_password(self, raw):
        if not self.password_hash or "$" not in self.password_hash:
            return False
        salt, h = self.password_hash.split("$", 1)
        return hashlib.sha256((salt + raw).encode()).hexdigest() == h


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String(128), unique=True, index=True)
    name = Column(String(64), default="")
    tel_phone = Column(String(20), index=True)
    gender = Column(String(4), default="0")
    create_time = Column(String(32), default="")
    source1 = Column(String(16), default="A13")
    source2 = Column(String(16), default="A1304")
    source3 = Column(String(16), default="A130403")
    dealer_id = Column(String(32), default="")
    series_id = Column(String(32), default="")
    series_name = Column(String(64), default="")
    province_name = Column(String(32), default="")
    city_name = Column(String(32), default="")
    county_name = Column(String(32), default="")
    source_channel = Column(String(32), default="")
    push_status = Column(String(16), default="pending", index=True)
    push_msg = Column(Text, default="")
    push_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_by = Column(String(64), default="")

    def to_api_dict(self):
        d = {}
        if self.lead_id:
            d["id"] = self.lead_id
        if self.create_time:
            d["createTime"] = self.create_time
        if self.source1:
            d["source1"] = self.source1
        if self.source2:
            d["source2"] = self.source2
        if self.source3:
            d["source3"] = self.source3
        if self.name:
            d["name"] = self.name
        if self.tel_phone:
            d["telPhone"] = self.tel_phone
        d["gender"] = self.gender or "0"
        if self.dealer_id:
            d["dealerId"] = self.dealer_id
        if self.series_id:
            d["seriesId"] = self.series_id
        if self.series_name:
            d["seriesName"] = self.series_name
        if self.province_name:
            d["provinceName"] = self.province_name
        if self.city_name:
            d["cityName"] = self.city_name
        if self.county_name:
            d["countyName"] = self.county_name
        return d


class PushLog(Base):
    __tablename__ = "push_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String(128), index=True)
    tel_phone = Column(String(20), default="")
    name = Column(String(64), default="")
    environment = Column(String(16), default="测试环境")
    result_code = Column(String(16), default="")
    result_msg = Column(Text, default="")
    pushed_by = Column(String(64), default="")
    pushed_at = Column(DateTime, default=datetime.now)


class Dealer(Base):
    __tablename__ = "dealers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    network = Column(String(16), default="")
    region = Column(String(32), default="")
    province = Column(String(32), default="", index=True)
    city = Column(String(32), default="", index=True)
    erp_code = Column(String(32), unique=True, index=True)
    name = Column(String(128), default="")
    short_name = Column(String(64), default="")


class CarModel(Base):
    __tablename__ = "car_models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(32), default="")
    code = Column(String(32), unique=True, index=True)
    name = Column(String(64), default="")


class DealerModel(Base):
    __tablename__ = "dealer_models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    erp_code = Column(String(32), index=True)
    model_code = Column(String(32), index=True)


class LeadHistory(Base):
    __tablename__ = "lead_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(String(128), index=True)
    action = Column(String(16))
    field_name = Column(String(32), default="")
    old_value = Column(Text, default="")
    new_value = Column(Text, default="")
    operator = Column(String(64), default="")
    created_at = Column(DateTime, default=datetime.now)


def init_db():
    Base.metadata.create_all(bind=engine)
