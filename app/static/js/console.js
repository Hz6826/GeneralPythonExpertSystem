/* console.js —— 与后端推理引擎通信，并把状态渲染到页面 */
(function () {
    'use strict';

    const $ = function (id) {
        return document.getElementById(id);
    };

    const el = {
        facts: $('fact-list'),
        rules: $('rule-list'),
        log: $('log'),
        iter: $('stat-iter'),
        stop: $('stat-stop'),
        form: $('fact-form'),
        fname: $('fact-name'),
        fvalue: $('fact-value'),
        step: $('btn-step'),
        run: $('btn-run'),
        reset: $('btn-reset')
    };

    const STOP_TEXT = {
        no_rule: '没有可匹配的规则',
        no_change: '事实不再增长（不动点）',
        max_iter: '达到最大迭代次数'
    };

    let busy = false;

    /* ---------------- HTTP ---------------- */

    function api(path, body) {
        const opts = {method: body === undefined ? 'GET' : 'POST'};
        if (body !== undefined) {
            opts.headers = {'Content-Type': 'application/json'};
            opts.body = JSON.stringify(body);
        }
        return fetch(path, opts).then(function (res) {
            if (!res.ok) throw new Error(path + ' → HTTP ' + res.status);
            return res.json();
        });
    }

    function send(path, body) {
        if (busy) return;
        busy = true;
        toggleButtons(false);

        api(path, body)
            .then(render)
            .catch(function (err) {
                pushError(err.message);
            })
            .finally(function () {
                busy = false;
                toggleButtons(true);
            });
    }

    function toggleButtons(on) {
        el.step.disabled = !on;
        el.run.disabled = !on;
        el.reset.disabled = !on;
    }

    /* ---------------- 渲染 ---------------- */

    function render(state) {
        renderFacts(state.facts || []);
        renderRules(state.rules || []);
        renderLog(state.log || []);

        el.iter.textContent = state.iterations == null ? 0 : state.iterations;
        el.stop.textContent = state.stop_reason
            ? (STOP_TEXT[state.stop_reason] || state.stop_reason)
            : '—';
    }

    function renderFacts(facts) {
        if (!facts.length) {
            el.facts.innerHTML = '<li class="empty">（空）</li>';
            return;
        }
        const frag = document.createDocumentFragment();
        facts.forEach(function (f) {
            const li = document.createElement('li');

            const name = document.createElement('span');
            name.className = 'fname';
            name.textContent = f.name;
            li.appendChild(name);

            if (f.value !== '' && f.value != null) {
                const val = document.createElement('span');
                val.className = 'fval';
                val.textContent = ' = ' + f.value;
                li.appendChild(val);
            }
            frag.appendChild(li);
        });
        el.facts.replaceChildren(frag);
    }

    function renderRules(rules) {
        if (!rules.length) {
            el.rules.innerHTML = '<li class="empty">（空）</li>';
            return;
        }
        const frag = document.createDocumentFragment();
        rules.forEach(function (r) {
            const li = document.createElement('li');
            if (r.applicable) li.classList.add('applicable');
            if (r.fired) li.classList.add('fired');

            const name = document.createElement('span');
            name.className = 'rname';
            name.textContent = r.name;

            const prio = document.createElement('span');
            prio.className = 'rprio';
            prio.textContent = 'P' + (r.priority == null ? 0 : r.priority);

            li.append(name, prio);
            frag.appendChild(li);
        });
        el.rules.replaceChildren(frag);
    }

    function renderLog(entries) {
        if (!entries.length) {
            el.log.innerHTML = '<li class="empty">（尚未触发任何规则）</li>';
            return;
        }
        const frag = document.createDocumentFragment();
        entries.forEach(function (e) {
            const li = document.createElement('li');

            if (e.stop) {
                li.className = 'stop';
                li.textContent = '停止：' + (STOP_TEXT[e.stop] || e.stop);
            } else {
                const name = document.createElement('span');
                name.className = 'rname';
                name.textContent = e.rule;
                li.appendChild(name);

                if (e.added) {
                    const added = document.createElement('span');
                    added.className = 'radded';
                    added.textContent = '  → ' + e.added;
                    li.appendChild(added);
                }
            }
            frag.appendChild(li);
        });
        el.log.replaceChildren(frag);
        el.log.scrollTop = el.log.scrollHeight;
    }

    function pushError(msg) {
        const li = document.createElement('li');
        li.className = 'stop';
        li.textContent = '错误：' + msg;
        el.log.appendChild(li);
        el.log.scrollTop = el.log.scrollHeight;
    }

    /* ---------------- 事件 ---------------- */

    el.step.addEventListener('click', function () {
        send('/api/step', {});
    });
    el.run.addEventListener('click', function () {
        send('/api/run', {});
    });
    el.reset.addEventListener('click', function () {
        send('/api/reset', {});
    });

    el.form.addEventListener('submit', function (ev) {
        ev.preventDefault();

        const name = el.fname.value.trim();
        if (!name) {
            el.fname.focus();
            return;
        }

        const raw = el.fvalue.value.trim();
        el.fname.value = '';
        el.fvalue.value = '';
        el.fname.focus();

        send('/api/assert', {name: name, value: raw === '' ? true : raw});
    });

    /* ---------------- 启动 ---------------- */

    api('/api/state').then(render).catch(function (e) {
        pushError(e.message);
    });
})();
