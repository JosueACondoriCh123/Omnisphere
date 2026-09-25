'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { runLocalSample } = require('./local-model.cjs');

test('la prueba local envía una frase acotada y devuelve sólo la traducción', async () => {
  const calls = [];
  const result = await runLocalSample(' Hola ', 'en', async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ choices: [{ message: { content: ' Hello ' } }] }) };
  });
  assert.equal(result, 'Hello');
  assert.equal(calls[0].url, 'http://127.0.0.1:8092/v1/chat/completions');
  assert.equal(JSON.parse(calls[0].options.body).messages[1].content, 'Hola');
});

test('rechaza entradas inválidas sin enviarlas al motor', async () => {
  const request = () => { throw new Error('No debe invocarse'); };
  await assert.rejects(runLocalSample('x'.repeat(501), 'en', request), /500 caracteres/);
  await assert.rejects(runLocalSample('hola', 'fr', request), /Idioma/);
});

test('un fallo local muestra un error sin incluir detalles del servidor', async () => {
  await assert.rejects(runLocalSample('hola', 'en', async () => ({ ok: false, status: 500 })), /Gemma rechazó/);
});
