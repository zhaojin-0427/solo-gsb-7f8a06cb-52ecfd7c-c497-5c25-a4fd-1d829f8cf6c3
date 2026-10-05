"""本地遮挡日照窗口计算服务。

核心规则：
- 测点按方位角环形排序，相邻点线性插值，末点到首点跨 360° 连续插值；
- 当地日期 00:00 至次日 00:00 转成 UTC，逐个 UTC 整分钟计算；
- 太阳仰角（无折射）严格大于 0° 且严格高于该方位遮挡角才计为直晒；
- 相邻命中分钟合并为半开时段 [start, end)，按本地时间带 UTC 偏移显示；
- 夏令时切换日按实际 23/25 小时处理，重复本地时刻不合并、不漏算。
"""

from __future__ import annotations

import bisect
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import azimuth as sun_azimuth
from astral.sun import elevation as sun_elevation
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

ALLOWED_TIMEZONES = ("Asia/Shanghai", "Europe/Berlin", "America/New_York")
MIN_POINTS = 2
MAX_POINTS = 12

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="本地遮挡日照窗口")


# ---------------------------------------------------------------- 数据模型

class HorizonPoint(BaseModel):
    azimuth: float
    elevation: float

    @field_validator("azimuth")
    @classmethod
    def _check_azimuth(cls, v: float) -> float:
        if not math.isfinite(v) or not (0.0 <= v < 360.0):
            raise ValueError("方位角必须在 [0, 360) 范围内（正北为 0°，顺时针）")
        return v

    @field_validator("elevation")
    @classmethod
    def _check_elevation(cls, v: float) -> float:
        if not math.isfinite(v) or not (0.0 <= v <= 80.0):
            raise ValueError("遮挡仰角必须在 0～80° 范围内")
        return v


class CalcRequest(BaseModel):
    date: date
    latitude: float
    longitude: float
    timezone: str
    points: list[HorizonPoint]

    @field_validator("latitude")
    @classmethod
    def _check_latitude(cls, v: float) -> float:
        if not math.isfinite(v) or not (-66.0 <= v <= 66.0):
            raise ValueError("纬度必须在 -66～66 范围内")
        return v

    @field_validator("longitude")
    @classmethod
    def _check_longitude(cls, v: float) -> float:
        if not math.isfinite(v) or not (-180.0 <= v <= 180.0):
            raise ValueError("经度必须在 -180～180 范围内")
        return v

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, v: str) -> str:
        if v not in ALLOWED_TIMEZONES:
            raise ValueError(
                "时区仅支持 " + "、".join(ALLOWED_TIMEZONES)
            )
        return v

    @field_validator("points")
    @classmethod
    def _check_points(cls, v: list[HorizonPoint]) -> list[HorizonPoint]:
        if not (MIN_POINTS <= len(v) <= MAX_POINTS):
            raise ValueError(f"测点数量必须在 {MIN_POINTS}～{MAX_POINTS} 个之间")
        seen: set[float] = set()
        for p in v:
            if p.azimuth in seen:
                raise ValueError(f"方位角 {p.azimuth:g}° 重复，测点方位角不得重复")
            seen.add(p.azimuth)
        return v


# ---------------------------------------------------------------- 错误处理

FIELD_NAMES = {
    "date": "日期",
    "latitude": "纬度",
    "longitude": "经度",
    "timezone": "时区",
    "points": "测点",
    "azimuth": "方位角",
    "elevation": "遮挡仰角",
}


def _loc_to_field(loc: tuple) -> str:
    parts: list[str] = []
    for item in loc:
        if item == "body":
            continue
        if isinstance(item, int):
            parts.append(f"第 {item + 1} 行")
        else:
            parts.append(FIELD_NAMES.get(str(item), str(item)))
    return "·".join(parts) if parts else "请求"


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        field = _loc_to_field(err.get("loc", ()))
        msg = err.get("msg", "输入无效")
        err_type = err.get("type", "")
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, "):]
        elif err_type == "missing":
            msg = "必填字段缺失"
        elif err_type.startswith("date"):
            msg = "日期格式不正确，应为 YYYY-MM-DD"
        elif err_type in ("float_parsing", "float_type", "int_parsing"):
            msg = "应为有效数字"
        elif err_type in ("string_type",):
            msg = "应为字符串"
        elif err_type in ("list_type",):
            msg = "应为测点数组"
        errors.append({"field": field, "message": msg})
    return JSONResponse(status_code=422, content={"errors": errors})


