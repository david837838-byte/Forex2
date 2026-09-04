(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    } else {
        root.FibonacciAnalysis = api;
    }
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const RETRACEMENTS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
    const KEY_LEVELS = ['38.2', '50', '61.8'];

    function isFiniteNumber(value) {
        return typeof value === 'number' && Number.isFinite(value);
    }

    function findPivot(values, kind, span, startIndex) {
        for (let i = values.length - span - 1; i >= Math.max(span, startIndex); i--) {
            const candidate = values[i];
            if (!isFiniteNumber(candidate)) continue;

            let isPivot = true;
            for (let offset = 1; offset <= span; offset++) {
                if (kind === 'high' && (candidate < values[i - offset] || candidate < values[i + offset])) {
                    isPivot = false;
                    break;
                }
                if (kind === 'low' && (candidate > values[i - offset] || candidate > values[i + offset])) {
                    isPivot = false;
                    break;
                }
            }
            if (isPivot) return { price: candidate, index: i };
        }
        return null;
    }

    function fallbackExtreme(values, kind, startIndex) {
        let bestIndex = -1;
        let bestValue = kind === 'high' ? -Infinity : Infinity;
        for (let i = startIndex; i < values.length; i++) {
            const value = values[i];
            if (!isFiniteNumber(value)) continue;
            if ((kind === 'high' && value > bestValue) || (kind === 'low' && value < bestValue)) {
                bestValue = value;
                bestIndex = i;
            }
        }
        return bestIndex >= 0 ? { price: bestValue, index: bestIndex } : null;
    }

    function invalidResult(reason) {
        return {
            valid: false,
            reason,
            direction: 'neutral',
            confluence: 'NEUTRAL',
            inGoldenZone: false,
            levels: {},
            extensions: {}
        };
    }

    function calculateFromAnchors(input) {
        const swingHigh = Number(input.swingHigh);
        const swingLow = Number(input.swingLow);
        const highIndex = Number(input.highIndex);
        const lowIndex = Number(input.lowIndex);
        const currentPrice = Number(input.currentPrice);
        const atr = Number(input.atr);

        if (![swingHigh, swingLow, highIndex, lowIndex, currentPrice].every(Number.isFinite)) {
            return invalidResult('بيانات الموجة غير مكتملة');
        }

        const range = swingHigh - swingLow;
        const minimumRange = Number.isFinite(atr) && atr > 0 ? atr * 0.5 : Math.abs(currentPrice) * 0.00001;
        if (range <= Math.max(minimumRange, Number.EPSILON) || highIndex === lowIndex) {
            return invalidResult('الموجة السعرية أقصر من أن تعطي مستويات موثوقة');
        }

        const direction = highIndex > lowIndex ? 'bullish' : 'bearish';
        const levels = {};
        RETRACEMENTS.forEach(ratio => {
            const key = ratio === 0 ? '0' : ratio === 1 ? '100' : (ratio * 100).toFixed(1).replace(/\.0$/, '');
            levels[key] = direction === 'bullish'
                ? swingHigh - (range * ratio)
                : swingLow + (range * ratio);
        });

        const extensions = direction === 'bullish'
            ? { '127.2': swingHigh + (range * 0.272), '161.8': swingHigh + (range * 0.618) }
            : { '127.2': swingLow - (range * 0.272), '161.8': swingLow - (range * 0.618) };

        const retracementCandidates = ['23.6', ...KEY_LEVELS, '78.6'];
        let nearestLevel = retracementCandidates[0];
        for (const level of retracementCandidates.slice(1)) {
            if (Math.abs(currentPrice - levels[level]) < Math.abs(currentPrice - levels[nearestLevel])) {
                nearestLevel = level;
            }
        }

        const nearestPrice = levels[nearestLevel];
        const distance = Math.abs(currentPrice - nearestPrice);
        const distanceAtr = Number.isFinite(atr) && atr > 0 ? distance / atr : null;
        const goldenZoneLow = Math.min(levels['50'], levels['61.8']);
        const goldenZoneHigh = Math.max(levels['50'], levels['61.8']);
        const inGoldenZone = currentPrice >= goldenZoneLow && currentPrice <= goldenZoneHigh;
        const nearKeyLevel = KEY_LEVELS.includes(nearestLevel) && distanceAtr !== null && distanceAtr <= 0.35;
        const actionable = inGoldenZone || nearKeyLevel;
        const confluence = actionable ? (direction === 'bullish' ? 'BUY' : 'SELL') : 'NEUTRAL';

        return {
            valid: true,
            direction,
            confluence,
            swingHigh,
            swingLow,
            highIndex,
            lowIndex,
            range,
            levels,
            extensions,
            nearestLevel,
            nearestPrice,
            distanceAtr,
            goldenZoneLow,
            goldenZoneHigh,
            inGoldenZone,
            actionable,
            label: direction === 'bullish' ? 'موجة صاعدة' : 'موجة هابطة'
        };
    }

    function analyze(highs, lows, currentPrice, atr, options) {
        if (!Array.isArray(highs) || !Array.isArray(lows) || highs.length !== lows.length || highs.length < 10) {
            return invalidResult('لا توجد شموع كافية لتحليل فيبوناتشي');
        }

        const settings = options || {};
        const lookback = Math.max(20, Number(settings.lookback) || 80);
        const span = Math.max(1, Number(settings.pivotSpan) || 2);
        const startIndex = Math.max(0, highs.length - lookback);
        const high = findPivot(highs, 'high', span, startIndex) || fallbackExtreme(highs, 'high', startIndex);
        const low = findPivot(lows, 'low', span, startIndex) || fallbackExtreme(lows, 'low', startIndex);

        if (!high || !low) return invalidResult('تعذر تحديد قمة وقاع الموجة');

        return calculateFromAnchors({
            swingHigh: high.price,
            swingLow: low.price,
            highIndex: high.index,
            lowIndex: low.index,
            currentPrice,
            atr
        });
    }

    function buildChartSvg(candles, analysis, requestedWidth, requestedHeight) {
        if (!analysis?.valid || !Array.isArray(candles) || candles.length < 10) return '';

        const width = Math.max(360, Number(requestedWidth) || 900);
        const height = Math.max(300, Number(requestedHeight) || 420);
        const visibleCount = Math.min(80, candles.length);
        const visibleStart = candles.length - visibleCount;
        const visible = candles.slice(visibleStart).map((candle, offset) => ({
            index: visibleStart + offset,
            time: Number(candle.time),
            open: Number(candle.open),
            high: Number(candle.high),
            low: Number(candle.low),
            close: Number(candle.close),
            volume: Number(candle.volume) || 0
        })).filter(candle => [candle.open, candle.high, candle.low, candle.close].every(Number.isFinite));

        if (visible.length < 10) return '';

        const padding = { top: 26, right: 122, bottom: 36, left: 14 };
        const plotWidth = width - padding.left - padding.right;
        const plotHeight = height - padding.top - padding.bottom;
        const fibValues = [...Object.values(analysis.levels), ...Object.values(analysis.extensions)].filter(Number.isFinite);
        let minPrice = Math.min(...visible.map(c => c.low), ...fibValues);
        let maxPrice = Math.max(...visible.map(c => c.high), ...fibValues);
        const rawRange = maxPrice - minPrice;
        const margin = Math.max(rawRange * 0.04, Math.abs(maxPrice) * 0.00001, Number.EPSILON);
        minPrice -= margin;
        maxPrice += margin;

        const y = price => padding.top + ((maxPrice - price) / (maxPrice - minPrice)) * plotHeight;
        const x = position => padding.left + ((position + 0.5) / visible.length) * plotWidth;
        const xForIndex = index => x(index - visibleStart);
        const candleStep = plotWidth / visible.length;
        const candleWidth = Math.max(3, Math.min(11, candleStep * 0.72));
        const format = price => {
            const decimals = Math.abs(price) < 10 ? 5 : Math.abs(price) < 1000 ? 3 : 2;
            return price.toFixed(decimals);
        };

        const parts = [
            `<svg class="fibonacci-svg" direction="ltr" style="direction:ltr" shape-rendering="geometricPrecision" data-visible-count="${visible.length}" data-plot-left="${padding.left}" data-plot-right="${padding.left + plotWidth}" data-plot-top="${padding.top}" data-plot-bottom="${padding.top + plotHeight}" viewBox="0 0 ${width} ${height}" role="img" aria-label="مخطط شموع تفاعلي مع مستويات فيبوناتشي" xmlns="http://www.w3.org/2000/svg">`,
            '<defs>',
            '<linearGradient id="fib-chart-bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#101b2c"/><stop offset="100%" stop-color="#070c15"/></linearGradient>',
            '<linearGradient id="fib-golden-zone" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="#ffb300" stop-opacity="0.05"/><stop offset="55%" stop-color="#ffd740" stop-opacity="0.2"/><stop offset="100%" stop-color="#ff8f00" stop-opacity="0.08"/></linearGradient>',
            '<linearGradient id="fib-up-candle" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#2de2b5"/><stop offset="100%" stop-color="#00a982"/></linearGradient>',
            '<linearGradient id="fib-down-candle" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#ff6b7f"/><stop offset="100%" stop-color="#d92d4f"/></linearGradient>',
            '<filter id="fib-glow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="2.2" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
            '<filter id="fib-last-candle-glow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="2.8" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
            `<clipPath id="fib-plot-clip"><rect x="${padding.left}" y="${padding.top}" width="${plotWidth}" height="${plotHeight}"/></clipPath>`,
            '</defs>',
            `<rect width="${width}" height="${height}" rx="8" fill="url(#fib-chart-bg)"/>`,
            `<rect x="${padding.left + plotWidth}" y="0" width="${padding.right}" height="${height}" fill="#080e18" opacity="0.78"/>`
        ];

        for (let grid = 0; grid <= 5; grid++) {
            const gridY = padding.top + (plotHeight * grid / 5);
            const gridPrice = maxPrice - ((maxPrice - minPrice) * grid / 5);
            parts.push(`<line x1="${padding.left}" y1="${gridY}" x2="${padding.left + plotWidth}" y2="${gridY}" stroke="#2c3d54" stroke-width="1" opacity="0.38"/>`);
            parts.push(`<text x="${padding.left + plotWidth - 6}" y="${gridY - 4}" fill="#607d8b" font-size="9" text-anchor="end" font-family="Arial, sans-serif">${format(gridPrice)}</text>`);
        }
        for (let grid = 0; grid <= 4; grid++) {
            const gridX = padding.left + (plotWidth * grid / 4);
            parts.push(`<line x1="${gridX}" y1="${padding.top}" x2="${gridX}" y2="${padding.top + plotHeight}" stroke="#26384d" stroke-width="1" opacity="0.28"/>`);
        }

        const goldenTop = Math.min(y(analysis.goldenZoneLow), y(analysis.goldenZoneHigh));
        const goldenHeight = Math.abs(y(analysis.goldenZoneLow) - y(analysis.goldenZoneHigh));
        parts.push(`<rect data-zone="golden" x="${padding.left}" y="${goldenTop}" width="${plotWidth}" height="${goldenHeight}" fill="url(#fib-golden-zone)" stroke="#ffc107" stroke-width="0.7" stroke-opacity="0.34"/>`);
        parts.push(`<text x="${padding.left + 8}" y="${goldenTop + 14}" fill="#ffd54f" font-size="10" font-weight="700" font-family="Arial, sans-serif">GOLDEN ZONE 50–61.8%</text>`);

        const maxVolume = Math.max(...visible.map(candle => candle.volume), 1);
        const volumeHeight = plotHeight * 0.14;
        parts.push(`<g data-layer="volume" clip-path="url(#fib-plot-clip)" opacity="0.24">`);
        visible.forEach((candle, position) => {
            const barHeight = (candle.volume / maxVolume) * volumeHeight;
            const bullish = candle.close >= candle.open;
            const color = bullish ? '#16d9ad' : '#ff506d';
            parts.push(`<rect x="${x(position) - candleWidth / 2}" y="${padding.top + plotHeight - barHeight}" width="${candleWidth}" height="${barHeight}" fill="${color}" rx="0.7"/>`);
        });
        parts.push('</g>');

        parts.push('<g data-layer="candles" clip-path="url(#fib-plot-clip)">');
        visible.forEach((candle, position) => {
            const candleX = x(position);
            const bullish = candle.close >= candle.open;
            const color = bullish ? '#16d9ad' : '#ff506d';
            const borderColor = bullish ? '#57f0ca' : '#ff8b9d';
            const fill = bullish ? 'url(#fib-up-candle)' : 'url(#fib-down-candle)';
            const bodyY = Math.min(y(candle.open), y(candle.close));
            const bodyHeight = Math.max(2.2, Math.abs(y(candle.open) - y(candle.close)));
            const isDoji = Math.abs(candle.close - candle.open) <= Math.max((candle.high - candle.low) * 0.035, Number.EPSILON);
            const isLatest = position === visible.length - 1;
            parts.push(`<g class="fib-candle ${bullish ? 'fib-candle-up' : 'fib-candle-down'}${isLatest ? ' fib-candle-latest' : ''}" data-candle-position="${position}">`);
            parts.push(`<line class="fib-candle-wick" x1="${candleX}" y1="${y(candle.high)}" x2="${candleX}" y2="${y(candle.low)}" stroke="${color}" stroke-width="1.25" stroke-linecap="round" vector-effect="non-scaling-stroke"/>`);
            if (isLatest) {
                parts.push(`<rect x="${candleX - candleWidth / 2 - 2}" y="${bodyY - 2}" width="${candleWidth + 4}" height="${bodyHeight + 4}" fill="none" stroke="${borderColor}" stroke-width="1" rx="2" opacity="0.38" filter="url(#fib-last-candle-glow)"/>`);
            }
            parts.push(`<rect class="fib-candle-body" x="${candleX - candleWidth / 2}" y="${bodyY}" width="${candleWidth}" height="${bodyHeight}" fill="${fill}" stroke="${borderColor}" stroke-width="0.65" rx="1.15" vector-effect="non-scaling-stroke"/>`);
            if (isDoji) {
                parts.push(`<line class="fib-candle-doji" x1="${candleX - candleWidth * 0.62}" y1="${bodyY + bodyHeight / 2}" x2="${candleX + candleWidth * 0.62}" y2="${bodyY + bodyHeight / 2}" stroke="${borderColor}" stroke-width="1.2" vector-effect="non-scaling-stroke"/>`);
            }
            parts.push('</g>');
        });
        parts.push('</g>');

        const lineDefinitions = [
            ['0', '#64b5f6', '0%'],
            ['23.6', '#90a4ae', '23.6%'],
            ['38.2', '#ffca28', '38.2%'],
            ['50', '#ffd700', '50%'],
            ['61.8', '#ff9800', '61.8%'],
            ['78.6', '#90a4ae', '78.6%'],
            ['100', '#64b5f6', '100%']
        ];
        lineDefinitions.forEach(([key, color, label]) => {
            const price = analysis.levels[key];
            if (!Number.isFinite(price)) return;
            const lineY = y(price);
            const emphasized = KEY_LEVELS.includes(key);
            parts.push(`<line data-level="${key}" x1="${padding.left}" y1="${lineY}" x2="${padding.left + plotWidth}" y2="${lineY}" stroke="${color}" stroke-width="${emphasized ? 1.8 : 1}" stroke-dasharray="${emphasized ? '8 4' : '4 5'}" opacity="0.92"${emphasized ? ' filter="url(#fib-glow)"' : ''}/>`);
            parts.push(`<rect x="${padding.left + plotWidth + 5}" y="${lineY - 10}" width="${padding.right - 10}" height="19" rx="4" fill="${color}" opacity="${emphasized ? '0.18' : '0.09'}"/>`);
            parts.push(`<text x="${padding.left + plotWidth + 10}" y="${lineY + 4}" fill="${color}" font-size="10.5" font-weight="${emphasized ? '700' : '500'}" font-family="Arial, sans-serif">${label}</text>`);
            parts.push(`<text x="${width - 6}" y="${lineY + 4}" fill="${color}" font-size="10.5" text-anchor="end" font-family="Arial, sans-serif">${format(price)}</text>`);
        });

        Object.entries(analysis.extensions).forEach(([key, price]) => {
            const lineY = y(price);
            parts.push(`<line data-extension="${key}" x1="${padding.left}" y1="${lineY}" x2="${padding.left + plotWidth}" y2="${lineY}" stroke="#ba68c8" stroke-width="1" stroke-dasharray="3 5" opacity="0.8"/>`);
            parts.push(`<text x="${padding.left + plotWidth + 9}" y="${lineY + 4}" fill="#ce93d8" font-size="9.5" font-family="Arial, sans-serif">EXT ${key}%</text>`);
            parts.push(`<text x="${width - 6}" y="${lineY + 4}" fill="#ce93d8" font-size="9.5" text-anchor="end" font-family="Arial, sans-serif">${format(price)}</text>`);
        });

        if (analysis.lowIndex >= visibleStart && analysis.highIndex >= visibleStart) {
            parts.push(`<line data-wave="anchor" x1="${xForIndex(analysis.lowIndex)}" y1="${y(analysis.swingLow)}" x2="${xForIndex(analysis.highIndex)}" y2="${y(analysis.swingHigh)}" stroke="#29b6f6" stroke-width="2.2" opacity="0.95" filter="url(#fib-glow)"/>`);
            parts.push(`<circle cx="${xForIndex(analysis.lowIndex)}" cy="${y(analysis.swingLow)}" r="4.5" fill="#07111e" stroke="#29b6f6" stroke-width="2"/>`);
            parts.push(`<circle cx="${xForIndex(analysis.highIndex)}" cy="${y(analysis.swingHigh)}" r="4.5" fill="#07111e" stroke="#29b6f6" stroke-width="2"/>`);
            parts.push(`<text x="${xForIndex(analysis.lowIndex)}" y="${y(analysis.swingLow) + 16}" fill="#81d4fa" font-size="9" text-anchor="middle" font-weight="700">SWING LOW</text>`);
            parts.push(`<text x="${xForIndex(analysis.highIndex)}" y="${y(analysis.swingHigh) - 9}" fill="#81d4fa" font-size="9" text-anchor="middle" font-weight="700">SWING HIGH</text>`);
        }

        const currentPrice = visible[visible.length - 1].close;
        const currentY = y(currentPrice);
        parts.push(`<line data-current-price="true" x1="${padding.left}" y1="${currentY}" x2="${padding.left + plotWidth}" y2="${currentY}" stroke="#00b0ff" stroke-width="1.3" stroke-dasharray="2 3" opacity="0.95"/>`);
        parts.push(`<rect x="${padding.left + plotWidth + 5}" y="${currentY - 10}" width="${padding.right - 10}" height="20" rx="4" fill="#0277bd"/>`);
        parts.push(`<text x="${padding.left + plotWidth + 10}" y="${currentY + 4}" fill="#fff" font-size="9.5" font-weight="700">NOW</text>`);
        parts.push(`<text x="${width - 6}" y="${currentY + 4}" fill="#fff" font-size="10" text-anchor="end" font-weight="700">${format(currentPrice)}</text>`);

        const timePositions = [0, Math.floor((visible.length - 1) / 2), visible.length - 1];
        timePositions.forEach(position => {
            const rawTime = visible[position].time;
            const milliseconds = rawTime < 100000000000 ? rawTime * 1000 : rawTime;
            const label = Number.isFinite(milliseconds)
                ? new Date(milliseconds).toLocaleDateString('ar', { month: 'short', day: 'numeric' })
                : '';
            parts.push(`<text x="${x(position)}" y="${height - 8}" fill="#78909c" font-size="10" text-anchor="middle" font-family="Arial, sans-serif">${label}</text>`);
        });

        parts.push(`<g data-crosshair="true" visibility="hidden" pointer-events="none"><line data-crosshair-x x1="0" y1="${padding.top}" x2="0" y2="${padding.top + plotHeight}" stroke="#b0bec5" stroke-width="0.8" stroke-dasharray="3 3" opacity="0.75"/><line data-crosshair-y x1="${padding.left}" y1="0" x2="${padding.left + plotWidth}" y2="0" stroke="#b0bec5" stroke-width="0.8" stroke-dasharray="3 3" opacity="0.55"/></g>`);

        parts.push('</svg>');
        return parts.join('');
    }

    return { analyze, calculateFromAnchors, buildChartSvg };
}));
