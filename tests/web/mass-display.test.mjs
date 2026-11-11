import assert from 'node:assert/strict';
import test from 'node:test';
import {formatMass} from '../../src/forgepdm/web/mass-display.mjs';
for (const [value, expected] of [
 ['0','0'], ['1.4580623990476929862','1.458'], ['2.500','2.5'],
 ['0.0009','<0.001'], ['0.001','0.001'], ['1.2345','1.235'],
 ['999.9995','1000'], ['1E-20','<0.001'], ['1E+25','10000000000000000000000000'],
]) test(`mass ${value}`, () => assert.equal(formatMass(value),expected));
test('grams conversion rounds only after conversion', () => {
 assert.equal(formatMass('0.0000012345',3),'0.001');
 assert.equal(formatMass('0.0000009',3),'<0.001');
 assert.equal(formatMass('0.01612345678',3),'16.123');
});
