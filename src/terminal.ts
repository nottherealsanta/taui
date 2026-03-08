import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { RpcClient } from './rpc';
import '@xterm/xterm/css/xterm.css';

export function createTerminal(container: HTMLElement, rpc?: RpcClient) {
  const term = new Terminal({
    theme: {
      background: '#1e1e1e',
      foreground: '#d4d4d4',
    },
  });
  const fitAddon = new FitAddon();
  term.loadAddon(fitAddon);
  term.open(container);
  fitAddon.fit();

  let currentRunId: number | null = null;

  function appendOutput(line: string) {
    term.writeln(line);
  }

  async function runCommand(command: string, specRef: string, workdir: string = '.') {
    if (!rpc) return;

    term.clear();
    term.writeln(`$ ${command}`);
    term.writeln('');

    try {
      const result = await rpc.request('run/start', {
        spec_ref: specRef,
        command,
        workdir,
      });
      currentRunId = result.run_id;
    } catch (error) {
      term.writeln(`Error: ${error}`);
    }
  }

  async function stopCommand() {
    if (!rpc || !currentRunId) return;

    try {
      await rpc.request('run/stop', {});
      term.writeln('\n^C');
      currentRunId = null;
    } catch (error) {
      term.writeln(`Error stopping: ${error}`);
    }
  }

  function markCompleted() {
    currentRunId = null;
  }

  function clear() {
    term.clear();
  }

  window.addEventListener('resize', () => {
    fitAddon.fit();
  });

  return {
    appendOutput,
    runCommand,
    stopCommand,
    markCompleted,
    clear,
    get currentRunId() {
      return currentRunId;
    },
  };
}
