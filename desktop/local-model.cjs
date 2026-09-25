'use strict';

async function runLocalSample(input, target, request = fetch) {
  const text = typeof input === 'string' ? input.trim() : '';
  if (!text || text.length > 500) throw new Error('Escribí una frase de hasta 500 caracteres.');
  if (!['es', 'en'].includes(target)) throw new Error('Idioma de destino inválido.');

  let response;
  try {
    response = await request('http://127.0.0.1:8092/v1/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        model: 'gemma-4-E2B-it', stream: false, temperature: 0.1, max_tokens: 180,
        messages: [
          { role: 'system', content: `Traduce la frase al ${target === 'en' ? 'inglés' : 'español'}. Responde solo con la traducción, sin explicaciones.` },
          { role: 'user', content: text },
        ],
      }),
      signal: AbortSignal.timeout(60000),
    });
  } catch {
    throw new Error('Gemma no respondió. Comprobá que el motor local esté activo.');
  }
  if (!response.ok) throw new Error('Gemma rechazó la prueba. Revisá el estado del motor local.');
  let result;
  try { result = await response.json(); } catch { throw new Error('Gemma devolvió una respuesta inválida.'); }
  const translation = result?.choices?.[0]?.message?.content;
  if (typeof translation !== 'string' || !translation.trim()) {
    throw new Error('Gemma no devolvió texto.');
  }
  return translation.trim().slice(0, 2000);
}

module.exports = { runLocalSample };
