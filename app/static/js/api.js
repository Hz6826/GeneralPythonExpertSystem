/* ============================================================
   api.js —— /api/v1 客户端（只依赖 fetch，无第三方库）

   后端契约见 app/route.py：
     · 所有 /api/v1/* 响应都是「信封」格式
         成功  {code: 0,  status: "success", data: {...}}
         失败  {code: ≠0, status: "error",   message: "..."}
     · 失败时 HTTP 状态码与 code 一致；函数内部抛出的普通异常
       一律被 auto_handle_exception 收敛成 HTTP 500 / code -1。
     · 未注册的路径不经过装饰器，Flask 直接返回 HTML 404（没有信封），
       所以调用方必须容忍「非 JSON 响应」。

   对外只暴露 window.ExpertAPI。
   ============================================================ */
(function (global) {
    'use strict';

    var BASE = '/api/v1';
    var TIMEOUT_MS = 15000;     // 请求超时：避免一个挂死的请求把 UI 的 busy 状态永久锁住

    /* ---------------- 错误类型 ---------------- */

    /**
     * @param {string} message 人类可读的说明
     * @param {{code?:number, http?:number, path?:string, raw?:string}} info
     */
    function ApiError(message, info) {
        var err = Error.call(this, message);
        this.name = 'ApiError';
        this.message = message;
        this.code = info && typeof info.code === 'number' ? info.code : -1;
        this.http = info && typeof info.http === 'number' ? info.http : 0;
        this.path = (info && info.path) || '';
        this.raw = (info && info.raw) || '';
        this.stack = err.stack || '';
    }

    ApiError.prototype = Object.create(Error.prototype);
    ApiError.prototype.constructor = ApiError;

    /** 网络层根本没连上（服务未启动 / 断网）。 */
    ApiError.prototype.isOffline = function () {
        return this.http === 0;
    };

    /**
     * route.py 里用 RuntimeError 表达的「业务拒绝」，例如
     * “Engine is running!” / “Engine is not running!”。
     * 非 debug 模式下 message 会被抹成 "Unknown error"，只能靠 HTTP 500 + code -1 判断。
     */
    ApiError.prototype.isServerRejection = function () {
        return this.http === 500 && this.code === -1;
    };

    /* ---------------- 底层请求 ---------------- */

    function buildUrl(path, query) {
        var url = BASE + path;
        if (!query) return url;
        var qs = new URLSearchParams();
        Object.keys(query).forEach(function (key) {
            var value = query[key];
            if (value === undefined || value === null) return;
            qs.append(key, String(value));
        });
        var s = qs.toString();
        return s ? url + '?' + s : url;
    }

    /**
     * 发一次请求，拆掉信封后返回 data。
     * @returns {Promise<object>} 永远 resolve 成对象（后端 data 为空时是 {}）
     */
    function request(method, path, options) {
        var opts = options || {};
        var url = buildUrl(path, opts.query);

        var init = {
            method: method,
            headers: { 'Accept': 'application/json' },
            cache: 'no-store',
            credentials: 'same-origin'
        };
        if (opts.body !== undefined) {
            init.headers['Content-Type'] = 'application/json';
            init.body = JSON.stringify(opts.body);
        }

        // 超时保护：后端卡住时也能让调用方的 finally 跑到，把按钮放开
        var timedOut = false;
        var timer = null;
        if (typeof AbortController !== 'undefined') {
            var controller = new AbortController();
            init.signal = controller.signal;
            timer = setTimeout(function () {
                timedOut = true;
                controller.abort();
            }, opts.timeout === undefined ? TIMEOUT_MS : opts.timeout);
        }

        function done() {
            if (timer !== null) {
                clearTimeout(timer);
                timer = null;
            }
        }

        return fetch(url, init).then(function (res) {
            return res.text().then(function (text) {
                done();
                var payload = null;
                if (text) {
                    try {
                        payload = JSON.parse(text);
                    } catch (e) {
                        payload = null;
                    }
                }

                // ① 非 JSON：Flask 内置错误页（路径拼错、方法不允许……）
                if (payload === null || typeof payload !== 'object') {
                    throw new ApiError(
                        '服务端返回了非 JSON 响应（HTTP ' + res.status + '）',
                        { code: -1, http: res.status, path: path, raw: String(text).slice(0, 200) }
                    );
                }

                // ② 信封里声明失败，或 HTTP 层失败
                var failed = res.ok === false ||
                    payload.status === 'error' ||
                    (typeof payload.code === 'number' && payload.code !== 0);

                if (failed) {
                    var msg = typeof payload.message === 'string' && payload.message
                        ? payload.message
                        : 'HTTP ' + res.status;
                    throw new ApiError(msg, {
                        code: typeof payload.code === 'number' ? payload.code : -1,
                        http: res.status,
                        path: path,
                        raw: String(text).slice(0, 200)
                    });
                }

                // ③ 成功：拆信封
                return (payload.data && typeof payload.data === 'object') ? payload.data : {};
            });
        }, function (err) {
            done();
            if (timedOut) {
                throw new ApiError(
                    '请求 ' + path + ' 超时（' + (opts.timeout === undefined ? TIMEOUT_MS : opts.timeout) + 'ms）',
                    { code: -1, http: 0, path: path }
                );
            }
            throw new ApiError(
                '请求 ' + path + ' 失败：' + (err && err.message ? err.message : '网络错误'),
                { code: -1, http: 0, path: path }
            );
        });
    }

    function post(path, options) {
        var opts = options || {};
        // 绝大多数 POST 端点没有请求体，但 Flask 也能接受空对象
        return request('POST', path, {
            query: opts.query,
            body: opts.body === undefined ? {} : opts.body,
            timeout: opts.timeout
        });
    }

    /* ---------------- 端点 ---------------- */

    var ExpertAPI = {
        ApiError: ApiError,
        BASE: BASE,

        /* 健康检查：GET /api/v1/ → data = {} */
        ping: function () {
            return request('GET', '/');
        },

        /* ---- example ---- */

        /** GET /example/list → {list: [name, ...]} */
        listExamples: function () {
            return request('GET', '/example/list');
        },

        /** POST /example/load?name=<name> → {}（会清空工作记忆并复位推理状态） */
        loadExample: function (name) {
            return post('/example/load', { query: { name: name } });
        },

        /** GET /example/doc?name=<name> → {name, doc}，doc 是该知识库的 markdown 说明 */
        getExampleDoc: function (name) {
            return request('GET', '/example/doc', { query: { name: name } });
        },

        /* ---- engine ---- */

        /** POST /engine/init → {}（清空知识库 + 工作记忆 + 推理状态） */
        engineInit: function () {
            return post('/engine/init');
        },

        /** POST /engine/reset → {}（只复位推理状态，保留知识库与事实） */
        engineReset: function () {
            return post('/engine/reset');
        },

        /** POST /engine/run → {}；引擎已在运行时后端返回 500/code -1 */
        engineRun: function () {
            return post('/engine/run');
        },

        /** POST /engine/pause → {}；引擎未运行时后端返回 500/code -1 */
        enginePause: function () {
            return post('/engine/pause');
        },

        /** POST /engine/status → {running, iterations, stop_reason, reached_max_iterations} */
        engineStatus: function () {
            return post('/engine/status');
        },

        /**
         * POST /engine/step
         *  → 触发成功 {fired: true, name, conditions, conclusion, priority, iterations}
         *      conditions 是 route.py 转好的函数名列表，例如
         *      ["has_wire_connected", "has_link_down"]；conclusion 是 {name, value}。
         *  → 无规则   {fired: false, stop_reason, iterations}
         *
         * 注意：这个端点有副作用 —— 即使响应读不出来，迭代数也已经 +1、
         * 结论也已经写入工作记忆，所以调用方在异常分支里必须回读
         * /engine/status 与 /engine/facts 来判断这一步到底有没有发生。
         */
        engineStep: function () {
            return post('/engine/step');
        },

        /* ---- facts ---- */

        /** GET /engine/facts → {facts: [{name, value}, ...]} */
        listFacts: function () {
            return request('GET', '/engine/facts');
        },

        /**
         * POST /engine/facts → {facts: [...]}
         * value 必须可哈希（不能是对象/数组），省略时后端默认为 true。
         */
        addFact: function (name, value, hasValue) {
            var body = { name: name };
            if (hasValue) body.value = value;
            return post('/engine/facts', { body: body });
        },

        /** GET /engine/facts/<name> → {fact: {name, value}} */
        getFact: function (name) {
            return request('GET', '/engine/facts/' + encodeURIComponent(name));
        },

        /** DELETE /engine/facts/<name> → {facts: [...]}；不存在时 404 */
        deleteFact: function (name) {
            return request('DELETE', '/engine/facts/' + encodeURIComponent(name));
        },

        /** DELETE /engine/facts → {facts: []} */
        clearFacts: function () {
            return request('DELETE', '/engine/facts');
        }
    };

    global.ExpertAPI = ExpertAPI;

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = ExpertAPI;   // 便于 Node 下做单元测试
    }
})(typeof window !== 'undefined' ? window : globalThis);
