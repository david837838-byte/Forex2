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
            close: Number(candle.close)
        })).filter(candle => [candle.open, candle.high, candle.low, candle.close].every(Number.isFinite));

        if (visible.length < 10) return '';

        const padding = { top: 18, right: 94, bottom: 30, left: 12 };
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
        const candleWidth = Math.max(2, Math.min(8, (plotWidth / visible.length) * 0.62));
        const format = price => {
            const decimals = Math.abs(price) < 10 ? 5 : Math.abs(price) < 1000 ? 3 : 2;
            return price.toFixed(decimals);
        };

        const parts = [
            `<svg class="fibonacci-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="مخطط شموع مع مستويات فيبوناتشي" xmlns="http://www.w3.org/2000/svg">`,
            `<rect width="${width}" height="${height}" fill="#0b111d"/>`
        ];

        for (let grid = 0; grid <= 4; grid++) {
            const gridY = padding.top + (plotHeight * grid / 4);
            parts.push(`<line x1="${padding.left}" y1="${gridY}" x2="${padding.left + plotWidth}" y2="${gridY}" stroke="#243247" stroke-width="1" opacity="0.45"/>`);
        }

        const goldenTop = Math.min(y(analysis.goldenZoneLow), y(analysis.goldenZoneHigh));
        const goldenHeight = Math.abs(y(analysis.goldenZoneLow) - y(analysis.goldenZoneHigh));
        parts.push(`<rect data-zone="golden" x="${padding.left}" y="${goldenTop}" width="${plotWidth}" height="${goldenHeight}" fill="#ffd700" opacity="0.11"/>`);

        visible.forEach((candle, position) => {
            const candleX = x(position);
            const bullish = candle.close >= candle.open;
            const color = bullish ? '#00e676' : '#ff5252';
            const bodyY = Math.min(y(candle.open), y(candle.close));
            const bodyHeight = Math.max(1.2, Math.abs(y(candle.open) - y(candle.close)));
            parts.push(`<line x1="${candleX}" y1="${y(candle.high)}" x2="${candleX}" y2="${y(candle.low)}" stroke="${color}" stroke-width="1"/>`);
            parts.push(`<rect x="${candleX - candleWidth / 2}" y="${bodyY}" width="${candleWidth}" height="${bodyHeight}" fill="${color}" rx="0.8"/>`);
        });

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
            parts.push(`<line data-level="${key}" x1="${padding.left}" y1="${lineY}" x2="${padding.left + plotWidth}" y2="${lineY}" stroke="${color}" stroke-width="${emphasized ? 1.7 : 1}" stroke-dasharray="${emphasized ? '7 4' : '4 5'}" opacity="0.9"/>`);
            parts.push(`<text x="${padding.left + plotWidth + 6}" y="${lineY + 4}" fill="${color}" font-size="11" font-family="Arial, sans-serif">${label} ${format(price)}</text>`);
        });

        Object.entries(analysis.extensions).forEach(([key, price]) => {
            const lineY = y(price);
            parts.push(`<line data-extension="${key}" x1="${padding.left}" y1="${lineY}" x2="${padding.left + plotWidth}" y2="${lineY}" stroke="#ba68c8" stroke-width="1" stroke-dasharray="3 5" opacity="0.8"/>`);
            parts.push(`<text x="${padding.left + plotWidth + 6}" y="${lineY + 4}" fill="#ce93d8" font-size="10" font-family="Arial, sans-serif">E${key}% ${format(price)}</text>`);
        });

        if (analysis.lowIndex >= visibleStart && analysis.highIndex >= visibleStart) {
            parts.push(`<line data-wave="anchor" x1="${xForIndex(analysis.lowIndex)}" y1="${y(analysis.swingLow)}" x2="${xForIndex(analysis.highIndex)}" y2="${y(analysis.swingHigh)}" stroke="#29b6f6" stroke-width="2" opacity="0.9"/>`);
            parts.push(`<circle cx="${xForIndex(analysis.lowIndex)}" cy="${y(analysis.swingLow)}" r="4" fill="#29b6f6"/>`);
            parts.push(`<circle cx="${xForIndex(analysis.highIndex)}" cy="${y(analysis.swingHigh)}" r="4" fill="#29b6f6"/>`);
        }

        const currentPrice = visible[visible.length - 1].close;
        parts.push(`<line data-current-price="true" x1="${padding.left}" y1="${y(currentPrice)}" x2="${padding.left + plotWidth}" y2="${y(currentPrice)}" stroke="#00b0ff" stroke-width="1.2" opacity="0.9"/>`);

        const timePositions = [0, Math.floor((visible.length - 1) / 2), visible.length - 1];
        timePositions.forEach(position => {
            const rawTime = visible[position].time;
            const milliseconds = rawTime < 100000000000 ? rawTime * 1000 : rawTime;
            const label = Number.isFinite(milliseconds)
                ? new Date(milliseconds).toLocaleDateString('ar', { month: 'short', day: 'numeric' })
                : '';
            parts.push(`<text x="${x(position)}" y="${height - 8}" fill="#78909c" font-size="10" text-anchor="middle" font-family="Arial, sans-serif">${label}</text>`);
        });

        parts.push('</svg>');
        return parts.join('');
    }

    return { analyze, calculateFromAnchors, buildChartSvg };
}));
