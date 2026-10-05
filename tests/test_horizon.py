"""遮挡插值单元测试。"""
import math

from app.main import HorizonPoint, HorizonProfile


def test_linear_interpolation_basic():
    p = HorizonProfile([HorizonPoint(0, 0), HorizonPoint(90, 30),
                        HorizonPoint(180, 10), HorizonPoint(270, 20)])
    assert p.obstruction(0) == 0
    assert math.isclose(p.obstruction(45), 15)
    assert math.isclose(p.obstruction(135), 20)
    assert p.obstruction(180) == 10


def test_wrap_interpolation_last_to_first_across_360():
    # 末点 350° 仰角 10，首点 10° 仰角 30：跨 360° 的弧长为 20°
    p = HorizonProfile([HorizonPoint(10, 30), HorizonPoint(180, 5), HorizonPoint(350, 10)])
    assert math.isclose(p.obstruction(0), 20)      # 跨 0° 中点
    assert math.isclose(p.obstruction(355), 15)
    assert math.isclose(p.obstruction(5), 25)
    assert math.isclose(p.obstruction(350), 10)
    assert math.isclose(p.obstruction(10), 30)
    assert math.isclose(p.obstruction(359.999), 20.0, abs_tol=1e-2)


def test_two_points_wrap():
    p = HorizonProfile([HorizonPoint(90, 20), HorizonPoint(270, 40)])
    assert math.isclose(p.obstruction(0), 30)      # 270 -> 450(=90) 中点
    assert math.isclose(p.obstruction(180), 30)
    assert math.isclose(p.obstruction(90), 20)
    assert math.isclose(p.obstruction(270), 40)


def test_interpolation_is_continuous_everywhere():
    pts = [HorizonPoint(15, 12), HorizonPoint(120, 3), HorizonPoint(200, 44),
           HorizonPoint(300, 8)]
    p = HorizonProfile(pts)
    prev = p.obstruction(359.9)
    worst = 0.0
    for k in range(0, 3600):
        a = k / 10.0
        v = p.obstruction(a)
        worst = max(worst, abs(v - prev))
        prev = v
    # 步长 0.1°，遮挡角逐段线性且跨 360° 连续，相邻采样差应很小
    assert worst < 0.5
