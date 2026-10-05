"""遮挡日照窗口计算服务 (FastAPI + Astral)。

核心规则：
- 当地民用日期的零点到次日零点，先换算成 UTC（zoneinfo，自动处理夏令时），
  再逐个 UTC 整分钟遍历；因此春令时切换日本地为 23 小时、秋令时为 25 小时，
  回拨产生的重复本地时刻会被自然地各计算一次，不会合并或漏算。
- 用 Astral 计算太阳仰角（关闭大气折射）与方位角；仅当太阳仰角严格 > 0°
  且严格高于该方位处线性插值得到的遮挡仰角时，该分钟计为直晒。
- 直晒时段按 UTC 连续分钟合并（半开区间），再映射回带 UTC 偏移的本地时间。
"""
from __future__ import annotations

import bisect
import datetime as dt
from zoneinfo import ZoneInfo

from astral import Observer
from astral import sun as astral_sun
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ALLOWED_TIMEZONES = ["Asia/Shanghai", "Europe/Berlin", "America/New_York"]
MIN_POINTS, MAX_POINTS = 2, 12
LAT_MIN, LAT_MAX = -66.0, 66.0
LON_MIN, LON_MAX = -180.0, 180.0
ELEV_MIN, ELEV_MAX = 0.0, 80.0

app = FastAPI(title="遮挡日照窗口", version="1.0")


class HorizonPoint:
    """一个地平线测点：方位角 azimuth（正北 0°，顺时针，[0,360)）与遮挡仰角 elevation。"""

    __slots__ = ("azimuth", "elevation")

    def __init__(self, azimuth: float, elevation: float):
        self.azimuth = azimuth
        self.elevation = elevation


class HorizonProfile:
    """环形遮挡剖面。测点按方位角升序排列，相邻点（含末点跨 360° 回首点）
    之间对遮挡仰角做线性插值。"""

    def __init__(self, points: list[HorizonPoint]):
        ordered = sorted(points, key=lambda p: p.azimuth)
        self.azimuths = [p.azimuth for p in ordered]
        self.elevations = [p.elevation for p in ordered]

    def obstruction(self, azimuth: float) -> float:
        """返回指定方位角处的线性插值遮挡仰角。"""
        a = azimuth % 360.0
        az = self.azimuths
        # 第一个方位角 <= a 的测点右侧位置
        i = bisect.bisect_right(az, a) - 1
        if i >= 0 and i < len(az) - 1:
            a0, a1 = az[i], az[i + 1]
            e0, e1 = self.elevations[i], self.elevations[i + 1]
            return e0 + (e1 - e0) * (a - a0) / (a1 - a0)
        if i == len(az) - 1:
            # 末点 -> 跨 360° -> 首点
            a0, a1 = az[-1], az[0] + 360.0
            e0, e1 = self.elevations[-1], self.elevations[0]
            return e0 + (e1 - e0) * ((a if a >= a0 else a + 360.0) - a0) / (a1 - a0)
        # a 小于最小方位角：首点 <- 跨 0° <- 末点
        a0, a1 = az[-1] - 360.0, az[0]
        e0, e1 = self.elevations[-1], self.elevations[0]
        return e0 + (e1 - e0) * (a - a0) / (a1 - a0)

    def as_list(self) -> list[dict]:
        return [{"azimuth": a, "elevation": e}
                for a, e in zip(self.azimuths, self.elevations)]


def _error(errors: dict[str, str]) -> JSONResponse:
    return JSONResponse(status_code=400, content={"ok": False, "errors": errors})


def _parse_number(value, field: str, label: str, lo: float, hi: float,
                  errors: dict[str, str], integer: bool = False):
    """解析并校验一个数值字段，失败时把中文错误写入 errors[field]。"""
    if isinstance(value, bool) or value is None:
        errors[field] = f"{label}必须填写"
        return None
    if isinstance(value, str) and not value.strip():
        errors[field] = f"{label}必须填写"
        return None
    try:
        num = int(value) if integer else float(value)
    except (TypeError, ValueError):
        kind = "整数" if integer else "数字"
        errors[field] = f"{label}必须是{kind}"
        return None
    if integer and float(num) != float(value):
        errors[field] = f"{label}必须是整数"
        return None
    if num < lo or num > hi:
        errors[field] = f"{label}必须在 {lo:g}～{hi:g} 之间"
        return None
    return num


