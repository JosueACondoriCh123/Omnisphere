'use strict';

const STAGE_IDS = Object.freeze(Array.from({ length: 10 }, (_, index) => String(index + 1)));
const STAGE_SET = new Set(STAGE_IDS);

function validStage(value) {
  if (typeof value !== 'string' || !STAGE_SET.has(value)) throw new Error('Sala inválida');
  return value;
}

module.exports = { STAGE_IDS, validStage };
