(function () {
  'use strict';

  // 只在课程目录页运行
  const TARGET_HASH = '#/CourseLearning/CourseInfo';
  const API_PATH = '/api/study/course/info/getCourseInformation';

  // 存储从 API 拦截到的资源数据：Map<resourceId, {id, name, url, suffix, courseCode}>
  const resourceMap = new Map();
  // 存储学习状态：Map<resourceId(number), boolean> 来自 getCourseInfoViewtime
  const learnedMap = new Map();
  let panelMounted = false;
  let renderRetryCount = 0;
  const filters = { type: 'all', learned: 'unlearned' };
  const checkedStateMap = new Map();
  const openConfig = { mode: 'simulate', intervalMs: 10000 };

  // ── 1. 拦截 XHR，在课程信息 API 响应时解析资源数据 ──────────────────────────
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url) {
    this._swjtuUrl = url;
    return origOpen.apply(this, arguments);
  };

  XMLHttpRequest.prototype.send = function (body) {
    if (this._swjtuUrl && this._swjtuUrl.includes(API_PATH)) {
      this.addEventListener('load', function () {
        try {
          const data = JSON.parse(this.responseText);
          parseResourceData(data);
          // 数据就绪后，若面板已挂载则刷新，否则等待挂载
          if (panelMounted) renderList();
        } catch (e) { /* ignore */ }
      });
    }
    return origSend.apply(this, arguments);
  };

  function parseResourceData(data) {
    const chapters = data?.datas?.data?.chapter ?? [];
    // 递归遍历所有章节树
    function walk(nodes) {
      for (const node of nodes) {
        if (node.chapter && node.chapter.length) walk(node.chapter);
        for (const res of (node.resource ?? [])) {
          resourceMap.set(res.id, {
            id: res.id,
            name: res.name,
            url: res.url,
            suffix: res.suffix,
            courseCode: res.course_code,
          });
        }
      }
    }
    walk(chapters);
  }

  function getCourseCodeFromHash() {
    const m = location.hash.match(/[?&]code=([^&]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function fetchLearnedMap() {
    const code = getCourseCodeFromHash();
    if (!code) return Promise.resolve();
    return fetch(`/api/study/course/info/getCourseInfoViewtime?code=${encodeURIComponent(code)}`, {
      credentials: 'include',
    })
      .then(r => r.json())
      .then(data => {
        const map = data?.datas ?? {};
        learnedMap.clear();
        for (const [id, status] of Object.entries(map)) {
          learnedMap.set(Number(id), status === '已学习');
        }
      })
      .catch(() => {});
  }

  function ensureResourceData() {
    const needsResource = resourceMap.size === 0;
    const needsLearned = learnedMap.size === 0;
    if (!needsResource && !needsLearned) return Promise.resolve();
    const code = getCourseCodeFromHash();
    if (!code) return Promise.resolve();
    const promises = [];
    if (needsResource) {
      promises.push(
        fetch(`/api/study/course/info/getCourseInformation?code=${encodeURIComponent(code)}`, {
          credentials: 'include',
        })
          .then(r => r.json())
          .then(data => parseResourceData(data))
          .catch(() => {})
      );
    }
    if (needsLearned) {
      promises.push(fetchLearnedMap());
    }
    return Promise.all(promises);
  }

  // ── 2. 监听路由变化，在课程目录页挂载面板 ────────────────────────────────────
  function checkAndMount() {
    if (!location.hash.startsWith(TARGET_HASH)) {
      unmountPanel();
      return;
    }
    if (!panelMounted) {
      waitForCourseContent().then(mountPanel);
    }
  }

  // 等 Vue 渲染出 .list-item
  function waitForCourseContent() {
    return new Promise(resolve => {
      const check = () => {
        if (document.querySelector('.list-item')) return resolve();
        setTimeout(check, 300);
      };
      check();
    });
  }

  window.addEventListener('hashchange', checkAndMount);
  // 初始检查（页面可能直接打开课程页）
  setTimeout(checkAndMount, 500);

  // ── 3. 面板挂载 / 卸载 ────────────────────────────────────────────────────────
  let panelEl = null;

  function mountPanel() {
    if (panelMounted) return;
    panelMounted = true;
    renderRetryCount = 0;

    // 在 body 上插入面板
    panelEl = document.createElement('div');
    panelEl.id = 'swjtu-panel';
    panelEl.innerHTML = getPanelHTML();
    document.body.appendChild(panelEl);
    injectStyles();

    panelEl.querySelector('#swjtu-toggle').addEventListener('click', toggleCollapse);
    panelEl.querySelector('#swjtu-open-btn').addEventListener('click', openSelected);
    panelEl.querySelector('#swjtu-check-unlearned').addEventListener('click', () => setAll(false));
    panelEl.querySelector('#swjtu-uncheck-all').addEventListener('click', () => setAll(true));
    panelEl.querySelector('#swjtu-filter-type').addEventListener('change', onFilterChange);
    panelEl.querySelector('#swjtu-filter-learned').addEventListener('change', onFilterChange);
    panelEl.querySelector('#swjtu-open-mode').addEventListener('change', onOpenConfigChange);
    panelEl.querySelector('#swjtu-open-interval').addEventListener('change', onOpenConfigChange);

    syncOpenConfigToUI();
    ensureResourceData().then(() => renderList());
  }

  function unmountPanel() {
    if (panelEl) { panelEl.remove(); panelEl = null; }
    panelMounted = false;
    learnedMap.clear();
  }

  // ── 4. 渲染列表 ───────────────────────────────────────────────────────────────
  function renderList() {
    if (!panelEl) return;

    const allItems = collectItems();
    const items = applyFilters(allItems);
    const listEl = panelEl.querySelector('#swjtu-list');
    const countEl = panelEl.querySelector('#swjtu-count');

    // 如果 resourceMap 或 learnedMap 还没数据，等 fetch 完成后再渲染（最多重试 10 次）
    if ((resourceMap.size === 0 || learnedMap.size === 0) && renderRetryCount < 10) {
      renderRetryCount++;
      ensureResourceData().then(() => setTimeout(renderList, 300));
      return;
    }
    if (allItems.length === 0 && renderRetryCount < 10) {
      renderRetryCount++;
      setTimeout(renderList, 300);
      return;
    }

    listEl.innerHTML = '';

    let total = 0, unlearned = 0;

    for (const item of items) {
      total++;
      if (!item.learned) unlearned++;

      const row = document.createElement('label');
      row.className = 'swjtu-row' + (item.learned ? ' swjtu-learned' : ' swjtu-unlearned');

      const cb = document.createElement('input');
      cb.type = 'checkbox';
      const safeUrl = (typeof item.fullUrl === 'string' && item.fullUrl.startsWith('https://e-learning.swjtu.edu.cn/#/CourseLearning/'))
        ? item.fullUrl
        : '';
      const key = getItemKey(item);
      const checked = checkedStateMap.has(key) ? checkedStateMap.get(key) : false;
      cb.checked = checked;
      cb.dataset.url = safeUrl;
      cb.dataset.key = key;
      cb.addEventListener('change', () => {
        checkedStateMap.set(key, cb.checked);
        updateOpenBtn();
      });

      const icon = document.createElement('span');
      icon.className = 'swjtu-icon';
      icon.textContent = item.type === 'video' ? '▶' : '📄';

      const name = document.createElement('span');
      name.className = 'swjtu-name';
      name.textContent = item.name;

      const badge = document.createElement('span');
      badge.className = 'swjtu-badge' + (item.learned ? ' swjtu-badge-done' : '');
      badge.textContent = item.learned ? '已学习' : '未学习';

      row.appendChild(cb);
      row.appendChild(icon);
      row.appendChild(name);
      row.appendChild(badge);
      listEl.appendChild(row);
    }

    countEl.textContent = `当前 ${total} 条，未学习 ${unlearned} 条`;
    updateOpenBtn();
  }

  function getItemKey(item) {
    if (item.resourceId) return `res::${item.resourceId}`;
    return `${item.type}::${item.name}`;
  }

  function applyFilters(items) {
    return items.filter(item => {
      const typePass = filters.type === 'all' || item.type === filters.type;
      const learnedPass = filters.learned === 'all'
        || (filters.learned === 'learned' && item.learned)
        || (filters.learned === 'unlearned' && !item.learned);
      return typePass && learnedPass;
    });
  }

  function onFilterChange() {
    if (!panelEl) return;
    filters.type = panelEl.querySelector('#swjtu-filter-type').value;
    filters.learned = panelEl.querySelector('#swjtu-filter-learned').value;
    renderList();
  }

  function onOpenConfigChange() {
    if (!panelEl) return;
    openConfig.mode = panelEl.querySelector('#swjtu-open-mode').value;
    const intervalRaw = Number(panelEl.querySelector('#swjtu-open-interval').value);
    openConfig.intervalMs = Number.isFinite(intervalRaw) ? Math.max(300, Math.floor(intervalRaw)) : 1200;
    panelEl.querySelector('#swjtu-open-interval').value = String(openConfig.intervalMs);
  }

  function syncOpenConfigToUI() {
    if (!panelEl) return;
    panelEl.querySelector('#swjtu-open-mode').value = openConfig.mode;
    panelEl.querySelector('#swjtu-open-interval').value = String(openConfig.intervalMs);
  }

  // ── 5. 从 DOM 读取资源列表，结合 resourceMap + learnedMap 构建条目 ──────────
  function collectItems() {
    const items = [];
    const domItems = document.querySelectorAll('.list-item');

    for (const el of domItems) {
      const nameEl = el.querySelector('.name');
      const tagEl = el.querySelector('.tag');
      const titleEl = el.querySelector('.titel');
      if (!nameEl || !tagEl) continue;

      // 没有 .titel 的条目（如论坛评论）不是课程资源，跳过
      if (!titleEl) continue;

      const rawName = nameEl.textContent.trim();
      const name = rawName.replace(/\s*\(\d{2}:\d{2}:\d{2}\)\s*$/, '');
      const isVideo = titleEl.textContent.includes('视频');

      // 从 resourceMap 匹配：按名称 + 类型
      let matched = null;
      for (const [, res] of resourceMap) {
        const sameType = isVideo ? res.suffix === 'mp4' : res.suffix !== 'mp4';
        if (sameType && res.name === name) {
          matched = res;
          break;
        }
      }

      // 优先用 learnedMap（来自 getCourseInfoViewtime），否则回退到 DOM
      const learned = matched
        ? (learnedMap.has(matched.id) ? learnedMap.get(matched.id) : tagEl.classList.contains('active'))
        : tagEl.classList.contains('active');

      items.push({
        name,
        learned,
        type: isVideo ? 'video' : 'doc',
        fullUrl: matched ? buildUrl(matched) : null,
        resourceId: matched?.id ?? null,
      });
    }

    return items;
  }

  function buildUrl(res) {
    const type = res.suffix === 'mp4' ? 'video' : 'doc';
    const encodedName = encodeURIComponent(res.name);
    const encodedUrl = encodeURIComponent(res.url);
    return `https://e-learning.swjtu.edu.cn/#/CourseLearning/${type}?id=${res.id}&courseCode=${res.courseCode}&url=${encodedUrl}&name=${encodedName}`;
  }

  // ── 6. 批量打开选中项 ─────────────────────────────────────────────────────────
  function getVisibleCheckedRows() {
    return Array.from(panelEl.querySelectorAll('#swjtu-list .swjtu-row')).filter(row => {
      const cb = row.querySelector('input[type=checkbox]');
      return cb?.checked;
    });
  }

  function openSelected() {
    if (openConfig.mode === 'simulate') {
      openSelectedSimulated();
      return;
    }
    openSelectedDirect();
  }

  function openSelectedDirect() {
    const checked = panelEl.querySelectorAll('#swjtu-list input[type=checkbox]:checked');
    let count = 0;
    for (const cb of checked) {
      const url = cb.dataset.url;
      if (url && url.startsWith('https://e-learning.swjtu.edu.cn/#/CourseLearning/')) {
        setTimeout(() => window.open(url, '_blank'), count * 300);
        count++;
      }
    }
  }


  function openSelectedSimulated() {
    const rows = getVisibleCheckedRows();
    const keys = rows.map(row => {
      const cb = row.querySelector('input[type=checkbox]');
      const urlStr = cb?.dataset?.url ?? '';
      // 从 URL 里取 id 用于学习记录接口
      const idMatch = urlStr.match(/[?&]id=(\d+)/);
      const courseCodeMatch = urlStr.match(/[?&]courseCode=([^&]+)/);
      return {
        name: row.querySelector('.swjtu-name')?.textContent?.trim() ?? '',
        type: row.querySelector('.swjtu-icon')?.textContent?.includes('▶') ? 'video' : 'doc',
        url: urlStr,
        resourceId: idMatch ? idMatch[1] : null,
        courseCode: courseCodeMatch ? decodeURIComponent(courseCodeMatch[1]) : null,
      };
    }).filter(k => k.name && k.url);

    function clickNext(idx) {
      if (idx >= keys.length) {
        // 全部处理完，刷新 learnedMap 并重新渲染面板
        fetchLearnedMap().then(() => renderList());
        return;
      }
      const { url, resourceId, courseCode } = keys[idx];

      // 上报学习记录（与真实点击行为等价）
      if (resourceId && courseCode) {
        fetch('/api/study/record/browsing/insertresourceviewing', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
          body: JSON.stringify({ course_code: courseCode, key_id: Number(resourceId) }),
        }).catch(() => {});
      }

      if (url.startsWith('https://e-learning.swjtu.edu.cn/#/CourseLearning/')) {
        window.open(url, '_blank');
      }

      setTimeout(() => clickNext(idx + 1), openConfig.intervalMs);
    }

    clickNext(0);
  }


// ── 7. 辅助函数 ───────────────────────────────────────────────────────────────
  function updateOpenBtn() {
    if (!panelEl) return;
    const n = panelEl.querySelectorAll('#swjtu-list input[type=checkbox]:checked').length;
    panelEl.querySelector('#swjtu-open-btn').textContent = `打开选中 (${n})`;
  }

  function setAll(uncheckAll) {
    panelEl.querySelectorAll('#swjtu-list input[type=checkbox]').forEach(cb => {
      const shouldCheck = uncheckAll ? false : !cb.closest('.swjtu-row').classList.contains('swjtu-learned');
      cb.checked = shouldCheck;
      if (cb.dataset.key) checkedStateMap.set(cb.dataset.key, shouldCheck);
    });
    updateOpenBtn();
  }

  let collapsed = false;
  function toggleCollapse() {
    collapsed = !collapsed;
    panelEl.querySelector('#swjtu-body').style.display = collapsed ? 'none' : 'flex';
    panelEl.querySelector('#swjtu-toggle').textContent = collapsed ? '▼ 展开' : '▲ 收起';
  }

  // ── 8. HTML 模板 ──────────────────────────────────────────────────────────────
  function getPanelHTML() {
    return `
      <div id="swjtu-header">
        <span id="swjtu-title">📚 课程学习面板</span>
        <span id="swjtu-count"></span>
        <button id="swjtu-toggle">▲ 收起</button>
      </div>
      <div id="swjtu-body">
        <div id="swjtu-toolbar">
          <label class="swjtu-filter-label">类型
            <select id="swjtu-filter-type">
              <option value="all">全部</option>
              <option value="video">视频</option>
              <option value="doc">文档</option>
            </select>
          </label>
          <label class="swjtu-filter-label">状态
            <select id="swjtu-filter-learned">
              <option value="unlearned" selected>未学习</option>
              <option value="learned">已学习</option>
              <option value="all">全部</option>
            </select>
          </label>
          <label class="swjtu-filter-label">打开
            <select id="swjtu-open-mode">
              <option value="direct">直链</option>
              <option value="simulate" selected>仿真点击</option>
            </select>
          </label>
          <label class="swjtu-filter-label">间隔
            <input id="swjtu-open-interval" type="number" min="300" step="100" value="10000" />
            <span>ms</span>
          </label>
          <button id="swjtu-check-unlearned">勾选未学习</button>
          <button id="swjtu-uncheck-all">全不选</button>
          <button id="swjtu-open-btn">打开选中 (0)</button>
        </div>
        <div id="swjtu-list"></div>
      </div>
    `;
  }

  // ── 9. 样式注入 ───────────────────────────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById('swjtu-style')) return;
    const style = document.createElement('style');
    style.id = 'swjtu-style';
    style.textContent = `
      #swjtu-panel {
        position: fixed;
        top: 80px;
        right: 0;
        width: 340px;
        max-height: calc(100vh - 100px);
        background: #fff;
        border: 1px solid #ddd;
        border-right: none;
        border-radius: 8px 0 0 8px;
        box-shadow: -4px 0 16px rgba(0,0,0,0.12);
        z-index: 99999;
        display: flex;
        flex-direction: column;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        font-size: 13px;
        color: #333;
      }
      #swjtu-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 12px;
        background: #1a6fc4;
        color: #fff;
        border-radius: 8px 0 0 0;
        flex-shrink: 0;
      }
      #swjtu-title { font-weight: 600; font-size: 14px; flex: 1; }
      #swjtu-count { font-size: 11px; opacity: 0.85; white-space: nowrap; }
      #swjtu-toggle {
        background: rgba(255,255,255,0.2);
        border: none;
        color: #fff;
        cursor: pointer;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 12px;
        white-space: nowrap;
      }
      #swjtu-body {
        display: flex;
        flex-direction: column;
        overflow: hidden;
        flex: 1;
      }
      #swjtu-toolbar {
        display: flex;
        gap: 6px;
        padding: 8px 10px;
        border-bottom: 1px solid #eee;
        flex-shrink: 0;
        flex-wrap: wrap;
      }
      #swjtu-toolbar button {
        padding: 4px 10px;
        border-radius: 4px;
        border: 1px solid #ccc;
        background: #f5f5f5;
        cursor: pointer;
        font-size: 12px;
        color: #333;
      }
      .swjtu-filter-label {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 12px;
        color: #555;
      }
      .swjtu-filter-label select,
      .swjtu-filter-label input {
        height: 24px;
        border: 1px solid #ccc;
        border-radius: 4px;
        background: #fff;
        font-size: 12px;
        padding: 0 4px;
        width: 74px;
        box-sizing: border-box;
      }
      #swjtu-open-btn {
        background: #1a6fc4 !important;
        color: #fff !important;
        border-color: #1a6fc4 !important;
        margin-left: auto;
      }
      #swjtu-list {
        overflow-y: auto;
        flex: 1;
        padding: 4px 0;
      }
      .swjtu-row {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 5px 10px;
        cursor: pointer;
        line-height: 1.4;
        border-bottom: 1px solid #f0f0f0;
      }
      .swjtu-row:hover { background: #f8f9fa; }
      .swjtu-row input[type=checkbox] { flex-shrink: 0; cursor: pointer; }
      .swjtu-icon { flex-shrink: 0; font-size: 12px; }
      .swjtu-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .swjtu-learned .swjtu-name { color: #888; }
      .swjtu-badge {
        flex-shrink: 0;
        font-size: 11px;
        padding: 1px 5px;
        border-radius: 3px;
        background: #fee;
        color: #c00;
      }
      .swjtu-badge-done {
        background: #e8f5e9;
        color: #2e7d32;
      }
    `;
    document.head.appendChild(style);
  }
})();
