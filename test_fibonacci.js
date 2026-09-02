'use strict';

const assert = require('assert');
const FibonacciAnalysis = require('./fibonacci.js');

function closeTo(actual, expected, tolerance = 1e-9) {
    assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} is not close to ${expected}`);
}

const bullish = FibonacciAnalysis.calculateFromAnchors({
    swingLow: 100,
    swingHigh: 110,
    lowIndex: 5,
    highIndex: 20,
    currentPrice: 104.2,
    atr: 1
});
assert.strictEqual(bullish.valid, true);
assert.strictEqual(bullish.direction, 'bullish');
assert.strictEqual(bullish.confluence, 'BUY');
assert.strictEqual(bullish.inGoldenZone, true);
assert.strictEqual(bullish.nearestLevel, '61.8');
closeTo(bullish.levels['38.2'], 106.18);
closeTo(bullish.levels['61.8'], 103.82);
closeTo(bullish.extensions['161.8'], 116.18);

const bearish = FibonacciAnalysis.calculateFromAnchors({
    swingHigh: 110,
    swingLow: 100,
    highIndex: 5,
    lowIndex: 20,
    currentPrice: 105.8,
    atr: 1
});
assert.strictEqual(bearish.valid, true);
assert.strictEqual(bearish.direction, 'bearish');
assert.strictEqual(bearish.confluence, 'SELL');
assert.strictEqual(bearish.inGoldenZone, true);
assert.strictEqual(bearish.nearestLevel, '61.8');
closeTo(bearish.levels['38.2'], 103.82);
closeTo(bearish.levels['61.8'], 106.18);
closeTo(bearish.extensions['127.2'], 97.28);

const farFromRetracement = FibonacciAnalysis.calculateFromAnchors({
    swingLow: 100,
    swingHigh: 110,
    lowIndex: 2,
    highIndex: 9,
    currentPrice: 111,
    atr: 1
});
assert.strictEqual(farFromRetracement.confluence, 'NEUTRAL');

const invalid = FibonacciAnalysis.calculateFromAnchors({
    swingLow: 100,
    swingHigh: 100.1,
    lowIndex: 2,
    highIndex: 9,
    currentPrice: 100.05,
    atr: 1
});
assert.strictEqual(invalid.valid, false);

console.log('Fibonacci analysis tests passed.');
