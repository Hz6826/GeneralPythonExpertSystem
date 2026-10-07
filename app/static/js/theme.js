/* ============================================================
   theme.js —— 主题切换：只换 <link> 的 href，不刷新页面

   主题清单以 index.html 里 <select id="theme-select"> 的 option 为准，
   这里不再维护第二份白名单。首次绘制前的主题套用由 index.html 里的
   内联脚本完成（避免默认主题闪一下），本文件负责后续的切换与记忆。
   ============================================================ */
(function () {
    'use strict';

    var link = document.getElementById('theme-stylesheet');
    var select = document.getElementById('theme-select');
    if (!link || !select) return;

    var base = link.dataset.cssBase || '/static/css';
    var KEY = 'expert-theme';

    var options = Array.prototype.map.call(select.options, function (opt) {
        return opt.value;
    });
    if (!options.length) return;

    function normalize(name) {
        return (name && options.indexOf(name) !== -1) ? name : options[0];
    }

    function apply(name) {
        var file = normalize(name);

        if (link.getAttribute('href') !== base + '/' + file) {
            link.href = base + '/' + file;
        }
        select.value = file;

        // 便于调试和按主题写额外样式：<html data-theme="retro">
        document.documentElement.dataset.theme =
            file.replace(/^theme-/, '').replace(/\.css$/, '');

        try {
            localStorage.setItem(KEY, file);
        } catch (e) { /* 隐私模式等场景忽略 */ }

        return file;
    }

    var saved = null;
    try {
        saved = localStorage.getItem(KEY);
    } catch (e) { /* 忽略 */ }

    apply(saved);

    select.addEventListener('change', function () {
        apply(select.value);
    });
})();
