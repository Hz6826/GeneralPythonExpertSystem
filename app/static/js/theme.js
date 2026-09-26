/* theme.js —— 主题切换：只换 <link> 的 href，不刷新页面 */
(function () {
    'use strict';

    const link = document.getElementById('theme-stylesheet');
    const select = document.getElementById('theme-select');
    if (!link || !select) return;

    const base = link.dataset.cssBase || '/static/css';
    const KEY = 'expert-theme';

    // 恢复上次选择
    let saved = null;
    try {
        saved = localStorage.getItem(KEY);
    } catch (e) {
    }
    if (saved) {
        select.value = saved;
        link.href = base + '/' + saved;
    }

    select.addEventListener('change', function () {
        const file = select.value;
        link.href = base + '/' + file;
        try {
            localStorage.setItem(KEY, file);
        } catch (e) {
        }
    });
})();
