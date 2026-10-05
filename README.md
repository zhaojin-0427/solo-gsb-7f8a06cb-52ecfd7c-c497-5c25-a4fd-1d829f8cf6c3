# 遮挡日照窗口计算器

根据地平线遮挡测点与太阳运行轨迹，计算指定地点、指定民用日期内太阳
**未被遮挡且位于地平线以上**的直晒时段。

- 后端：Python + FastAPI + [Astral](https://astral.readthedocs.io/)（太阳位置）
- 前端：原生 HTML / CSS / JavaScript，无构建步骤、无外部账号
- 时区：Python 标准库 `zoneinfo`（IANA 数据库），正确处理夏令时

## 一键运行

```bash
docker compose up --build
```

然后浏览器打开 <http://localhost:8000> 即可。

停止：`Ctrl+C`（或 `docker compose down`）。

## 输入说明

| 字段 | 范围 / 取值 |
| --- | --- |
| 民用日期 | `YYYY-MM-DD`（当地墙钟日期） |
| 纬度 | -66 ～ 66（十进制度，北正南负） |
| 经度 | -180 ～ 180（十进制度，东正西负） |
| 时区 | `Asia/Shanghai` / `Europe/Berlin` / `America/New_York` |
| 地平线测点 | 2 ～ 12 个；方位角以正北为 0°、顺时针，范围 `[0, 360)`，不得重复；遮挡仰角 0 ～ 80° |

测点可在页面上随时增删。提交后：

- 测点按方位角环形排序，相邻点之间对遮挡仰角**线性插值**，
  末点到首点**跨 360° 连续插值**；
- 页面展示当日时间轴（直晒段、刻度、夏令时切换标记）、
  带 UTC 偏移的本地半开时段列表与极坐标遮挡剖面图；
- 输入错误会在对应字段下方逐条指出；无直晒时显示 **0 分钟**与空列表。

## 计算规则（与需求逐条对应）

1. **本地日 → UTC**：把当地日期的 `00:00` 与次日 `00:00` 两个墙钟时刻用
   `zoneinfo` 转换为 UTC，得到当天实际覆盖的 UTC 区间。
   - 春令时拨快日为 **23 小时（1380 分钟）**，秋令时回拨日为
     **25 小时（1500 分钟）**，普通日为 24 小时。
   - 回拨产生的重复本地墙钟时刻对应两段不同的 UTC 分钟，
     **逐分钟各计算一次，不会合并，也不会漏算**。
2. **逐 UTC 整分钟**：从起始 UTC 时刻起，每过一个整分钟用 Astral 计算：
   - 太阳仰角 `sun.elevation(..., with_refraction=False)`——
     **关闭大气折射的几何仰角**；
   - 太阳方位角 `sun.azimuth()`（正北 0°、顺时针），按 360 取模。
3. **命中条件（严格大于）**：
   `太阳仰角 > 0°` **且** `太阳仰角 > 该方位插值遮挡仰角`。
   仰角恰好 0° 或恰好等于遮挡角的分钟不计入。
4. **合并与展示**：相邻的命中 UTC 分钟合并为半开区间
   `[起始分钟, 结束分钟)`，再把两端分别转回本地时间并标注各自的 UTC 偏移
   （若区间跨越偏移切换，起止显示不同偏移）。

> 因为以 UTC 整分钟为合并单位，回拨日同一本地墙钟时刻出现两次时，
> 它们属于不同的 UTC 分钟，绝不会被错误合并。

## API

`POST /api/calculate`

```json
{
  "date": "2024-06-21",
  "latitude": 39.9042,
  "longitude": 116.4074,
  "timezone": "Asia/Shanghai",
  "points": [
    {"azimuth": 0, "elevation": 10},
    {"azimuth": 90, "elevation": 20},
    {"azimuth": 180, "elevation": 8},
    {"azimuth": 270, "elevation": 30}
  ]
}
```

成功返回 `sunlit_minutes`、`intervals`（半开本地时段+偏移+分钟数）、
`transitions`（夏令时切换点）、`ticks`、`samples` 与排序后的 `horizon`。
校验失败返回 HTTP 400：

```json
{ "ok": false, "errors": { "points.2.azimuth": "第 3 个测点的方位角与其它测点重复（180°）" } }
```

错误键定位到具体字段（`date` / `latitude` / `longitude` / `timezone` /
`points` / `points.<行号>.azimuth` / `points.<行号>.elevation`）。

## 本地开发（不用 Docker）

```bash
python3 -m pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

运行测试：

```bash
python3 -m pip install pytest httpx
PYTHONPATH=. pytest -q
```

## 项目结构

```
.
├── app/
│   ├── main.py            # FastAPI 应用：校验、逐日计算、DST 处理
│   └── static/
│       ├── index.html     # 页面结构
│       ├── styles.css     # 样式
│       └── app.js         # 测点增删、校验、时间轴与剖面图渲染
├── tests/                 # pytest 测试（插值/API/DST/校验）
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
└── requirements.txt
```

## 说明与限制

- 纬度限制在 ±66° 以内（极圈以外），避免极昼/极夜带来的语义歧义。
- 观测点海拔取 0；时间均以分钟为最小粒度（半开区间）。
- 太阳位置由 Astral 基于 NOAA 太阳算法计算，结果为几何（无折射）值。
