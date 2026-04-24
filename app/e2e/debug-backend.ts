import { MockBackend } from './mock-backend'

const backend = new MockBackend({ port: 8000 })

await backend.start()
console.log('[debug-backend] mock backend listening on ws://127.0.0.1:8000/ws')

const shutdown = async () => {
  await backend.stop()
  process.exit(0)
}

process.on('SIGINT', () => {
  void shutdown()
})

process.on('SIGTERM', () => {
  void shutdown()
})

setInterval(() => {
  // keep process alive for manual browser debugging
}, 1000)