# ---------------------------------------------------------------- 核心计算

def make_obstruction_interp(points: list[HorizonPoint]):
    """按方位角环形排序并构造线性插值函数，末点到首点跨 360° 连续插值。"""
    ordered = sorted(points, key=lambda p: p.azimuth)
    azs = [p.azimuth for p in ordered] + [ordered[0].azimuth + 360.0]
    els = [p.elevation for p in ordered] + [ordered[0].elevation]

    def obstruction(az: float) -> float:
        # az ∈ [0, 360)
        if az < azs[0]:
            az += 360.0
        i = bisect.bisect_right(azs, az) - 1
        if i >= len(azs) - 1:
            i = len(azs) - 2
        a0, a1 = azs[i], azs[i + 1]
        e0, e1 = els[i], els[i + 1]
        if a1 <= a0:
            return e0
        t = (az - a0) / (a1 - a0)
        return e0 + t * (e1 - e0)

    return obstruction


def _format_local(dt_utc: datetime, tz: ZoneInfo) -> tuple[str, str]:
    lt = dt_utc.astimezone(tz)
    off = lt.utcoffset() or timedelta(0)
    total = int(off.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return lt.strftime("%H:%M"), f"UTC{sign}{total // 60:02d}:{total % 60:02d}"


def compute_windows(req: CalcRequest) -> dict:
    tz = ZoneInfo(req.timezone)
    start_local = datetime.combine(req.date, time.min, tzinfo=tz)
    end_local = datetime.combine(req.date + timedelta(days=1), time.min, tzinfo=tz)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    # 夏令时切换日：这里自然得到 1380 / 1440 / 1500 分钟
    day_minutes = int((end_utc - start_utc).total_seconds() // 60)

    obstruction = make_obstruction_interp(req.points)
    observer = Observer(latitude=req.latitude, longitude=req.longitude)

    one_minute = timedelta(minutes=1)
    hits: list[datetime] = []
    t = start_utc
    while t < end_utc:
        elev = sun_elevation(observer, t, with_refraction=False)
        if elev > 0.0:
            az = sun_azimuth(observer, t)
            if elev > obstruction(az):
                hits.append(t)
        t += one_minute

    # 合并相邻命中分钟为半开时段 [start, end)
    merged: list[list[datetime]] = []
    for ht in hits:
        if merged and ht == merged[-1][1]:
            merged[-1][1] = ht + one_minute
        else:
            merged.append([ht, ht + one_minute])

    windows = []
    total_minutes = 0
    for w_start, w_end in merged:
        minutes = int((w_end - w_start).total_seconds() // 60)
        total_minutes += minutes
        s_local, s_off = _format_local(w_start, tz)
        e_local, e_off = _format_local(w_end, tz)
        windows.append({
            "startMinute": int((w_start - start_utc).total_seconds() // 60),
            "endMinute": int((w_end - start_utc).total_seconds() // 60),
            "startLocal": s_local,
            "startOffset": s_off,
            "endLocal": e_local,
            "endOffset": e_off,
            "minutes": minutes,
        })

    # 时间轴刻度：每 3 小时一个，标注本地时刻（重复的本地时刻会自然出现两次）
    ticks = []
    for m in range(0, day_minutes + 1, 180):
        lt = (start_utc + timedelta(minutes=m)).astimezone(tz)
        ticks.append({"minute": m, "label": lt.strftime("%H:%M")})
    if ticks[-1]["minute"] != day_minutes:
        ticks.append({"minute": day_minutes, "label": "00:00"})

    return {
        "date": req.date.isoformat(),
        "timezone": req.timezone,
        "dayMinutes": day_minutes,
        "totalMinutes": total_minutes,
        "windows": windows,
        "ticks": ticks,
    }


# ---------------------------------------------------------------- 路由

@app.post("/api/sun-windows")
async def sun_windows(req: CalcRequest):
    return compute_windows(req)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
