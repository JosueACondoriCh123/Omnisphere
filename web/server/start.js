import { createApp } from './app.js';
import { pruneExpired } from './db.js';

const port = Number(process.env.OMNISTAGE_PORT || 8080);
const host = process.env.OMNISTAGE_HOST || '127.0.0.1';
const publicPort = Number(process.env.OMNISTAGE_PUBLIC_PORT || 8088);
const publicHost = process.env.OMNISTAGE_PUBLIC_HOST || '127.0.0.1';
const app = createApp();
app.server.listen(port, host, () => {
  console.log(`OmniStage SQLite API: http://${host}:${port}`);
});
app.publicServer.listen(publicPort, publicHost, () => {
  console.log(`OmniStage public API: http://${publicHost}:${publicPort}`);
});
const cleanup = setInterval(() => pruneExpired(app.db), 60 * 60 * 1000);
cleanup.unref();

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, async () => {
    clearInterval(cleanup);
    await app.close();
    app.db.close();
    process.exit(0);
  });
}
