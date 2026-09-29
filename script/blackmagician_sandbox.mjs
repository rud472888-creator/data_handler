// Run the original Blackmagician API against a dedicated local Firestore emulator.
// Usage: FIRESTORE_EMULATOR_HOST=127.0.0.1:8299 node script/blackmagician_sandbox.mjs /path/to/blackmagician --seed
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
if (!/^127\.0\.0\.1:\d+$/.test(process.env.FIRESTORE_EMULATOR_HOST ?? '')) throw new Error('A loopback Firestore emulator is required.');
const repo = resolve(process.argv[2]);
const moduleAt = path => import(pathToFileURL(resolve(repo, path)).href);
const { initializeApp } = await moduleAt('web/functions/node_modules/firebase-admin/lib/esm/app/index.js');
const { getFirestore, Timestamp } = await moduleAt('web/functions/node_modules/firebase-admin/lib/esm/firestore/index.js');
const { createApi } = await moduleAt('web/functions/api.mjs');
const { default: express } = await moduleAt('web/functions/node_modules/express/index.js');
initializeApp({ projectId: 'demo-datahandler-blackmagician' });
const db = getFirestore();
const projectId = 'datahandler-sandbox-20260911';
const sessionId = 'DH-SANDBOX-0911';
const project = db.doc(`projects/${projectId}`);
const session = project.collection('sessions').doc(sessionId);
if (process.argv.includes('--seed')) {
  if ((await project.get()).exists) throw new Error('Sandbox already exists; omit --seed to reuse.');
  await project.create({ projectName: 'Data Handler 연동 샌드박스', hostDeviceId: 'datahandler-test-host', sandbox: true });
  await project.collection('sessionAccess').doc(sessionId).create({ projectId, sessionId, inviteCode: 'DH11-TEST',
    inviteCodeExpiresAt: Timestamp.fromMillis(Date.now() + 86400000), oneTimeCode: false,
    sessionActive: true, hostDeviceId: 'datahandler-test-host' });
  await session.create({ projectName: 'Data Handler 연동 샌드박스', cameraId: 'A', cameraName: 'PYXIS 6K (샌드박스)',
    scene: '24A', reel: 'A001', fps: 2398, iso: 800, whiteBalance: 5600, recordCounter: 3,
    isRecording: false, isSessionEnded: false, webBridgeVersion: 1, hostHeartbeatAt: Timestamp.now() });
  await session.collection('script').doc('state').create({ sceneInfo: '데이터핸들러 전달 확인: 창가 장면',
    scripterName: '연동 테스트', cutNumber: 2, scriptTake: 3, takeResult: 'OK' });
  for (let index = 1; index <= 3; index++) {
    const entry = { takeId: `dh-take-${index}`, sessionId, clipName: `A001_C00${index}`,
      cameraId: 'A', reel: 'A001', scene: '24A', scriptTake: index, cameraTake: index,
      takeResult: ['', 'KEEP', 'OK'][index - 1], sceneInfo: ['첫 테이크', '동선 확인', '최종 테이크'][index - 1],
      createdAt: Timestamp.fromMillis(Date.now() - (4 - index) * 60000) };
    await session.collection('scriptEntries').doc(`legacy-document-${index}`).create(entry);
    await project.collection('takeRecords').doc(entry.takeId).create(entry);
  }
}
const api = createApi(db, { eventsUrl: '/api/events', allowedOrigins: ['http://127.0.0.1:8899'] });
const app = express();
app.use((req, res, next) => req.path.startsWith('/api/') ? api(req, res, next) : next());
app.use(express.static(resolve(repo, 'web/dist')));
const server = app.listen(8899, '127.0.0.1', () => console.log(JSON.stringify({ url: 'http://127.0.0.1:8899',
  firestore: process.env.FIRESTORE_EMULATOR_HOST, projectId, sessionId, invitation: 'DH11-TEST', sandbox: true })));
const close = () => server.close(() => db.terminate().finally(() => process.exit(0)));
process.on('SIGINT', close); process.on('SIGTERM', close);
