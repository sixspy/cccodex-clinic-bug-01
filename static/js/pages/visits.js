import { api, chip, escapeHtml } from '../api.js';

export async function renderVisits(el) {
  const [batches, sites, protocols, wp] = await Promise.all([
    api('/api/batches'),
    api('/api/sites'),
    api('/api/protocols?status=' + encodeURIComponent('生效')),
    api('/api/water_pin/dash'),
  ]);
  const siteOpts = (sites.items || [])
    .filter((s) => s.status !== '停用')
    .map((s) => `<option value="${s.id}">${escapeHtml(s.site_code + ' · ' + s.name)}</option>`)
    .join('');
  const protoOpts = (protocols.items || [])
    .map((p) => `<option value="${p.id}">${escapeHtml(p.protocol_code + ' · ' + p.title)}</option>`)
    .join('');

  el.innerHTML = `
    <div class="card">
      <h2><span id="wpHeadChip">${chip(wp.chip)}</span> 访视清单抓取批次</h2>
      <p class="muted">按试验中心开批次，模拟抓取访视行，合格行可入库，缺口行进入质控与补采。</p>
      <div class="row">
        <select id="siteId">${siteOpts}</select>
        <select id="protocolId"><option value="">默认生效方案</option>${protoOpts}</select>
        <input id="bnote" placeholder="批次备注" />
        <button id="createBatch">开新批次</button>
      </div>
    </div>
    <div class="card" id="waterPinPanel">
      <h2>水位钉点 <span class="muted">甲路·旁路账册</span></h2>
      <p class="muted">提交即整笔写库；封存后读轨只认旁路账册并拒回刷，旧窗重灌一律被挡。</p>
      <div id="wpBody"></div>
      <div class="row">
        <input id="wpRef" placeholder="关联批次ID（可空）" style="width:150px" />
        <input id="wpNote" placeholder="钉定备注" value="水位钉定" />
        <button id="wpCommit">钉定水位</button>
      </div>
      <div id="wpMsg" class="muted"></div>
    </div>
    <div class="card">
      <h2>水位钉点名录</h2>
      <table>
        <thead>
          <tr><th>#</th><th>当场键</th><th>窗止点</th><th>指纹</th><th>状态</th><th>落点时间</th></tr>
        </thead>
        <tbody id="wpRows"></tbody>
      </table>
      <div id="wpDetail" class="detail-box">点击名录行查看水位钉点落点详情。</div>
    </div>
    <div class="card">
      <h2>水位钉点队列形态</h2>
      <div id="wpQueue" class="row"></div>
    </div>
    <div class="card">
      <div class="row">
        <select id="statusFilter">
          <option value="">全部批次状态</option>
          <option>采集中</option>
          <option>已收齐</option>
          <option>已关闭</option>
        </select>
        <button id="reload" class="ghost">刷新列表</button>
      </div>
      <table>
        <thead>
          <tr>
            <th>批次编码</th><th>中心</th><th>方案</th><th>状态</th>
            <th>行数</th><th>缺口</th><th>备注</th><th>操作</th>
          </tr>
        </thead>
        <tbody id="batchBody">
          ${(batches.items || []).map(batchRow).join('')}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>批次详情与访视行</h2>
      <div id="batchDetail" class="muted">点击「查看」加载批次内访视行与质量分布。</div>
    </div>`;

  function batchRow(b) {
    return `
      <tr>
        <td>${escapeHtml(b.batch_code)}</td>
        <td>${escapeHtml(b.site_name || '')}</td>
        <td>${escapeHtml((b.protocol_code || '-') + (b.protocol_version ? '@' + b.protocol_version : ''))}</td>
        <td>${chip(b.status)}</td>
        <td>${b.item_count}</td>
        <td>${b.gap_count}</td>
        <td class="muted">${escapeHtml(b.note || '')}</td>
        <td class="row">
          <button data-view="${b.id}" class="ghost">查看</button>
          <button data-crawl="${b.id}">模拟抓取</button>
          <button data-ingest="${b.id}">合格入库</button>
          <button data-complete="${b.id}" class="warn">标已收齐</button>
          <button data-close="${b.id}" class="danger">关闭</button>
        </td>
      </tr>`;
  }

  const detail = el.querySelector('#batchDetail');
  const showErr = (msg) => { detail.innerHTML = `<p class="err">${escapeHtml(msg)}</p>`; };

  function renderWaterPin(wp) {
    el.querySelector('#wpHeadChip').innerHTML = chip(wp.chip);
    const landing = wp.landing;
    el.querySelector('#wpBody').innerHTML = `
      <div class="grid">
        <div class="stat"><div class="n">${escapeHtml(wp.chip)}</div><div class="l">水位徽标</div></div>
        <div class="stat"><div class="n">${escapeHtml(wp.window_end || '窗止点旧')}</div><div class="l">窗止点</div></div>
        <div class="stat"><div class="n">${escapeHtml(wp.active_read)}</div><div class="l">读轨</div></div>
        <div class="stat"><div class="n">${wp.reject_refresh ? '拒回刷' : '未封存'}</div><div class="l">回刷闸门</div></div>
      </div>
      <div class="detail-box" id="wpLandingRow">水位钉点落点：${
        landing
          ? `${escapeHtml(landing.pin_key)} · 窗止点 ${escapeHtml(landing.window_end)} · 指纹 ${escapeHtml(landing.fingerprint)} · ${escapeHtml(landing.created_at || '')}`
          : '暂无（未钉定）'
      }</div>
      ${wp.mismatch ? '<p class="err">水位徽标与窗止点拧花：指纹不一致，旧窗重灌已被闸门挡住。</p>' : ''}`;
    const rows = wp.rows || [];
    el.querySelector('#wpRows').innerHTML = rows.map((r) => `
      <tr data-pin="${r.id}" style="cursor:pointer">
        <td>${r.id}</td>
        <td>${escapeHtml(r.pin_key)}</td>
        <td>${escapeHtml(r.window_end)}</td>
        <td class="muted">${escapeHtml(r.fingerprint)}</td>
        <td>${chip(r.status)}</td>
        <td class="muted">${escapeHtml(r.created_at || '')}</td>
      </tr>`).join('') || '<tr><td colspan="6" class="muted">暂无水位钉点落点行</td></tr>';
    el.querySelectorAll('[data-pin]').forEach((tr) => {
      tr.onclick = () => {
        const row = rows.find((x) => String(x.id) === tr.dataset.pin);
        if (!row) return;
        el.querySelector('#wpDetail').innerHTML = `
          <strong>落点详情 #${row.id}</strong><br/>
          当场键：${escapeHtml(row.pin_key)}<br/>
          读轨账册：${escapeHtml(row.route)}<br/>
          窗止点：${escapeHtml(row.window_end)}<br/>
          指纹：${escapeHtml(row.fingerprint)}<br/>
          关联：${escapeHtml(String(row.ref_id || '-'))} · 备注：${escapeHtml(row.note || '')}<br/>
          状态：${escapeHtml(row.status)} · 落点时间：${escapeHtml(row.created_at || '')}`;
      };
    });
    const queue = wp.queue || [];
    el.querySelector('#wpQueue').innerHTML = queue.length
      ? queue.map((q) => `
        <span class="chip ${q.active ? 'ok' : 'idle'}" title="${escapeHtml(q.fingerprint)}">
          ${q.seq}·${escapeHtml(q.pin_key)} → ${escapeHtml(q.stage)}
        </span>`).join('')
      : '<span class="muted">队列为空，尚未钉定。</span>';
  }

  async function reloadWaterPin() {
    const wp = await api('/api/water_pin/dash');
    renderWaterPin(wp);
  }

  el.querySelector('#wpCommit').onclick = async () => {
    const msg = el.querySelector('#wpMsg');
    try {
      const body = { note: el.querySelector('#wpNote').value };
      const ref = el.querySelector('#wpRef').value.trim();
      if (ref) body.ref_id = Number(ref);
      const r = await api('/api/water_pin/commit', { method: 'POST', body: JSON.stringify(body) });
      msg.className = 'muted';
      msg.textContent = r.message || '水位钉点已落台';
      await reloadWaterPin();
    } catch (e) {
      msg.className = 'err';
      msg.textContent = e.message;
      await reloadWaterPin().catch(() => {});
    }
  };

  renderWaterPin(wp);

  async function loadDetail(id) {
    const b = await api(`/api/batches/${id}`);
    const qs = b.quality_stats || {};
    detail.innerHTML = `
      <div class="row">
        <strong>${escapeHtml(b.batch_code)}</strong>
        ${chip(b.status)}
        <span class="muted">${escapeHtml(b.site_name)} · 方案 ${escapeHtml(b.protocol_title || '-')}</span>
      </div>
      <div class="grid">
        <div class="stat"><div class="n">${b.item_count}</div><div class="l">访视行</div></div>
        <div class="stat"><div class="n">${b.gap_count}</div><div class="l">缺口行</div></div>
        <div class="stat"><div class="n">${qs['合格'] || 0}</div><div class="l">合格</div></div>
        <div class="stat"><div class="n">${(qs['缺字段'] || 0) + (qs['编码空'] || 0) + (qs['重复键'] || 0)}</div><div class="l">异常质量</div></div>
      </div>
      <div class="row">
        <input id="subjectKey" placeholder="受试者键" />
        <input id="visitCode" placeholder="访视编码" value="V1" style="width:90px" />
        <input id="payload" placeholder='载荷 JSON，如 {"visit_date":"2026-11-20","investigator":"王医生","weight_kg":60}' style="min-width:320px" />
        <select id="qualityForce">
          <option value="">自动推断质量</option>
          <option>合格</option>
          <option>缺字段</option>
          <option>编码空</option>
          <option>重复键</option>
        </select>
        <button id="addRow">追加访视行</button>
        <button id="runQc" class="warn">对本批质控扫描</button>
        <button id="enqueueGaps">缺口排队补采</button>
      </div>
      <table>
        <thead><tr><th>ID</th><th>受试者</th><th>访视</th><th>质量</th><th>状态</th><th>载荷摘要</th><th>操作</th></tr></thead>
        <tbody>
          ${(b.items || []).map((r) => `
            <tr>
              <td>${r.id}</td>
              <td>${escapeHtml(r.subject_key)}</td>
              <td>${escapeHtml(r.visit_code)}</td>
              <td>${chip(r.quality)}</td>
              <td>${chip(r.status)}</td>
              <td class="muted">${escapeHtml((r.payload || '').slice(0, 80))}</td>
              <td class="row">
                <button data-enqueue-row="${r.id}" ${r.quality === '合格' && r.status === '已入库' ? 'disabled' : ''}>排队补采</button>
                <button data-mark="${r.id}" data-st="待补采" class="ghost">标待补采</button>
              </td>
            </tr>`).join('') || '<tr><td colspan="7" class="muted">暂无访视行</td></tr>'}
        </tbody>
      </table>`;

    detail.querySelector('#addRow').onclick = async () => {
      try {
        const q = detail.querySelector('#qualityForce').value;
        await api(`/api/batches/${id}/items`, {
          method: 'POST',
          body: JSON.stringify({
            subject_key: detail.querySelector('#subjectKey').value,
            visit_code: detail.querySelector('#visitCode').value,
            payload: detail.querySelector('#payload').value,
            quality: q || null,
          }),
        });
        await loadDetail(id);
        await softReload();
      } catch (e) { showErr(e.message); }
    };
    detail.querySelector('#runQc').onclick = async () => {
      try {
        const r = await api(`/api/batches/${id}/qc`, { method: 'POST', body: '{}' });
        detail.insertAdjacentHTML('afterbegin', `<p class="muted">质控新建发现 ${r.created} 条</p>`);
        await loadDetail(id);
      } catch (e) { showErr(e.message); }
    };
    detail.querySelector('#enqueueGaps').onclick = async () => {
      try {
        const r = await api(`/api/batches/${id}/backfill`, { method: 'POST', body: '{}' });
        detail.insertAdjacentHTML('afterbegin', `<p class="muted">已排队 ${r.enqueued}，跳过 ${r.skipped}</p>`);
      } catch (e) { showErr(e.message); }
    };
    detail.querySelectorAll('[data-enqueue-row]').forEach((btn) => {
      btn.onclick = async () => {
        try {
          await api(`/api/rows/${btn.dataset.enqueueRow}/enqueue`, { method: 'POST', body: '{}' });
          await loadDetail(id);
        } catch (e) { showErr(e.message); }
      };
    });
    detail.querySelectorAll('[data-mark]').forEach((btn) => {
      btn.onclick = async () => {
        try {
          await api(`/api/rows/${btn.dataset.mark}/status`, {
            method: 'POST',
            body: JSON.stringify({ status: btn.dataset.st }),
          });
          await loadDetail(id);
        } catch (e) { showErr(e.message); }
      };
    });
  }

  async function softReload() {
    const status = el.querySelector('#statusFilter').value;
    const url = status ? `/api/batches?status=${encodeURIComponent(status)}` : '/api/batches';
    const data = await api(url);
    el.querySelector('#batchBody').innerHTML = (data.items || []).map(batchRow).join('');
    bindBatchActions();
  }

  function bindBatchActions() {
    el.querySelectorAll('[data-view]').forEach((btn) => {
      btn.onclick = () => loadDetail(btn.dataset.view).catch((e) => showErr(e.message));
    });
    el.querySelectorAll('[data-crawl]').forEach((btn) => {
      btn.onclick = async () => {
        try {
          await api(`/api/batches/${btn.dataset.crawl}/crawl`, {
            method: 'POST',
            body: JSON.stringify({ count: 5, mix_bad: true }),
          });
          await softReload();
          await loadDetail(btn.dataset.crawl);
        } catch (e) { showErr(e.message); }
      };
    });
    el.querySelectorAll('[data-ingest]').forEach((btn) => {
      btn.onclick = async () => {
        try {
          await api(`/api/batches/${btn.dataset.ingest}/ingest`, { method: 'POST', body: '{}' });
          await softReload();
          await loadDetail(btn.dataset.ingest);
        } catch (e) { showErr(e.message); }
      };
    });
    el.querySelectorAll('[data-complete]').forEach((btn) => {
      btn.onclick = async () => {
        try {
          await api(`/api/batches/${btn.dataset.complete}/complete`, { method: 'POST', body: '{}' });
          await softReload();
        } catch (e) { showErr(e.message); }
      };
    });
    el.querySelectorAll('[data-close]').forEach((btn) => {
      btn.onclick = async () => {
        try {
          await api(`/api/batches/${btn.dataset.close}/close`, { method: 'POST', body: '{}' });
          await softReload();
        } catch (e) { showErr(e.message); }
      };
    });
  }

  el.querySelector('#createBatch').onclick = async () => {
    try {
      const body = {
        site_id: Number(el.querySelector('#siteId').value),
        note: el.querySelector('#bnote').value,
      };
      const pid = el.querySelector('#protocolId').value;
      if (pid) body.protocol_id = Number(pid);
      const created = await api('/api/batches', { method: 'POST', body: JSON.stringify(body) });
      await softReload();
      await loadDetail(created.id);
    } catch (e) { showErr(e.message); }
  };
  el.querySelector('#reload').onclick = () => softReload().catch((e) => showErr(e.message));
  el.querySelector('#statusFilter').onchange = () => softReload().catch((e) => showErr(e.message));
  bindBatchActions();
}
