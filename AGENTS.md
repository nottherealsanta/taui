Taui is an agentic coding interface from the future. The primary focus on writing good spec. Users collaborate with agents to write a spec, and then Taui generates code based on the spec. The spec is detailed and has code references (through LSPs, either has <file_path>:<function_name> or <file_path>:<line_ranges>). It takes cues from literate programming.

The users interacts through two primary ways:
1. **Spec Writing**: Users writes or edits specs. Agents then implmenent this spec. 
2. **Agentic**: Users talks to agents, and agents can ask questions, agents then writes/edits spec and then implement the spec.

There are two main panes in the UI. 
One is for Spec. user can select markdown file and see it forrmated. They can also edit the file. 
after editing the file, a agent works on the diff to make sure code matches the spec. 

the other is for talking to agents. This pane has multiple tabs for different agents.
there is a concept of 'prime' agent. 'prime' agent tab has all history of talking to prime. but user can mark a new context by "/new" but they can also refer to older message. 
prime as ability to launch root and sub agents. 
root agents are for longer task, usually bigger task. root agents can trigger multiple sub agents. 
every root agents gets a tab and a color ( so that user can refer to them ) 
root and prime can write new specs or edit spec when needed.


- Spec → Test generation as first-class
- Spec evolution tracking
Every time the spec changes, store a snapshot + diff + "why" (user or agent). This becomes incredible documentation and makes code review trivial.
