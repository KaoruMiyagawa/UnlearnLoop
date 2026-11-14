import assert from 'node:assert/strict';
import test from 'node:test';
import { compareWriting, countWritingWords } from '../src/learn/writingText.ts';

test('word count treats contractions and hyphenated terms as one word', () => {
  assert.equal(countWritingWords('  Café\nI don’t use one-size-fits-all methods. 📝'), 6);
  assert.equal(countWritingWords('📝 \n —  _'), 0);
});

test('revision comparison preserves order and literal markup and bounds long comparisons', () => {
  assert.deepEqual(compareWriting('A\nB\nC', 'A\n<script>\nC'), [
    { kind: 'same', text: 'A' },
    { kind: 'removed', text: 'B' },
    { kind: 'added', text: '<script>' },
    { kind: 'same', text: 'C' },
  ]);
  assert.equal(compareWriting('a\n'.repeat(600), 'b\n'.repeat(600)), null);
});
