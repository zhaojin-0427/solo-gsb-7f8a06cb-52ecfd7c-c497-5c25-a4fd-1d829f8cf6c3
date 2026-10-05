const pointsBody = document.getElementById('points-body');
const addBtn = document.getElementById('add-point');
const form = document.getElementById('calc-form');
const errorsBox = document.getElementById('errors');
const resultBox = document.getElementById('result');

function refreshRowButtons() {
  const rows = pointsBody.querySelectorAll('tr');
  addBtn.disabled = rows.length >= 12;
  rows.forEach((r) => {
    r.querySelector('.remove-point').disabled = rows.length <= 2;
  });
}

function addPointRow(az = '', el = '') {
  const tr = document.createElement('tr');
  tr.innerHTML =
    `<td><input type="number" class="az" min="0" max="359.999999" step="any" value="${az}" required></td>` +
    `<td><input type="number" class="el" min="0" max="80" step="any" value="${el}" required></td>` +
    `<td><button type="button" class="remove-point">删除</button></td>`;
  tr.querySelector('.remove-point').addEventListener('click', () => {
    tr.remove();
    refreshRowButtons();
  });
  pointsBody.appendChild(tr);
  refreshRowButtons();
}

addBtn.addEventListener('click', () => addPointRow());

// 默认两个测点
addPointRow(90, 15);
addPointRow(270, 10);

// 默认日期为今天（本地）
document.getElementById('date').value = new Date().toLocaleDateString('sv-SE');

function showErrors(list) {
  errorsBox.innerHTML = '';
  if (!list.length) {
    errorsBox.hidden = true;
    return;
  }
  const ul = document.createElement('ul');
  for (const e of list) {
    const li = document.createElement('li');
    li.textContent = `${e.field}：${e.message}`;
    ul.appendChild(li);
  }
  errorsBox.appendChild(ul);
  errorsBox.hidden = false;
}

function renderTimeline(data) {
  const tl = document.getElementById('timeline');
  tl.innerHTML = '';

  const bar = document.createElement('div');
  bar.className = 'bar';
  for (const w of data.windows) {
    const seg = document.createElement('div');
    seg.className = 'seg';
    seg.style.left = (w.startMinute / data.dayMinutes) * 100 + '%';
    seg.style.width = ((w.endMinute - w.startMinute) / data.dayMinutes) * 100 + '%';
    seg.title = `${w.startLocal} (${w.startOffset}) – ${w.endLocal} (${w.endOffset})，${w.minutes} 分钟`;
    bar.appendChild(seg);
  }
  tl.appendChild(bar);

  const ticks = document.createElement('div');
  ticks.className = 'ticks';
  for (const t of data.ticks) {
    const tick = document.createElement('span');
    tick.className = 'tick';
    tick.style.left = (t.minute / data.dayMinutes) * 100 + '%';
    tick.textContent = t.minute === data.dayMinutes ? '次日 00:00' : t.label;
    if (t.minute === 0) tick.classList.add('first');
    if (t.minute === data.dayMinutes) tick.classList.add('last');
    ticks.appendChild(tick);
  }
  tl.appendChild(ticks);

  const legend = document.createElement('div');
  legend.className = 'legend';
  legend.innerHTML = '<span class="swatch"></span> 直晒时段（绿色）';
  tl.appendChild(legend);
}

function renderResult(data) {
  resultBox.hidden = false;
  document.getElementById('result-date').textContent =
    `（${data.date}，${data.timezone}，当日 ${data.dayMinutes} 分钟）`;

  document.getElementById('summary').textContent =
    `直晒总时长：${data.totalMinutes} 分钟，共 ${data.windows.length} 个时段。`;

  const ul = document.getElementById('windows');
  ul.innerHTML = '';
  if (data.windows.length === 0) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = '（空列表）当日无直晒时段，总计 0 分钟。';
    ul.appendChild(li);
  } else {
    for (const w of data.windows) {
      const li = document.createElement('li');
      li.textContent =
        `${w.startLocal} (${w.startOffset}) – ${w.endLocal} (${w.endOffset}) · ${w.minutes} 分钟`;
      ul.appendChild(li);
    }
  }
  renderTimeline(data);
}

form.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  showErrors([]);
  resultBox.hidden = true;

  const clientErrors = [];
  const dateVal = document.getElementById('date').value;
  if (!dateVal) clientErrors.push({ field: '日期', message: '必填字段缺失' });

  const points = [];
  pointsBody.querySelectorAll('tr').forEach((tr, i) => {
    const az = tr.querySelector('.az').value;
    const el = tr.querySelector('.el').value;
    if (az === '' || el === '') {
      clientErrors.push({ field: `测点·第 ${i + 1} 行`, message: '方位角与遮挡仰角均必填' });
      return;
    }
    points.push({ azimuth: Number(az), elevation: Number(el) });
  });
  if (clientErrors.length) {
    showErrors(clientErrors);
    return;
  }

  const payload = {
    date: dateVal,
    latitude: Number(document.getElementById('latitude').value),
    longitude: Number(document.getElementById('longitude').value),
    timezone: document.getElementById('timezone').value,
    points,
  };

  const submitBtn = document.getElementById('submit-btn');
  submitBtn.disabled = true;
  try {
    const resp = await fetch('/api/sun-windows', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) {
      if (data && Array.isArray(data.errors)) {
        showErrors(data.errors);
      } else {
        showErrors([{ field: '请求', message: `服务器返回错误（${resp.status}）` }]);
      }
      return;
    }
    renderResult(data);
  } catch (err) {
    showErrors([{ field: '网络', message: '请求失败：' + err.message }]);
  } finally {
    submitBtn.disabled = false;
  }
});
