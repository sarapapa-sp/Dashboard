var dagfuncs = (window.dashAgGridFunctions = window.dashAgGridFunctions || {});

// Accounting format: 1,234,567 | (1,234,567) for negatives | - for zero/blank
dagfuncs.accountingFormatter = function (params) {
    if (params.value == null || params.value === '') return '-';
    var v = Number(params.value);
    if (!Number.isFinite(v)) return '-';
    var rounded = Math.round(v);
    if (rounded === 0) return '-';
    var n = Math.abs(rounded).toLocaleString('en-US');
    return rounded < 0 ? '(' + n + ')' : n;
};
