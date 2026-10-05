# 本地遮挡日照窗口

根据地平线遮挡测点，计算某地某天太阳实际直晒的时间段。纯本地运行，无需外部账号或网络服务。

- 后端：Python + FastAPI + [Astral](https://astral.readthedocs.io/)（无折射太阳仰角/方位角）
- 前端：原生 HTML / JavaScript / CSS
- 部署：单条 `docker compose up --build` 即可

## 快速开始

```bash
docker compose up --build
```

然后浏览器打开 <http://localhost:8000>。

本地开发（不用 Docker）：

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 输入规则

| 字段 | 规则 |
| --- | --- |
| 日期 | 民用日期 `YYYY-MM-DD` |
| 纬度 | -66 ～ 66 |
| 经度 | -180 ～ 180 |
| 时区 | 仅 `Asia/Shanghai`、`Europe/Berlin`、`America/New_York` |
| 测点 | 2～12 个；方位角以正北为 0° 顺时针，范围 `[0, 360)`，不得重复；遮挡仰角 0～80° |

输入有误时，接口返回 422 及逐字段中文错误信息，页面会指出具体字段（含测点行号）。

## 算法说明

1. **地平线插值**：测点按方位角环形排序，相邻点之间对遮挡仰角做线性插值；末点到首点跨越 360° 连续插值，保证整条地平线闭合。
2. **逐分钟判定**：把当地日期 00:00 至次日 00:00 转换为 UTC，从起始 UTC 整分钟开始逐分钟步进，用 Astral 计算**无折射**太阳仰角与方位角（`with_refraction=False`）。
3. **直晒条件**：仅当太阳仰角**严格大于 0°** 且**严格高于**该方位（插值后的）遮挡仰角时，该分钟计为直晒。
4. **时段合并**：相邻命中分钟合并为半开时段 `[start, end)`，以本地时间（带 UTC 偏移，如 `UTC+02:00`）显示，并给出总分钟数。
5. **夏令时**：当地一天按实际 23 / 24 / 25 小时处理（1380 / 1440 / 1500 个 UTC 分钟）。秋季拨回时重复的本地时刻来自不同的 UTC 分钟，不会被合并或漏算；时段两端分别标注各自的 UTC 偏移以区分。
6. **空结果**：无直晒时返回总分钟数 0 与空时段列表，页面如实显示。

## API

`POST /api/sun-windows`

```json
{
  "date": "2026-06-01",
  "latitude": 31.2304,
  "longitude": 121.4737,
  "timezone": "Asia/Shanghai",
  "points": [
    { "azimuth": 90, "elevation": 15 },
    { "azimuth": 270, "elevation": 10 }
  ]
}
```

响应：

```json
{
  "date": "2026-06-01",
  "timezone": "Asia/Shanghai",
  "dayMinutes": 1440,
  "totalMinutes": 512,
  "windows": [
    {
      "startMinute": 321,
      "endMinute": 655,
      "startLocal": "05:21",
      "startOffset": "UTC+08:00",
      "endLocal": "10:55",
      "endOffset": "UTC+08:00",
      "minutes": 334
    }
  ],
  "ticks": [{ "minute": 0, "label": "00:00" }]
}
```

`windows[].startMinute/endMinute` 为相对当日起点（UTC）的分钟偏移，供时间轴定位；`ticks` 为时间轴刻度（本地时刻标签）。

## 项目结构

```
app/
  main.py            # FastAPI 应用与核心计算
  static/index.html  # 页面
  static/app.js      # 交互与渲染
  static/style.css   # 样式
requirements.txt
Dockerfile
docker-compose.yml
```
