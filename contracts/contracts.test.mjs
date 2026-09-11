import { test } from 'node:test'
import assert from 'node:assert/strict'
import { network } from 'hardhat'
import { BrowserProvider, ContractFactory } from 'ethers'
import { compile } from './compile.mjs'

test('wallet ownership, task completion authorization, and non-replayable reputation', async () => {
  const local = await network.connect('hardhatMainnet')
  try {
    const provider = new BrowserProvider(local.provider)
    const owner = await provider.getSigner(0)
    const stranger = await provider.getSigner(1)
    const compiled = compile()
    const deploy = async name => {
      const c = await new ContractFactory(compiled[name].abi, compiled[name].evm.bytecode.object, owner).deploy()
      await c.waitForDeployment()
      return c
    }
    const registry = await deploy('AgentRegistry')
    await (await registry.register('https://agent.example', 'Research specialist', 30000, ['research'])).wait()
    assert.equal((await registry.getAgent(await owner.getAddress())).price, 30000n)
    assert.equal((await registry.list(0, 10)).length, 1)
    await assert.rejects(async () => (await registry.connect(stranger).deactivate()).wait())
    const emitter = await deploy('TaskEmitter')
    await (await emitter.post('Research request', 50000, Math.floor(Date.now() / 1000) + 3600)).wait()
    await assert.rejects(async () => (await emitter.connect(stranger).complete(1, await stranger.getAddress())).wait())
    await (await emitter.complete(1, await stranger.getAddress())).wait()
    const reputation = await deploy('Reputation')
    await assert.rejects(async () => (await reputation.connect(stranger).recordScore(await stranger.getAddress(), 5, 1)).wait())
    await (await reputation.recordScore(await stranger.getAddress(), 5, 1)).wait()
    await assert.rejects(async () => (await reputation.recordScore(await owner.getAddress(), 4, 1)).wait())
    assert.deepEqual(Array.from(await reputation.getReputation(await stranger.getAddress())), [5n, 1n])
    await (await reputation.invalidateScore(await stranger.getAddress(), 0, 'Disputed result')).wait()
    assert.deepEqual(Array.from(await reputation.getReputation(await stranger.getAddress())), [0n, 0n])
    assert.equal((await reputation.getScore(await stranger.getAddress(), 0)).valid, false)
  } finally {
    await local.close()
  }
})
