import fs from 'node:fs'
import solc from 'solc'
import { fileURLToPath } from 'node:url'

export function compile() {
  const sources = Object.fromEntries(['AgentRegistry', 'TaskEmitter', 'Reputation'].map(name =>
    [`${name}.sol`, { content: fs.readFileSync(new URL(`${name}.sol`, import.meta.url), 'utf8') }],
  ))
  const result = JSON.parse(solc.compile(JSON.stringify({
    language: 'Solidity', sources,
    settings: { evmVersion: 'shanghai', optimizer: { enabled: true, runs: 200 }, outputSelection: { '*': { '*': ['abi', 'evm.bytecode.object'] } } },
  })))
  const errors = result.errors?.filter(e => e.severity === 'error') || []
  if (errors.length) throw new Error(errors.map(e => e.formattedMessage).join('\n'))
  return Object.fromEntries(Object.values(result.contracts).flatMap(file => Object.entries(file)))
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  fs.mkdirSync(new URL('artifacts/', import.meta.url), { recursive: true })
  for (const [name, artifact] of Object.entries(compile())) {
    fs.writeFileSync(new URL(`artifacts/${name}.json`, import.meta.url), JSON.stringify(artifact, null, 2))
    console.log(`Compiled ${name}`)
  }
}
