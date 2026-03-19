from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///./leads.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


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
    pushed_at = Column(DateTime, default=datetime.now)


def init_db():
    Base.metadata.create_all(bind=engine)
