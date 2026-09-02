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

    return { analyze, calculateFromAnchors };
}));