def validate_payload(data) -> tuple[dict | None, dict[str, str]]:
    errors: dict[str, str] = {}
    if not isinstance(data, dict):
        return None, {"_": "请求体必须是 JSON 对象"}

    date_text = data.get("date")
    date_obj = None
    if not isinstance(date_text, str) or not date_text.strip():
        errors["date"] = "日期必须填写，格式 YYYY-MM-DD"
    else:
        try:
            date_obj = dt.datetime.strptime(date_text.strip(), "%Y-%m-%d").date()
        except ValueError:
            errors["date"] = "日期格式无效，应为 YYYY-MM-DD"

    latitude = _parse_number(data.get("latitude"), "latitude", "纬度",
                             LAT_MIN, LAT_MAX, errors)
    longitude = _parse_number(data.get("longitude"), "longitude", "经度",
                              LON_MIN, LON_MAX, errors)

    timezone = data.get("timezone")
    if not isinstance(timezone, str) or timezone not in ALLOWED_TIMEZONES:
        errors["timezone"] = "时区只能是 Asia/Shanghai、Europe/Berlin 或 America/New_York"

    points_in = data.get("points")
    points: list[HorizonPoint] = []
    if not isinstance(points_in, list):
        errors["points"] = "测点必须是数组"
    else:
        if not (MIN_POINTS <= len(points_in) <= MAX_POINTS):
            errors["points"] = f"测点数量必须为 {MIN_POINTS}～{MAX_POINTS} 个"
        seen_az: set[float] = set()
        for idx, raw in enumerate(points_in):
            prefix = f"points.{idx}"
            if not isinstance(raw, dict):
                errors[prefix] = "测点必须是对象"
                continue
            az = _parse_number(raw.get("azimuth"), f"{prefix}.azimuth",
                               f"第 {idx + 1} 个测点的方位角",
                               0.0, 359.999999, errors)
            elev = _parse_number(raw.get("elevation"), f"{prefix}.elevation",
                                 f"第 {idx + 1} 个测点的遮挡仰角",
                                 ELEV_MIN, ELEV_MAX, errors)
            if az is not None:
                if az in seen_az:
                    errors[f"{prefix}.azimuth"] = (
                        f"第 {idx + 1} 个测点的方位角与其它测点重复（{az:g}°）")
                else:
                    seen_az.add(az)
            if az is not None and elev is not None:
                points.append(HorizonPoint(az, elev))

    if errors:
        return None, errors
    return {
        "date": date_obj,
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "points": points,
    }, {}


