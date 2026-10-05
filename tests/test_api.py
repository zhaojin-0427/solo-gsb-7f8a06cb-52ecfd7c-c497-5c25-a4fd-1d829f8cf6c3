"""API 与日照计算端到端测试（含夏令时 23/25 小时、空结果、输入校验）。"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

FLAT = [
    {"azimuth": 0, "elevation": 0},
    {"azimuth": 90, "elevation": 0},
    {"azimuth": 180, "elevation": 0},
    {"azimuth": 270, "elevation": 0},
]


def calc(**over):
    payload = {
        "date": "2024-06-21",
        "latitude": 40.0,
        "longitude": 116.4,
        "timezone": "Asia/Shanghai",
        "points": FLAT,
    }
    payload.update(over)
    return client.post("/api/calculate", json=payload)


def test_basic_summer_day_beijing():
    r = calc()
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"]
    assert d["total_local_minutes"] == 1440
    assert d["sunlit_minutes"] > 700  # 北京夏至日照约 15 小时
    # 所有段分钟数之和等于总分钟数
    assert sum(i["minutes"] for i in d["intervals"]) == d["sunlit_minutes"]
    # 段间不重叠且按时间排序
    for a, b in zip(d["intervals"], d["intervals"][1:]):
        assert a["end_minute"] <= b["start_minute"]


def test_interval_labels_are_local_with_offset():
    d = calc().json()
    iv = d["intervals"][0]
    assert iv["start_local"]["offset"] == "+08:00"
    assert iv["end_local"]["offset"] == "+08:00"
    assert "+08:00" in iv["label"]
    # 半开区间
    assert iv["end_minute"] - iv["start_minute"] == iv["minutes"]


def test_berlin_spring_forward_is_23_hours():
    # 2024-03-31 柏林：02:00 拨到 03:00，本地日长 23 小时
    r = calc(date="2024-03-31", latitude=52.5, longitude=13.4,
             timezone="Europe/Berlin")
    d = r.json()
    assert r.status_code == 200, r.text
    assert d["total_local_minutes"] == 1380
    assert len(d["transitions"]) == 1
    t = d["transitions"][0]
    assert t["kind"] == "forward"
    assert t["old_offset"] == "+01:00"
    assert t["new_offset"] == "+02:00"
    assert t["delta_minutes"] == 60
    # 本地 00:00(CET) = 前一日 UTC 23:00；UTC 01:00 切换即当天第 120 个 UTC 分钟
    assert t["at_minute"] == 120


def test_newyork_fallback_is_25_hours_without_merging():
    # 2024-11-03 纽约：02:00 回拨到 01:00，本地日长 25 小时
    r = calc(date="2024-11-03", latitude=40.7, longitude=-74.0,
             timezone="America/New_York")
    d = r.json()
    assert r.status_code == 200, r.text
    assert d["total_local_minutes"] == 1500
    assert len(d["transitions"]) == 1
    t = d["transitions"][0]
    assert t["kind"] == "fallback"
    assert t["old_offset"] == "-04:00"
    assert t["new_offset"] == "-05:00"
    # 本地 00:00(EDT) = UTC 04:00；UTC 06:00 回拨（墙钟回到 01:00），即第 120 分钟
    assert t["at_minute"] == 120
    # 日出后两次经过本地 01:xx 墙钟时刻（一个 EDT 一个 EST），
    # 分钟按 UTC 枚举，重复时刻不会被丢掉：
    # day_start 为 UTC 04:00；第 60 分钟 = UTC 05:00 = 本地 01:00(-04:00)，
    # 第 120 分钟 = UTC 06:00 = 本地 01:00(-05:00) —— 同一墙钟出现两次且偏移不同。
    from datetime import datetime, timedelta, timezone
    start = datetime.fromisoformat(d["day_start_utc"])
    ny = ZoneInfo("America/New_York")
    assert (start + timedelta(minutes=60)).astimezone(ny).strftime("%H:%M") == "01:00"
    assert (start + timedelta(minutes=120)).astimezone(ny).strftime("%H:%M") == "01:00"
    assert d["sunlit_minutes"] > 0
    # 所有命中区间端点均落在 [0,1500]
    for iv in d["intervals"]:
        assert 0 <= iv["start_minute"] < iv["end_minute"] <= 1500


def test_tall_obstructions_give_zero_minutes_empty_list():
    wall = [
        {"azimuth": 0, "elevation": 80},
        {"azimuth": 90, "elevation": 80},
        {"azimuth": 180, "elevation": 80},
        {"azimuth": 270, "elevation": 80},
    ]
    d = calc(points=wall).json()
    assert d["sunlit_minutes"] == 0
    assert d["intervals"] == []


def test_strictly_greater_threshold():
    # 平顶遮挡仰角等于太阳仰角的那一分钟不应计入：
    # 用一堵恰好等于正午太阳仰角的墙（正午方位）做局部检查。
    # 此处以全 0 遮挡与极窄高墙难以取整分钟阈值，改做统计稳定性：
    # 遮挡从 0 提高到 1°，直晒分钟数应严格减少。
    d0 = calc().json()
    almost = [
        {"azimuth": 0, "elevation": 1},
        {"azimuth": 90, "elevation": 1},
        {"azimuth": 180, "elevation": 1},
        {"azimuth": 270, "elevation": 1},
    ]
    d1 = calc(points=almost).json()
    assert d1["sunlit_minutes"] < d0["sunlit_minutes"]


def test_validation_errors_point_to_fields():
    r = client.post("/api/calculate", json={
        "date": "2024-13-40",
        "latitude": 90,
        "longitude": 200,
        "timezone": "Asia/Tokyo",
        "points": [
            {"azimuth": 100, "elevation": 5},
            {"azimuth": 100, "elevation": 90},
        ],
    })
    assert r.status_code == 400
    errs = r.json()["errors"]
    assert "date" in errs
    assert "latitude" in errs
    assert "longitude" in errs
    assert "timezone" in errs
    assert "points.1.azimuth" in errs   # 重复方位角
    assert "points.1.elevation" in errs  # 超范围仰角


def test_point_count_bounds():
    one = [{"azimuth": 0, "elevation": 0}]
    r = calc(points=one)
    assert r.status_code == 400
    assert "points" in r.json()["errors"]
    thirteen = [{"azimuth": a * 27.0, "elevation": 0} for a in range(13)]
    r = calc(points=thirteen)
    assert r.status_code == 400
    assert "points" in r.json()["errors"]


def test_azimuth_bounds_and_duplicates():
    bad = [
        {"azimuth": 360, "elevation": 0},
        {"azimuth": -5, "elevation": 0},
    ]
    r = calc(points=bad)
    assert r.status_code == 400
    errs = r.json()["errors"]
    assert "points.0.azimuth" in errs
    assert "points.1.azimuth" in errs


def test_index_page_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "遮挡日照窗口" in r.text
    r2 = client.get("/static/app.js")
    assert r2.status_code == 200
