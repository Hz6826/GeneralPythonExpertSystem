/* ============================================================
   console.js —— 推理控制台：状态管理 + 渲染 + 与 /api/v1 交互

   设计要点
     1. 后端是真源：每次动作后都用 /engine/status + /engine/facts 回读，
        前端不自己推算迭代数。
     2. 「运行到底」走 POST /engine/run，是后端后台线程；前端用轮询观察，
        结束时补一条汇总轨迹。「单步到底」则由前端循环 /engine/step，
        慢一些但轨迹里能逐条看到 IF/THEN。
     3. 轮询用「世代」令牌（state.pollGen）管理：任何一次 await 之后都要
        确认自己仍然是当前那一条轮询链，否则直接退出，避免旧的 tick 写错
        状态或把新链掐死。
     4. 所有请求都由 api.js 加了超时，所以 busy/running 不会被一个挂死的
        请求永久锁住。
   ============================================================ */
(function () {
    'use strict';

    var API = window.ExpertAPI;
    if (!API) {
        console.error('api.js 未加载');
        return;
    }

    /* ============================================================
       常量
       ============================================================ */

    var STOP_TEXT = {
        no_rule: '没有可匹配的规则',
        no_change: '事实不再增长（不动点）',
        max_iter: '达到最大迭代次数'
    };

    var POLL_MS = 400;          // 后台推理时的轮询间隔
    var NEW_FACT_TTL = 1800;    // 新增事实高亮时长
    var MAX_TRACE = 1500;       // 轨迹最多保留条数（要能装下一次 max_iter=1000 的完整推理）
    var MAX_STEPS = 1200;       // 「单步到底」的前端保护上限
    var MAX_POLL_FAILURES = 8;  // 连续轮询失败多少次后放弃并解锁界面
    var DIALOG_ANIM_MS = 140;   // 确认框退出动画时长，要和 base.css 里的保持一致
    var LS_EXAMPLE = 'expert-example';

    /* ============================================================
       DOM
       ============================================================ */

    function $(id) { return document.getElementById(id); }

    var el = {
        // 顶栏
        conn: $('conn'),
        toast: $('toast'),

        // 推理控制
        step: $('btn-step'),
        stepAll: $('btn-step-all'),
        run: $('btn-run'),
        pause: $('btn-pause'),
        reset: $('btn-reset'),
        init: $('btn-init'),
        statRunning: $('stat-running'),
        statIter: $('stat-iter'),
        statStop: $('stat-stop'),
        statFacts: $('stat-facts'),
        engineHint: $('engine-hint'),
        lockEngine: $('lock-engine'),

        // 工作记忆
        facts: $('fact-list'),
        factCount: $('fact-count'),
        form: $('fact-form'),
        fname: $('fact-name'),
        fvalue: $('fact-value'),
        ftype: $('fact-type'),
        assertBtn: $('btn-assert'),
        bulkToggle: $('btn-bulk-toggle'),
        clearFacts: $('btn-clear-facts'),
        bulkForm: $('bulk-form'),
        bulkText: $('bulk-text'),
        bulkSubmit: $('btn-bulk-assert'),
        bulkCancel: $('btn-bulk-cancel'),
        lockFacts: $('lock-facts'),

        // 知识库
        exampleSelect: $('example-select'),
        loadExample: $('btn-load-example'),
        kbHint: $('kb-hint'),
        kbDocPanel: $('kb-doc-panel'),
        kbDocBody: $('kb-doc-body'),

        // 轨迹
        log: $('log'),
        logCount: $('log-count'),
        copyLog: $('btn-copy-log'),
        clearLog: $('btn-clear-log'),

        // 网页内确认框
        confirmOverlay: $('confirm-overlay'),
        confirmTitle: $('confirm-title'),
        confirmMessage: $('confirm-message'),
        confirmOk: $('confirm-ok'),
        confirmCancel: $('confirm-cancel')
    };

    // 缺任何一个元素都直接退出：否则 bindEvents 会在中途抛异常，
    // 结果是「一个事件都没绑上」，比直接不启动更难排查。
    var missing = Object.keys(el).filter(function (key) { return !el[key]; });
    if (missing.length) {
        console.error('页面结构不完整，缺少元素：' + missing.join(', '));
        return;
    }

    /* ============================================================
       状态
       ============================================================ */

    var state = {
        facts: [],
        iterations: 0,
        running: false,
        paused: false,          // 上次停下来的原因是「用户点了暂停」而不是推理到停机
        stopReason: null,
        reachedMax: false,
        trace: [],
        busy: false,
        connected: false,
        kbLoaded: false,       // 后端 /engine/status 的 kb_loaded：没有知识库就锁住两张卡片
        kbName: null,
        docCache: {},          // 知识库名 -> markdown 原文
        docBlocks: [],         // 当前渲染出来的代码块文本，供「一键填入」按钮按索引取用
        docRendered: null,     // 面板里当前展示的是哪个知识库的说明
        docLoading: null,      // 正在拉取说明的知识库名
        newFacts: new Map(),   // name -> 首次出现时间戳
        flashTimer: null,
        pollTimer: null,
        pollCtx: null,
        pollGen: 0,            // 轮询世代：让在途的旧 tick 自动失效
        pollFailures: 0
    };

    /* ============================================================
       小工具
       ============================================================ */

    function span(cls, text) {
        var node = document.createElement('span');
        node.className = cls;
        node.textContent = text;
        return node;
    }

    function emptyItem(text) {
        var li = document.createElement('li');
        li.className = 'empty';
        li.textContent = text;
        return li;
    }

    function stopText(reason) {
        if (!reason) return '—';
        return STOP_TEXT[reason] || reason;
    }

    /** 值的展示形式：true 是默认值，不显示；字符串加引号以便和布尔/数字区分。 */
    function formatValue(value) {
        if (value === true) return '';
        if (value === false) return 'false';
        if (value === null) return 'null';
        if (typeof value === 'number') return String(value);
        if (typeof value === 'string') return JSON.stringify(value);
        try { return JSON.stringify(value); } catch (e) { return String(value); }
    }

    function factNames(facts) {
        var set = new Set();
        (facts || []).forEach(function (f) { set.add(f.name); });
        return set;
    }

    function diffAdded(beforeNames, afterFacts) {
        var added = [];
        (afterFacts || []).forEach(function (f) {
            if (!beforeNames.has(f.name)) added.push(f.name);
        });
        return added;
    }

    /* ============================================================
       提示条 / 连接状态
       ============================================================ */

    var toastTimer = null;

    function toast(message, kind) {
        if (!el.toast) return;
        el.toast.textContent = message;
        el.toast.className = 'toast toast-' + (kind || 'info');
        el.toast.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () {
            el.toast.hidden = true;
        }, kind === 'error' ? 7000 : 3600);
    }

    function setConnected(ok) {
        state.connected = !!ok;
        if (!el.conn) return;
        el.conn.textContent = ok ? '已连接' : '未连接';
        el.conn.className = 'badge ' + (ok ? 'badge-ok' : 'badge-bad');
        el.conn.title = ok ? 'GET /api/v1/ 正常' : 'GET /api/v1/ 失败：后端可能没有启动';
    }

    /* ============================================================
       网页内确认框（替代 window.confirm，支持动画 + 背景模糊）
       ============================================================ */

    var dialogResolve = null;
    var dialogTimer = null;

    /**
     * @param {{title?:string, message?:string, okText?:string, cancelText?:string,
     *          danger?:boolean}} opts
     * @returns {Promise<boolean>} 点「确定」为 true，取消 / Esc / 点背景为 false
     */
    function confirmDialog(opts) {
        var options = opts || {};

        return new Promise(function (resolve) {
            // 极端情况下如果已经有框在开着，先把上一个当作取消，再复用同一个框
            if (dialogResolve) {
                var previous = dialogResolve;
                dialogResolve = null;
                previous(false);
            }

            el.confirmTitle.textContent = options.title || '请确认';
            el.confirmMessage.textContent = options.message || '';
            el.confirmOk.textContent = options.okText || '确定';
            el.confirmCancel.textContent = options.cancelText || '取消';
            // 默认按危险操作渲染（红色确定按钮）
            el.confirmOk.className = options.danger === false ? 'btn-primary' : 'btn-danger';

            dialogResolve = resolve;

            clearTimeout(dialogTimer);
            el.confirmOverlay.classList.remove('is-closing', 'is-open');
            el.confirmOverlay.hidden = false;
            // 强制一次重排，保证连续弹框时进场动画会重新播放
            void el.confirmOverlay.offsetWidth;
            el.confirmOverlay.classList.add('is-open');
            el.confirmOk.focus();
        });
    }

    function closeDialog(result) {
        if (!dialogResolve) return;
        var resolve = dialogResolve;
        dialogResolve = null;

        el.confirmOverlay.classList.remove('is-open');
        el.confirmOverlay.classList.add('is-closing');
        clearTimeout(dialogTimer);
        dialogTimer = setTimeout(function () {
            el.confirmOverlay.hidden = true;
            el.confirmOverlay.classList.remove('is-closing');
            resolve(result);
        }, DIALOG_ANIM_MS);
    }

    function bindDialog() {
        el.confirmOk.addEventListener('click', function () { closeDialog(true); });
        el.confirmCancel.addEventListener('click', function () { closeDialog(false); });

        // 点背景（不是点对话框本身）当作取消
        el.confirmOverlay.addEventListener('click', function (ev) {
            if (ev.target === el.confirmOverlay) closeDialog(false);
        });

        // Esc 取消；Tab 只在两个按钮之间循环，避免焦点跑到模糊层后面
        el.confirmOverlay.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape') {
                ev.preventDefault();
                closeDialog(false);
                return;
            }
            if (ev.key !== 'Tab') return;
            ev.preventDefault();
            var focusables = [el.confirmCancel, el.confirmOk];
            var index = focusables.indexOf(document.activeElement);
            var next = ev.shiftKey
                ? (index <= 0 ? focusables.length - 1 : index - 1)
                : (index === focusables.length - 1 ? 0 : index + 1);
            focusables[next].focus();
        });
    }

    /** 把任意异常翻译成用户能看懂的一句话。 */
    function describeError(err) {
        if (!(err instanceof API.ApiError)) {
            return (err && err.message) ? err.message : String(err);
        }
        if (err.isOffline()) {
            return '连不上后端：' + err.message;
        }
        if (err.isServerRejection()) {
            // route.py 用 RuntimeError 表示“业务拒绝”，非 debug 模式下 message 会被抹成
            // "Unknown error"，所以只能按路径反推原因。
            var map = {
                '/engine/run': '引擎已经在运行中',
                '/engine/pause': '引擎当前没有在运行'
            };
            return map[err.path] || '服务端拒绝了该操作（HTTP 500 / code -1）';
        }
        return err.message + '（HTTP ' + err.http + '，code ' + err.code + '）';
    }

    function handleError(err) {
        var msg = describeError(err);
        pushTrace({ kind: 'error', text: msg });
        toast(msg, 'error');
        if (err instanceof API.ApiError && err.isOffline()) setConnected(false);
    }

    /* ============================================================
       轨迹
       ============================================================ */

    /**
     * 追加一条轨迹。常见的「只往末尾加」情况只插入一个节点，
     * 避免「单步到底」跑上千步时每次都整表重渲染（O(n²)）。
     */
    function pushTrace(entry) {
        state.trace.push(entry);
        if (state.trace.length > MAX_TRACE) {
            state.trace.splice(0, state.trace.length - MAX_TRACE);
            renderTrace();
            return;
        }
        if (state.trace.length === 1) {
            renderTrace();          // 从占位项变成真实条目
            return;
        }
        appendTraceNode(traceEntryNode(entry));
    }

    function appendTraceNode(node) {
        if (!el.log) return;
        var atBottom = el.log.scrollTop + el.log.clientHeight >= el.log.scrollHeight - 32;
        el.log.appendChild(node);
        if (atBottom) el.log.scrollTop = el.log.scrollHeight;
        if (el.logCount) el.logCount.textContent = String(state.trace.length);
    }

    function suffixFor(value) {
        var text = formatValue(value);
        return text === '' ? '' : ' = ' + text;
    }

    function traceEntryNode(e) {
        var li = document.createElement('li');
        li.className = 'trace-' + e.kind;

        if (e.kind === 'rule') {
            var head = document.createElement('div');
            head.className = 't-head';
            if (typeof e.iterations === 'number') {
                head.appendChild(span('t-iter', '迭代 ' + e.iterations));
            }
            if (e.degraded) {
                head.appendChild(span('rname', '规则已触发'));
                head.appendChild(span('t-note', '后端未返回详情'));
            } else {
                head.appendChild(span('rname', e.name || '(未命名规则)'));
                if (e.priority !== undefined && e.priority !== null) {
                    head.appendChild(span('rprio', 'P' + e.priority));
                }
            }
            li.appendChild(head);

            // conditions 由 route.py 转成了函数名字符串（has_xxx），可以直接展示
            if (e.conditions && e.conditions.length) {
                var cond = document.createElement('div');
                cond.className = 't-cond';
                cond.appendChild(span('t-label', 'IF'));
                cond.appendChild(span('t-body', e.conditions.join(' ∧ ')));
                li.appendChild(cond);
            }

            var concl = e.conclusion;
            var line = document.createElement('div');
            line.className = 't-concl';
            line.appendChild(span('t-label', 'THEN'));
            if (concl && typeof concl === 'object' && concl.name) {
                line.appendChild(span('radded', concl.name + suffixFor(concl.value)));
            } else if (e.added && e.added.length) {
                line.appendChild(span('radded', '新增 ' + e.added.join('、')));
            } else if (e.degraded) {
                line.appendChild(span('radded', '（结论未知，请查看工作记忆）'));
            } else {
                line.appendChild(span('radded', '未新增事实（结论已在工作记忆中）'));
            }
            li.appendChild(line);

            if (e.stop) {
                li.appendChild(span('t-note', '停止：' + stopText(e.stop)));
            }
            return li;
        }

        if (e.kind === 'stop') {
            li.textContent = '停止：' + stopText(e.stop) +
                (e.iterations === undefined ? '' : '（迭代 ' + e.iterations + '）');
            return li;
        }

        if (e.kind === 'run') {
            li.textContent = '后台推理结束：触发 ' + e.fired + ' 条规则，迭代 ' + e.iterations +
                (e.stop ? '，停止原因：' + stopText(e.stop) : '');
            return li;
        }

        if (e.kind === 'error') {
            li.textContent = '错误：' + e.text;
            return li;
        }

        li.textContent = e.text;
        return li;
    }

    /** 纯文本形式，给「复制轨迹」用。 */
    function traceEntryText(e) {
        if (e.kind !== 'rule') return traceEntryNode(e).textContent;

        var parts = [];
        parts.push('迭代 ' + (e.iterations === undefined ? '?' : e.iterations));
        if (e.degraded) {
            parts.push('规则已触发（后端未返回详情）');
        } else {
            parts.push((e.name || '(未命名规则)') +
                (e.priority === undefined || e.priority === null ? '' : ' [P' + e.priority + ']'));
        }
        if (e.conditions && e.conditions.length) parts.push('IF ' + e.conditions.join(' AND '));
        if (e.conclusion && e.conclusion.name) {
            parts.push('THEN ' + e.conclusion.name + suffixFor(e.conclusion.value));
        } else if (e.added && e.added.length) {
            parts.push('THEN 新增 ' + e.added.join('、'));
        } else if (e.degraded) {
            parts.push('THEN (未知)');
        } else {
            parts.push('THEN 未新增事实');
        }
        if (e.stop) parts.push('停止：' + stopText(e.stop));
        return parts.join('  ');
    }

    function renderTrace() {
        if (!el.log) return;
        if (!state.trace.length) {
            el.log.replaceChildren(emptyItem('（还没有动作：断言事实后点「单步」或「运行到底」）'));
        } else {
            var atBottom = el.log.scrollTop + el.log.clientHeight >= el.log.scrollHeight - 32;
            var frag = document.createDocumentFragment();
            state.trace.forEach(function (e) { frag.appendChild(traceEntryNode(e)); });
            el.log.replaceChildren(frag);
            if (atBottom) el.log.scrollTop = el.log.scrollHeight;
        }
        if (el.logCount) el.logCount.textContent = String(state.trace.length);
    }

    function traceToText() {
        return state.trace.map(traceEntryText).join('\n');
    }

    /* ============================================================
       渲染：控制区 / 状态 / 事实
       ============================================================ */

    function renderControls() {
        var lockAll = state.busy || state.running;   // 推理控制：跑的时候也不许点
        var lockFacts = lockAll;                     // 工作记忆：跑的时候只读，避免和轮询抢渲染
        var noKb = !state.kbLoaded;                  // 没知识库：两张卡片整体锁掉

        if (el.step) el.step.disabled = lockAll || noKb;
        if (el.stepAll) el.stepAll.disabled = lockAll || noKb;
        if (el.run) el.run.disabled = lockAll || noKb;
        if (el.pause) el.pause.disabled = state.busy || !state.running;
        if (el.reset) el.reset.disabled = lockAll || noKb;
        if (el.init) el.init.disabled = lockAll || noKb;
        if (el.loadExample) el.loadExample.disabled = lockAll || el.exampleSelect.disabled;
        if (el.clearFacts) el.clearFacts.disabled = lockFacts || noKb || !state.facts.length;
        if (el.assertBtn) el.assertBtn.disabled = lockFacts || noKb;
        if (el.bulkToggle) el.bulkToggle.disabled = lockFacts || noKb;
        if (el.bulkSubmit) el.bulkSubmit.disabled = lockFacts || noKb;
        if (el.bulkCancel) el.bulkCancel.disabled = state.busy;
        if (el.fname) el.fname.disabled = lockFacts || noKb;
        if (el.fvalue) el.fvalue.disabled = lockFacts || noKb;
        if (el.ftype) el.ftype.disabled = lockFacts || noKb;
        if (el.bulkText) el.bulkText.disabled = lockFacts || noKb;

        // 每行的 × 也要真的 disabled：不能只是点下去没反应
        var icons = el.facts ? el.facts.querySelectorAll('.icon-btn') : [];
        for (var i = 0; i < icons.length; i++) icons[i].disabled = lockFacts || noKb;

        el.facts.classList.toggle('is-locked', lockFacts || noKb);
        document.body.classList.toggle('is-running', state.running);
        renderLock();
    }

    /** 没有知识库时，用半透明遮罩盖住「工作记忆」和「推理控制」两张卡片。 */
    function renderLock() {
        var noKb = !state.kbLoaded;
        var offline = !state.connected;

        [el.lockFacts, el.lockEngine].forEach(function (node) {
            if (!node) return;
            node.hidden = !noKb;
            if (!noKb) return;
            var title = node.querySelector('p');
            if (title) title.textContent = offline ? '后端未连接' : '请先载入知识库';
        });

        // 说明面板里的「一键填入」按钮：没知识库 / 正忙的时候也不能点
        if (el.kbDocBody) {
            var fills = el.kbDocBody.querySelectorAll('[data-act="fill"]');
            var locked = noKb || state.busy || state.running;
            for (var i = 0; i < fills.length; i++) fills[i].disabled = locked;
        }
    }

    function renderStatus() {
        if (el.statRunning) {
            el.statRunning.textContent = state.running ? '运行中…' : '已停止';
            el.statRunning.className = state.running ? 'is-running' : '';
        }
        if (el.statIter) el.statIter.textContent = String(state.iterations);
        if (el.statStop) el.statStop.textContent = stopText(state.stopReason);
        if (el.statFacts) el.statFacts.textContent = String(state.facts.length);
        if (el.factCount) el.factCount.textContent = String(state.facts.length);
        if (el.engineHint) el.engineHint.textContent = engineHint();
        renderControls();
    }

    function engineHint() {
        if (state.running) return '后台推理进行中，界面每 ' + POLL_MS + 'ms 回读一次状态；工作记忆此时只读。';
        if (state.paused) return '已暂停在第 ' + state.iterations + ' 步；可以继续「单步」或「运行到底」。';
        if (state.reachedMax || state.stopReason === 'max_iter') {
            return '已达最大迭代次数（核心默认 1000）；需要重置后才能继续。';
        }
        if (state.stopReason === 'no_rule') return '没有可匹配的规则了；继续断言事实后可以再次单步/运行。';
        if (state.stopReason === 'no_change') return '已到不动点：再次触发同一规则但没有产生新事实。';
        if (!state.facts.length) return '工作记忆为空：先在左侧断言症状事实（例如 wire_connected）。';
        return '就绪：可以「单步」逐条观察规则触发，或「运行到底」跑到不动点。';
    }

    function renderFacts() {
        if (!el.facts) return;
        if (!state.facts.length) {
            el.facts.replaceChildren(emptyItem('（空）断言一条事实，或载入示例知识库后补充症状。'));
            renderControls();
            return;
        }

        var now = Date.now();
        var frag = document.createDocumentFragment();
        state.facts.forEach(function (f) {
            var li = document.createElement('li');
            li.dataset.name = f.name;
            var born = state.newFacts.get(f.name);
            if (born && now - born < NEW_FACT_TTL) li.className = 'is-new';

            var name = document.createElement('button');
            name.type = 'button';
            name.className = 'fname';
            name.dataset.act = 'fill';
            name.title = '点击填入断言表单';
            name.textContent = f.name;
            li.appendChild(name);

            var text = formatValue(f.value);
            if (text !== '') {
                li.appendChild(span('fval', '= ' + text));
            }

            var del = document.createElement('button');
            del.type = 'button';
            del.className = 'icon-btn';
            del.dataset.act = 'del';
            del.title = '删除事实 ' + f.name;
            del.setAttribute('aria-label', '删除事实 ' + f.name);
            del.textContent = '×';
            li.appendChild(del);

            frag.appendChild(li);
        });
        el.facts.replaceChildren(frag);
        renderControls();
    }

    /* ============================================================
       状态写入
       ============================================================ */

    function applyStatus(status) {
        if (!status) return;
        state.running = !!status.running;
        state.iterations = typeof status.iterations === 'number' ? status.iterations : 0;
        state.stopReason = status.stop_reason || null;
        state.reachedMax = !!status.reached_max_iterations;

        // 知识库状态以后端为准：刷新页面 / 换标签页都不会失真。
        // 只有真的带了 kb_loaded 的响应才更新，避免本地拼出来的 status 把它冲掉。
        if (typeof status.kb_loaded === 'boolean') {
            var prevLoaded = state.kbLoaded;
            var prevName = state.kbName;
            state.kbLoaded = status.kb_loaded;
            state.kbName = status.kb_name || null;
            if (!state.kbLoaded) state.docBlocks = [];
            // 从「没有」变成「有」，或者换了一个知识库，都要把说明换成新的
            if (state.kbLoaded && (!prevLoaded || prevName !== state.kbName)) ensureDoc();
        }

        renderStatus();
        renderKbHint();
    }

    function applyFacts(facts, addedNames) {
        state.facts = Array.isArray(facts) ? facts.slice() : [];
        var now = Date.now();
        if (addedNames && addedNames.length) {
            addedNames.forEach(function (n) { state.newFacts.set(n, now); });
            clearTimeout(state.flashTimer);
            state.flashTimer = setTimeout(renderFacts, NEW_FACT_TTL + 80);
        }
        // 高亮表只用来做一次性动画，攒多了就清掉过期项
        if (state.newFacts.size > 200) {
            state.newFacts.forEach(function (ts, name) {
                if (now - ts > NEW_FACT_TTL) state.newFacts.delete(name);
            });
        }
        renderFacts();
        renderStatus();
    }

    async function refreshStatus() {
        var status = await API.engineStatus();
        setConnected(true);
        applyStatus(status);
        return status;
    }

    async function refreshAll() {
        var both = await Promise.all([API.engineStatus(), API.listFacts()]);
        setConnected(true);
        applyStatus(both[0]);
        applyFacts(both[1].facts || []);
    }

    /* ============================================================
       动作包装
       ============================================================ */

    async function runAction(fn) {
        if (state.busy) return;
        state.busy = true;
        state.paused = false;      // 用户又动手了，不再是「暂停休息」状态
        renderControls();
        try {
            await fn();
        } catch (err) {
            handleError(err);
        } finally {
            state.busy = false;
            renderControls();
        }
    }

    /* ============================================================
       推理控制
       ============================================================ */

    async function doStep() {
        await runAction(async function () {
            var beforeIter = state.iterations;
            var beforeNames = factNames(state.facts);
            var data = null;
            var failure = null;

            try {
                data = await API.engineStep();
                setConnected(true);
            } catch (err) {
                if (!(err instanceof API.ApiError) || !err.isServerRejection()) throw err;
                failure = err;
            }

            /* --- 情况一：后端明确回答“没有规则可触发” --- */
            if (data && data.fired === false) {
                applyStatus({
                    running: false,
                    iterations: data.iterations,
                    stop_reason: data.stop_reason,
                    // 引擎里 reached_max_iterations 就是 stop_reason == "max_iter"
                    reached_max_iterations: data.stop_reason === 'max_iter'
                });
                pushTrace({ kind: 'stop', stop: data.stop_reason, iterations: data.iterations });
                toast('没有可触发的规则：' + stopText(data.stop_reason), 'warn');
                return;
            }

            /* --- 情况二：正常触发了一条规则（route.py 已把 conditions 转成函数名列表） --- */
            if (data && data.fired) {
                var factsData = null;
                try { factsData = await API.listFacts(); } catch (e) { factsData = null; }
                // 状态回读失败不能吞掉这一条规则轨迹：副作用已经发生了
                try { await refreshStatus(); } catch (e) { /* 保持本地状态，轨迹照写 */ }
                var added = factsData ? diffAdded(beforeNames, factsData.facts || []) : [];
                if (factsData) applyFacts(factsData.facts || [], added);
                pushTrace({
                    kind: 'rule',
                    name: data.name,
                    conditions: data.conditions,
                    priority: data.priority,
                    conclusion: data.conclusion,
                    iterations: data.iterations,
                    added: added,
                    stop: state.stopReason
                });
                return;
            }

            /* --- 情况三：兜底。后端 500 但副作用可能已经发生（例如旧版本后端），
                   用迭代数变化 + 事实差集还原这一步。 --- */
            var status = null;
            try { status = await API.engineStatus(); } catch (e) { status = null; }
            if (!status || status.iterations <= beforeIter) {
                throw failure || new Error('单步失败');
            }

            var list = null;
            try { list = await API.listFacts(); } catch (e) { list = null; }
            var newOnes = list ? diffAdded(beforeNames, list.facts || []) : [];
            applyStatus(status);
            if (list) applyFacts(list.facts || [], newOnes);
            pushTrace({
                kind: 'rule',
                degraded: true,
                iterations: status.iterations,
                added: newOnes,
                stop: status.stop_reason
            });
            toast('单步已执行，但后端没有返回规则详情', 'warn');
        });
    }

    /**
     * 单步到底：反复调用 /engine/step，把每一条触发的规则都写进轨迹。
     *
     * 和「运行到底」的区别：
     *   · 运行到底 走 POST /engine/run，由后端线程一口气跑完（快、可暂停），
     *     但接口不回传逐条规则，前端只能给出一条汇总。
     *   · 单步到底 由前端循环调用 /engine/step，慢一些，但轨迹里能看到
     *     每一步的 IF / THEN，适合排查推理链。
     */
    async function doStepAll() {
        await runAction(async function () {
            var fired = 0;
            var startIter = state.iterations;
            var names = factNames(state.facts);
            var stopped = false;
            var loopError = null;

            for (var i = 0; i < MAX_STEPS; i++) {
                var data = null;
                try {
                    data = await API.engineStep();
                    setConnected(true);
                } catch (err) {
                    // 中途出错也要把已经跑完的部分交代清楚，不能闷掉
                    loopError = err;
                    break;
                }

                if (!data.fired) {
                    applyStatus({
                        running: false,
                        iterations: data.iterations,
                        stop_reason: data.stop_reason,
                        reached_max_iterations: data.stop_reason === 'max_iter'
                    });
                    pushTrace({ kind: 'stop', stop: data.stop_reason, iterations: data.iterations });
                    stopped = true;
                    break;
                }

                fired++;
                var added = [];
                if (data.conclusion && data.conclusion.name && !names.has(data.conclusion.name)) {
                    added.push(data.conclusion.name);
                    names.add(data.conclusion.name);
                }
                pushTrace({
                    kind: 'rule',
                    name: data.name,
                    conditions: data.conditions,
                    priority: data.priority,
                    conclusion: data.conclusion,
                    iterations: data.iterations,
                    added: added,
                    stop: data.stop_reason
                });
            }

            // 无论中间是否出错，都把界面同步回后端真源
            try { await refreshAll(); } catch (e) { /* 下次轮询/操作会再同步 */ }

            pushTrace({
                kind: 'info',
                text: '单步到底结束：共触发 ' + fired + ' 条规则，迭代 ' +
                    startIter + ' → ' + state.iterations +
                    (stopped ? '' : (loopError ? '（中途出错）' : '（已到前端上限 ' + MAX_STEPS + ' 步）'))
            });
            if (loopError) {
                handleError(loopError);
            } else {
                toast('单步到底：触发了 ' + fired + ' 条规则', fired ? 'ok' : 'warn');
            }
        });
    }

    async function doRun() {
        await runAction(async function () {
            var ctx = {
                beforeIter: state.iterations,
                names: factNames(state.facts)
            };
            try {
                await API.engineRun();
                setConnected(true);
            } catch (err) {
                // 500 / code -1 既可能是「已经在跑」，也可能是 run_in_background 内部真的炸了。
                // 回读一次状态来区分，别把真正的错误伪装成「已在运行中」。
                if (err instanceof API.ApiError && err.isServerRejection()) {
                    var st = null;
                    try { st = await API.engineStatus(); } catch (e) { st = null; }
                    if (st && st.running) {
                        toast('引擎已经在运行中', 'warn');
                        startPolling(ctx);
                        return;
                    }
                }
                throw err;
            }
            startPolling(ctx);
        });
    }

    async function doPause() {
        await runAction(async function () {
            try {
                await API.enginePause();
            } catch (err) {
                if (err instanceof API.ApiError && err.isServerRejection()) {
                    toast('引擎当前没有在运行', 'warn');
                    state.pollCtx = null;
                    stopPolling();
                    await refreshStatus().catch(function () {});
                    return;
                }
                throw err;
            }
            // 让下一次轮询知道这是「暂停」而不是「推理到停机」
            if (state.pollCtx) state.pollCtx.paused = true;
            pushTrace({ kind: 'info', text: '已请求暂停后台推理' });
            toast('已暂停', 'ok');
            if (!state.pollTimer) {
                // 没有正在跑的轮询链，自己回读一次状态
                await refreshStatus().catch(function () {});
                if (!state.running) {
                    state.paused = true;
                    pushTrace({ kind: 'info', text: '已暂停在第 ' + state.iterations + ' 步' });
                    renderStatus();
                }
            }
        });
    }

    async function doReset() {
        await runAction(async function () {
            state.pollCtx = null;
            stopPolling();
            state.paused = false;
            await API.engineReset();
            await refreshStatus();
            pushTrace({ kind: 'info', text: '已复位推理状态（保留事实与知识库）' });
            toast('已重置推理状态', 'ok');
        });
    }

    async function doInit() {
        var go = await confirmDialog({
            title: '全部初始化',
            message: '会清空知识库与工作记忆，且不可撤销。确定继续？',
            okText: '全部初始化'
        });
        if (!go) return;
        await runAction(async function () {
            state.pollCtx = null;
            stopPolling();
            state.paused = false;
            await API.engineInit();
            state.newFacts.clear();
            applyStatus({
                running: false,
                iterations: 0,
                stop_reason: null,
                reached_max_iterations: false,
                kb_loaded: false,
                kb_name: null
            });
            applyFacts([]);
            renderDocPlaceholder('载入知识库后，这里会显示它的用途说明与示例事实模板。');
            state.trace.length = 0;
            pushTrace({ kind: 'info', text: '已全部初始化：知识库与工作记忆均已清空' });
            toast('已全部初始化', 'ok');
        });
    }

    /* ---- 后台推理轮询 ---- */

    /**
     * @param {{beforeIter:number, names:Set, paused?:boolean}} ctx
     * @param {{adopted?:boolean}} [opts] adopted=true 表示这是「刷新页面后接管
     *        一个已经在跑的后台任务」，不是本页发起的。
     */
    function startPolling(ctx, opts) {
        stopPolling();                       // 里面会让世代号 +1，作废在途的旧 tick
        ctx.gen = state.pollGen;
        ctx.paused = false;
        state.pollCtx = ctx;
        state.pollFailures = 0;
        state.paused = false;
        state.running = true;
        renderStatus();
        pushTrace({
            kind: 'info',
            text: (opts && opts.adopted)
                ? '检测到后端正在推理，已接管状态轮询…'
                : '开始后台推理…'
        });
        pollTick();
    }

    function stopPolling() {
        state.pollGen += 1;                  // 让所有在途的 tick 失效
        if (state.pollTimer) {
            clearTimeout(state.pollTimer);
            state.pollTimer = null;
        }
        state.running = false;
        renderControls();
    }

    /** 当前这条轮询链是否仍然有效（未被取消、也没被新的一次 run 顶掉）。 */
    function stillCurrent(ctx) {
        return state.pollCtx === ctx && ctx.gen === state.pollGen;
    }

    async function pollTick() {
        var ctx = state.pollCtx;
        if (!ctx) return;

        var status = null;
        try {
            status = await API.engineStatus();
            setConnected(true);
        } catch (err) {
            if (!stillCurrent(ctx)) return;
            setConnected(false);

            // 后端一直读不到就放弃轮询并解锁，避免界面永久卡在「运行中」。
            state.pollFailures += 1;
            if (state.pollFailures >= MAX_POLL_FAILURES) {
                pushTrace({ kind: 'error', text: '连续 ' + state.pollFailures + ' 次读不到引擎状态，已停止轮询（请检查后端）' });
                toast('读不到引擎状态，已停止轮询', 'error');
                state.pollCtx = null;
                stopPolling();
                return;
            }
            state.pollTimer = setTimeout(pollTick, 1200);
            return;
        }

        if (!stillCurrent(ctx)) return;      // 等待期间被重置/初始化/载入示例取消了

        state.pollFailures = 0;
        applyStatus(status);

        try {
            var data = await API.listFacts();
            if (!stillCurrent(ctx)) return;
            var facts = data.facts || [];
            var added = diffAdded(ctx.names, facts);
            added.forEach(function (n) { ctx.names.add(n); });
            applyFacts(facts, added);
        } catch (e) {
            /* 单次读事实失败不影响轮询 */
        }

        if (!stillCurrent(ctx)) return;

        if (!status.running) {
            finishPolling(status, ctx);
            return;
        }
        state.pollTimer = setTimeout(pollTick, POLL_MS);
    }

    function finishPolling(status, ctx) {
        if (!stillCurrent(ctx)) return;      // 收尾权只属于当前那条链

        state.pollCtx = null;
        stopPolling();

        var fired = Math.max(0, (status.iterations || 0) - (ctx.beforeIter || 0));

        if (ctx.paused && !status.stop_reason) {
            // 用户按了暂停：推理并没有到停机点，别写成「运行结束」
            state.paused = true;
            pushTrace({
                kind: 'info',
                text: '已暂停：本次触发 ' + fired + ' 条规则，停在第 ' + (status.iterations || 0) + ' 步（事实保留，可继续推理）'
            });
            toast('已暂停在第 ' + (status.iterations || 0) + ' 步', 'ok');
            renderStatus();
            return;
        }

        pushTrace({
            kind: 'run',
            fired: fired,
            iterations: status.iterations || 0,
            stop: status.stop_reason
        });
        toast(fired ? '后台推理结束：共触发 ' + fired + ' 条规则' : '后台推理结束：没有可触发的规则',
            fired ? 'ok' : 'warn');
    }

    /* ============================================================
       工作记忆
       ============================================================ */

    function validateName(name) {
        if (!name) throw new Error('事实名不能为空');
        if (name.indexOf('/') !== -1) {
            throw new Error('事实名不能包含 “/”：后端路由 <string:name> 不匹配斜杠');
        }
        if (name.length > 200) throw new Error('事实名过长（>200 字符）');
    }

    function assertHashable(value) {
        if (value !== null && typeof value === 'object') {
            throw new Error('值不能是对象或数组：引擎把事实放进 set，值必须可哈希');
        }
    }

    /** @returns {{value:*, hasValue:boolean}} */
    function coerceValue(raw, mode) {
        var text = String(raw === undefined || raw === null ? '' : raw).trim();

        if (mode === 'text') return { value: text, hasValue: true };

        if (mode === 'number') {
            var n = Number(text);
            if (text === '' || !isFinite(n)) throw new Error('不是合法数字：' + text);
            return { value: n, hasValue: true };
        }

        if (mode === 'bool') {
            var lower = text.toLowerCase();
            if (lower === 'true' || lower === '1' || lower === 'yes' || lower === '是') {
                return { value: true, hasValue: true };
            }
            if (lower === 'false' || lower === '0' || lower === 'no' || lower === '否') {
                return { value: false, hasValue: true };
            }
            throw new Error('布尔值只能是 true / false（也接受 1 / 0）');
        }

        if (mode === 'json') {
            if (text === '') throw new Error('JSON 模式下值不能为空');
            var parsed;
            try {
                parsed = JSON.parse(text);
            } catch (e) {
                throw new Error('不是合法 JSON：' + e.message);
            }
            assertHashable(parsed);
            return { value: parsed, hasValue: true };
        }

        /* 自动 */
        if (text === '') return { value: true, hasValue: false };   // 交给后端默认 true
        if (text === 'true') return { value: true, hasValue: true };
        if (text === 'false') return { value: false, hasValue: true };
        if (text === 'null') return { value: null, hasValue: true };
        if (/^-?\d+(\.\d+)?$/.test(text)) return { value: Number(text), hasValue: true };
        return { value: text, hasValue: true };
    }

    async function submitFact(ev) {
        if (ev) ev.preventDefault();
        if (state.busy || state.running) return;   // 后台推理期间工作记忆只读

        var name = el.fname.value.trim();
        if (!name) { el.fname.focus(); return; }

        var parsed;
        try {
            validateName(name);
            parsed = coerceValue(el.fvalue.value, el.ftype.value);
        } catch (err) {
            toast(err.message, 'error');
            return;
        }

        await runAction(async function () {
            var beforeNames = factNames(state.facts);
            var wasIter = state.iterations;
            var reopened = state.stopReason !== null;

            var data = await API.addFact(name, parsed.value, parsed.hasValue);
            var facts = data.facts || [];
            applyFacts(facts, diffAdded(beforeNames, facts));

            el.fname.value = '';
            el.fvalue.value = '';
            el.fname.focus();

            await refreshStatus().catch(function () {});
            if (reopened && state.stopReason === null) {
                pushTrace({ kind: 'info', text: '事实变动，引擎已重新打开（可从第 ' + wasIter + ' 步继续）' });
            }
        });
    }

    async function removeFact(name) {
        if (state.busy || state.running) return;
        await runAction(async function () {
            var data = await API.deleteFact(name);
            state.newFacts.delete(name);
            applyFacts(data.facts || []);
            await refreshStatus().catch(function () {});

            var status = state.stopReason;
            pushTrace({
                kind: 'info',
                text: '已删除事实 ' + name + (status === null ? '（引擎已重新打开）' : '')
            });
        });
    }

    async function clearFacts() {
        if (state.busy || state.running) return;
        if (!state.facts.length) return;
        var go = await confirmDialog({
            title: '清空工作记忆',
            message: '将删除工作记忆中的全部 ' + state.facts.length + ' 条事实，且不可撤销。',
            okText: '清空'
        });
        if (!go) return;
        await runAction(async function () {
            var data = await API.clearFacts();
            state.newFacts.clear();
            applyFacts(data.facts || []);
            await refreshStatus().catch(function () {});
            pushTrace({ kind: 'info', text: '已清空工作记忆' });
        });
    }

    /* ---- 批量断言 ---- */

    function parseBulk(text) {
        var items = [];
        String(text || '').split(/\r?\n/).forEach(function (raw, index) {
            var line = raw.trim();
            if (!line || line.charAt(0) === '#') return;
            var eq = line.indexOf('=');
            if (eq === -1) {
                items.push({ line: index + 1, name: line, raw: '' });
            } else {
                items.push({
                    line: index + 1,
                    name: line.slice(0, eq).trim(),
                    raw: line.slice(eq + 1).trim()
                });
            }
        });
        return items;
    }

    /**
     * 逐条断言一批事实。批量断言表单和知识库说明里的「一键填入」共用这一套。
     * @param {Array<{line:number,name:string,raw:string}>} items
     * @param {{source?:string, clearFirst?:boolean, onDone?:Function}} [opts]
     *        clearFirst=true 时先清空工作记忆再写入（「一键填入」模板用）
     */
    async function assertBulkItems(items, opts) {
        var options = opts || {};
        var label = options.source || '批量断言';

        await runAction(async function () {
            var ok = 0;
            var errors = [];

            if (options.clearFirst) {
                var cleared = await API.clearFacts();
                state.newFacts.clear();
                applyFacts(cleared.facts || []);
            }

            for (var i = 0; i < items.length; i++) {
                var item = items[i];
                try {
                    validateName(item.name);
                    var parsed = coerceValue(item.raw, 'auto');
                    var data = await API.addFact(item.name, parsed.value, parsed.hasValue);
                    applyFacts(data.facts || []);
                    ok++;
                } catch (err) {
                    errors.push('第 ' + item.line + ' 行：' + describeError(err));
                }
            }

            await refreshStatus().catch(function () {});
            pushTrace({
                kind: 'info',
                text: label + '完成：成功 ' + ok + ' 条' +
                    (errors.length ? '，失败 ' + errors.length + ' 条' : '')
            });
            if (errors.length) {
                errors.slice(0, 3).forEach(function (msg) {
                    pushTrace({ kind: 'error', text: msg });
                });
                toast(label + '：成功 ' + ok + ' 条，失败 ' + errors.length + ' 条', 'error');
            } else {
                toast(label + '：成功写入 ' + ok + ' 条事实', 'ok');
            }
            if (options.onDone) options.onDone(ok, errors.length);
        });
    }

    async function submitBulk(ev) {
        if (ev) ev.preventDefault();
        if (state.busy || state.running || !state.kbLoaded) return;   // 没知识库 / 后台推理期间只读

        var items = parseBulk(el.bulkText.value);
        if (!items.length) {
            toast('没有可提交的内容', 'warn');
            return;
        }

        await assertBulkItems(items, {
            source: '批量断言',
            onDone: function (ok, failed) {
                if (!failed) {
                    el.bulkText.value = '';
                    el.bulkForm.hidden = true;
                }
            }
        });
    }

    /* ============================================================
       知识库
       ============================================================ */

    function rememberExample(name) {
        try { localStorage.setItem(LS_EXAMPLE, name); } catch (e) { /* 忽略 */ }
    }

    function rememberedExample() {
        try { return localStorage.getItem(LS_EXAMPLE); } catch (e) { return null; }
    }

    function renderKbHint() {
        if (!el.kbHint) return;
        if (state.kbName) {
            el.kbHint.textContent = '当前知识库：' + state.kbName +
                '（载入新的示例会替换它并清空工作记忆）';
        } else if (!state.kbLoaded) {
            el.kbHint.textContent = '尚未载入知识库。载入示例会替换知识库并清空工作记忆。';
        } else {
            el.kbHint.textContent = '知识库已载入，但后端没有记录名称。';
        }
    }

    /* ---------------- 知识库说明（markdown 子集渲染） ----------------
       后端把 network.py 的 docstring 原样返回，这里只认一个很小的 markdown
       子集，并且全部用 createElement + textContent 生成节点 —— 不碰 innerHTML，
       所以 docstring 里就算写了 HTML 也只会被当成文字。
    ------------------------------------------------------------------ */

    function mdInline(text, parent) {
        // 支持 `code` 与 **bold**，其余按纯文本处理
        var pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g;
        var last = 0;
        var match;
        while ((match = pattern.exec(text)) !== null) {
            if (match.index > last) {
                parent.appendChild(document.createTextNode(text.slice(last, match.index)));
            }
            var token = match[0];
            if (token.charAt(0) === '`') {
                var code = document.createElement('code');
                code.textContent = token.slice(1, -1);
                parent.appendChild(code);
            } else {
                var strong = document.createElement('strong');
                strong.textContent = token.slice(2, -2);
                parent.appendChild(strong);
            }
            last = match.index + token.length;
        }
        if (last < text.length) {
            parent.appendChild(document.createTextNode(text.slice(last)));
        }
    }

    function mdBlockNode(lines, info) {
        var wrapper = document.createElement('div');
        wrapper.className = 'md-block';

        var text = lines.join('\n');
        var kind = info.trim().toLowerCase();

        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'mini';
        button.dataset.block = String(state.docBlocks.length);
        button.dataset.act = kind === 'facts' ? 'fill' : 'copy';
        button.textContent = kind === 'facts' ? '一键填入' : '复制';
        wrapper.appendChild(button);

        if (kind === 'facts') wrapper.classList.add('md-fillable');

        var pre = document.createElement('pre');
        var code = document.createElement('code');
        code.textContent = text;
        pre.appendChild(code);
        wrapper.appendChild(pre);

        state.docBlocks.push(text);
        return wrapper;
    }

    /** 把 markdown 渲染进 mount；只支持标题 / 代码块 / 列表 / 段落 / 行内 code、bold。 */
    function renderMarkdown(text, mount) {
        mount.replaceChildren();
        state.docBlocks = [];

        var lines = String(text || '').split(/\r?\n/);
        var i = 0;

        while (i < lines.length) {
            var line = lines[i];
            var trimmed = line.trim();

            if (trimmed === '') { i++; continue; }

            // 围栏代码块
            if (trimmed.indexOf('```') === 0) {
                var info = trimmed.slice(3);
                var body = [];
                i++;
                while (i < lines.length && lines[i].trim().indexOf('```') !== 0) {
                    body.push(lines[i]);
                    i++;
                }
                if (i < lines.length) i++;     // 吃掉收尾围栏；未闭合就吃到结尾
                mount.appendChild(mdBlockNode(body, info));
                continue;
            }

            // 标题
            var heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
            if (heading) {
                var level = Math.min(2 + heading[1].length, 5);   // # -> h3, ## -> h4, ### 及以上 -> h5
                var h = document.createElement('h' + level);
                mdInline(heading[2], h);
                mount.appendChild(h);
                i++;
                continue;
            }

            // 分隔线
            if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
                mount.appendChild(document.createElement('hr'));
                i++;
                continue;
            }

            // 无序列表
            if (/^[-*]\s+/.test(trimmed)) {
                var ul = document.createElement('ul');
                while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
                    var li = document.createElement('li');
                    mdInline(lines[i].trim().replace(/^[-*]\s+/, ''), li);
                    ul.appendChild(li);
                    i++;
                }
                mount.appendChild(ul);
                continue;
            }

            // 有序列表
            if (/^\d+\.\s+/.test(trimmed)) {
                var ol = document.createElement('ol');
                while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
                    var li2 = document.createElement('li');
                    mdInline(lines[i].trim().replace(/^\d+\.\s+/, ''), li2);
                    ol.appendChild(li2);
                    i++;
                }
                mount.appendChild(ol);
                continue;
            }

            // 段落：连续非空行合并
            var para = document.createElement('p');
            var buf = [];
            while (i < lines.length) {
                var t = lines[i].trim();
                if (t === '' || t.indexOf('```') === 0 || /^#{1,6}\s+/.test(t) ||
                    /^[-*]\s+/.test(t) || /^\d+\.\s+/.test(t)) {
                    break;
                }
                buf.push(t);
                i++;
            }
            mdInline(buf.join(' '), para);
            mount.appendChild(para);
        }

        if (!mount.childNodes.length) {
            var empty = document.createElement('p');
            empty.className = 'md-empty';
            empty.textContent = '该知识库没有提供说明。';
            mount.appendChild(empty);
        }
    }

    function renderDocPlaceholder(text) {
        if (!el.kbDocBody) return;
        state.docBlocks = [];
        state.docRendered = null;
        el.kbDocBody.replaceChildren();
        var p = document.createElement('p');
        p.className = 'md-empty';
        p.textContent = text;
        el.kbDocBody.appendChild(p);
    }

    /** 拉取（或从缓存取出）指定知识库的说明并渲染。 */
    async function loadDoc(name) {
        if (!name) { renderDocPlaceholder('载入知识库后，这里会显示它的用途说明与示例事实模板。'); return; }

        if (Object.prototype.hasOwnProperty.call(state.docCache, name)) {
            renderMarkdown(state.docCache[name], el.kbDocBody);
            state.docRendered = name;
            return;
        }
        if (state.docLoading === name) return;      // 同一个知识库已经在取了，别重复发请求

        state.docLoading = name;
        renderDocPlaceholder('正在读取知识库说明…');
        try {
            var data = await API.getExampleDoc(name);
            setConnected(true);
            state.docCache[name] = data.doc || '';
            if (state.kbName === name) {
                renderMarkdown(state.docCache[name], el.kbDocBody);
                state.docRendered = name;
            }
        } catch (err) {
            if (state.kbName === name) {
                renderDocPlaceholder('无法读取知识库说明：' + describeError(err));
            }
        } finally {
            if (state.docLoading === name) state.docLoading = null;
        }
    }

    /** 只在「当前知识库的说明还没渲染出来」时取一次（切换知识库会自动重取）。 */
    function ensureDoc() {
        if (!el.kbDocBody) return;
        if (!state.kbName) {
            renderDocPlaceholder('载入知识库后，这里会显示它的用途说明与示例事实模板。');
            return;
        }
        if (state.docRendered === state.kbName) return;
        loadDoc(state.kbName);
    }

    function fillExamples(names, placeholder) {
        if (!el.exampleSelect) return;
        el.exampleSelect.replaceChildren();

        if (!names || !names.length) {
            var only = document.createElement('option');
            only.value = '';
            only.textContent = placeholder || '（后端没有注册示例）';
            el.exampleSelect.appendChild(only);
            el.exampleSelect.disabled = true;
            renderControls();
            return;
        }

        names.forEach(function (name) {
            var opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            el.exampleSelect.appendChild(opt);
        });
        el.exampleSelect.disabled = false;

        var saved = rememberedExample();
        if (saved && names.indexOf(saved) !== -1) el.exampleSelect.value = saved;
        renderControls();
    }

    async function doLoadExample() {
        var name = el.exampleSelect.value;
        if (!name) { toast('请先选择示例知识库', 'warn'); return; }

        await runAction(async function () {
            state.pollCtx = null;
            stopPolling();
            state.paused = false;
            await API.loadExample(name);

            state.newFacts.clear();
            rememberExample(name);

            // refreshAll 的 applyStatus 会用后端的 kb_name 更新 state.kbName，
            // 并在名称变化时自动重取说明，所以这里不用自己设
            await refreshAll();
            el.kbDocPanel.open = true;      // 载入知识库后自动展开说明面板
            state.trace.length = 0;
            pushTrace({
                kind: 'info',
                text: '已载入知识库 ' + name + '：工作记忆已清空，请断言症状事实（例如 wire_connected）'
            });
            toast('已载入 ' + name, 'ok');
        });
    }

    /* ============================================================
       轨迹操作
       ============================================================ */

    function clearTrace() {
        state.trace.length = 0;
        renderTrace();
    }

    /** 复制一段文本，带 execCommand 降级。 */
    function copyText(text, okMessage) {
        var message = okMessage || '已复制到剪贴板';

        function fallback() {
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.setAttribute('readonly', 'readonly');
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            document.body.appendChild(ta);
            ta.select();
            var ok = false;
            try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
            document.body.removeChild(ta);
            toast(ok ? message : '复制失败，请手动选择文本', ok ? 'ok' : 'error');
        }

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function () {
                toast(message, 'ok');
            }, fallback);
        } else {
            fallback();
        }
    }

    function copyTrace() {
        var text = traceToText();
        if (!text) { toast('轨迹为空', 'warn'); return; }
        copyText(text, '轨迹已复制到剪贴板');
    }

    /* ---- 知识库说明里的代码块按钮 ---- */

    async function runBlockAction(index, act) {
        var text = state.docBlocks[index];
        if (typeof text !== 'string') return;

        if (act === 'copy') {
            if (!text.trim()) { toast('这个代码块是空的', 'warn'); return; }
            copyText(text, '代码块已复制到剪贴板');
            return;
        }

        if (!state.kbLoaded) { toast('请先载入知识库', 'warn'); return; }
        if (state.busy || state.running) return;

        var items = parseBulk(text);
        if (!items.length) { toast('这个模板里没有可断言的事实', 'warn'); return; }

        // 一键填入 = 先清空工作记忆，再按模板写入（等于切换到该故障场景）。
        // 会丢掉已有事实，所以和「清空事实」一样先问一句；没事实可清就不打扰。
        if (state.facts.length) {
            var go = await confirmDialog({
                title: '清空并填入模板',
                message: '将清空工作记忆中的全部 ' + state.facts.length + ' 条事实，' +
                    '并填入模板里的 ' + items.length + ' 条事实。',
                okText: '清空并填入'
            });
            if (!go) return;
        }
        await assertBulkItems(items, { source: '清空并填入模板', clearFirst: true });
    }

    /* ============================================================
       事件绑定
       ============================================================ */

    function bindEvents() {
        el.step.addEventListener('click', doStep);
        el.stepAll.addEventListener('click', doStepAll);
        el.run.addEventListener('click', doRun);
        el.pause.addEventListener('click', doPause);
        el.reset.addEventListener('click', doReset);
        el.init.addEventListener('click', doInit);

        el.form.addEventListener('submit', submitFact);

        el.facts.addEventListener('click', function (ev) {
            var target = ev.target;
            if (!target || !target.closest) return;

            var del = target.closest('[data-act="del"]');
            if (del) {
                var row = del.closest('li');
                if (row && row.dataset.name) removeFact(row.dataset.name);
                return;
            }

            var fill = target.closest('[data-act="fill"]');
            if (fill) {
                el.fname.value = fill.dataset.name || '';
                el.fname.focus();
                if (el.fname.select) el.fname.select();
            }
        });

        el.bulkToggle.addEventListener('click', function () {
            el.bulkForm.hidden = !el.bulkForm.hidden;
            if (!el.bulkForm.hidden) el.bulkText.focus();
        });
        el.bulkCancel.addEventListener('click', function () {
            el.bulkForm.hidden = true;
        });
        el.bulkForm.addEventListener('submit', submitBulk);
        el.clearFacts.addEventListener('click', clearFacts);

        el.loadExample.addEventListener('click', doLoadExample);
        el.exampleSelect.addEventListener('change', function () {
            if (el.exampleSelect.value) rememberExample(el.exampleSelect.value);
        });

        el.clearLog.addEventListener('click', clearTrace);
        el.copyLog.addEventListener('click', copyTrace);

        document.addEventListener('keydown', function (ev) {
            if (ev.ctrlKey || ev.metaKey || ev.altKey || ev.defaultPrevented) return;
            var t = ev.target;
            var tag = t && t.tagName ? t.tagName.toLowerCase() : '';
            if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
            if (t && t.isContentEditable) return;
            if (dialogResolve) return;      // 确认框开着时不响应快捷键，避免操作到模糊层后面

            var key = String(ev.key || '').toLowerCase();
            if (key === 's') { ev.preventDefault(); el.step.click(); }
            else if (key === 'a') { ev.preventDefault(); el.stepAll.click(); }
            else if (key === 'r') { ev.preventDefault(); el.run.click(); }
            else if (key === 'p') { ev.preventDefault(); el.pause.click(); }
        });

        window.addEventListener('beforeunload', stopPolling);
    }

    function bindDocPanel() {
        // 代码块右上角的按钮：一键填入 / 复制
        el.kbDocBody.addEventListener('click', function (ev) {
            var target = ev.target;
            if (!target || !target.closest) return;
            var btn = target.closest('[data-block]');
            if (!btn) return;
            var index = parseInt(btn.dataset.block, 10);
            if (isNaN(index)) return;
            runBlockAction(index, btn.dataset.act);
        });

        // 折叠面板展开时如果还没取过说明，补取一次
        el.kbDocPanel.addEventListener('toggle', function () {
            if (el.kbDocPanel.open) ensureDoc();
        });
    }

    /* ============================================================
       启动
       ============================================================ */

    async function boot() {
        bindEvents();
        bindDocPanel();
        bindDialog();
        renderFacts();
        renderStatus();
        renderTrace();
        renderKbHint();
        renderDocPlaceholder('载入知识库后，这里会显示它的用途说明与示例事实模板。');

        try {
            await API.ping();
            setConnected(true);
        } catch (err) {
            setConnected(false);
            // 后端都连不上，别让示例下拉框一直停在「加载中…」
            fillExamples([], '（无法连接后端）');
            handleError(err);
            return;
        }

        try {
            var examples = await API.listExamples();
            fillExamples(examples.list || []);
        } catch (err) {
            // 拉不到列表就别让下拉框一直停在「加载中…」
            fillExamples([], '（无法读取示例列表）');
            handleError(err);
        }

        try {
            await refreshAll();
            // 刷新页面 / 新开标签页时后端可能正在跑：必须接管轮询，
            // 否则界面会永远停在「运行中…」且所有按钮都被锁住。
            if (state.running) {
                startPolling({
                    beforeIter: state.iterations,
                    names: factNames(state.facts)
                }, { adopted: true });
            }
        } catch (err) {
            handleError(err);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