def _offset_hours(td: dt.timedelta) -> str:
    """把 UTC 偏移格式化为 +HH:MM / -HH:MM。"""
    total = int(td.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"


def _local_parts(utc_dt: dt.datetime, tz: ZoneInfo) -> dict:
    """UTC 时间 -> 本地墙钟各分量（含 UTC 偏移）。"""
    local = utc_dt.astimezone(tz)
    return {
        "iso": local.isoformat(),
        "date": local.strftime("%Y-%m-%d"),
        "time": local.strftime("%H:%M"),
        "offset": _offset_hours(local.utcoffset()),
    }


def _local_day_utc_bounds(date_obj: dt.date, tz: ZoneInfo) -> tuple[dt.datetime, dt.datetime]:
    """当地零点与次日零点（墙钟）对应的 UTC 时刻。"""
    start_local = dt.datetime.combine(date_obj, dt.time.min, tzinfo=tz)
    end_local = dt.datetime.combine(date_obj + dt.timedelta(days=1), dt.time.min, tzinfo=tz)
    return start_local.astimezone(dt.timezone.utc), end_local.astimezone(dt.timezone.utc)


def compute_sunlight(parsed: dict) -> dict:
    date_obj: dt.date = parsed["date"]
    tz = ZoneInfo(parsed["timezone"])
    observer = Observer(parsed["latitude"], parsed["longitude"], 0.0)
    profile = HorizonProfile(parsed["points"])

    start_utc, end_utc = _local_day_utc_bounds(date_obj, tz)
    total_minutes = int((end_utc - start_utc).total_seconds() // 60)  # 1380 / 1440 / 1500

    hits: list[int] = []          # 命中的 UTC 整分钟（相对 start_utc 的分钟序号）
    transitions: list[dict] = []  # 夏令时切换点
    samples: list[dict] = []      # 每 10 分钟太阳样本，供前端绘制
    prev_offset = None

    minute = start_utc
    for m in range(total_minutes):
        offset = minute.astimezone(tz).utcoffset()
        if prev_offset is not None and offset != prev_offset:
            delta_minutes = int((offset - prev_offset).total_seconds() // 60)
            transitions.append({
                "at_minute": m,
                "local": _local_parts(minute, tz),
                "old_offset": _offset_hours(prev_offset),
                "new_offset": _offset_hours(offset),
                "kind": "forward" if delta_minutes > 0 else "fallback",
                "delta_minutes": abs(delta_minutes),
            })
        prev_offset = offset

        elev = astral_sun.elevation(observer, minute, with_refraction=False)
        if elev > 0.0:
            az = astral_sun.azimuth(observer, minute) % 360.0
            obstruction = profile.obstruction(az)
            if elev > obstruction:
                hits.append(m)
            if m % 10 == 0:
                samples.append({
                    "minute": m,
                    "azimuth": round(az, 3),
                    "elevation": round(elev, 3),
                    "obstruction": round(obstruction, 3),
                    "sunlit": elev > obstruction,
                })
        elif m % 10 == 0:
            samples.append({
                "minute": m,
                "azimuth": round(astral_sun.azimuth(observer, minute) % 360.0, 3),
                "elevation": round(elev, 3),
                "obstruction": round(profile.obstruction(
                    astral_sun.azimuth(observer, minute) % 360.0), 3),
                "sunlit": False,
            })
        minute += dt.timedelta(minutes=1)

    # 合并相邻命中分钟（UTC 连续）
    intervals: list[dict] = []
    if hits:
        run_start = prev_hit = hits[0]
        for hit in hits[1:]:
            if hit == prev_hit + 1:
                prev_hit = hit
                continue
            intervals.append(_make_interval(run_start, prev_hit + 1,
                                            start_utc, tz))
            run_start = prev_hit = hit
        intervals.append(_make_interval(run_start, prev_hit + 1,
                                        start_utc, tz))

    ticks = []
    for m in range(0, total_minutes + 1, 120):  # 每 2 小时一个刻度
        ticks.append({"minute": m, "local": _local_parts(start_utc + dt.timedelta(minutes=m), tz)})
    if ticks[-1]["minute"] != total_minutes:
        ticks.append({"minute": total_minutes,
                      "local": _local_parts(end_utc, tz)})

    return {
        "ok": True,
        "date": date_obj.isoformat(),
        "timezone": parsed["timezone"],
        "latitude": parsed["latitude"],
        "longitude": parsed["longitude"],
        "total_local_minutes": total_minutes,
        "day_start_utc": start_utc.isoformat(),
        "day_end_utc": end_utc.isoformat(),
        "sunlit_minutes": len(hits),
        "intervals": intervals,
        "transitions": transitions,
        "ticks": ticks,
        "samples": samples,
        "horizon": profile.as_list(),
    }


def _make_interval(start_m: int, end_m: int, start_utc: dt.datetime,
                   tz: ZoneInfo) -> dict:
    """把 [start_m, end_m) 的 UTC 分钟段转成带偏移的本地半开时段。"""
    s = start_utc + dt.timedelta(minutes=start_m)
    e = start_utc + dt.timedelta(minutes=end_m)
    sp, ep = _local_parts(s, tz), _local_parts(e, tz)
    if sp["offset"] == ep["offset"]:
        label = f'{sp["date"]} {sp["time"]} – {ep["time"]} (UTC{sp["offset"]})'
    else:
        label = (f'{sp["date"]} {sp["time"]} (UTC{sp["offset"]}) – '
                 f'{ep["date"]} {ep["time"]} (UTC{ep["offset"]})')
    return {
        "start_minute": start_m,
        "end_minute": end_m,
        "minutes": end_m - start_m,
        "start_local": sp,
        "end_local": ep,
        "label": label,
    }


@app.post("/api/calculate")
async def calculate(request: Request):
    try:
        data = await request.json()
    except Exception:
        return _error({"_": "请求体不是合法的 JSON"})
    parsed, errors = validate_payload(data)
    if errors:
        return _error(errors)
    return compute_sunlight(parsed)


app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    with open("app/static/index.html", encoding="utf-8") as fh:
        return fh.read()
